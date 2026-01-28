from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid as uuidlib
import traceback
from pathlib import Path
from typing import Any, Dict, Optional, Literal

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .auth import require_api_key
# Import config and storage as modules so we can patch paths if needed
from . import config, storage, projects, search
from .config import (
    CORS_ORIGINS,
    PUBLIC_BASE_URL,
    UPLOAD_DIR,        # may be a docker path like /app/data
    MAX_UPLOAD_MB,
    DEFAULT_PROVIDER,
    LLM_BASE_URL,
    COMFY_BASE_URL,
    MEDIA_BASE_URL,
    LLM_MODEL,
    OLLAMA_BASE_URL,
    EDIT_SESSION_URL,
)
from .orchestrator import orchestrate, handle_request
from .providers import provider_info
from .storage import init_db, list_conversations, get_messages, delete_image_url, delete_conversation
from .migrations import run_migrations
from .game_mode import init_game_db, next_variation, get_session_events
from .story_mode import (
    init_story_db,
    start_story,
    continue_story,
    next_scene,
    get_story,
    list_story_sessions,
    delete_story_session,
    delete_scene,
    update_scene_image,
)

# Civitai search support
from .civitai import (
    CivitaiClient,
    CivitaiSearchQuery,
    search_and_normalize,
    get_civitai_cache,
)

# Studio module routes
from .studio.routes import router as studio_router
from .studio.repo import init_studio_db

# Upscale module routes
from .upscale import router as upscale_router

# Enhance module routes
from .enhance import router as enhance_router

# Background module routes
from .background import router as background_router

# Outpaint module routes
from .outpaint import router as outpaint_router

# Capabilities module routes
from .capabilities import router as capabilities_router

