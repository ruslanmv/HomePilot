"""Edit sessions when the edit-session sidecar is not running.

The hosted Space has no sidecar and no ComfyUI. A linked Hugging Face account
(or the Space's own token) redraws the active picture from the instruction.
The JSON matches the sidecar so the Edit tab does not change its calls.
Brush masks, outpaint, and background replace stay on a computer with a GPU.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi.responses import JSONResponse


class _Version:
    def __init__(self, url: str, instruction: str, parent_url: Optional[str]) -> None:
        self.url = url
        self.instruction = instruction
        self.created_at = time.time()
        self.parent_url = parent_url
        self.settings: Dict[str, Any] = {}


class _Session:
    def __init__(self) -> None:
        self.active_image_url: Optional[str] = None
        self.original_image_url: Optional[str] = None
        self.versions: List[_Version] = []

    @property
    def history(self) -> List[str]:
        return [v.url for v in self.versions]


_sessions: Dict[str, _Session] = {}


def active() -> bool:
    """Use this store instead of the sidecar."""
    from .connectors.huggingface import hosted_media
    return hosted_media()


def _session(conversation_id: str) -> _Session:
    rec = _sessions.get(conversation_id)
    if rec is None:
        rec = _Session()
        _sessions[conversation_id] = rec
    return rec


def _public(conversation_id: str, rec: _Session) -> Dict[str, Any]:
    return {
        "conversation_id": conversation_id,
        "active_image_url": rec.active_image_url,
        "original_image_url": rec.original_image_url,
        "versions": [
            {
                "url": v.url,
                "instruction": v.instruction,
                "created_at": v.created_at,
                "parent_url": v.parent_url,
                "settings": v.settings,
            }
            for v in rec.versions
        ],
        "history": rec.history,
    }


def _push(rec: _Session, url: str, instruction: str, parent_url: Optional[str]) -> None:
    rec.versions.insert(0, _Version(url, instruction, parent_url))
    rec.versions = rec.versions[:20]
    rec.active_image_url = url
    if not rec.original_image_url:
        rec.original_image_url = url


def _user_id() -> str:
    from .connectors.context import current_user_id
    return current_user_id() or ""


async def _store_bytes(raw: bytes, mime: str, conversation_id: str) -> str:
    from .files import save_generated_media_as_asset
    asset = save_generated_media_as_asset(
        _user_id(), raw, mime or "image/png", "image", conversation_id=conversation_id,
    )
    return asset["url"]


async def upload(request, conversation_id: str) -> JSONResponse:
    """POST /v1/edit-sessions/{id}/image — file upload or a JSON image_url."""
    content_type = request.headers.get("content-type", "")
    rec = _session(conversation_id)
    instruction = ""
    if "application/json" in content_type:
        body = await request.json()
        image_url = (body.get("image_url") or "").strip()
        if not image_url:
            return JSONResponse(status_code=400, content={"ok": False, "error": "image_url is required"})
        from .files import _upload_root
        from .multimodal import _load_image_bytes
        try:
            raw, mime = await _load_image_bytes(image_url, _upload_root())
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(status_code=404, content={"ok": False, "error": f"Image not found ({exc})"})
        url = await _store_bytes(raw, mime, conversation_id)
    else:
        form = await request.form()
        upload_file = form.get("file")
        if upload_file is None or not hasattr(upload_file, "read"):
            return JSONResponse(status_code=400, content={"ok": False, "error": "file is required"})
        raw = await upload_file.read()
        if not raw:
            return JSONResponse(status_code=400, content={"ok": False, "error": "file is empty"})
        mime = getattr(upload_file, "content_type", None) or "image/png"
        instruction = str(form.get("instruction") or "")
        url = await _store_bytes(raw, mime, conversation_id)
    parent = rec.active_image_url
    _push(rec, url, "[Original Upload]", parent)
    body_out = _public(conversation_id, rec)
    if instruction.strip():
        edited = await _apply(conversation_id, instruction, model="")
        body_out = _public(conversation_id, rec)
        body_out["result"] = edited
    return JSONResponse(status_code=200, content=body_out)


async def _apply(conversation_id: str, message: str, model: str) -> Dict[str, Any]:
    from .connectors.huggingface import edit_picture

    rec = _session(conversation_id)
    if not rec.active_image_url:
        return {"ok": False, "error": "No active image. Upload an image first."}
    drawn = await edit_picture(
        user_id=_user_id() or None,
        model=model,
        image_url=rec.active_image_url,
        prompt=message,
    )
    if drawn.get("url"):
        _push(rec, drawn["url"], message.strip() or "edit", rec.active_image_url)
    return {
        "text": drawn.get("text") or "",
        "media": {"images": [drawn["url"]]} if drawn.get("url") else None,
        "provider": "huggingface",
    }


async def dispatch(request, path: str, method: str) -> JSONResponse:
    """GET/DELETE/POST under /v1/edit-sessions/{path}."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return JSONResponse(status_code=404, content={"ok": False, "error": "Missing conversation"})
    conversation_id, action = parts[0], parts[1] if len(parts) > 1 else ""
    rec = _session(conversation_id)

    if method == "GET" and not action:
        return JSONResponse(status_code=200, content=_public(conversation_id, rec))
    if method == "DELETE" and not action:
        _sessions.pop(conversation_id, None)
        return JSONResponse(status_code=200, content={"ok": True})
    if method == "DELETE" and action == "version":
        image_url = request.query_params.get("image_url") or ""
        rec.versions = [v for v in rec.versions if v.url != image_url]
        if rec.active_image_url == image_url:
            rec.active_image_url = rec.versions[0].url if rec.versions else None
        return JSONResponse(status_code=200, content={"ok": True, **_public(conversation_id, rec)})
    if method == "POST" and action == "message":
        body = await request.json()
        message = str(body.get("message") or "")
        model = str(body.get("model") or "")
        if not rec.active_image_url:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "No active image. Upload an image first."},
            )
        raw = await _apply(conversation_id, message, model)
        if not (raw.get("media") or {}).get("images"):
            return JSONResponse(status_code=502, content={"ok": False, "error": raw.get("text") or "Edit failed"})
        return JSONResponse(status_code=200, content={"raw": raw})
    if method == "POST" and action == "select":
        body = await request.json()
        image_url = str(body.get("image_url") or "")
        if not image_url:
            return JSONResponse(status_code=400, content={"ok": False, "error": "image_url is required"})
        known = next((v for v in rec.versions if v.url == image_url), None)
        _push(rec, image_url, known.instruction if known else "[Selected as base]", rec.active_image_url)
        return JSONResponse(status_code=200, content=_public(conversation_id, rec))
    if method == "POST" and action == "revert":
        try:
            index = int(request.query_params.get("index") or 0)
        except ValueError:
            index = 0
        if not rec.versions:
            return JSONResponse(status_code=400, content={"ok": False, "error": "Nothing to revert to"})
        index = max(0, min(index, len(rec.versions) - 1))
        chosen = rec.versions[index]
        rec.active_image_url = chosen.url
        return JSONResponse(status_code=200, content=_public(conversation_id, rec))
    return JSONResponse(status_code=404, content={"ok": False, "error": "Unknown edit action"})
