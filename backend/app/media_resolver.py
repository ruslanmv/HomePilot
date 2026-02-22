"""
media:// URI resolver.

Instead of asking the LLM to reproduce long /files/... URLs (which it
truncates, wraps, or hallucinates), we give it short stable refs like:

    media://persona/<project_id>/default
    media://persona/<project_id>/label/Lingerie

This endpoint resolves them and serves the image file directly with
cache headers so the browser doesn't re-fetch on every React render.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote

from fastapi import APIRouter, Cookie, Header, HTTPException, Query
from fastapi.responses import FileResponse

from .config import PUBLIC_BASE_URL, UPLOAD_DIR
from .projects import get_project_by_id, _file_url_exists

router = APIRouter(tags=["media"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _abs_img_url(url: str) -> str:
    """Convert relative /files/... to absolute using PUBLIC_BASE_URL."""
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    base = (PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
    return f"{base}{url if url.startswith('/') else '/' + url}"


def _upload_root() -> Path:
    """Return the upload root directory (same as files.py)."""
    p = Path(UPLOAD_DIR)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[1] / "data" / "uploads"
    return p


def _url_to_local_path(url: str) -> Optional[Path]:
    """
    Convert a resolved absolute URL back to a local filesystem path.
    Works for /files/ URLs (the committed avatar paths).
    """
    idx = url.find("/files/")
    if idx < 0:
        # Try /comfy/view/ URLs — these are proxied, can't serve locally
        return None
    rel = url[idx + len("/files/"):]
    if not rel or ".." in rel:
        return None
    path = _upload_root() / rel
    if path.is_file():
        return path
    return None


def _resolve_user(
    authorization: str,
    homepilot_session: Optional[str],
    token_param: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Same logic as files.py: header / cookie / query-token auth."""
    from .users import ensure_users_tables, get_current_user, _validate_token
    ensure_users_tables()
    user = get_current_user(
        authorization=authorization,
        homepilot_session=homepilot_session,
    )
    if user:
        return user
    if token_param:
        return _validate_token(token_param)
    return None


def _build_label_index(project_id: str) -> Dict[str, str]:
    """
    Build a deterministic mapping:
        "default"        -> absolute image URL
        "label:<Label>"  -> absolute image URL

    Uses the same data path as build_persona_context in projects.py.
    """
    project_data = get_project_by_id(project_id)
    if not project_data:
        raise HTTPException(status_code=404, detail="Project not found")
    if project_data.get("project_type") != "persona":
        raise HTTPException(status_code=400, detail="Not a persona project")

    pap = project_data.get("persona_appearance") or {}
    selected = pap.get("selected") or {}
    sel_set_id = selected.get("set_id", "")
    sel_image_id = selected.get("image_id", "")

    _committed_file = pap.get("selected_filename", "")
    _committed_url = _abs_img_url(f"/files/{_committed_file}") if _committed_file else ""

    mapping: Dict[str, str] = {}
    default_url = ""

    # --- portrait sets ---
    for s in pap.get("sets") or []:
        for img in s.get("images") or []:
            url = img.get("url", "")
            if not url:
                continue
            full_url = _abs_img_url(url)
            is_default = (
                img.get("id") == sel_image_id
                and (img.get("set_id", s.get("set_id", "")) == sel_set_id)
            )
            if is_default and _committed_url:
                full_url = _committed_url
            if not _file_url_exists(full_url):
                continue
            label = "Default Look" if is_default else "Portrait"
            mapping.setdefault(f"label:{label}", full_url)
            if is_default:
                default_url = full_url

    # --- outfit variations ---
    for outfit in pap.get("outfits") or []:
        o_label = outfit.get("label", "Outfit")
        for img in outfit.get("images") or []:
            url = img.get("url", "")
            if not url:
                continue
            full_url = _abs_img_url(url)
            is_default = (
                img.get("id") == sel_image_id
                and img.get("set_id", "") == sel_set_id
            )
            if is_default and _committed_url:
                full_url = _committed_url
            if not _file_url_exists(full_url):
                continue
            mapping.setdefault(f"label:{o_label}", full_url)
            if is_default:
                default_url = full_url

    # fallback default
    if not default_url:
        for v in mapping.values():
            default_url = v
            break
    if default_url:
        mapping["default"] = default_url

    return mapping


def _resolve_ref(ref: str) -> str:
    """Parse a media:// ref and return the resolved absolute image URL."""
    ref = unquote(ref)
    if not ref.startswith("media://"):
        raise HTTPException(status_code=400, detail="Invalid ref — must start with media://")

    parts = ref.replace("media://", "").split("/")
    if len(parts) < 3:
        raise HTTPException(status_code=400, detail="Invalid ref format")

    kind, project_id, action = parts[0], parts[1], parts[2]
    if kind != "persona":
        raise HTTPException(status_code=404, detail="Unknown media kind")

    idx = _build_label_index(project_id)

    if action == "default":
        url = idx.get("default")
        if not url:
            raise HTTPException(status_code=404, detail="No default image")
        return url

    if action == "label":
        if len(parts) < 4:
            raise HTTPException(status_code=400, detail="Missing label")
        label = "/".join(parts[3:])
        url = idx.get(f"label:{label}")
        if not url:
            raise HTTPException(status_code=404, detail=f"Label '{label}' not found")
        return url

    raise HTTPException(status_code=404, detail="Unknown action")


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/media/resolve")
def resolve_media(
    ref: str = Query(..., description="media://persona/<project_id>/default or media://persona/<project_id>/label/<Label>"),
    token: Optional[str] = Query(default=None),
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
):
    """
    Resolve a media:// ref and serve the image file directly.
    Uses FileResponse with cache headers so the browser doesn't re-fetch
    on every React re-render (prevents image blinking).
    """
    user = _resolve_user(authorization, homepilot_session, token_param=token)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    url = _resolve_ref(ref)

    # Try to serve file directly from disk (fast, cacheable)
    local_path = _url_to_local_path(url)
    if local_path:
        mime = mimetypes.guess_type(str(local_path))[0] or "image/png"
        return FileResponse(
            path=str(local_path),
            media_type=mime,
            filename=local_path.name,
            headers={
                "Cache-Control": "private, max-age=3600, immutable",
            },
        )

    # Fallback: redirect to the URL (e.g. ComfyUI proxied images)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url, headers={"Cache-Control": "private, max-age=3600"})