app = FastAPI(title="HomePilot Orchestrator", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Studio routes (/studio/*)
app.include_router(studio_router)

# Include Upscale routes (/v1/upscale)
app.include_router(upscale_router)

# Include Enhance routes (/v1/enhance)
app.include_router(enhance_router)

# Include Background routes (/v1/background)
app.include_router(background_router)

# Include Outpaint routes (/v1/outpaint)
app.include_router(outpaint_router)

# Include Capabilities routes (/v1/capabilities)
app.include_router(capabilities_router)

# ----------------------------
# Models
# ----------------------------

ProviderName = Literal["openai_compat", "ollama", "openai", "claude", "watsonx"]


class ChatIn(BaseModel):
    message: str = Field(..., description="User message (raw input)")
    conversation_id: Optional[str] = Field(None, description="Conversation id (optional)")
    project_id: Optional[str] = Field(None, description="Project ID context (optional)")
    fun_mode: bool = Field(False, description="Frontend fun mode toggle")
    mode: Optional[str] = Field(None, description="chat|imagine|edit|animate|project")
    provider: Optional[ProviderName] = Field(
        None,
        description="LLM provider selection. If omitted, backend default is used.",
    )
    ollama_base_url: Optional[str] = Field(
        None,
        description="Optional Ollama base URL override (e.g., http://localhost:11434)",
    )
    ollama_model: Optional[str] = Field(
        None,
        description="Optional Ollama model override (e.g., llama3:8b)",
    )
    provider_base_url: Optional[str] = Field(
        None,
        description="Optional base URL override for the selected provider.",
    )
    provider_model: Optional[str] = Field(
        None,
        description="Optional model override for the selected provider.",
    )
    # Backwards-compatible fields for openai_compat (vLLM)
    llm_base_url: Optional[str] = Field(
        None,
        description="Optional OpenAI-compatible (vLLM) base URL override.",
    )
    llm_model: Optional[str] = Field(
        None,
        description="Optional OpenAI-compatible (vLLM) model override.",
    )
    # Custom generation parameters
    textTemperature: Optional[float] = Field(None, description="Text generation temperature (0-2)")
    textMaxTokens: Optional[int] = Field(None, description="Max tokens for text generation")
    imgWidth: Optional[int] = Field(None, description="Image width")
    imgHeight: Optional[int] = Field(None, description="Image height")
    imgSteps: Optional[int] = Field(None, description="Image generation steps")
    imgCfg: Optional[float] = Field(None, description="Image CFG scale")
    imgSeed: Optional[int] = Field(None, description="Image generation seed (0 = random)")
    imgModel: Optional[str] = Field(None, description="Image model selection (sdxl, flux-schnell, flux-dev, pony-xl, sd15-uncensored)")
    imgBatchSize: Optional[int] = Field(1, ge=1, le=4, description="Number of images to generate per request (1, 2, or 4)")
    vidSeconds: Optional[int] = Field(None, description="Video duration in seconds")
    vidFps: Optional[int] = Field(None, description="Video FPS")
    vidMotion: Optional[str] = Field(None, description="Video motion bucket")
    vidModel: Optional[str] = Field(None, description="Video model selection (svd, wan-2.2, seedream)")
    nsfwMode: Optional[bool] = Field(None, description="Enable NSFW/uncensored mode")
    promptRefinement: Optional[bool] = Field(True, description="Enable AI prompt refinement for image generation (default: True)")
    # ----------------------------
    # Game Mode (Infinite Variations)
    # ----------------------------
    gameMode: Optional[bool] = Field(False, description="Enable game mode (prompt variations)")
    gameSessionId: Optional[str] = Field(None, description="Game session id (keeps variation memory)")
    gameStrength: Optional[float] = Field(0.65, description="Variation strength 0..1")
    gameLocks: Optional[Dict[str, Any]] = Field(None, description="Lock settings (world/style/etc)")
    gameWorldBible: Optional[str] = Field("", description="Optional world bible text for consistency")
    # ----------------------------
    # Reference Image (img2img similar generation)
    # ----------------------------
    imgReference: Optional[str] = Field(None, description="Reference image URL for img2img generation")
    imgRefStrength: Optional[float] = Field(0.35, description="Reference strength 0..1 (0=very similar, 1=more creative)")


class ChatOut(BaseModel):
    conversation_id: str
    text: str
    media: Optional[Dict[str, Any]] = None

class ProjectFile(BaseModel):
    name: str
    size: Optional[str] = None
    path: Optional[str] = None

class ProjectCreateIn(BaseModel):
    name: str
    description: Optional[str] = ""
    instructions: Optional[str] = ""
    files: Optional[list] = []
    is_public: Optional[bool] = False


# ----------------------------
# Helpers
# ----------------------------

def _base_url_from_request(req: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL.rstrip("/")
    return str(req.base_url).rstrip("/")


def _safe_err(message: str, *, code: str = "error") -> Dict[str, Any]:
    return {"ok": False, "code": code, "message": message}


def _compute_upload_dir() -> Path:
    """
    Production-safe upload dir resolution:

    - If UPLOAD_DIR is absolute and writable => use it (e.g. Docker /app/data)
    - Otherwise fall back to a repo-local writable path: backend/data/uploads
    - Supports overriding via env var UPLOAD_DIR (common in docker-compose/k8s)
    """
    env_dir = os.getenv("UPLOAD_DIR")
    cfg_dir = env_dir or (str(UPLOAD_DIR) if UPLOAD_DIR else "")
    candidate = Path(cfg_dir) if cfg_dir else Path()

    # Absolute candidate first (Docker/Prod)
    if candidate.is_absolute():
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            testfile = candidate / ".write_test"
            testfile.write_text("ok")
            testfile.unlink(missing_ok=True)
            return candidate
        except Exception:
            # Not writable in this environment (common on local/WSL)
            pass

    # Local dev fallback (always writable)
    backend_dir = Path(__file__).resolve().parents[1]  # .../backend
    fallback = backend_dir / "data" / "uploads"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


UPLOAD_PATH: Path = _compute_upload_dir()


def _ensure_db_path_is_writable():
    """
    Fixes the 'Permission denied: /app/data' error for local development.
    If the configured SQLITE_PATH is not writable, we patch it to use
    the safe local 'data' directory calculated above.
    """
    current_db_path = getattr(config, "SQLITE_PATH", None)
    
    # If no path configured, nothing to fix
    if not current_db_path:
        return

    # Check if we can write to the configured directory
    target_dir = os.path.dirname(current_db_path) or "."
    is_writable = False
    
    try:
        os.makedirs(target_dir, exist_ok=True)
        # Try touching a file to verify real write permissions
        test_file = os.path.join(target_dir, ".perm_test")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        is_writable = True
    except (OSError, PermissionError):
        is_writable = False

    if not is_writable:
        # Fallback: Use the parent of our safe UPLOAD_PATH (e.g. backend/data/db.sqlite)
        safe_db_path = UPLOAD_PATH.parent / "db.sqlite"
        print(f"INFO: Configured DB path '{current_db_path}' is not writable. Switching to local: {safe_db_path}")
        
        # Monkey-patch the config and storage modules
        # This ensures init_db() uses the new path
        new_path_str = str(safe_db_path)
        
        if hasattr(config, "SQLITE_PATH"):
            config.SQLITE_PATH = new_path_str
        
        # storage.py likely imported SQLITE_PATH, so we must update it there too
        if hasattr(storage, "SQLITE_PATH"):
            storage.SQLITE_PATH = new_path_str


def _ensure_static_mount() -> None:
    """
    StaticFiles validates the directory at mount time,
    so mount only after ensuring the directory exists.
    """
    # idempotent mount
    for route in app.router.routes:
        if getattr(route, "name", None) == "files":
            return
    app.mount("/files", StaticFiles(directory=str(UPLOAD_PATH)), name="files")


# ----------------------------
# Startup
# ----------------------------

@app.on_event("startup")
def _startup() -> None:
    # Ensure DB path is valid before initializing
    _ensure_db_path_is_writable()
    # Database
    init_db()
    # Initialize game mode database tables
    init_game_db()
    # Initialize story mode database tables
    init_story_db()
    # Initialize Creator Studio database tables (SQLite persistence)
    init_studio_db()
    # Run migrations
    try:
        run_migrations()
    except Exception as e:
        print(f"Warning: Failed to run migrations: {e}")
    # Files mount
    _ensure_static_mount()


# Ensure local storage is ready even when lifespan events are not executed
# (e.g. Starlette TestClient instantiated without a context manager).
try:
    _ensure_db_path_is_writable()
    init_db()
except Exception:
    pass

# Mount at import-time too (needed for some test setups and for immediate serving)
_ensure_static_mount()


# ----------------------------
# Error handling (prod-safe)
# ----------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(_: Request, exc: Exception):
    # In real deployments, log `exc` to your logger/observability stack.
    return JSONResponse(
        status_code=500,
        content=_safe_err("Internal server error.", code="internal_error"),
    )


# ----------------------------
# Routes
# ----------------------------

@app.get("/health")
async def health() -> JSONResponse:
    """
    Quick health check with provider availability.
    """
    status = {
        "ok": True,
        "service": "homepilot-backend",
        "version": app.version,
    }

    # Check Ollama
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags")
            ollama_ok = (r.status_code == 200)
    except Exception:
        ollama_ok = False

    # Check OpenAI-compatible (vLLM)
    vllm_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{LLM_BASE_URL.rstrip('/')}/models")
            vllm_ok = (r.status_code == 200)
    except Exception:
        vllm_ok = False

    status["providers"] = {
        "ollama": {"ok": ollama_ok, "base_url": OLLAMA_BASE_URL},
        "openai_compat": {"ok": vllm_ok, "base_url": LLM_BASE_URL},
    }

    return JSONResponse(status_code=200, content=status)


@app.get("/health/detailed")
async def health_detailed() -> JSONResponse:
    """
    Comprehensive health check for all services.
    Tests: Ollama, ComfyUI, vLLM
    """
    health_status = {
        "backend": {"ok": True, "service": "homepilot-backend", "version": app.version},
        "ollama": {"ok": False, "message": "Not tested"},
        "comfyui": {"ok": False, "message": "Not tested"},
        "llm": {"ok": False, "message": "Not tested"},
    }

    # Test Ollama
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{OLLAMA_BASE_URL}")
            if response.status_code == 200:
                health_status["ollama"] = {
                    "ok": True,
                    "url": OLLAMA_BASE_URL,
                    "status": "running"
                }
                # Try to get models
                try:
                    models_response = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
                    if models_response.status_code == 200:
                        models_data = models_response.json()
                        model_names = [m.get("name") for m in models_data.get("models", [])]
                        health_status["ollama"]["models"] = model_names
                        health_status["ollama"]["model_count"] = len(model_names)
                except Exception:
                    pass
            else:
                health_status["ollama"] = {
                    "ok": False,
                    "url": OLLAMA_BASE_URL,
                    "message": f"HTTP {response.status_code}"
                }
    except Exception as e:
        health_status["ollama"] = {
            "ok": False,
            "url": OLLAMA_BASE_URL,
            "message": f"Connection failed: {str(e)}"
        }

    # Test ComfyUI
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{COMFY_BASE_URL}/system_stats")
            if response.status_code == 200:
                health_status["comfyui"] = {
                    "ok": True,
                    "url": COMFY_BASE_URL,
                    "status": "running"
                }
            else:
                health_status["comfyui"] = {
                    "ok": False,
                    "url": COMFY_BASE_URL,
                    "message": f"HTTP {response.status_code}"
                }
    except Exception as e:
        health_status["comfyui"] = {
            "ok": False,
            "url": COMFY_BASE_URL,
            "message": f"Connection failed: {str(e)}"
        }

    # Test LLM (vLLM)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{LLM_BASE_URL}/models")
            if response.status_code == 200:
                health_status["llm"] = {
                    "ok": True,
                    "url": LLM_BASE_URL,
                    "status": "running"
                }
            else:
                health_status["llm"] = {
                    "ok": False,
                    "url": LLM_BASE_URL,
                    "message": f"HTTP {response.status_code}"
                }
    except Exception as e:
        health_status["llm"] = {
            "ok": False,
            "url": LLM_BASE_URL,
            "message": f"Connection failed: {str(e)}"
        }

    # Determine overall health
    all_ok = health_status["ollama"]["ok"] or health_status["llm"]["ok"]  # At least one LLM should work

    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "ok": all_ok,
            "services": health_status,
            "timestamp": uuidlib.uuid4().hex[:8],  # Simple timestamp
        },
    )


@app.get("/providers")
async def providers() -> JSONResponse:
    info = provider_info()
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "default": DEFAULT_PROVIDER,
            "available": sorted(list(info.keys())),
            "providers": info,
        },
    )


@app.get("/settings")
async def settings(request: Request) -> JSONResponse:
    base = _base_url_from_request(request)
    info = provider_info()
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "default_provider": DEFAULT_PROVIDER,
            "providers": info,
            "public_base_url": base,
            "llm_base_url": LLM_BASE_URL,
            "llm_model": LLM_MODEL,
            "comfy_base_url": COMFY_BASE_URL,
            "media_base_url": MEDIA_BASE_URL,
            "upload_dir": str(UPLOAD_PATH),
            "max_upload_mb": int(MAX_UPLOAD_MB),
        },
    )


# -----------------------------------------------------------------------------
# API Keys Management (Optional - for gated HuggingFace / Civitai models)
# -----------------------------------------------------------------------------

from .api_keys import (
    get_api_keys_status,
    get_api_key,
    set_api_key,
    delete_api_key,
)


class ApiKeySetRequest(BaseModel):
    """Request to set an API key."""
    provider: str = Field(..., description="Provider: 'huggingface' or 'civitai'")
    key: str = Field(..., description="The API key/token")


class ApiKeyTestRequest(BaseModel):
    """Request to test an API key."""
    provider: str = Field(..., description="Provider to test")
    key: Optional[str] = Field(None, description="Key to test (uses stored if not provided)")


@app.get("/settings/api-keys")
async def get_api_keys_endpoint() -> JSONResponse:
    """
    Get status of configured API keys (masked, not actual values).

    API keys are OPTIONAL - HomePilot works without them.
    Keys are only needed for:
    - Gated HuggingFace models (FLUX, SVD XT 1.1)
    - NSFW/restricted Civitai models
    """
    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "keys": get_api_keys_status(),
            "note": "API keys are optional. Only needed for gated/restricted models.",
        },
    )


@app.post("/settings/api-keys")
async def set_api_key_endpoint(req: ApiKeySetRequest) -> JSONResponse:
    """Set an API key for a provider (huggingface or civitai)."""
    if req.provider not in ("huggingface", "civitai"):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"Unknown provider: {req.provider}. Use 'huggingface' or 'civitai'."},
        )

    set_api_key(req.provider, req.key)  # type: ignore

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "message": f"API key for {req.provider} saved successfully",
            "status": get_api_keys_status()[req.provider],
        },
    )


@app.delete("/settings/api-keys/{provider}")
async def delete_api_key_endpoint(provider: str) -> JSONResponse:
    """Remove a stored API key."""
    if provider not in ("huggingface", "civitai"):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"Unknown provider: {provider}. Use 'huggingface' or 'civitai'."},
        )

    deleted = delete_api_key(provider)  # type: ignore

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "deleted": deleted,
            "message": f"API key for {provider} {'removed' if deleted else 'was not set'}",
        },
    )


@app.post("/settings/api-keys/test")
async def test_api_key_endpoint(req: ApiKeyTestRequest) -> JSONResponse:
    """
    Test if an API key is valid by making a test request to the provider.
    If no key is provided in the request, tests the stored/env key.
    """
    if req.provider not in ("huggingface", "civitai"):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": f"Unknown provider: {req.provider}"},
        )

    key = req.key.strip() if req.key else get_api_key(req.provider)  # type: ignore
    if not key:
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "valid": False,
                "message": f"No API key provided or stored for {req.provider}",
            },
        )

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15) as client:
            if req.provider == "huggingface":
                # Test HF token by getting user info
                r = await client.get(
                    "https://huggingface.co/api/whoami-v2",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if r.status_code == 200:
                    data = r.json()
                    return JSONResponse(content={
                        "ok": True,
                        "valid": True,
                        "message": f"Authenticated as: {data.get('name', 'unknown')}",
                        "username": data.get("name"),
                    })
                else:
                    return JSONResponse(content={
                        "ok": True,
                        "valid": False,
                        "message": f"Invalid token (HTTP {r.status_code})",
                    })

            elif req.provider == "civitai":
                # Test Civitai key by getting current user
                r = await client.get(
                    "https://civitai.com/api/v1/me",
                    headers={"Authorization": f"Bearer {key}"},
                )
                if r.status_code == 200:
                    data = r.json()
                    return JSONResponse(content={
                        "ok": True,
                        "valid": True,
                        "message": f"Authenticated as: {data.get('username', 'unknown')}",
                        "username": data.get("username"),
                    })
                else:
                    return JSONResponse(content={
                        "ok": True,
                        "valid": False,
                        "message": f"Invalid API key (HTTP {r.status_code})",
                    })

    except Exception as e:
        return JSONResponse(content={
            "ok": True,
            "valid": False,
            "message": f"Connection error: {str(e)}",
        })

    return JSONResponse(content={"ok": True, "valid": False, "message": "Unknown error"})


@app.get("/models")
async def list_models(
    provider: str = Query("openai_compat", description="Provider to list models from"),
    base_url: Optional[str] = Query(None, description="Override base URL for the provider"),
    model_type: Optional[str] = Query(None, description="For ComfyUI: 'image', 'video', or 'edit'"),
) -> JSONResponse:
    """
    List available models from a provider.
    Supports:
      - openai_compat: GET {base}/models   (expects OpenAI-style response)
      - ollama: GET {base}/api/tags
      - openai: OpenAI API
      - claude: Anthropic API
      - watsonx: IBM watsonx.ai
      - comfyui: Returns local image/video models list

    Example: GET /models?provider=ollama&base_url=http://localhost:11434
    Example: GET /models?provider=comfyui&model_type=image
    """
    try:
        # ComfyUI model listing - scan filesystem for installed models
        if provider == "comfyui":
            from .providers import scan_installed_models

            if model_type == "image":
                models = scan_installed_models("image")
            elif model_type == "video":
                models = scan_installed_models("video")
            elif model_type == "edit":
                models = scan_installed_models("edit")
            elif model_type == "enhance":
                models = scan_installed_models("enhance")
            else:
                # Return all if not specified
                models = (
                    scan_installed_models("image")
                    + scan_installed_models("video")
                    + scan_installed_models("edit")
                    + scan_installed_models("enhance")
                )

            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "provider": "comfyui",
                    "model_type": model_type or "all",
                    "models": models,
                    "count": len(models),
                    "message": f"Scanned filesystem - found {len(models)} installed models",
                },
            )

        # Everything else uses the shared model catalog
        from .model_catalog import list_models_for_provider

        # Validate provider string against our ProviderName literal
        if provider not in {"openai_compat", "ollama", "openai", "claude", "watsonx"}:
            return JSONResponse(
                status_code=400,
                content=_safe_err(
                    f"Provider '{provider}' is not supported for model listing.",
                    code="unsupported_provider",
                ),
            )
        prov: ProviderName = provider  # type: ignore

        models, err = await list_models_for_provider(prov, base_url=base_url)
        if err:
            return JSONResponse(status_code=503, content=_safe_err(err, code="models_unavailable"))

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "provider": provider,
                "base_url": (base_url or ""),
                "models": models,
                "count": len(models),
            },
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                f"Error listing models: {str(e)}",
                code="models_error",
            ),
        )


@app.get("/model-catalog")
async def get_model_catalog() -> JSONResponse:
    """
    Return the curated model catalog with recommended models for all providers.

    The catalog is read from model_catalog_data.json and includes:
    - Model IDs and labels
    - Recommended flags
    - Model descriptions, sizes, capabilities
    - Download URLs and install paths (for ComfyUI)

    This endpoint provides a static catalog that can be easily maintained by
    editing the JSON file. To add/remove models, simply edit the JSON file.

    Example: GET /model-catalog
    Returns: { "ok": true, "providers": { ... }, "version": "1.0.0" }
    """
    try:
        catalog_path = Path(__file__).parent / "model_catalog_data.json"

        if not catalog_path.exists():
            return JSONResponse(
                status_code=404,
                content=_safe_err(
                    "Model catalog file not found. Please create model_catalog_data.json",
                    code="catalog_not_found",
                ),
            )

        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog_data = json.load(f)

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "version": catalog_data.get("version", "1.0.0"),
                "last_updated": catalog_data.get("last_updated", "unknown"),
                "providers": catalog_data.get("providers", {}),
            },
        )

    except json.JSONDecodeError as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                f"Invalid JSON in model catalog: {str(e)}",
                code="catalog_invalid_json",
            ),
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                f"Error loading model catalog: {str(e)}",
                code="catalog_error",
            ),
        )


# ----------------------------
# Civitai Search API
# ----------------------------

class CivitaiSearchRequest(BaseModel):
    """Request model for Civitai search."""
    model_config = {"protected_namespaces": ()}

    query: str = Field(..., min_length=1, max_length=100, description="Search query")
    model_type: str = Field(default="image", description="Model type: 'image' or 'video'")
    nsfw: bool = Field(default=False, description="Include NSFW results (requires API key)")
    limit: int = Field(default=20, ge=1, le=50, description="Results per page")
    page: int = Field(default=1, ge=1, description="Page number")
    sort: str = Field(default="Highest Rated", description="Sort order")


@app.post("/civitai/search")
async def civitai_search(
    req: CivitaiSearchRequest,
    request: Request,
    x_civitai_api_key: Optional[str] = None,
) -> JSONResponse:
    """
    Search Civitai models.

    This is an enterprise-safe backend proxy for Civitai API:
    - API key is OPTIONAL for SFW/public searches
    - For NSFW searches, pass X-Civitai-Api-Key header (optional)
    - Results are cached briefly to reduce upstream rate pressure
    - Responses are normalized to a stable schema

    Example:
        POST /civitai/search
        {
            "query": "anime",
            "model_type": "image",
            "nsfw": false,
            "limit": 20,
            "page": 1
        }
    """
    try:
        # Get API key from header if provided
        api_key = request.headers.get("X-Civitai-Api-Key") or x_civitai_api_key

        # Sanitize query
        query = req.query.strip()[:100]
        if not query:
            return JSONResponse(
                status_code=400,
                content=_safe_err("Query is required", code="invalid_query"),
            )

        # Validate model_type
        if req.model_type not in ("image", "video"):
            return JSONResponse(
                status_code=400,
                content=_safe_err("model_type must be 'image' or 'video'", code="invalid_model_type"),
            )

        # Create client (with optional API key for NSFW)
        # Only pass API key if NSFW is requested
        client = CivitaiClient(api_key=api_key if req.nsfw else None)

        # Build search query
        search_query = CivitaiSearchQuery(
            query=query,
            model_type=req.model_type,
            limit=req.limit,
            page=req.page,
            nsfw=req.nsfw,
            sort=req.sort,
        )

        # Get cache and perform search
        cache = get_civitai_cache()
        results = await search_and_normalize(
            client=client,
            cache=cache,
            query=search_query,
        )

        print(f"[CIVITAI] Search '{query}' returned {len(results.get('items', []))} results")

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "query": query,
                "model_type": req.model_type,
                "nsfw": req.nsfw,
                "items": results.get("items", []),
                "metadata": results.get("metadata", {}),
            },
        )

    except httpx.HTTPStatusError as e:
        error_msg = f"Civitai API error: {e.response.status_code}"
        print(f"[CIVITAI] {error_msg}")
        return JSONResponse(
            status_code=502,
            content=_safe_err(error_msg, code="civitai_api_error"),
        )
    except httpx.TimeoutException:
        print("[CIVITAI] Request timeout")
        return JSONResponse(
            status_code=504,
            content=_safe_err("Civitai API timeout - try again later", code="civitai_timeout"),
        )
    except Exception as e:
        print(f"[CIVITAI] Unexpected error: {e}")
        return JSONResponse(
            status_code=500,
            content=_safe_err("Search failed - please try again", code="civitai_error"),
        )


@app.get("/civitai/search")
async def civitai_search_get(
    request: Request,
    query: str = Query(..., min_length=1, max_length=100, description="Search query"),
    model_type: str = Query(default="image", description="Model type: 'image' or 'video'"),
    nsfw: bool = Query(default=False, description="Include NSFW results"),
    limit: int = Query(default=20, ge=1, le=50, description="Results per page"),
    page: int = Query(default=1, ge=1, description="Page number"),
    sort: str = Query(default="Highest Rated", description="Sort order"),
) -> JSONResponse:
    """
    GET version of Civitai search for easier testing.

    Example: GET /civitai/search?query=anime&model_type=image&limit=10
    """
    req = CivitaiSearchRequest(
        query=query,
        model_type=model_type,
        nsfw=nsfw,
        limit=limit,
        page=page,
        sort=sort,
    )
    return await civitai_search(req, request)


class ModelInstallRequest(BaseModel):
    model_config = {"protected_namespaces": ()}

    provider: str = Field(..., description="Provider (ollama, comfyui, civitai)")
    model_type: str = Field(..., description="Model type (chat, image, video, edit)")
    model_id: str = Field(..., description="Model ID to install")
    base_url: Optional[str] = Field(None, description="Optional base URL override")
    civitai_version_id: Optional[str] = Field(None, description="Civitai version ID (for civitai provider)")
    civitai_api_key: Optional[str] = Field(None, description="Optional Civitai API key for restricted/NSFW downloads")


@app.post("/models/install")
async def install_model(req: ModelInstallRequest) -> JSONResponse:
    """
    Install a model using the download.py script.

    Supports:
    - ollama: Uses ollama pull
    - comfyui: Downloads from catalog
    - civitai: Downloads from Civitai by version ID (experimental)
    """
    import logging
    import sys

    logger = logging.getLogger("homepilot.install")
    logger.setLevel(logging.INFO)

    # Ensure we have a handler
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[INSTALL] %(message)s"))
        logger.addHandler(handler)

    try:
        script_path = Path(__file__).parent.parent.parent / "scripts" / "download.py"

        if not script_path.exists():
            logger.error(f"Download script not found at {script_path}")
            return JSONResponse(
                status_code=500,
                content=_safe_err(
                    "Download script not found. Please ensure scripts/download.py exists.",
                    code="script_not_found",
                ),
            )

        logger.info(f"Starting model installation: provider={req.provider}, model={req.model_id}")

        # Build command based on provider
        cmd = ["python3", str(script_path)]

        if req.provider == "civitai":
            # Experimental Civitai download
            if not req.civitai_version_id:
                return JSONResponse(
                    status_code=400,
                    content=_safe_err(
                        "civitai_version_id required for Civitai provider",
                        code="missing_version_id",
                    ),
                )

            cmd.extend([
                "--civitai",
                "--version-id", req.civitai_version_id,
                "--type", req.model_type,
            ])

            if req.model_id:
                cmd.extend(["--output", req.model_id])

        elif req.provider == "ollama":
            # Ollama: Use ollama pull directly
            logger.info(f"Pulling Ollama model: {req.model_id}")
            pull_cmd = ["ollama", "pull", req.model_id]

            # Use Popen to stream output to logs
            process = subprocess.Popen(
                pull_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            output_lines = []
            for line in iter(process.stdout.readline, ""):
                line = line.rstrip()
                if line:
                    logger.info(f"  {line}")
                    output_lines.append(line)
            process.wait()

            if process.returncode == 0:
                logger.info(f"Successfully pulled Ollama model: {req.model_id}")
                return JSONResponse(
                    status_code=200,
                    content={
                        "ok": True,
                        "message": f"Successfully pulled {req.model_id}",
                        "provider": "ollama",
                        "model_id": req.model_id,
                        "output": "\n".join(output_lines),
                    },
                )
            else:
                logger.error(f"Failed to pull Ollama model: {req.model_id}")
                return JSONResponse(
                    status_code=500,
                    content=_safe_err(
                        f"Ollama pull failed: {output_lines[-5:] if output_lines else 'Unknown error'}",
                        code="ollama_pull_failed",
                    ),
                )

        elif req.provider == "comfyui":
            # ComfyUI: Download from catalog
            cmd.extend(["--model", req.model_id])

        else:
            return JSONResponse(
                status_code=400,
                content=_safe_err(
                    f"Unsupported provider: {req.provider}",
                    code="unsupported_provider",
                ),
            )

        # Run download script for comfyui and civitai
        # Pass Civitai API key via environment variable (secure - not visible in process list)
        env = os.environ.copy()
        if req.civitai_api_key and req.provider == "civitai":
            env["CIVITAI_API_KEY"] = req.civitai_api_key

        logger.info(f"Running download script: {' '.join(cmd)}")

        # Use Popen to stream output in real-time
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )

        output_lines = []
        for line in iter(process.stdout.readline, ""):
            line = line.rstrip()
            if line:
                logger.info(f"  {line}")
                output_lines.append(line)
                # Flush stdout to ensure logs appear immediately
                sys.stdout.flush()

        process.wait()

        if process.returncode == 0:
            logger.info(f"Successfully installed model: {req.model_id}")
            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "message": f"Successfully installed {req.model_id}",
                    "provider": req.provider,
                    "model_id": req.model_id,
                    "output": "\n".join(output_lines),
                },
            )
        else:
            logger.error(f"Failed to install model: {req.model_id}")
            # Get last few lines for error message
            error_output = "\n".join(output_lines[-10:]) if output_lines else "Unknown error"
            return JSONResponse(
                status_code=500,
                content=_safe_err(
                    f"Installation failed: {error_output}",
                    code="installation_failed",
                ),
            )

    except subprocess.TimeoutExpired:
        logger.error(f"Installation timed out for model: {req.model_id}")
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                "Installation timed out. Large models may take longer.",
                code="timeout",
            ),
        )
    except Exception as e:
        logger.exception(f"Installation error for model {req.model_id}: {e}")
        return JSONResponse(
            status_code=500,
            content=_safe_err(
                f"Installation error: {str(e)}",
                code="installation_error",
            ),
        )


@app.get("/models/health")
async def check_models_health(
    model_type: Optional[str] = Query(None, description="Filter by model type: 'image', 'video', 'edit'"),
    provider: Optional[str] = Query(None, description="Filter by provider: 'comfyui', 'civitai'"),
) -> JSONResponse:
    """
    Check health status of all model download URLs.

    Returns health information for each downloadable model including:
    - status: 'healthy', 'unhealthy', 'timeout', 'error'
    - http_status: HTTP response code
    - response_time_ms: Time to check URL
    - error_message: Error details if unhealthy

    Use this to verify model sources before downloading.
    """
    import time
    import requests
    from concurrent.futures import ThreadPoolExecutor, as_completed

    try:
        # Load catalog
        catalog_path = Path(__file__).parent / "model_catalog_data.json"
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = json.load(f)

        # Collect models to check
        models_to_check = []
        providers_data = catalog.get("providers", {})

        for prov_name, prov_data in providers_data.items():
            # Skip non-downloadable providers
            if prov_name in ("ollama", "openai", "claude", "openai_compat", "watsonx"):
                continue

            if provider and prov_name != provider:
                continue

            for type_name, model_list in prov_data.items():
                if model_type and type_name != model_type:
                    continue

                if not isinstance(model_list, list):
                    continue

                for model in model_list:
                    download_url = model.get("download_url")
                    if download_url:
                        models_to_check.append({
                            "id": model.get("id"),
                            "label": model.get("label", model.get("id")),
                            "provider": prov_name,
                            "type": type_name,
                            "url": download_url,
                            "size_gb": model.get("size_gb"),
                        })

        def check_single_url(model_info):
            """Check a single URL health."""
            url = model_info["url"]
            start = time.time()
            try:
                resp = requests.head(
                    url,
                    headers={"User-Agent": "HomePilot-HealthCheck/1.0"},
                    timeout=10,
                    allow_redirects=True,
                )
                elapsed_ms = int((time.time() - start) * 1000)

                if resp.status_code < 400:
                    status = "healthy"
                    error = None
                else:
                    status = "unhealthy"
                    error = f"HTTP {resp.status_code}"
                    if "x-error-message" in resp.headers:
                        error += f": {resp.headers['x-error-message']}"

                return {
                    **model_info,
                    "status": status,
                    "http_status": resp.status_code,
                    "response_time_ms": elapsed_ms,
                    "error": error,
                }
            except requests.exceptions.Timeout:
                return {
                    **model_info,
                    "status": "timeout",
                    "http_status": None,
                    "response_time_ms": int((time.time() - start) * 1000),
                    "error": "Request timed out",
                }
            except Exception as e:
                return {
                    **model_info,
                    "status": "error",
                    "http_status": None,
                    "response_time_ms": int((time.time() - start) * 1000),
                    "error": str(e),
                }

        # Run checks concurrently
        results = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(check_single_url, m): m for m in models_to_check}
            for future in as_completed(futures):
                results.append(future.result())

        # Calculate summary
        healthy = len([r for r in results if r["status"] == "healthy"])
        unhealthy = len([r for r in results if r["status"] == "unhealthy"])
        timeout = len([r for r in results if r["status"] == "timeout"])
        errors = len([r for r in results if r["status"] == "error"])

        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "summary": {
                    "total": len(results),
                    "healthy": healthy,
                    "unhealthy": unhealthy,
                    "timeout": timeout,
                    "error": errors,
                },
                "results": sorted(results, key=lambda x: (x["status"] != "healthy", x["type"], x["id"])),
            },
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=_safe_err(f"Health check failed: {str(e)}", code="health_check_error"),
        )


@app.get("/conversations")
async def conversations(limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    """List saved conversations (History/Today sidebar)."""
    try:
        items = list_conversations(limit=limit)
        return JSONResponse(status_code=200, content={"ok": True, "conversations": items})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to list conversations: {e}", code="conversations_error"))


@app.get("/conversations/{conversation_id}/messages")
async def conversation_messages(conversation_id: str, limit: int = Query(200, ge=1, le=1000)) -> JSONResponse:
    """Load full message list for a conversation."""
    try:
        msgs = get_messages(conversation_id, limit=limit)
        return JSONResponse(status_code=200, content={"ok": True, "conversation_id": conversation_id, "messages": msgs})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to load conversation: {e}", code="conversation_load_error"))


@app.delete("/conversations/{conversation_id}")
async def delete_conversation_endpoint(conversation_id: str) -> JSONResponse:
    """Delete all messages from a specific conversation."""
    try:
        deleted_count = delete_conversation(conversation_id)
        return JSONResponse(status_code=200, content={"ok": True, "deleted": deleted_count > 0, "deleted_messages": deleted_count, "conversation_id": conversation_id})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to delete conversation: {e}", code="delete_conversation_error"))


@app.delete("/media/image")
async def delete_image(request: Request) -> JSONResponse:
    """Delete an image URL from all messages in the database."""
    try:
        body = await request.json()
        image_url = body.get("image_url")

        if not image_url:
            return JSONResponse(status_code=400, content=_safe_err("image_url is required", code="missing_image_url"))

        updated_count = delete_image_url(image_url)
        return JSONResponse(status_code=200, content={"ok": True, "deleted": updated_count > 0, "updated_messages": updated_count})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to delete image: {e}", code="delete_image_error"))


@app.get("/conversations/{conversation_id}/search")
async def search_conversation(
    conversation_id: str,
    q: str = Query(..., description="Search query"),
    limit: int = Query(20, ge=1, le=100)
) -> JSONResponse:
    """Search within a specific conversation."""
    try:
        results = search.search_conversation_history(
            query=q,
            conversation_id=conversation_id,
            limit=limit
        )
        return JSONResponse(status_code=200, content={
            "ok": True,
            "conversation_id": conversation_id,
            "query": q,
            "results": results,
            "count": len(results)
        })
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Search failed: {e}"))


# ----------------------------
# Projects API
# ----------------------------

@app.post("/projects", dependencies=[Depends(require_api_key)])
async def create_project(data: ProjectCreateIn) -> JSONResponse:
    """Create a new project context."""
    try:
        # Convert pydantic model to dict for storage
        project_dict = data.dict()
        result = projects.create_new_project(project_dict)
        return JSONResponse(status_code=201, content={"ok": True, "project": result})
    except Exception as e:
        print(f"ERROR creating project: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to create project: {e}"))

@app.get("/projects", dependencies=[Depends(require_api_key)])
async def list_projects() -> JSONResponse:
    """List all available projects."""
    try:
        result = projects.list_all_projects()
        return JSONResponse(status_code=200, content={"ok": True, "projects": result})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to list projects: {e}"))

@app.get("/projects/examples")
async def get_example_projects() -> JSONResponse:
    """Get list of example project templates."""
    try:
        examples = projects.get_example_projects()
        return JSONResponse(status_code=200, content={"ok": True, "examples": examples})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to get examples: {e}"))

@app.post("/projects/from-example/{example_id}", dependencies=[Depends(require_api_key)])
async def create_from_example(example_id: str) -> JSONResponse:
    """Create a new project from an example template."""
    try:
        result = projects.create_project_from_example(example_id)
        if result:
            return JSONResponse(status_code=201, content={"ok": True, "project": result})
        else:
            return JSONResponse(status_code=404, content=_safe_err("Example not found", code="not_found"))
    except Exception as e:
        print(f"ERROR creating project from example: {e}")
        traceback.print_exc()
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to create from example: {e}"))

@app.get("/projects/{project_id}")
async def get_project(project_id: str) -> JSONResponse:
    """Get a specific project by ID."""
    try:
        result = projects.get_project_by_id(project_id)
        if not result:
            # Check if it's an example project
            examples = projects.get_example_projects()
            for example in examples:
                if example["id"] == project_id:
                    result = example
                    break

        if not result:
            return JSONResponse(status_code=404, content=_safe_err("Project not found", code="not_found"))

        # Add document count if RAG is enabled
        if projects.RAG_ENABLED:
            try:
                doc_count = projects.get_project_document_count(project_id)
                result = {**result, "document_count": doc_count}
            except Exception as e:
                print(f"Error getting document count: {e}")
                result = {**result, "document_count": 0}
        else:
            result = {**result, "document_count": 0}

        return JSONResponse(status_code=200, content={"ok": True, "project": result})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to get project: {e}"))

@app.post("/projects/{project_id}/upload", dependencies=[Depends(require_api_key)])
async def upload_to_project(project_id: str, file: UploadFile = File(...)) -> JSONResponse:
    """Upload a file to a project's knowledge base."""
    import time
    try:
        # First, save the file using existing upload logic
        filename = file.filename or "upload.txt"
        ext = os.path.splitext(filename)[1].lower()[:10]

        if ext not in {".pdf", ".txt", ".md"}:
            return JSONResponse(
                status_code=400,
                content=_safe_err("Only PDF, TXT, and MD files are supported", code="invalid_file_type")
            )

        max_bytes = int(MAX_UPLOAD_MB) * 1024 * 1024
        name = f"{uuidlib.uuid4().hex}{ext}"
        path = UPLOAD_PATH / name

        written = 0
        chunk_size = 1024 * 1024  # 1MB

        try:
            with path.open("wb") as f:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        path.unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=413,
                            detail=f"File too large. Max {MAX_UPLOAD_MB}MB.",
                        )
                    f.write(chunk)
        finally:
            await file.close()

        # Process the file and add to vector database
        try:
            from .vectordb import process_and_add_file
            chunks_added = process_and_add_file(project_id, path)

            # Update project metadata with file info
            project = projects.get_project_by_id(project_id)
            if project:
                files_list = project.get("files", [])
                files_list.append({
                    "name": filename,
                    "size": f"{written / 1024 / 1024:.2f} MB",
                    "path": str(path),
                    "chunks": chunks_added
                })

                # Update project
                db = projects._load_projects_db()
                db[project_id]["files"] = files_list
                db[project_id]["updated_at"] = time.time()
                projects._save_projects_db(db)

            return JSONResponse(status_code=201, content={
                "ok": True,
                "filename": filename,
                "size_bytes": written,
                "chunks_added": chunks_added,
                "message": f"File processed and {chunks_added} chunks added to knowledge base"
            })

        except Exception as e:
            # Clean up file if processing failed
            path.unlink(missing_ok=True)
            raise e

    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to upload file: {e}"))

@app.delete("/projects/{project_id}", dependencies=[Depends(require_api_key)])
async def delete_project(project_id: str) -> JSONResponse:
    """Delete a project and its knowledge base."""
    try:
        result = projects.delete_project(project_id)
        if result:
            return JSONResponse(status_code=200, content={"ok": True, "message": "Project deleted successfully"})
        else:
            return JSONResponse(status_code=404, content=_safe_err("Project not found", code="not_found"))
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to delete project: {e}"))

@app.put("/projects/{project_id}", dependencies=[Depends(require_api_key)])
async def update_project(project_id: str, request: Request) -> JSONResponse:
    """Update project details."""
    try:
        data = await request.json()
        result = projects.update_project(project_id, data)
        if result:
            return JSONResponse(status_code=200, content={"ok": True, "project": result})
        else:
            return JSONResponse(status_code=404, content=_safe_err("Project not found", code="not_found"))
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to update project: {e}"))

@app.get("/projects/{project_id}/documents", dependencies=[Depends(require_api_key)])
async def list_project_documents(project_id: str) -> JSONResponse:
    """List documents in a project's knowledge base."""
    try:
        project = projects.get_project_by_id(project_id)
        if not project:
            return JSONResponse(status_code=404, content=_safe_err("Project not found", code="not_found"))

        documents = project.get("files", [])
        return JSONResponse(status_code=200, content={"ok": True, "documents": documents})
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to list documents: {e}"))

@app.delete("/projects/{project_id}/documents/{document_name}", dependencies=[Depends(require_api_key)])
async def delete_project_document(project_id: str, document_name: str) -> JSONResponse:
    """Delete a document from a project's knowledge base."""
    try:
        project = projects.get_project_by_id(project_id)
        if not project:
            return JSONResponse(status_code=404, content=_safe_err("Project not found", code="not_found"))

        # Remove from files list
        files_list = project.get("files", [])
        updated_files = [f for f in files_list if f.get("name") != document_name]

        if len(updated_files) == len(files_list):
            return JSONResponse(status_code=404, content=_safe_err("Document not found", code="not_found"))

        # Delete physical file if exists
        for f in files_list:
            if f.get("name") == document_name and f.get("path"):
                try:
                    Path(f["path"]).unlink(missing_ok=True)
                except Exception as e:
                    print(f"Error deleting file: {e}")

        # Update project
        db = projects._load_projects_db()
        db[project_id]["files"] = updated_files
        db[project_id]["updated_at"] = time.time()
        projects._save_projects_db(db)

        # Note: We can't selectively delete chunks from ChromaDB easily
        # So we inform the user that full re-indexing would be needed
        return JSONResponse(status_code=200, content={
            "ok": True,
            "message": "Document removed from project. Note: For full knowledge base update, delete and re-upload all documents."
        })
    except Exception as e:
        return JSONResponse(status_code=500, content=_safe_err(f"Failed to delete document: {e}"))


# ----------------------------
# Chat & Upload
# ----------------------------

@app.post("/chat", dependencies=[Depends(require_api_key)])
async def chat(inp: ChatIn) -> JSONResponse:
    """
    Unified chat endpoint with mode-aware routing.
    Stable response schema:
      { conversation_id, text, media }
    """
    # Debug: Log incoming imgModel parameter
    print(f"[CHAT ENDPOINT] imgModel received from frontend: '{inp.imgModel}' (type: {type(inp.imgModel).__name__ if inp.imgModel is not None else 'None'})")

    # Build payload for mode-aware handler
    payload = {
        "message": inp.message,
        "conversation_id": inp.conversation_id,
        "project_id": inp.project_id,
        "fun_mode": inp.fun_mode,
        "provider": inp.provider,
        "ollama_base_url": inp.ollama_base_url,
        "ollama_model": inp.ollama_model,
        "provider_base_url": inp.provider_base_url,
        "provider_model": inp.provider_model,
        "llm_base_url": inp.llm_base_url,
        "llm_model": inp.llm_model,
        "textTemperature": inp.textTemperature,
        "textMaxTokens": inp.textMaxTokens,
        "imgWidth": inp.imgWidth,
        "imgHeight": inp.imgHeight,
        "imgSteps": inp.imgSteps,
        "imgCfg": inp.imgCfg,
        "imgSeed": inp.imgSeed,
        "imgModel": inp.imgModel,
        "imgBatchSize": inp.imgBatchSize,
        "vidSeconds": inp.vidSeconds,
        "vidFps": inp.vidFps,
        "vidMotion": inp.vidMotion,
        "vidModel": inp.vidModel,
        "nsfwMode": inp.nsfwMode,
        "promptRefinement": inp.promptRefinement,
        # Reference image for img2img similar generation
        "imgReference": inp.imgReference,
        "imgRefStrength": inp.imgRefStrength,
    }

    # ----------------------------
    # Game Mode: Infinite Variations
    # Works independently of promptRefinement - generates variations of user prompt
    # If promptRefinement is also enabled, the variation will be further refined
    # IMPORTANT: Uses timeout to prevent hanging if Ollama is slow/unresponsive
    # ----------------------------
    if (inp.mode == "imagine") and bool(inp.gameMode):
        # Preserve original message for fallback
        original_message = inp.message

        try:
            options = {
                "strength": float(inp.gameStrength or 0.65),
                "locks": inp.gameLocks or {},
                "world_bible": inp.gameWorldBible or "",
            }

            # Resolve Ollama settings for Game Mode variation generation
            # Fallback chain: explicit ollama fields -> provider fields -> config defaults
            game_ollama_url = (
                inp.ollama_base_url
                or inp.provider_base_url
                or inp.llm_base_url
                or OLLAMA_BASE_URL
            )
            # For model, only use ollama_model or llm_model (NOT provider_model which is image checkpoint)
            game_ollama_model = (
                inp.ollama_model
                or inp.llm_model
                or None  # Let game_mode.py use OLLAMA_MODEL from config
            )

            print(f"[GAME MODE] ollama_base_url={game_ollama_url}, ollama_model={game_ollama_model}")

            # Time-box the LLM call to prevent hanging (15s timeout)
            # If Ollama is slow/unavailable, we fall back to original prompt
            vr = await asyncio.wait_for(
                next_variation(
                    base_prompt=inp.message,
                    session_id=inp.gameSessionId,
                    options=options,
                    ollama_base_url=game_ollama_url,
                    ollama_model=game_ollama_model,
                ),
                timeout=15.0,
            )

            print(f"[GAME MODE] variation_prompt={vr.variation_prompt[:100] if vr.variation_prompt else 'None'}...")

            # Replace the message with the variation prompt
            payload["message"] = vr.variation_prompt

            # Attach game info into payload so we can include it in response media
            payload["_game"] = {
                "enabled": True,
                "session_id": vr.session_id,
                "counter": vr.counter,
                "base_prompt": vr.base_prompt,
                "variation_prompt": vr.variation_prompt,
                "tags": vr.tags,
            }

        except asyncio.TimeoutError:
            # LLM took too long - fall back to original prompt so image still generates
            print(f"[GAME MODE] TIMEOUT: LLM took too long, using original prompt")
            payload["message"] = original_message
            payload["_game"] = {
                "enabled": True,
                "error": "Game Mode LLM timeout - using original prompt",
            }

        except Exception as e:
            # Any other error - fall back to original prompt so image still generates
            print(f"[GAME MODE] ERROR: {e}, using original prompt")
            payload["message"] = original_message
            payload["_game"] = {
                "enabled": True,
                "error": str(e),
            }

    # Route through mode-aware handler
    out = await handle_request(mode=inp.mode, payload=payload)

    # Merge game metadata into media (if present)
    game_meta = payload.get("_game")
    if isinstance(game_meta, dict):
        if out.get("media") is None:
            out["media"] = {}
        if isinstance(out.get("media"), dict):
            out["media"]["game"] = game_meta

    if not isinstance(out, dict):
        out = {}

    cid = out.get("conversation_id") or inp.conversation_id or str(uuidlib.uuid4())

    text = out.get("text")
    if not isinstance(text, str) or not text.strip():
        text = "…"

    media = out.get("media", None)
    if media is not None and not isinstance(media, dict):
        media = None

    return JSONResponse(
        status_code=200,
        content={"conversation_id": cid, "text": text, "media": media},
    )


@app.post("/upload", dependencies=[Depends(require_api_key)])
async def upload(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    """
    Stream uploads to disk (avoid reading entire file in memory).
    """
    filename = file.filename or "upload.png"
    ext = os.path.splitext(filename)[1].lower()[:10]
    if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
        ext = ".png"

    max_bytes = int(MAX_UPLOAD_MB) * 1024 * 1024
    name = f"{uuidlib.uuid4().hex}{ext}"
    path = UPLOAD_PATH / name

    written = 0
    chunk_size = 1024 * 1024  # 1MB

    try:
        with path.open("wb") as f:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Max {MAX_UPLOAD_MB}MB.",
                    )
                f.write(chunk)
    finally:
        await file.close()

    base = _base_url_from_request(request)
    return JSONResponse(status_code=201, content={"url": f"{base}/files/{name}"})


# ----------------------------
# Game Mode API
# ----------------------------

@app.get("/game/sessions/{session_id}/events", dependencies=[Depends(require_api_key)])
async def game_session_events(session_id: str, limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    """
    Fetch variation history for a game session.
    Returns chronological list of generated variations with their tags.
    """
    try:
        events = get_session_events(session_id, limit=limit)
        return JSONResponse(status_code=200, content={"ok": True, "session_id": session_id, "events": events})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


# ----------------------------
# Story Mode API (Studio)
# ----------------------------

class StoryStartIn(BaseModel):
    premise: str = Field(..., min_length=3, max_length=4000)
    title_hint: str = Field("", max_length=200)
    options: Optional[Dict[str, Any]] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None


class StoryNextIn(BaseModel):
    session_id: str
    refine_image_prompt: Optional[bool] = None
    tts_enabled: Optional[bool] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None


@app.post("/story/start", dependencies=[Depends(require_api_key)])
async def story_start_endpoint(inp: StoryStartIn) -> JSONResponse:
    """
    Start a story session. Returns session_id + story bible.
    """
    try:
        res = await start_story(
            inp.premise,
            title_hint=inp.title_hint,
            options=inp.options,
            ollama_base_url=inp.ollama_base_url,
            ollama_model=inp.ollama_model,
        )
        return JSONResponse(status_code=200, content=res.model_dump())
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


class StoryContinueIn(BaseModel):
    previous_session_id: str
    title_hint: str = ""
    direction_hint: str = ""
    options: Optional[Dict[str, Any]] = None
    ollama_base_url: Optional[str] = None
    ollama_model: Optional[str] = None


@app.post("/story/continue", dependencies=[Depends(require_api_key)])
async def story_continue_endpoint(inp: StoryContinueIn) -> JSONResponse:
    """
    Continue a story as the next chapter in a saga.
    Uses the previous story's ending as the starting point.
    Returns new session_id + chapter bible.
    """
    try:
        res = await continue_story(
            inp.previous_session_id,
            title_hint=inp.title_hint,
            direction_hint=inp.direction_hint,
            options=inp.options,
            ollama_base_url=inp.ollama_base_url,
            ollama_model=inp.ollama_model,
        )
        return JSONResponse(status_code=200, content=res.model_dump())
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.post("/story/next", dependencies=[Depends(require_api_key)])
async def story_next_endpoint(inp: StoryNextIn) -> JSONResponse:
    """
    Generate next scene (narration + image prompt).
    Frontend then calls image generation with scene.image_prompt.
    """
    try:
        res = await next_scene(
            session_id=inp.session_id,
            refine_image_prompt=inp.refine_image_prompt,
            tts_enabled=inp.tts_enabled,
            ollama_base_url=inp.ollama_base_url,
            ollama_model=inp.ollama_model,
        )
        return JSONResponse(status_code=200, content=res.model_dump())
    except ValueError as e:
        error_msg = str(e)
        # Check if this is a "story complete" error
        if "Story complete" in error_msg or "scenes have been generated" in error_msg:
            return JSONResponse(
                status_code=200,
                content={"ok": True, "story_complete": True, "message": error_msg}
            )
        return JSONResponse(status_code=400, content={"ok": False, "error": error_msg})
    except Exception as e:
        return JSONResponse(status_code=400, content={"ok": False, "error": str(e)})


@app.get("/story/{session_id}", dependencies=[Depends(require_api_key)])
async def story_get_endpoint(session_id: str) -> JSONResponse:
    """
    Get story bible + scenes so far (for TV playback UI).
    """
    try:
        data = get_story(session_id)
        return JSONResponse(status_code=200, content=data)
    except Exception as e:
        return JSONResponse(status_code=404, content={"ok": False, "error": str(e)})


@app.get("/story/sessions/list", dependencies=[Depends(require_api_key)])
async def story_list_endpoint(limit: int = Query(50, ge=1, le=200)) -> JSONResponse:
    """
    List all story sessions.
    """
    try:
        sessions = list_story_sessions(limit=limit)
        return JSONResponse(status_code=200, content={"ok": True, "sessions": sessions})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.delete("/story/{session_id}", dependencies=[Depends(require_api_key)])
async def story_delete_endpoint(session_id: str) -> JSONResponse:
    """
    Delete a story session and all its scenes.
    """
    try:
        deleted = delete_story_session(session_id)
        return JSONResponse(status_code=200, content={"ok": True, "deleted": deleted})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.delete("/story/{session_id}/scene/{scene_idx}", dependencies=[Depends(require_api_key)])
async def story_delete_scene_endpoint(session_id: str, scene_idx: int) -> JSONResponse:
    """
    Delete a single scene from a story session. Remaining scenes will be re-indexed.
    """
    try:
        deleted = delete_scene(session_id, scene_idx)
        if deleted:
            return JSONResponse(status_code=200, content={"ok": True, "deleted": True})
        else:
            return JSONResponse(status_code=404, content={"ok": False, "error": "Scene not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


class UpdateSceneImageIn(BaseModel):
    session_id: str
    scene_idx: int
    image_url: str


@app.post("/story/scene/image", dependencies=[Depends(require_api_key)])
async def story_update_scene_image(inp: UpdateSceneImageIn) -> JSONResponse:
    """
    Update a scene's image_url after image generation.
    This persists the image URL so it's available after page reload.
    """
    try:
        success = update_scene_image(inp.session_id, inp.scene_idx, inp.image_url)
        if success:
            return JSONResponse(status_code=200, content={"ok": True})
        else:
            return JSONResponse(status_code=404, content={"ok": False, "error": "Scene not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


# =============================================================================
# EDIT SESSION PROXY ROUTES
# =============================================================================
# These routes proxy requests to the edit-session sidecar service.
# This allows the frontend to use a single backend URL for all requests.
# =============================================================================

# Create a shared httpx client for edit-session proxy
_edit_session_client: Optional[httpx.AsyncClient] = None


def get_edit_session_client() -> httpx.AsyncClient:
    """Get or create the shared httpx client for edit-session proxy."""
    global _edit_session_client
    if _edit_session_client is None:
        _edit_session_client = httpx.AsyncClient(
            base_url=EDIT_SESSION_URL,
            timeout=httpx.Timeout(60.0, connect=5.0),
        )
    return _edit_session_client


@app.on_event("shutdown")
async def close_edit_session_client():
    """Clean up the httpx client on shutdown."""
    global _edit_session_client
    if _edit_session_client is not None:
        await _edit_session_client.aclose()
        _edit_session_client = None


async def _proxy_to_edit_session(
    request: Request,
    path: str,
    method: str = "GET",
) -> JSONResponse:
    """
    Proxy a request to the edit-session sidecar service.
    Forwards headers, query params, and body to the sidecar.
    """
    client = get_edit_session_client()

    # Build URL with query params
    url = f"/v1/edit-sessions/{path}"
    if request.query_params:
        url += f"?{request.query_params}"

    # Forward relevant headers
    headers = {}
    if "authorization" in request.headers:
        headers["authorization"] = request.headers["authorization"]
    if "x-api-key" in request.headers:
        headers["x-api-key"] = request.headers["x-api-key"]
    if "content-type" in request.headers:
        headers["content-type"] = request.headers["content-type"]

    try:
        # Get request body for non-GET requests
        body = None
        if method in ("POST", "PUT", "PATCH"):
            body = await request.body()

        # Make the proxied request
        response = await client.request(
            method=method,
            url=url,
            headers=headers,
            content=body,
        )

        # Return the response
        return JSONResponse(
            status_code=response.status_code,
            content=response.json() if response.content else None,
        )

    except httpx.ConnectError:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "Edit session service unavailable",
                "detail": f"Cannot connect to edit-session service at {EDIT_SESSION_URL}",
                "code": "edit_session_unavailable",
            },
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={
                "ok": False,
                "error": "Edit session service timeout",
                "code": "edit_session_timeout",
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"Edit session proxy error: {str(e)}",
                "code": "edit_session_proxy_error",
            },
        )


@app.get("/v1/edit-sessions/{conversation_id}")
async def get_edit_session(request: Request, conversation_id: str) -> JSONResponse:
    """Get current state of an edit session (proxied to sidecar)."""
    return await _proxy_to_edit_session(request, conversation_id, "GET")


@app.delete("/v1/edit-sessions/{conversation_id}")
async def delete_edit_session(request: Request, conversation_id: str) -> JSONResponse:
    """Delete/clear an edit session (proxied to sidecar)."""
    return await _proxy_to_edit_session(request, conversation_id, "DELETE")


@app.post("/v1/edit-sessions/{conversation_id}/image")
async def upload_edit_image(request: Request, conversation_id: str) -> JSONResponse:
    """
    Upload an image to start/update an edit session (proxied to sidecar).
    Handles multipart form data.
    """
    client = get_edit_session_client()
    url = f"/v1/edit-sessions/{conversation_id}/image"

    # Forward headers
    headers = {}
    if "authorization" in request.headers:
        headers["authorization"] = request.headers["authorization"]
    if "x-api-key" in request.headers:
        headers["x-api-key"] = request.headers["x-api-key"]

    try:
        # For file uploads, we need to forward the raw body with content-type
        body = await request.body()
        content_type = request.headers.get("content-type", "")

        response = await client.post(
            url,
            content=body,
            headers={**headers, "content-type": content_type},
        )

        return JSONResponse(
            status_code=response.status_code,
            content=response.json() if response.content else None,
        )

    except httpx.ConnectError:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "Edit session service unavailable",
                "detail": f"Cannot connect to edit-session service at {EDIT_SESSION_URL}",
                "code": "edit_session_unavailable",
            },
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": f"Edit session proxy error: {str(e)}",
                "code": "edit_session_proxy_error",
            },
        )


@app.post("/v1/edit-sessions/{conversation_id}/message")
async def send_edit_message(request: Request, conversation_id: str) -> JSONResponse:
    """Send an edit instruction message (proxied to sidecar)."""
    return await _proxy_to_edit_session(request, f"{conversation_id}/message", "POST")


@app.post("/v1/edit-sessions/{conversation_id}/select")
async def select_edit_image(request: Request, conversation_id: str) -> JSONResponse:
    """Select an image from results as the new active image (proxied to sidecar)."""
    return await _proxy_to_edit_session(request, f"{conversation_id}/select", "POST")


@app.post("/v1/edit-sessions/{conversation_id}/revert")
async def revert_edit_session(request: Request, conversation_id: str) -> JSONResponse:
    """Revert to a previous state in the edit session history (proxied to sidecar)."""
    return await _proxy_to_edit_session(request, f"{conversation_id}/revert", "POST")