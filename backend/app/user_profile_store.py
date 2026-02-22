"""
Per-User Profile, Secrets & Memory — additive module.

Replaces the global profile.json / profile_secrets.json / user_memory.json
with SQLite-backed, user-scoped storage.  All new endpoints live under
/v1/user-profile and /v1/user-memory and require Bearer authentication.

The OLD global endpoints (/v1/profile, /v1/memory) remain untouched for
backward compatibility (single-user / API-key mode).

ADDITIVE ONLY — does not modify any existing module.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from .config import SQLITE_PATH
from .users import _validate_token

router = APIRouter(tags=["user-profile"])


# ---------------------------------------------------------------------------
# Auth dependency (reusable)
# ---------------------------------------------------------------------------

def require_current_user(authorization: str = Header(default="")) -> Dict[str, Any]:
    """
    FastAPI dependency: require a valid Bearer token.
    Returns the full user dict or raises 401.
    """
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        raise HTTPException(401, "Authentication required")
    user = _validate_token(token)
    if not user:
        raise HTTPException(401, "Invalid or expired token")
    return user


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_db_path() -> str:
    from .storage import _get_db_path as _storage_db_path
    return _storage_db_path()


def ensure_user_profile_tables() -> None:
    """Create per-user profile / secrets / memory tables. Safe to call multiple times."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles(
            user_id TEXT PRIMARY KEY,
            data TEXT NOT NULL DEFAULT '{}',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_secrets(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '',
            description TEXT DEFAULT '',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, key),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_secrets_user ON user_secrets(user_id)"
    )

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_memory_items(
            id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            text TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            importance INTEGER DEFAULT 2,
            last_confirmed_iso TEXT DEFAULT '',
            source TEXT DEFAULT 'user',
            pinned INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, id),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_memory_user ON user_memory_items(user_id)"
    )

    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Profile CRUD
# ---------------------------------------------------------------------------

