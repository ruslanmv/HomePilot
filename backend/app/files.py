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

import hashlib
import mimetypes
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Cookie, Header, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from .config import UPLOAD_DIR, MAX_UPLOAD_MB  # noqa: F401  (UPLOAD_DIR: kept for importers)
from . import media_links, media_ops, media_quota, media_validate
from .media_storage import (StorageKeyError, backend_name, get_storage, local_storage, normalize_key,
                            storage_for_read, storage_named)
from .media_storage import upload_root as _storage_root
from .storage import _get_db_path, ensure_file_assets_columns

# Cache headers for served files — prevents image flickering on React re-renders.
# Uploaded images are immutable (content-addressed), so long max-age is safe.
_FILE_CACHE_HEADERS = {"Cache-Control": "private, max-age=3600, immutable"}

router = APIRouter(tags=["files"])


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    return con


def _upload_root() -> Path:
    """The local upload root (media_storage.upload_root), created. The legacy path-based
    routes below read this disk directly; everything registered goes through get_storage()."""
    p = _storage_root()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _user_key(user_id: str, kind: str, project_id: str = "") -> str:
    """Where a user's files go, as a storage-key prefix:
    users/<user_id>/{uploads|images|projects/<project_id>|misc}."""
    if kind == "upload":
        sub = "uploads"
    elif kind == "image":
        sub = "images"
    elif kind == "project_asset":
        sub = f"projects/{project_id or 'unknown'}"
    else:
        sub = "misc"
    return f"users/{user_id}/{sub}"


