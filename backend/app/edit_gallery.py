"""
Rebuild the Edit Studio gallery — additive module.

Edit Studio keeps its gallery list only in the browser (localStorage), so a new
browser, another address or cleared site data shows an empty "Upload Image"
page although every edit session is still stored by the edit-session service.
This route reads those sessions and returns them as gallery items.

    GET /v1/edit-gallery/recover → {ok, items: [EditItem...], total, skipped_missing}

It reads the edit-session SQLite file directly, so it works even when the
edit-session service is not running. Sessions whose current image file no
longer exists are left out (reported as ``skipped_missing``).
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from fastapi import APIRouter, Depends, HTTPException

from . import users as _users

router = APIRouter(prefix="/v1/edit-gallery", tags=["edit"])


def _require_user(user: Optional[Dict[str, Any]] = Depends(_users.get_current_user)) -> Dict[str, Any]:
    if not user:
        raise HTTPException(401, "Sign in to restore your edits")
    return user


def edit_sessions_db() -> Optional[Path]:
    """The edit-session service's SQLite file, when it is on this computer."""
    env = os.getenv("EDIT_SESSION_SQLITE_PATH", "").strip()
    candidates = [Path(env)] if env else []
    repo = Path(__file__).resolve().parents[2]
    candidates += [repo / "edit-session" / "data" / "edit_sessions.sqlite", Path("/data/edit_sessions.sqlite")]
    return next((p for p in candidates if p.is_file()), None)


def _relative(url: str) -> str:
    """Backend links by path, so they work whatever host/port the page uses."""
    p = urlparse(url or "")
    if "/files/" in p.path or p.path.startswith("/comfy/view/"):
        return p.path + (f"?{p.query}" if p.query else "")
    return url or ""


def _exists(url: str) -> bool:
    p = urlparse(url or "")
    if p.path.endswith("/view") or p.path.startswith("/comfy/view/"):
        try:
            from .comfy import _get_comfyui_output_dir
            root = _get_comfyui_output_dir()
        except Exception:
            root = None
        if root is None:
            return True  # can't check; let the page try
        q = parse_qs(p.query)
        name = (q.get("filename") or [unquote(os.path.basename(p.path))])[0]
        sub = (q.get("subfolder") or [""])[0]
        return (root / sub / name).is_file()
    if "/files/" in p.path:
        rel = unquote(p.path.split("/files/", 1)[1])
        try:
            from .files import _upload_root
            root = _upload_root()
        except Exception:
            from .config import UPLOAD_DIR
            root = Path(UPLOAD_DIR)
        if (root / rel).is_file():
            return True
        con = sqlite3.connect(_users._get_db_path())
        try:
            row = con.execute("SELECT rel_path FROM file_assets WHERE id = ?", (rel,)).fetchone()
        finally:
            con.close()
        return bool(row and (root / row[0]).is_file())
    return True


def recover_items(db: Path) -> Dict[str, Any]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT conversation_id, active_image_url, original_image_url, history_json, updated_at "
            "FROM edit_sessions ORDER BY updated_at DESC"
        ).fetchall()
    finally:
        con.close()
    items: List[Dict[str, Any]] = []
    skipped = 0
    for conv, active, original, history, updated in rows:
        if not active or not _exists(active):
            skipped += 1
            continue
        try:
            versions = json.loads(history or "[]")
        except ValueError:
            versions = []
        items.append({
            "id": f"restored_{conv}",
            "url": _relative(active),
            "originalUrl": _relative(original or active),
            "createdAt": int(float(updated or 0) * 1000),
            "instruction": "",
            "conversationId": conv,
            "settings": {"restored": True, "versions": len(versions) if isinstance(versions, list) else 0},
        })
    return {"items": items, "total": len(rows), "skipped_missing": skipped}


@router.get("/recover")
def recover(user: Dict[str, Any] = Depends(_require_user)):
    db = edit_sessions_db()
    if db is None:
        return {"ok": True, "items": [], "total": 0, "skipped_missing": 0, "reason": "edit sessions not found"}
    return {"ok": True, **recover_items(db)}
