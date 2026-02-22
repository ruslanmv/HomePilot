"""
Multi-User Accounts — additive module.

Provides user registration, login, session tokens, and onboarding.
Zero changes to existing single-user behavior: if no users exist,
the system auto-creates a default user on first boot.

Storage: SQLite (same DB as everything else).
Passwords: optional, bcrypt-hashed when set.
Tokens: random bearer tokens stored in user_sessions table.

ADDITIVE ONLY — does not modify any existing module.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .config import SQLITE_PATH

router = APIRouter(prefix="/v1/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_db_path() -> str:
    from .storage import _get_db_path as _storage_db_path
    return _storage_db_path()


def ensure_users_tables() -> None:
    """Create users + user_sessions tables if they don't exist. Safe to call multiple times."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT DEFAULT '',
            email TEXT DEFAULT '',
            password_hash TEXT DEFAULT '',
            avatar_url TEXT DEFAULT '',
            onboarding_complete INTEGER DEFAULT 0,
            onboarding_data TEXT DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_sessions(
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            expires_at DATETIME,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id)"
    )

    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Password hashing (simple SHA-256 + salt — no bcrypt dependency needed)
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Hash password with random salt. Returns 'salt:hash'."""
    if not password:
        return ""
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored 'salt:hash'."""
    if not stored_hash:
        return not password  # No password set → only empty password matches
    if not password:
        return False
    parts = stored_hash.split(":", 1)
    if len(parts) != 2:
        return False
    salt, expected = parts
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return h == expected


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

def _create_token(user_id: str) -> str:
    """Create a new session token for a user."""
    token = secrets.token_urlsafe(48)
    expires = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + 30 * 86400))  # 30 days

    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO user_sessions(token, user_id, expires_at) VALUES (?, ?, ?)",
        (token, user_id, expires),
    )
    con.commit()
    con.close()
    return token


def _validate_token(token: str) -> Optional[Dict[str, Any]]:
    """Validate a bearer token. Returns user dict or None."""
    if not token:
        return None

    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute("""
        SELECT u.* FROM users u
        JOIN user_sessions s ON s.user_id = u.id
        WHERE s.token = ?
    """, (token,))

    row = cur.fetchone()
    con.close()

    if not row:
        return None

    return dict(row)


def _invalidate_token(token: str) -> None:
    """Delete a session token."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# User CRUD
# ---------------------------------------------------------------------------

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def list_users() -> List[Dict[str, Any]]:
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT id, username, display_name, email, avatar_url, onboarding_complete, created_at FROM users ORDER BY created_at")
    rows = cur.fetchall()
    con.close()
    return [dict(r) for r in rows]


def count_users() -> int:
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    con.close()
    return count


def create_user(
    username: str,
    password: str = "",
    email: str = "",
    display_name: str = "",
) -> Dict[str, Any]:
    """Create a new user. Returns user dict."""
    user_id = str(uuid.uuid4())
    password_hash = _hash_password(password) if password else ""
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("""
        INSERT INTO users(id, username, display_name, email, password_hash, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, username.strip(), display_name.strip(), email.strip(), password_hash, now, now))
    con.commit()
    con.close()

    return {
        "id": user_id,
        "username": username.strip(),
        "display_name": display_name.strip(),
        "email": email.strip(),
        "onboarding_complete": 0,
        "created_at": now,
    }


# ---------------------------------------------------------------------------
# Auto-login for single-user setups (backward compatibility)
# ---------------------------------------------------------------------------

def get_or_create_default_user() -> Dict[str, Any]:
    """
    If no users exist, create a default 'admin' user with no password.
    Returns the default user. This preserves backward compatibility:
    single-user setups work exactly as before.
    """
    users = list_users()
    if users:
        return users[0]

    return create_user(
        username="admin",
        password="",
        display_name="Admin",
    )


# ---------------------------------------------------------------------------
# Auth dependency (for protecting endpoints)
# ---------------------------------------------------------------------------

def get_current_user(authorization: str = Header(default="")) -> Optional[Dict[str, Any]]:
    """
    FastAPI dependency: extract user from Authorization header.
    Returns user dict or None. Does NOT raise — for optional auth.
    """
    if not authorization:
        return None
    token = authorization.replace("Bearer ", "").strip()
    if not token:
        return None
    return _validate_token(token)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=256)
    display_name: str = Field(default="", max_length=64)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=32)
    password: str = Field(default="", max_length=128)