def _ensure_user_dir(user_id: str, kind: str, project_id: str = "") -> Path:
    """The per-user directory on the local disk (kept for callers that still write paths)."""
    p = _upload_root() / _user_key(user_id, kind, project_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _resolve_user(
    authorization: str,
    homepilot_session: Optional[str],
    token_param: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Resolve authenticated user from Bearer header, cookie, or query token.
    The query token fallback is needed for <img> tags which can't set headers.

    Also accepts the OllaBridge compat API key (from auth.py) so that
    server-to-server media proxy requests can fetch non-public files
    (e.g. outfit images that don't start with 'avatar_').
    """
    from .users import ensure_users_tables, get_current_user
    ensure_users_tables()
    # Try header/cookie first
    user = get_current_user(authorization=authorization, homepilot_session=homepilot_session)
    if user:
        return user
    # Fallback: query parameter token (for <img> tags)
    if token_param:
        from .users import _validate_token
        result = _validate_token(token_param)
        if result:
            return result

    # Fallback: accept the compat API key (X-API-Key header or Bearer token
    # or ?token= param).  This allows OllaBridge's media proxy to fetch
    # non-public files (outfit images, view-pack angles) without needing a
    # real user session.
    from . import config as _cfg
    api_key = _cfg.API_KEY
    if api_key:
        _synthetic_user = {"id": "__api__", "username": "api"}
        # Check Authorization header
        if authorization:
            parts = authorization.split(" ", 1)
            if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip() == api_key:
                return _synthetic_user
        # Check ?token= param against API key
        if token_param and token_param.strip() == api_key:
            return _synthetic_user

    return None


# ---------------------------------------------------------------------------
# Asset CRUD
# ---------------------------------------------------------------------------

_backend_column_checked = False


def _ensure_backend_column(con: sqlite3.Connection) -> None:
    """The storage_backend column is added at startup (storage.init_db); a database opened
    without that — a test, a script — gets it here, once per process."""
    global _backend_column_checked
    if not _backend_column_checked:
        ensure_file_assets_columns(con)
        _backend_column_checked = True


def _now() -> str:
    """UTC, the way SQLite's CURRENT_TIMESTAMP writes it."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def _store_for(backend: Optional[str], key: str):
    """The storage holding ``key``: the one a registry row names, or — for a key with no row —
    whichever has it (media_storage.storage_for_read). None when the row names a backend this
    HomePilot is not configured for."""
    return storage_named(backend) if backend else storage_for_read(key)


def insert_asset(
    user_id: str,
    kind: str,
    rel_path: str,
    mime: str,
    size_bytes: int,
    original_name: str = "",
    project_id: str = "",
    conversation_id: str = "",
    storage_backend: Optional[str] = None,
    sha256: str = "",
    visibility: str = "private",
) -> str:
    """Register a file in file_assets. Returns the asset_id.

    ``storage_backend`` is the media backend that holds the bytes — the configured one when
    not given, which is where every writer in this module just put them. ``sha256`` is of
    the bytes as written ('' when the caller did not hash them); ``visibility`` is
    'private' (owner, signed link or API key) or 'public' (anyone)."""
    asset_id = f"f_{uuid.uuid4().hex[:20]}"
    backend = (storage_backend or get_storage().name).strip().lower()
    visibility = "public" if visibility == "public" else "private"
    con = _db()
    _ensure_backend_column(con)
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO file_assets(
            id, user_id, kind, rel_path, mime, size_bytes,
            original_name, project_id, conversation_id, storage_backend, sha256, visibility
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (asset_id, user_id, kind, rel_path, mime or "",
         int(size_bytes or 0), original_name or "",
         project_id or "", conversation_id or "", backend, sha256 or "", visibility),
    )
    con.commit()
    con.close()
    return asset_id


def get_asset(asset_id: str, include_deleted: bool = False) -> Optional[Dict[str, Any]]:
    """Look up a file asset by id. One in the trash (deleted_at set) is None unless asked for."""
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM file_assets WHERE id = ?", (asset_id,))
    row = cur.fetchone()
    con.close()
    if not row:
        return None
    asset = dict(row)
    if asset.get("deleted_at") and not include_deleted:
        return None
    return asset


def _remove_object(rel_path: str, backend: Optional[str] = None) -> bool:
    """Remove the bytes behind a file_assets row, from the backend the row names. Immediate,
    as before: soft deletion with deferred removal is the multi-user phase
    (docs/design/MEDIA_STORAGE.md)."""
    if not rel_path:
        return False
    try:
        storage = _store_for(backend, rel_path)
        if storage is None:
            print(f"[CLEANUP] {rel_path!r} is in media backend {backend!r}, which this HomePilot is not "
                  f"configured for (MEDIA_STORAGE_BACKEND={backend_name()}); the object was left in place.")
            return False
        return storage.delete(rel_path)
    except Exception as e:
        print(f"[CLEANUP] Failed to delete file {rel_path}: {e}")
        return False


def _trash_on() -> bool:
    """Deleted assets go to the trash first (MEDIA_TRASH_RETENTION_DAYS, 7 by default); 0 means
    bytes and row go at once, as before Phase 4."""
    return media_ops.trash_retention_days() > 0


def delete_asset_and_file(asset_id: str, *, purge: bool = False) -> bool:
    """
    Delete a file asset. The row is marked deleted and disappears from every read; its bytes
    stay until the trash is purged (media_ops.purge_trash, run by the backend), so a mistaken
    delete is recoverable for the retention window. ``purge=True`` — or a retention of 0 —
    removes the bytes and the row now. Returns True if the record was deleted either way.
    """
    if not asset_id:
        return False
    con = _db()
    _ensure_backend_column(con)
    cur = con.cursor()
    cur.execute("SELECT id, rel_path, storage_backend, deleted_at FROM file_assets WHERE id = ?", (asset_id,))
    row = cur.fetchone()
    if not row:
        con.close()
        return False

    if purge or not _trash_on():
        _remove_object(row["rel_path"], row["storage_backend"] or "local")
        cur.execute("DELETE FROM file_assets WHERE id = ?", (asset_id,))
    else:
        stamp = _now()
        cur.execute("UPDATE file_assets SET deleted_at = COALESCE(deleted_at, ?), updated_at = ? WHERE id = ?",
                    (stamp, stamp, asset_id))
    removed = cur.rowcount > 0
    con.commit()
    con.close()
    return removed


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
    fname = f"{uuid.uuid4().hex}.{ext}"
    rel_path = f"{_user_key(user_id, 'image', project_id=project_id)}/{fname}"
    get_storage().put(rel_path, image_bytes)

    asset_id = insert_asset(
        user_id=user_id,
        kind="image",
        rel_path=rel_path,
        mime=mime or "image/png",
        size_bytes=len(image_bytes),
        original_name=fname,
        project_id=project_id,
        conversation_id=conversation_id,
        sha256=hashlib.sha256(image_bytes).hexdigest(),
    )

    return {"asset_id": asset_id, "url": f"/files/{asset_id}", "mime": mime or "image/png", "rel_path": rel_path}


def save_generated_media_as_asset(
    user_id: str,
    media_bytes: bytes,
    mime: str,
    kind: str,
    project_id: str = "",
    conversation_id: str = "",
) -> Dict[str, Any]:
    """Store generated image/video bytes without losing their media type."""
    safe_kind = "video" if kind == "video" else "image"
    extension = mimetypes.guess_extension((mime or "").split(";", 1)[0].strip())
    allowed_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".webm"}
    extension = extension if extension in allowed_extensions else ".bin"
    filename = f"{uuid.uuid4().hex}{extension}"
    rel_path = f"{_user_key(user_id, safe_kind, project_id=project_id)}/{filename}"
    get_storage().put(rel_path, media_bytes)
    asset_id = insert_asset(
        user_id=user_id,
        kind=safe_kind,
        rel_path=rel_path,
        mime=mime or "application/octet-stream",
        size_bytes=len(media_bytes),
        original_name=filename,
        project_id=project_id,
        conversation_id=conversation_id,
        sha256=hashlib.sha256(media_bytes).hexdigest(),
    )
    return {"asset_id": asset_id, "url": f"/files/{asset_id}", "mime": mime, "rel_path": rel_path}


# ---------------------------------------------------------------------------
# Chat media persistence: download ComfyUI images → permanent file_assets
# ---------------------------------------------------------------------------

async def persist_chat_images(
    image_urls: list[str],
    user_id: str,
    conversation_id: str,
    project_id: str = "",
) -> list[str]:
    """
    Download generated images from ComfyUI and persist them as file_assets
    tied to the conversation. Returns a list of new /files/{asset_id} URLs
    to replace the volatile ComfyUI URLs in the message media.

    Images that are already /files/ URLs are returned unchanged.
    """
    import httpx
    from .config import COMFY_BASE_URL

    persisted: list[str] = []
    for url in image_urls:
        # Already a persisted /files/ URL — skip
        if "/files/" in url and "/comfy/" not in url:
            persisted.append(url)
            continue

        try:
            # Resolve the actual ComfyUI URL to fetch from
            fetch_url = url
            if url.startswith("/comfy/view/"):
                filename = os.path.basename(url.split("?")[0])
                fetch_url = f"{COMFY_BASE_URL.rstrip('/')}/view?filename={filename}&type=output"
            elif url.startswith(COMFY_BASE_URL.rstrip("/")):
                fetch_url = url
            elif url.startswith("http"):
                # External URL — leave as-is
                persisted.append(url)
                continue
            else:
                persisted.append(url)
                continue

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                follow_redirects=True,
            ) as client:
                resp = await client.get(fetch_url)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "image/png")
                image_bytes = resp.content

            if not image_bytes:
                persisted.append(url)
                continue

            # Save as a file asset
            result = save_generated_image_as_asset(
                user_id=user_id,
                image_bytes=image_bytes,
                mime=content_type,
                project_id=project_id,
                conversation_id=conversation_id,
            )
            persisted.append(result["url"])
            print(f"[PERSIST] Saved chat image: {url} → {result['url']}")

            # Also register in asset registry for durability
            try:
                from .asset_registry import register_asset
                register_asset(
                    storage_key=result.get("asset_id", ""),
                    kind="image",
                    mime=content_type,
                    size_bytes=len(image_bytes),
                    origin="comfy",
                    source_hint=url,
                    project_id=project_id,
                    user_id=user_id,
                )
            except Exception:
                pass  # non-critical

        except Exception as e:
            print(f"[PERSIST] Failed to persist image {url}: {e}")
            # Keep original URL as fallback
            persisted.append(url)

    return persisted


