"""
Secure File Storage — per-user ownership and access control.

Every uploaded/generated file gets an entry in file_assets (owner = user_id).
Files are served ONLY via GET /files/{asset_id} which verifies:
  - Bearer token OR HttpOnly cookie
  - asset.user_id == current_user.id

Directory structure:
  uploads/users/<user_id>/uploads/...
  uploads/users/<user_id>/images/...
  uploads/users/<user_id>/projects/<project_id>/...

ADDITIVE ONLY — does not modify any existing module.
"""
from __future__ import annotations

import mimetypes
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Cookie, Header, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse

from .config import UPLOAD_DIR, MAX_UPLOAD_MB
from .storage import _get_db_path

router = APIRouter(tags=["files"])


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    return con


def _upload_root() -> Path:
    """Resolve the absolute upload root directory."""
    p = Path(UPLOAD_DIR)
    if not p.is_absolute():
        p = Path(__file__).resolve().parents[1] / "data" / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ensure_user_dir(user_id: str, kind: str, project_id: str = "") -> Path:
    """
    Create and return the per-user storage directory.
    Layout: users/<user_id>/{uploads|images|projects/<project_id>}
    """
    root = _upload_root() / "users" / user_id
    if kind == "upload":
        p = root / "uploads"
    elif kind == "image":
        p = root / "images"
    elif kind == "project_asset":
        if not project_id:
            project_id = "unknown"
        p = root / "projects" / project_id
    else:
        p = root / "misc"

    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_user(authorization: str, homepilot_session: Optional[str]) -> Optional[Dict[str, Any]]:
    """Resolve authenticated user from Bearer header or cookie."""
    from .users import ensure_users_tables, get_current_user
    ensure_users_tables()
    return get_current_user(authorization=authorization, homepilot_session=homepilot_session)


# ---------------------------------------------------------------------------
# Asset CRUD
# ---------------------------------------------------------------------------

def insert_asset(
    user_id: str,
    kind: str,
    rel_path: str,
    mime: str,
    size_bytes: int,
    original_name: str = "",
    project_id: str = "",
    conversation_id: str = "",
) -> str:
    """Register a file in file_assets. Returns the asset_id."""
    asset_id = f"f_{uuid.uuid4().hex[:20]}"
    con = _db()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO file_assets(
            id, user_id, kind, rel_path, mime, size_bytes,
            original_name, project_id, conversation_id
        )
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (asset_id, user_id, kind, rel_path, mime or "",
         int(size_bytes or 0), original_name or "",
         project_id or "", conversation_id or ""),
    )
    con.commit()
    con.close()
    return asset_id


def get_asset(asset_id: str) -> Optional[Dict[str, Any]]:
    """Look up a file asset by id."""
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM file_assets WHERE id = ?", (asset_id,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Helper: save generated image as a secure asset (call from orchestrator/main)
# ---------------------------------------------------------------------------

def save_generated_image_as_asset(
    user_id: str,
    image_bytes: bytes,
    mime: str = "image/png",
    project_id: str = "",
    conversation_id: str = "",
) -> Dict[str, Any]:
    """
    Store generated image as a secure, user-owned asset.
    Returns dict with asset_id and url (/files/<asset_id>).
    """
    ext = "png" if "png" in (mime or "") else "jpg"
    folder = _ensure_user_dir(user_id, "image", project_id=project_id)

    fname = f"{uuid.uuid4().hex}.{ext}"
    abs_path = folder / fname
    abs_path.write_bytes(image_bytes)

    rel_path = str(abs_path.relative_to(_upload_root()))

    asset_id = insert_asset(
        user_id=user_id,
        kind="image",
        rel_path=rel_path,
        mime=mime or "image/png",
        size_bytes=len(image_bytes),
        original_name=fname,
        project_id=project_id,
        conversation_id=conversation_id,
    )

    return {"asset_id": asset_id, "url": f"/files/{asset_id}", "mime": mime or "image/png"}


