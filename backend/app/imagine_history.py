"""
Imagine history from the server — additive module.

The Imagine page keeps its gallery in the browser, capped at the latest 100
images, so older generations (and everything, in a new browser) were not shown
even though the server kept every one. Imagine sends each prompt to /chat as
"imagine <prompt>", and the reply message carries the images, so the full
history can be rebuilt from the signed-in account's conversations.

    GET /v1/imagine/history?limit=60&offset=0
        → {ok, items: [ImagineItem...], total, offset, limit}   newest first

Links to ComfyUI (http://<comfy>/view?filename=…) are rewritten to
/comfy/view/<file>, which the backend serves from disk even when ComfyUI is off.
"""
from __future__ import annotations

import calendar
import json
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query

from . import users as _users

router = APIRouter(prefix="/v1/imagine", tags=["imagine"])

# Same test the Imagine page uses to decide whether to prefix "imagine ".
_IMAGINE_PROMPT = re.compile(r"^\s*(imagine|generate|create|draw|make)\b", re.I)
_PREFIX = re.compile(r"^\s*imagine\s+", re.I)


def _require_user(user: Optional[Dict[str, Any]] = Depends(_users.get_current_user)) -> Dict[str, Any]:
    if not user:
        raise HTTPException(401, "Sign in to see your Imagine history")
    return user


def normalize_url(url: str) -> str:
    """Serve ComfyUI images through the backend, and backend files by path."""
    p = urlparse(url)
    if p.path.endswith("/view") and "filename=" in (p.query or ""):
        q = parse_qs(p.query)
        name = (q.get("filename") or [""])[0]
        sub = (q.get("subfolder") or [""])[0]
        out = f"/comfy/view/{quote(name)}"
        return f"{out}?subfolder={quote(sub)}" if sub else out
    if "/files/" in p.path or p.path.startswith("/comfy/view/"):
        return p.path + (f"?{p.query}" if p.query else "")
    return url


def _ms(ts: Optional[str]) -> int:
    if not ts:
        return 0
    try:
        return calendar.timegm(time.strptime(str(ts)[:19], "%Y-%m-%d %H:%M:%S")) * 1000
    except ValueError:
        return 0


def build_history(con: sqlite3.Connection, user_id: str) -> List[Dict[str, Any]]:
    rows = con.execute(
        """
        SELECT m.id, m.conversation_id, m.role, m.content, m.media, m.created_at
        FROM messages m
        JOIN conversation_owners o ON o.conversation_id = m.conversation_id
        WHERE o.user_id = ?
          AND (m.role = 'user' OR (m.media IS NOT NULL AND m.media LIKE '%images%'))
        ORDER BY m.conversation_id, m.id
        """,
        (user_id,),
    ).fetchall()

    last_prompt: Dict[str, str] = {}
    # One entry per image; when an image shows up again (reused as a reference),
    # keep the earliest message: that is where it was generated.
    by_url: Dict[str, Dict[str, Any]] = {}
    for mid, conv, role, content, media, created in rows:
        if role == "user":
            last_prompt[conv] = content or ""
            continue
        prompt = last_prompt.get(conv, "")
        if not _IMAGINE_PROMPT.match(prompt):
            continue
        try:
            meta = json.loads(media)
        except (TypeError, ValueError):
            continue
        if not isinstance(meta, dict):
            continue
        for i, raw in enumerate(meta.get("images") or []):
            if not isinstance(raw, str) or not raw:
                continue
            url = normalize_url(raw)
            created_ms = _ms(created)
            prev = by_url.get(url)
            if prev is not None and prev["createdAt"] <= created_ms:
                continue
            item: Dict[str, Any] = {
                "id": f"srv_{mid}_{i}",
                "url": url,
                "createdAt": created_ms,
                "prompt": meta.get("final_prompt") or _PREFIX.sub("", prompt).strip() or prompt,
                "status": "done",
            }
            if isinstance(meta.get("model"), str):
                item["model"] = meta["model"]
            for key in ("seed", "width", "height", "steps", "cfg"):
                if isinstance(meta.get(key), (int, float)):
                    item[key] = meta[key]
            by_url[url] = item
    items = sorted(by_url.values(), key=lambda it: it["createdAt"], reverse=True)
    return items


@router.get("/history")
def history(
    limit: int = Query(60, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: Dict[str, Any] = Depends(_require_user),
):
    con = sqlite3.connect(_users._get_db_path(), timeout=30)
    try:
        items = build_history(con, user["id"])
    finally:
        con.close()
    return {
        "ok": True,
        "items": items[offset: offset + limit],
        "total": len(items),
        "offset": offset,
        "limit": limit,
    }