async def persist_chat_video(
    video_url: str,
    user_id: str,
    conversation_id: str,
    project_id: str = "",
) -> str:
    """Persist a ComfyUI animation so clients never receive localhost URLs."""
    from .comfy import proxy_comfy_view_url

    if not video_url or ("/files/" in video_url and "/comfy/" not in video_url):
        return video_url

    from urllib.parse import parse_qs, urlencode, urlparse

    import httpx

    from .config import COMFY_BASE_URL

    parsed = urlparse(video_url)
    comfy = urlparse(COMFY_BASE_URL)
    if parsed.path != "/view" or parsed.hostname not in {
        comfy.hostname,
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
    }:
        return video_url

    query = parse_qs(parsed.query)
    filename = (query.get("filename") or [""])[0]
    if not filename:
        return video_url
    view_params = urlencode({
        'filename': filename,
        'subfolder': (query.get('subfolder') or [''])[0],
        'type': (query.get('type') or ['output'])[0],
    })
    fetch_url = f"{COMFY_BASE_URL.rstrip('/')}/view?{view_params}"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True
        ) as client:
            response = await client.get(fetch_url)
            response.raise_for_status()
        if not response.content:
            return proxy_comfy_view_url(video_url)
        content_type = response.headers.get("content-type") or mimetypes.guess_type(filename)[0]
        result = save_generated_media_as_asset(
            user_id=user_id,
            media_bytes=response.content,
            mime=content_type or "application/octet-stream",
            kind="video",
            project_id=project_id,
            conversation_id=conversation_id,
        )
        print(f"[PERSIST] Saved chat video: {video_url} → {result['url']}")
        # Keep the original extension visible in the stable URL. The Animate
        # client uses it to render animated WebP/GIF outputs with <img> rather
        # than the <video> element used for MP4/WebM.
        filename_query = urlencode({"filename": filename})
        return f"{result['url']}?{filename_query}"
    except Exception as error:
        print(f"[PERSIST] Failed to persist video {video_url}: {error}")
        return proxy_comfy_view_url(video_url)