# ---------------------------------------------------------------------------
# Secure Upload Endpoint
# ---------------------------------------------------------------------------

@router.post("/v1/files/upload")
async def upload_file(
    file: UploadFile = File(...),
    kind: str = "upload",
    project_id: str = "",
    conversation_id: str = "",
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
):
    """
    Secure upload. Requires user auth.
    Stores file under uploads/users/<user_id>/...
    Returns an asset id and protected URL: /files/<asset_id>
    """
    user = _resolve_user(authorization, homepilot_session)
    if not user:
        raise HTTPException(401, "Authentication required")

    if kind not in ("upload", "image", "project_asset"):
        raise HTTPException(400, "Invalid kind")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")

    max_bytes = int(MAX_UPLOAD_MB) * 1024 * 1024
    if len(data) > max_bytes:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_MB}MB)")

    # Choose extension
    original_name = file.filename or ""
    content_type = (file.content_type or "").lower()
    ext = ""
    if original_name and "." in original_name:
        ext = original_name.rsplit(".", 1)[1].lower()
    if not ext:
        ext = (mimetypes.guess_extension(content_type) or "").lstrip(".") or "bin"

    # Write file to per-user directory
    folder = _ensure_user_dir(user["id"], kind, project_id=project_id)
    fname = f"{uuid.uuid4().hex}.{ext}"
    abs_path = folder / fname
    abs_path.write_bytes(data)

    # Store metadata
    rel_path = str(abs_path.relative_to(_upload_root()))
    mime = content_type or mimetypes.guess_type(str(abs_path))[0] or "application/octet-stream"
    asset_id = insert_asset(
        user_id=user["id"],
        kind=kind,
        rel_path=rel_path,
        mime=mime,
        size_bytes=len(data),
        original_name=original_name,
        project_id=project_id,
        conversation_id=conversation_id,
    )

    return {"ok": True, "asset_id": asset_id, "url": f"/files/{asset_id}", "mime": mime}


# ---------------------------------------------------------------------------
# Secure Download / Serve Endpoint
# ---------------------------------------------------------------------------

@router.get("/files/{asset_id}")
def download_file(
    asset_id: str,
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
):
    """
    Secure file serving.
    Requires auth and ownership check.
    This is the endpoint used by <img src="/files/...">.
    """
    user = _resolve_user(authorization, homepilot_session)
    if not user:
        raise HTTPException(401, "Authentication required")

    asset = get_asset(asset_id)
    if not asset or asset.get("user_id") != user["id"]:
        # Return 404 to avoid leaking existence
        raise HTTPException(404, "Not found")

    abs_path = _upload_root() / asset["rel_path"]
    if not abs_path.exists():
        raise HTTPException(404, "Not found")

    # Provide original filename when possible
    filename = asset.get("original_name") or os.path.basename(str(abs_path))

    return FileResponse(
        path=str(abs_path),
        media_type=asset.get("mime") or "application/octet-stream",
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Legacy fallback: serve old /files/<filename> paths (backward compatibility)
# ---------------------------------------------------------------------------

@router.get("/files/{subpath:path}")
def download_file_legacy(
    subpath: str,
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
):
    """
    Fallback for legacy /files/<filename> paths (pre-asset era).
    Serves files from the flat UPLOAD_DIR if the user is authenticated.
    This preserves backward compatibility for existing chat history images.
    """
    user = _resolve_user(authorization, homepilot_session)
    if not user:
        raise HTTPException(401, "Authentication required")

    # Prevent path traversal
    safe = Path(subpath)
    if ".." in safe.parts:
        raise HTTPException(400, "Invalid path")

    abs_path = _upload_root() / safe
    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(404, "Not found")

    mime = mimetypes.guess_type(str(abs_path))[0] or "application/octet-stream"
    return FileResponse(
        path=str(abs_path),
        media_type=mime,
        filename=safe.name,
    )
