"""
Avatar gallery, saved per account — additive module.

The Avatar Studio gallery used to live only in the browser's localStorage, so a
different browser, a different address (localhost vs 127.0.0.1, another port)
or cleared site data showed "Create your first avatar" even though every image
was still on disk. These routes keep a copy on the server, tied to the signed-in
account, and can rebuild a gallery from the avatar images ComfyUI wrote.

    GET  /v1/avatar-gallery            → {ok, items: [...] | null}
    PUT  /v1/avatar-gallery {items}    → save the account's gallery
    GET  /v1/avatar-gallery/recover    → gallery items built from avatar images on disk

The items are the frontend's ``GalleryItem`` objects, stored as JSON as-is.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from . import users as _users

router = APIRouter(prefix="/v1/avatar-gallery", tags=["avatar"])

MAX_ITEMS = 1000
MAX_BYTES = 8 * 1024 * 1024

# ComfyUI writes avatars as <prefix>_<5 digits>_.png. The prefix says how it was made.
_AVATAR_FILE = re.compile(r"^(avatar(?:_instantid|_photomaker|_body)?)_(\d{5})_\.(png|jpg|jpeg|webp)$", re.I)
_MODE_BY_PREFIX = {
    "avatar": "studio_random",
    "avatar_instantid": "studio_reference",
    "avatar_photomaker": "studio_reference",
    "avatar_body": "studio_random",
}


def _require_user(user: Optional[Dict[str, Any]] = Depends(_users.get_current_user)) -> Dict[str, Any]:
    if not user:
        raise HTTPException(401, "Sign in to use your avatar gallery")
    return user


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(_users._get_db_path(), timeout=30)
    con.execute("""
        CREATE TABLE IF NOT EXISTS avatar_gallery(
            user_id TEXT PRIMARY KEY,
            items_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
    """)
    return con


@router.get("")
def get_gallery(user: Dict[str, Any] = Depends(_require_user)):
    con = _db()
    row = con.execute("SELECT items_json, updated_at FROM avatar_gallery WHERE user_id = ?", (user["id"],)).fetchone()
    con.close()
    if not row:
        return {"ok": True, "items": None}
    try:
        items = json.loads(row[0])
    except ValueError:
        items = []
    return {"ok": True, "items": items if isinstance(items, list) else [], "updated_at": row[1]}


@router.put("")
async def put_gallery(request: Request, user: Dict[str, Any] = Depends(_require_user)):
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "Avatar gallery is too large to save")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise HTTPException(400, "Body must be JSON")
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise HTTPException(400, "items must be a list of objects")
    items = items[:MAX_ITEMS]
    con = _db()
    with con:
        con.execute(
            "INSERT INTO avatar_gallery(user_id, items_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET items_json = excluded.items_json, updated_at = excluded.updated_at",
            (user["id"], json.dumps(items), time.time()),
        )
    con.close()
    return {"ok": True, "count": len(items)}


def _comfy_output_dir() -> Optional[Path]:
    try:
        from .comfy import _get_comfyui_output_dir
        return _get_comfyui_output_dir()
    except Exception:
        return None


def scan_avatar_files(root: Path) -> List[Dict[str, Any]]:
    """Avatar images under ``root`` (and its ``avatar/`` subfolder), newest first."""
    found: List[Dict[str, Any]] = []
    for sub in ("", "avatar"):
        folder = root / sub if sub else root
        if not folder.is_dir():
            continue
        for entry in os.scandir(folder):
            if not entry.is_file():
                continue
            m = _AVATAR_FILE.match(entry.name)
            if not m:
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            found.append({"name": entry.name, "subfolder": sub, "prefix": m.group(1).lower(), "mtime": mtime})
    found.sort(key=lambda f: f["mtime"], reverse=True)
    return found


@router.get("/recover")
def recover(
    limit: int = Query(200, ge=1, le=MAX_ITEMS),
    user: Dict[str, Any] = Depends(_require_user),
):
    """Gallery items for the avatar images ComfyUI left on this computer.

    Grouping, names and prompts were only kept in the browser, so each image
    comes back as its own avatar; the newest ``limit`` are returned."""
    root = _comfy_output_dir()
    if root is None:
        return {"ok": True, "items": [], "total": 0, "reason": "ComfyUI output folder not found"}
    files = scan_avatar_files(root)
    # Make the grid's thumbnails now, in the background, so the restored
    # gallery shows its pictures without each one being made on first view.
    # (Not under pytest: a background thread outliving a test run can crash
    # the interpreter at exit; warm_thumbnails has its own test.)
    if not os.getenv("PYTEST_CURRENT_TEST"):
        try:
            from .comfy_thumbs import warm_thumbnails
            warm_thumbnails([(f["name"], f["subfolder"]) for f in files[:limit]])
        except Exception:
            pass
    items = []
    for f in files[:limit]:
        url = f"/comfy/view/{f['name']}"
        if f["subfolder"]:
            url += f"?subfolder={f['subfolder']}"
        items.append({
            "id": f"restored_{f['prefix']}_{f['name'].rsplit('_', 2)[-2]}_{f['subfolder'] or 'root'}",
            "url": url,
            "mode": _MODE_BY_PREFIX.get(f["prefix"], "studio_random"),
            "createdAt": int(f["mtime"] * 1000),
            "role": "anchor",
            "tags": ["restored"],
        })
    return {"ok": True, "items": items, "total": len(files)}