def delete_conversation_media(conversation_id: str) -> int:
    """
    Delete all file_assets (and their files on disk) that belong to a
    conversation. Used when a chat is deleted.

    Does NOT touch persona avatar/outfit images (those live under
    projects/<id>/persona/appearance/).
    """
    con = _db()
    _ensure_backend_column(con)
    cur = con.cursor()
    cur.execute(
        "SELECT id, rel_path, storage_backend FROM file_assets WHERE conversation_id = ? AND deleted_at IS NULL",
        (conversation_id,),
    )
    rows = cur.fetchall()
    deleted = 0

    if _trash_on():
        # To the trash: gone from every read now, bytes removed when the retention has passed.
        stamp = _now()
        for row in rows:
            cur.execute("UPDATE file_assets SET deleted_at = ?, updated_at = ? WHERE id = ?", (stamp, stamp, row["id"]))
            deleted += 1
        con.commit()
    else:
        for row in rows:
            if _remove_object(row["rel_path"], row["storage_backend"] or "local"):
                deleted += 1
        if rows:
            cur.execute("DELETE FROM file_assets WHERE conversation_id = ?", (conversation_id,))
            con.commit()

    con.close()
    print(f"[CLEANUP] {'Trashed' if _trash_on() else 'Deleted'} {deleted} files for conversation {conversation_id}")
    return deleted


