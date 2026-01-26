"""
HomePilot Edit Session Service - Main FastAPI Application

This service adds natural image editing sessions on top of HomePilot
without modifying HomePilot code.

Key features:
- Maintains an active image per conversation_id
- Allows natural language edits without re-uploading
- Provides image history for undo/branch operations
- Drop-in proxy compatibility with existing frontend
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import (
    FastAPI,
    Depends,
    UploadFile,
    File,
    Form,
    HTTPException,
    Request
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import settings
from .security import enforce_security, validate_select_url
from .store import get_store, VersionEntry
from .homepilot_client import HomePilotClient
from .utils_images import read_and_validate_upload, strip_exif
from .models import (
    EditMessageRequest,
    SelectImageRequest,
    SetActiveImageResponse,
    HomePilotChatResponse,
    VersionEntryModel,
)
from .health import router as health_router


# Regex to detect URLs in message text
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


# Application metadata
app = FastAPI(
    title="HomePilot Edit Session",
    description=(
        "Sidecar service for natural image editing sessions. "
        "Upload once, then chat to edit."
    ),
    version=settings.SERVICE_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)


# CORS middleware - tighten in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include health check routes
app.include_router(health_router)


# Custom exception handler for consistent error responses
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Return consistent JSON error responses."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


def _has_url(text: str) -> bool:
    """Check if text contains an HTTP(S) URL."""
    return bool(URL_RE.search(text or ""))


def _rewrite_edit_message(active_url: str, user_text: str) -> str:
    """
    Rewrite user message into HomePilot edit format.

    HomePilot expects: "edit <image_url> <instruction>"

    Args:
        active_url: URL of the active image
        user_text: User's edit instruction

    Returns:
        Formatted edit command string
    """
    user_text = (user_text or "").strip()
    return f"edit {active_url} {user_text}".strip()


def _extract_images(homepilot_response: Dict[str, Any]) -> list[str]:
    """
    Extract image URLs from HomePilot response.

    Handles various response shapes:
    - {"media": {"images": ["url1", ...]}}
    - {"images": [...]}
    - {"data": {"media": {"images": [...]}}}

    Args:
        homepilot_response: Response dict from HomePilot

    Returns:
        List of unique image URLs
    """
    images: list[str] = []

    def add(x: Any) -> None:
        if isinstance(x, str) and x.startswith(("http://", "https://")):
            images.append(x)

    if isinstance(homepilot_response, dict):
        # Try media.images
        media = homepilot_response.get("media")
        if isinstance(media, dict):
            ims = media.get("images")
            if isinstance(ims, list):
                for i in ims:
                    add(i)

        # Try top-level images
        ims2 = homepilot_response.get("images")
        if isinstance(ims2, list):
            for i in ims2:
                add(i)

        # Try data.media.images
        data = homepilot_response.get("data")
        if isinstance(data, dict):
            media2 = data.get("media")
            if isinstance(media2, dict):
                ims3 = media2.get("images")
                if isinstance(ims3, list):
                    for i in ims3:
                        add(i)

    # De-duplicate while preserving order
    deduped: list[str] = []
    seen: set[str] = set()
    for u in images:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


# =============================================================================
# COMPATIBILITY ENDPOINTS (Drop-in replacement for frontend)
# =============================================================================


@app.post(
    "/upload",
    dependencies=[Depends(enforce_security)],
    summary="Upload image (proxy)",
    description="Drop-in proxy for HomePilot /upload. Sets active image if conversation_id provided."
)
async def proxy_upload(
    file: UploadFile = File(..., description="Image file to upload"),
    conversation_id: Optional[str] = Form(
        default=None,
        description="Conversation ID to associate image with"
    ),
    strip_metadata: bool = Form(
        default=True,
        description="Remove EXIF metadata for privacy"
    ),
):
    """
    Upload an image to HomePilot.

    If conversation_id is provided, also sets the uploaded image
    as the active image for that edit session.
    """
    # Validate and read the upload
    raw = await read_and_validate_upload(file)

    # Optionally strip EXIF metadata
    if strip_metadata:
        raw = strip_exif(raw)

    # Forward to HomePilot
    hp = HomePilotClient()
    url = await hp.upload(
        file.filename or "upload.png",
        file.content_type or "image/png",
        raw
    )

    # Set as active image if conversation_id provided
    if conversation_id:
        store = get_store()
        store.set_active(conversation_id, url)

    return {"url": url}


@app.post(
    "/chat",
    dependencies=[Depends(enforce_security)],
    summary="Chat endpoint (proxy)",
    description="Drop-in proxy for HomePilot /chat with natural edit session support."
)
async def proxy_chat(req: Request, body: Dict[str, Any]):
    """
    Proxy chat requests to HomePilot with edit session support.

    If mode == "edit" and no URL exists in message:
    - Loads active_image_url for conversation_id
    - Rewrites message into: 'edit <active_url> <message>'
    - Forwards to HomePilot
    """
    # Parse request tolerantly (accept unknown keys)
    msg = str(body.get("message") or "")
    mode = body.get("mode")
    conversation_id = body.get("conversation_id")

    # Rewrite edit requests to include active image
    if mode == "edit" and conversation_id and not _has_url(msg):
        store = get_store()
        rec = store.get(conversation_id)

        if not rec.active_image_url:
            raise HTTPException(
                status_code=400,
                detail="No active image. Upload an image first."
            )

        body["message"] = _rewrite_edit_message(rec.active_image_url, msg)

    # Sanitize payload for HomePilot backend compatibility
    # - "comfyui" is not a valid LLM provider (backend expects: openai_compat, ollama, openai, claude, watsonx)
    # - For edit/imagine modes, provider isn't used anyway (routes to ComfyUI internally)
    # - Backend uses "imgModel" not "model" for image model selection
    # - Backend doesn't have "stream" field in ChatIn
    if body.get("provider") == "comfyui":
        body.pop("provider", None)
    if "model" in body and "imgModel" not in body:
        body["imgModel"] = body.pop("model")
    body.pop("stream", None)  # Backend ChatIn doesn't support stream

    # Forward to HomePilot
    hp = HomePilotClient()
    out = await hp.chat(body)
    return out


# =============================================================================
# SESSION MANAGEMENT ENDPOINTS (New API)
# =============================================================================


@app.post(
    "/v1/edit-sessions/{conversation_id}/image",
    dependencies=[Depends(enforce_security)],
    summary="Upload and set active image",
    description="Upload image, set as active, optionally run first edit instruction."
)
async def set_active_image(
    conversation_id: str,
    file: UploadFile = File(..., description="Image file to upload"),
    instruction: Optional[str] = Form(
        default=None,
        description="Optional initial edit instruction"
    ),
    strip_metadata: bool = Form(
        default=True,
        description="Remove EXIF metadata for privacy"
    ),
):
    """
    Upload an image and set it as the active image for editing.

    Optionally runs an initial edit instruction immediately.

    Returns the session state and edit results if instruction provided.
    """
    # Validate and read the upload
    raw = await read_and_validate_upload(file)

    if strip_metadata:
        raw = strip_exif(raw)

    # Upload to HomePilot
    hp = HomePilotClient()
    url = await hp.upload(
        file.filename or "upload.png",
        file.content_type or "image/png",
        raw
    )

    # Set as active in store (this is the original upload, no instruction yet)
    store = get_store()
    rec = store.set_active(conversation_id, url, instruction="[Original Upload]")

    result: Dict[str, Any] = {
        "conversation_id": conversation_id,
        "active_image_url": rec.active_image_url,
        "original_image_url": rec.original_image_url,
        "versions": [
            VersionEntryModel(
                url=v.url,
                instruction=v.instruction,
                created_at=v.created_at,
                parent_url=v.parent_url,
                settings=v.settings,
            ).model_dump()
            for v in rec.versions
        ],
        "history": rec.history,  # Legacy compatibility
    }

    # Run initial edit if instruction provided
    if instruction and instruction.strip():
        payload = {
            "message": _rewrite_edit_message(url, instruction),
            "mode": "edit",
            "conversation_id": conversation_id,
        }
        out = await hp.chat(payload)

        # Capture returned images into history with the instruction
        images = _extract_images(out)
        for img in images:
            store.push_version(
                conversation_id,
                img,
                instruction=instruction.strip(),
                parent_url=url,
            )

        # Refresh record after adding versions
        rec = store.get(conversation_id)
        result["versions"] = [
            VersionEntryModel(
                url=v.url,
                instruction=v.instruction,
                created_at=v.created_at,
                parent_url=v.parent_url,
                settings=v.settings,
            ).model_dump()
            for v in rec.versions
        ]
        result["history"] = rec.history
        result["result"] = out

    return result


@app.post(
    "/v1/edit-sessions/{conversation_id}/message",
    dependencies=[Depends(enforce_security)],
    summary="Apply natural language edit",
    description="Apply a natural language edit to the active image."
)
async def edit_message(conversation_id: str, req: EditMessageRequest):
    """
    Apply a natural language edit instruction to the active image.

    Examples:
    - "remove the background"
    - "make it sunset"
    - "add a cat in the corner"

    Returns HomePilot's response with generated images.
    """
    store = get_store()
    rec = store.get(conversation_id)

    if not rec.active_image_url:
        raise HTTPException(
            status_code=400,
            detail="No active image. Upload an image first."
        )

    hp = HomePilotClient()

    # Build payload for HomePilot backend
    # Note: Backend's ChatIn expects specific fields:
    # - provider must be one of: openai_compat, ollama, openai, claude, watsonx
    # - "comfyui" is NOT a valid LLM provider (it's for image/video generation)
    # - For edit mode, provider isn't used anyway (routes directly to ComfyUI)
    # - Backend uses "imgModel" not "model" for image model selection
    # - Backend doesn't support "stream" for edit mode
    provider = req.provider
    if provider == "comfyui":
        provider = None  # Don't send invalid provider; edit mode uses ComfyUI internally

    payload: Dict[str, Any] = {
        "message": _rewrite_edit_message(rec.active_image_url, req.message),
        "mode": "edit",
        "conversation_id": conversation_id,
        "provider": provider,
        "provider_base_url": req.provider_base_url,
        "imgModel": req.model,  # Backend expects imgModel, not model
        # Note: stream is not supported by backend ChatIn, omitting it
    }
    payload.update(req.extra or {})
    payload = {k: v for k, v in payload.items() if v is not None}

    # Execute edit
    out = await hp.chat(payload)

    # Store results in history with the instruction
    images = _extract_images(out)
    for img in images:
        store.push_version(
            conversation_id,
            img,
            instruction=req.message,
            parent_url=rec.active_image_url,
        )

    return HomePilotChatResponse(raw=out).model_dump()


@app.post(
    "/v1/edit-sessions/{conversation_id}/select",
    dependencies=[Depends(enforce_security)],
    summary="Select image as new base",
    description="Select a generated image as the new active base image."
)
async def select_image(conversation_id: str, req: SelectImageRequest):
    """
    Select a generated image as the new active base for further edits.

    Use this when the user chooses "Use this" on a generated result.
    SSRF protection is enforced on the image URL.
    """
    # Validate URL to prevent SSRF
    validate_select_url(req.image_url, settings.HOME_PILOT_BASE_URL)

    store = get_store()

    # Find the version entry to get its instruction
    rec = store.get(conversation_id)
    existing_version = rec.get_version_by_url(req.image_url)
    instruction = existing_version.instruction if existing_version else "[Selected as base]"

    rec = store.set_active(
        conversation_id,
        req.image_url,
        instruction=instruction,
    )

    return {
        "conversation_id": conversation_id,
        "active_image_url": rec.active_image_url or req.image_url,
        "original_image_url": rec.original_image_url,
        "versions": [
            VersionEntryModel(
                url=v.url,
                instruction=v.instruction,
                created_at=v.created_at,
                parent_url=v.parent_url,
                settings=v.settings,
            ).model_dump()
            for v in rec.versions
        ],
        "history": rec.history,
    }


@app.get(
    "/v1/edit-sessions/{conversation_id}",
    dependencies=[Depends(enforce_security)],
    summary="Get session state",
    description="Get the current state of an edit session."
)
async def get_session(conversation_id: str):
    """
    Get the current state of an edit session.

    Returns the active image URL, versions with metadata, and history.
    """
    store = get_store()
    rec = store.get(conversation_id)

    return {
        "conversation_id": conversation_id,
        "active_image_url": rec.active_image_url,
        "original_image_url": rec.original_image_url,
        "versions": [
            VersionEntryModel(
                url=v.url,
                instruction=v.instruction,
                created_at=v.created_at,
                parent_url=v.parent_url,
                settings=v.settings,
            ).model_dump()
            for v in rec.versions
        ],
        "history": rec.history,  # Legacy compatibility
    }


@app.delete(
    "/v1/edit-sessions/{conversation_id}",
    dependencies=[Depends(enforce_security)],
    summary="Clear session",
    description="Clear all data for an edit session."
)
async def clear_session(conversation_id: str):
    """
    Clear all session data for a conversation.

    Use this when starting fresh or cleaning up.
    """
    store = get_store()
    store.clear(conversation_id)
    return {"ok": True}


@app.delete(
    "/v1/edit-sessions/{conversation_id}/versions",
    dependencies=[Depends(enforce_security)],
    summary="Delete version",
    description="Delete a specific version from the session history."
)
async def delete_version(conversation_id: str, image_url: str):
    """
    Delete a specific version from the session history.

    Args:
        conversation_id: Session identifier
        image_url: URL of the image version to delete

    Returns:
        Updated session state with version removed
    """
    if not image_url:
        raise HTTPException(
            status_code=400,
            detail="image_url query parameter is required"
        )

    store = get_store()
    rec = store.delete_version(conversation_id, image_url)

    return {
        "ok": True,
        "conversation_id": conversation_id,
        "active_image_url": rec.active_image_url,
        "original_image_url": rec.original_image_url,
        "versions": [
            VersionEntryModel(
                url=v.url,
                instruction=v.instruction,
                created_at=v.created_at,
                parent_url=v.parent_url,
                settings=v.settings,
            ).model_dump()
            for v in rec.versions
        ],
        "history": rec.history,
    }


# =============================================================================
# UTILITY ENDPOINTS
# =============================================================================


@app.get(
    "/v1/edit-sessions/{conversation_id}/history",
    dependencies=[Depends(enforce_security)],
    summary="Get image history",
    description="Get the image history with version metadata for an edit session."
)
async def get_history(conversation_id: str):
    """
    Get the image history for an edit session.

    History includes all images that have been uploaded or generated
    in this session, most recent first, with full version metadata.
    """
    store = get_store()
    rec = store.get(conversation_id)

    return {
        "conversation_id": conversation_id,
        "versions": [
            VersionEntryModel(
                url=v.url,
                instruction=v.instruction,
                created_at=v.created_at,
                parent_url=v.parent_url,
                settings=v.settings,
            ).model_dump()
            for v in rec.versions
        ],
        "history": rec.history,  # Legacy compatibility
        "count": len(rec.versions),
    }


@app.post(
    "/v1/edit-sessions/{conversation_id}/revert",
    dependencies=[Depends(enforce_security)],
    summary="Revert to history image",
    description="Set a previous history image as the active image."
)
async def revert_to_history(
    conversation_id: str,
    index: int = 0
):
    """
    Revert to a previous image from history.

    Args:
        conversation_id: Session identifier
        index: History index (0 = most recent)

    Returns:
        Updated session state with versions
    """
    store = get_store()
    rec = store.get(conversation_id)

    if not rec.versions:
        raise HTTPException(
            status_code=400,
            detail="No history available"
        )

    if index < 0 or index >= len(rec.versions):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid history index. Valid range: 0-{len(rec.versions)-1}"
        )

    target_version = rec.versions[index]
    rec = store.set_active(
        conversation_id,
        target_version.url,
        instruction=f"[Reverted to: {target_version.instruction or 'previous version'}]",
    )

    return {
        "conversation_id": conversation_id,
        "active_image_url": rec.active_image_url,
        "original_image_url": rec.original_image_url,
        "versions": [
            VersionEntryModel(
                url=v.url,
                instruction=v.instruction,
                created_at=v.created_at,
                parent_url=v.parent_url,
                settings=v.settings,
            ).model_dump()
            for v in rec.versions
        ],
        "history": rec.history,
    }


# =============================================================================
# STARTUP / SHUTDOWN EVENTS
# =============================================================================


@app.on_event("startup")
async def startup_event():
    """Application startup tasks."""
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    logger.info(
        f"Starting {settings.SERVICE_NAME} v{settings.SERVICE_VERSION}"
    )
    logger.info(f"Store backend: {settings.STORE}")
    logger.info(f"HomePilot URL: {settings.HOME_PILOT_BASE_URL}")


@app.on_event("shutdown")
async def shutdown_event():
    """Application shutdown tasks."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Shutting down edit-session service")