class OnboardingRequest(BaseModel):
    display_name: str = Field(default="", max_length=64)
    use_cases: List[str] = Field(default_factory=list)
    preferred_tone: str = Field(default="balanced")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register")
def register(body: RegisterRequest):
    """Create a new user account."""
    ensure_users_tables()

    username = body.username.strip()
    if not username:
        raise HTTPException(400, "Username is required")

    # Check username format
    if not username.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "Username can only contain letters, numbers, hyphens, and underscores")

    # Check if username taken
    existing = get_user_by_username(username)
    if existing:
        raise HTTPException(409, "Username already taken")

    user = create_user(
        username=username,
        password=body.password,
        email=body.email,
        display_name=body.display_name or username,
    )

    token = _create_token(user["id"])

    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "email": user["email"],
            "onboarding_complete": False,
        },
        "token": token,
    }


@router.post("/login")
def login(body: LoginRequest):
    """Authenticate and get a session token."""
    ensure_users_tables()

    user = get_user_by_username(body.username.strip())
    if not user:
        raise HTTPException(401, "Invalid username or password")

    if not _verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid username or password")

    token = _create_token(user["id"])

    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "email": user["email"],
            "onboarding_complete": bool(user.get("onboarding_complete")),
        },
        "token": token,
    }


@router.post("/logout")
def logout(authorization: str = Header(default="")):
    """Invalidate the current session token."""
    token = authorization.replace("Bearer ", "").strip()
    if token:
        _invalidate_token(token)
    return {"ok": True}


@router.get("/me")
def get_me(authorization: str = Header(default="")):
    """Get the current authenticated user."""
    ensure_users_tables()

    token = authorization.replace("Bearer ", "").strip()
    user = _validate_token(token) if token else None

    if not user:
        # Auto-login for single-user / no-password setups
        users = list_users()
        if not users:
            # No users at all — first boot
            return {"ok": True, "user": None, "needs_setup": True}
        if len(users) == 1 and not users[0].get("password_hash"):
            # Single user, no password — auto-login
            auto_token = _create_token(users[0]["id"])
            return {
                "ok": True,
                "user": {
                    "id": users[0]["id"],
                    "username": users[0]["username"],
                    "display_name": users[0]["display_name"],
                    "email": users[0]["email"],
                    "onboarding_complete": bool(users[0].get("onboarding_complete")),
                },
                "token": auto_token,
            }
        return {"ok": True, "user": None, "needs_login": True}

    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "email": user["email"],
            "onboarding_complete": bool(user.get("onboarding_complete")),
        },
    }


@router.put("/onboarding")
def complete_onboarding(body: OnboardingRequest, authorization: str = Header(default="")):
    """Save onboarding answers and mark onboarding as complete."""
    ensure_users_tables()

    token = authorization.replace("Bearer ", "").strip()
    user = _validate_token(token) if token else None
    if not user:
        raise HTTPException(401, "Not authenticated")

    onboarding_data = {
        "display_name": body.display_name.strip(),
        "use_cases": body.use_cases[:6],  # cap at 6
        "preferred_tone": body.preferred_tone if body.preferred_tone in ("casual", "balanced", "professional") else "balanced",
    }

    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("""
        UPDATE users
        SET display_name = ?,
            onboarding_complete = 1,
            onboarding_data = ?,
            updated_at = ?
        WHERE id = ?
    """, (
        body.display_name.strip() or user["display_name"],
        json.dumps(onboarding_data),
        time.strftime("%Y-%m-%d %H:%M:%S"),
        user["id"],
    ))
    con.commit()
    con.close()

    # Also update the profile.json with onboarding data (bridge to existing system)
    try:
        from .profile import _data_root, _atomic_write_json, _read_json, PROFILE_FILE
        root = _data_root()
        profile_path = root / PROFILE_FILE
        profile = _read_json(profile_path, default={})
        if body.display_name:
            profile["display_name"] = body.display_name.strip()
        if body.preferred_tone:
            profile["preferred_tone"] = body.preferred_tone
        profile["personalization_enabled"] = True
        _atomic_write_json(profile_path, profile)
    except Exception:
        pass  # Non-fatal — profile sync is best-effort

    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": body.display_name.strip() or user["display_name"],
            "onboarding_complete": True,
        },
    }


@router.get("/users")
def get_users():
    """List all users (for user switcher). Passwords are never exposed."""
    ensure_users_tables()
    users = list_users()
    return {
        "ok": True,
        "users": users,
        "count": len(users),
    }