def get_conversation_media(
    conversation_id: str,
    user_id: Optional[str] = None,
) -> list[dict]:
    """
    List all persisted media assets for a conversation.
    Returns list of dicts with asset_id, url, mime, created_at.
    """
    con = _db()
    cur = con.cursor()
    if user_id:
        cur.execute(
            """
            SELECT id, rel_path, mime, original_name, created_at
            FROM file_assets
            WHERE conversation_id = ? AND user_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id, user_id),
        )
    else:
        cur.execute(
            """
            SELECT id, rel_path, mime, original_name, created_at
            FROM file_assets
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (conversation_id,),
        )
    rows = cur.fetchall()
    con.close()

    return [
        {
            "asset_id": r["id"],
            "url": f"/files/{r['id']}",
            "mime": r["mime"],
            "filename": r["original_name"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


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

    original_name = file.filename or ""
    content_type = (file.content_type or "").lower()
    # Before any byte is stored: what it claims to be, the owner's quota, the scanner if one is set.
    media_validate.check_image_claim(data[:media_validate.HEAD_BYTES], content_type, original_name)
    media_quota.check(user["id"], len(data))
    media_validate.scan_bytes(data, original_name)

    # Choose extension
    ext = ""
    if original_name and "." in original_name:
        ext = original_name.rsplit(".", 1)[1].lower()
    if not ext:
        ext = (mimetypes.guess_extension(content_type) or "").lstrip(".") or "bin"

    # Write to the user's area in media storage
    fname = f"{uuid.uuid4().hex}.{ext}"
    rel_path = f"{_user_key(user['id'], kind, project_id=project_id)}/{fname}"
    get_storage().put(rel_path, data)

    # Store metadata
    mime = content_type or mimetypes.guess_type(fname)[0] or "application/octet-stream"
    asset_id = insert_asset(
        user_id=user["id"],
        kind=kind,
        rel_path=rel_path,
        mime=mime,
        size_bytes=len(data),
        original_name=original_name,
        project_id=project_id,
        conversation_id=conversation_id,
        sha256=hashlib.sha256(data).hexdigest(),
    )

    return {"ok": True, "asset_id": asset_id, "url": f"/files/{asset_id}", "mime": mime}


@router.get("/v1/files/usage")
def files_usage(
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
):
    """How much of their media quota the caller uses (quota_bytes 0: no limit)."""
    user = _resolve_user(authorization, homepilot_session)
    if not user:
        raise HTTPException(401, "Authentication required")
    return {"ok": True, **media_quota.usage(user["id"])}


@router.get("/v1/files/{asset_id}/link")
def file_link(
    asset_id: str,
    ttl: int = Query(default=media_links.DEFAULT_TTL_S, ge=1, le=media_links.MAX_TTL_S),
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
):
    """A short-lived link to one of the caller's files — for an <img> on another origin or a
    share — that carries no account credential: /files/{id}?exp=…&sig=…"""
    user = _resolve_user(authorization, homepilot_session)
    if not user:
        raise HTTPException(401, "Authentication required")
    asset = get_asset(asset_id)
    if not asset or asset.get("user_id") != user["id"]:
        raise HTTPException(404, "Not found")
    signed = media_links.sign(asset_id, ttl)
    return {"ok": True, "asset_id": asset_id, "url": signed["url"], "expires_at": signed["exp"]}


# ---------------------------------------------------------------------------
# Secure Download / Serve Endpoint
# ---------------------------------------------------------------------------

def _is_public_file(name: str) -> bool:
    """Persona appearance images are public — served without auth.

    Covers avatar images (login screen) AND outfit / thumbnail images
    so that external services (VR chatbot via OllaBridge) can fetch
    persona visuals without a user session token.
    """
    if "/" in name or ".." in name:
        return False
    return name.startswith(("avatar_", "outfit_", "thumb_"))


def _is_user_avatar(name: str) -> bool:
    """Some account's current profile picture: the login screen shows those before anyone is
    signed in, so they are public by design."""
    try:
        con = _db()
        row = con.execute("SELECT 1 FROM users WHERE avatar_url = ? LIMIT 1", (f"/files/{name}",)).fetchone()
        con.close()
        return row is not None
    except Exception:
        return False


def _is_public_flat_file(name: str) -> bool:
    """A flat file served without an account: a user's current avatar, or a persona visual that
    also lives under a project's appearance folder. Any other avatar_*/outfit_*/thumb_* file
    now needs an account, a signed link or the API key (audit item A1)."""
    if not _is_public_file(name):
        return False
    return _is_user_avatar(name) or _find_persona_file(name) is not None


def _is_persona_visual_path(parts: tuple) -> bool:
    """projects/<id>/persona/appearance/<avatar_|outfit_|thumb_…>: the persona's own pictures,
    public by design (the gallery, OllaBridge's VR chatbot)."""
    return (len(parts) >= 4 and parts[0] == "projects" and "persona" in parts and "appearance" in parts
            and _is_public_file(parts[-1]))


def _owns_path(user: Dict[str, Any], parts: tuple) -> bool:
    """A path under users/<id>/ belongs to that account alone (audit item A2); anything else on
    the legacy routes is as before — flat root files, project folders."""
    if len(parts) >= 2 and parts[0] == "users":
        return parts[1] == str(user.get("id"))
    return True


def _serve_asset(asset: Dict[str, Any]):
    key = str(asset.get("rel_path") or "")
    return _serve_object(
        key,
        asset.get("mime") or "application/octet-stream",
        asset.get("original_name") or os.path.basename(key.replace("\\", "/")),
        backend=asset.get("storage_backend") or "local",
    )


def _find_persona_file(filename: str) -> Optional[Path]:
    """
    Search all project appearance directories for a file by name.

    Handles the case where selected_filename was stored with a stale
    project ID (e.g. from a project duplication or re-creation) — the
    file exists on disk under a different project folder.
    """
    projects_dir = _upload_root() / "projects"
    if not projects_dir.is_dir():
        return None
    # Search: projects/*/persona/appearance/<filename>
    for match in projects_dir.glob(f"*/persona/appearance/{filename}"):
        if match.is_file():
            return match
    return None


def _serve_object(key: str, mime: str, filename: str, backend: Optional[str] = None):
    """Serve an object from media storage — the backend its registry row names, or for a key
    with no row whichever has it: straight off the disk when that is local (a FileResponse,
    as before), streamed in 1 MB chunks otherwise."""
    storage = _store_for(backend, key)
    if storage is None:
        print(f"[FILES] {key!r} is in media backend {backend!r}, which this HomePilot is not configured "
              f"for (MEDIA_STORAGE_BACKEND={backend_name()}); configure it again to serve the file.")
        raise HTTPException(404, "Not found")
    try:
        if not storage.exists(key):
            raise HTTPException(404, "Not found")
        local = storage.local_path(key)
        if local is not None:
            return FileResponse(path=str(local), media_type=mime, filename=filename, headers=_FILE_CACHE_HEADERS)
        stream = storage.open(key)
    except StorageKeyError:
        raise HTTPException(404, "Not found")

    def _chunks():
        try:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            stream.close()

    safe_name = filename.replace('"', "")
    headers = {**_FILE_CACHE_HEADERS, "Content-Disposition": f'inline; filename="{safe_name}"'}
    return StreamingResponse(_chunks(), media_type=mime, headers=headers)


def _object_or_404(key: str, filename: str):
    """A path-based route's last resort: the object under ``key`` in the configured storage,
    when that is not this disk (an avatar or background written after a switch to S3)."""
    try:
        storage = get_storage()
        if storage.name != "local" and storage.exists(key):
            return _serve_object(key, mimetypes.guess_type(filename)[0] or "application/octet-stream", filename)
    except Exception:
        pass
    raise HTTPException(404, "Not found")


def resolve_local_file(file_ref: str) -> Optional[Path]:
    """A readable path on this disk for a ``/files/<ref>`` reference — a flat key or a
    file_assets id — for code that hands files to ComfyUI or copies them: the object itself
    when it is on the disk, else a copy fetched from the configured storage into
    ``<upload root>/.cache/media/<key>`` (kept; the same key resolves to the same path, and
    re-fetched when the size differs). None when nothing is found."""
    ref = (file_ref or "").split("?")[0].strip().strip("/")
    if not ref or ".." in Path(ref.replace("\\", "/")).parts:
        return None
    candidates: list = [(ref, None)]                       # a flat key: whichever store has it
    try:
        asset = get_asset(ref)
    except Exception:
        asset = None
    if asset and asset.get("rel_path"):                    # a registered asset: its own backend
        candidates.insert(0, (str(asset["rel_path"]), asset.get("storage_backend") or "local"))
    for key, backend in candidates:
        try:
            storage = _store_for(backend, key)
            if storage is None or not storage.exists(key):
                continue
            local = storage.local_path(key)
            if local is not None:
                return local
            cache_key = f".cache/media/{normalize_key(key)}"
            disk = local_storage()
            if not disk.exists(cache_key) or disk.size(cache_key) != storage.size(key):
                with storage.open(key) as src:
                    disk.put(cache_key, src)
            return disk.local_path(cache_key)
        except StorageKeyError:
            continue
        except Exception as e:
            print(f"[FILES] Could not resolve {key!r} to a local file: {e}")
            continue
    return None


@router.get("/files/{asset_id}")
def download_file(
    asset_id: str,
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
    token: Optional[str] = Query(default=None, alias="token"),
    exp: Optional[str] = Query(default=None),
    sig: Optional[str] = Query(default=None),
):
    """
    Secure file serving — the endpoint behind <img src="/files/...">.

    A registered asset is served to its owner (session, cookie, or ?token= for an <img> on
    another origin), to anyone with a signed link for it (?exp=&sig=, GET /v1/files/{id}/link),
    and to everyone when its visibility is public. A flat file is public only when it is a
    user's current avatar or a persona visual; other flat files need an account.
    """
    asset = get_asset(asset_id)
    if asset and (asset.get("visibility") == "public" or media_links.verify(asset_id, exp, sig)):
        return _serve_asset(asset)

    # A public flat file: a login-screen avatar or a persona visual.
    if not asset and _is_public_flat_file(asset_id):
        safe = Path(asset_id)
        abs_path = _upload_root() / safe
        if abs_path.exists() and abs_path.is_file():
            mime = mimetypes.guess_type(str(abs_path))[0] or "application/octet-stream"
            return FileResponse(path=str(abs_path), media_type=mime, filename=safe.name, headers=_FILE_CACHE_HEADERS)
        return _object_or_404(asset_id, safe.name)

    user = _resolve_user(authorization, homepilot_session, token_param=token)
    if not user:
        raise HTTPException(401, "Authentication required")

    if asset:
        if asset.get("user_id") != user["id"]:
            raise HTTPException(404, "Not found")
        return _serve_asset(asset)

    # Fallback: serve from flat uploads dir (avatars, legacy files)
    safe = Path(asset_id)
    if ".." in safe.parts:
        raise HTTPException(400, "Invalid path")
    abs_path = _upload_root() / safe
    if abs_path.exists() and abs_path.is_file():
        mime = mimetypes.guess_type(str(abs_path))[0] or "application/octet-stream"
        return FileResponse(path=str(abs_path), media_type=mime, filename=safe.name, headers=_FILE_CACHE_HEADERS)

    return _object_or_404(asset_id, safe.name)


# ---------------------------------------------------------------------------
# Legacy fallback: serve old /files/<filename> paths (backward compatibility)
# ---------------------------------------------------------------------------

@router.get("/files/{subpath:path}")
def download_file_legacy(
    subpath: str,
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
    token: Optional[str] = Query(default=None, alias="token"),
):
    """
    Fallback for legacy /files/<path> URLs (pre-asset era) and persona visuals.
    A persona's own pictures (projects/<id>/persona/appearance/…) are public; a path under
    users/<id>/ is served to that account only; other paths need an account, as before.
    Supports ?token=<session_token> for <img> tags that can't set headers.
    """
    # Prevent path traversal
    safe = Path(subpath.replace("\\", "/"))
    if ".." in safe.parts:
        raise HTTPException(400, "Invalid path")

    # Public without an account: a persona's own pictures, or a public flat file.
    if _is_persona_visual_path(safe.parts) or (len(safe.parts) == 1 and _is_public_flat_file(safe.name)):
        abs_path = _upload_root() / safe
        if abs_path.exists() and abs_path.is_file():
            mime = mimetypes.guess_type(str(abs_path))[0] or "application/octet-stream"
            return FileResponse(path=str(abs_path), media_type=mime, filename=safe.name, headers=_FILE_CACHE_HEADERS)
        # Fallback: the stored path may reference a stale project ID.
        # Search all project appearance dirs for the file by name.
        found = _find_persona_file(safe.name)
        if found:
            mime = mimetypes.guess_type(str(found))[0] or "application/octet-stream"
            return FileResponse(path=str(found), media_type=mime, filename=safe.name, headers=_FILE_CACHE_HEADERS)
        return _object_or_404(subpath, safe.name)

    user = _resolve_user(authorization, homepilot_session, token_param=token)
    if not user:
        raise HTTPException(401, "Authentication required")
    if not _owns_path(user, safe.parts):
        raise HTTPException(404, "Not found")

    abs_path = _upload_root() / safe
    if not abs_path.exists() or not abs_path.is_file():
        # Fallback: search project appearance dirs for the file by name
        found = _find_persona_file(safe.name) if "persona" in safe.parts else None
        if not found:
            return _object_or_404(subpath, safe.name)
        abs_path = found

    mime = mimetypes.guess_type(str(abs_path))[0] or "application/octet-stream"
    return FileResponse(
        path=str(abs_path),
        media_type=mime,
        filename=safe.name,
        headers=_FILE_CACHE_HEADERS,
    )