def _get_user_profile(user_id: str) -> Dict[str, Any]:
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("SELECT data FROM user_profiles WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    con.close()
    if row:
        try:
            return json.loads(row[0])
        except Exception:
            return {}
    return {}


def _save_user_profile(user_id: str, data: Dict[str, Any]) -> None:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO user_profiles(user_id, data, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
    """, (user_id, json.dumps(data, ensure_ascii=False), now))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Pydantic models (reuse shape from profile.py)
# ---------------------------------------------------------------------------

class UserProfileData(BaseModel):
    display_name: str = ""
    email: str = ""
    linkedin: str = ""
    website: str = ""
    company: str = ""
    role: str = ""
    locale: str = "en"
    timezone: str = ""
    bio: str = ""
    birthday: str = ""  # ISO date string e.g. "1990-05-15" (YYYY-MM-DD)

    personalization_enabled: bool = True
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    favorite_persona_tags: list[str] = Field(default_factory=list)
    preferred_tone: str = "neutral"

    allow_usage_for_recommendations: bool = True

    companion_mode_enabled: bool = False
    affection_level: str = "friendly"
    preferred_name: str = ""
    preferred_pronouns: str = ""
    preferred_terms_of_endearment: list[str] = Field(default_factory=list)

    hard_boundaries: list[str] = Field(default_factory=list)
    sensitive_topics: list[str] = Field(default_factory=list)
    consent_notes: str = ""

    default_spicy_strength: float = Field(0.30, ge=0.0, le=1.0)
    allowed_content_tags: list[str] = Field(default_factory=list)
    blocked_content_tags: list[str] = Field(default_factory=list)


class SecretUpsertBody(BaseModel):
    key: str = Field(..., min_length=1, max_length=64)
    value: str = Field(..., min_length=1, max_length=4096)
    description: str = ""


class MemoryItemBody(BaseModel):
    id: str = Field(..., min_length=6, max_length=64)
    text: str = Field(..., min_length=1, max_length=500)
    category: str = "general"
    importance: int = Field(default=2, ge=1, le=5)
    last_confirmed_iso: str = ""
    source: str = "user"
    pinned: bool = False


class MemoryBulkBody(BaseModel):
    items: List[MemoryItemBody]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm_list(xs: List[str]) -> List[str]:
    return sorted({(x or "").strip() for x in (xs or []) if (x or "").strip()})


def _mask_secret(value: str) -> str:
    v = value or ""
    if len(v) <= 6:
        return "••••••"
    return f"{v[:2]}••••••{v[-2:]}"


# ---------------------------------------------------------------------------
# Profile endpoints
# ---------------------------------------------------------------------------

@router.get("/v1/user-profile")
def get_user_profile(user: Dict[str, Any] = Depends(require_current_user)):
    ensure_user_profile_tables()
    data = _get_user_profile(user["id"])
    # Merge defaults for any missing fields
    defaults = UserProfileData().model_dump()
    merged = {**defaults, **data}
    return {"ok": True, "profile": merged}


@router.put("/v1/user-profile")
def put_user_profile(
    profile: UserProfileData,
    user: Dict[str, Any] = Depends(require_current_user),
):
    ensure_user_profile_tables()
    p = profile.model_dump()

    # Normalize list fields
    for k in (
        "likes", "dislikes", "favorite_persona_tags",
        "preferred_terms_of_endearment", "hard_boundaries",
        "sensitive_topics", "allowed_content_tags", "blocked_content_tags",
    ):
        p[k] = _norm_list(p.get(k, []))

    # Normalize enums
    if p.get("affection_level") not in ("friendly", "affectionate", "romantic"):
        p["affection_level"] = "friendly"
    if p.get("preferred_tone") not in ("neutral", "friendly", "formal"):
        p["preferred_tone"] = "neutral"

    # Clamp spicy strength
    try:
        s = float(p.get("default_spicy_strength", 0.30))
    except Exception:
        s = 0.30
    p["default_spicy_strength"] = max(0.0, min(1.0, s))

    _save_user_profile(user["id"], p)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Secrets endpoints (per-user)
# ---------------------------------------------------------------------------

@router.get("/v1/user-profile/secrets")
def list_user_secrets(user: Dict[str, Any] = Depends(require_current_user)):
    ensure_user_profile_tables()
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "SELECT key, value, description FROM user_secrets WHERE user_id = ? ORDER BY key COLLATE NOCASE",
        (user["id"],)
    )
    rows = cur.fetchall()
    con.close()

    items = [
        {"key": r["key"], "masked": _mask_secret(r["value"]), "description": r["description"] or ""}
        for r in rows
    ]
    return {"ok": True, "secrets": items}


@router.put("/v1/user-profile/secrets")
def upsert_user_secret(
    body: SecretUpsertBody,
    user: Dict[str, Any] = Depends(require_current_user),
):
    ensure_user_profile_tables()
    key = body.key.strip()
    if not key.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Invalid secret key format")

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO user_secrets(user_id, key, value, description, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id, key) DO UPDATE SET
            value = excluded.value,
            description = excluded.description,
            updated_at = excluded.updated_at
    """, (user["id"], key, body.value, (body.description or "").strip(), now))
    con.commit()
    con.close()
    return {"ok": True}


@router.delete("/v1/user-profile/secrets/{key}")
def delete_user_secret(
    key: str,
    user: Dict[str, Any] = Depends(require_current_user),
):
    ensure_user_profile_tables()
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("DELETE FROM user_secrets WHERE user_id = ? AND key = ?", (user["id"], key))
    con.commit()
    con.close()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Memory endpoints (per-user)
# ---------------------------------------------------------------------------

@router.get("/v1/user-memory")
def get_user_memory(user: Dict[str, Any] = Depends(require_current_user)):
    ensure_user_profile_tables()
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM user_memory_items WHERE user_id = ? ORDER BY pinned DESC, importance DESC",
        (user["id"],)
    )
    rows = cur.fetchall()
    con.close()

    items = [
        {
            "id": r["id"],
            "text": r["text"],
            "category": r["category"],
            "importance": r["importance"],
            "last_confirmed_iso": r["last_confirmed_iso"] or "",
            "source": r["source"],
            "pinned": bool(r["pinned"]),
        }
        for r in rows
    ]
    return {"ok": True, "memory": {"items": items}}


@router.put("/v1/user-memory")
def put_user_memory(
    body: MemoryBulkBody,
    user: Dict[str, Any] = Depends(require_current_user),
):
    ensure_user_profile_tables()
    ids = [x.id for x in body.items]
    if len(ids) != len(set(ids)):
        raise HTTPException(400, "Duplicate memory item id")

    now = time.strftime("%Y-%m-%d %H:%M:%S")
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()

    # Delete existing items for this user, then re-insert (bulk upsert)
    cur.execute("DELETE FROM user_memory_items WHERE user_id = ?", (user["id"],))
    for item in body.items:
        cur.execute("""
            INSERT INTO user_memory_items(id, user_id, text, category, importance,
                last_confirmed_iso, source, pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            item.id, user["id"], item.text, item.category, item.importance,
            item.last_confirmed_iso, item.source, 1 if item.pinned else 0, now, now,
        ))

    con.commit()
    con.close()
    return {"ok": True}


@router.delete("/v1/user-memory/{item_id}")
def delete_user_memory_item(
    item_id: str,
    user: Dict[str, Any] = Depends(require_current_user),
):
    ensure_user_profile_tables()
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "DELETE FROM user_memory_items WHERE user_id = ? AND id = ?",
        (user["id"], item_id),
    )
    con.commit()
    con.close()
    return {"ok": True}
