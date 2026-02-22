"""
Multi-User Accounts — additive module.

Provides user registration, login, session tokens, and onboarding.
Zero changes to existing single-user behavior: if no users exist,
the system auto-creates a default user on first boot.

Storage: SQLite (same DB as everything else).
Passwords: bcrypt-hashed (preferred) or SHA-256+salt (legacy fallback).
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

from fastapi import APIRouter, Depends, Header, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field

from .config import SQLITE_PATH, UPLOAD_DIR

# Try to import bcrypt for stronger password hashing (preferred).
# Falls back to SHA-256+salt if bcrypt is not installed.
try:
    import bcrypt
    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False

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
# Password hashing — bcrypt preferred, SHA-256+salt legacy fallback
# ---------------------------------------------------------------------------

def _hash_password(password: str) -> str:
    """Hash password. Uses bcrypt if available, else SHA-256+salt."""
    if not password:
        return ""
    if _HAS_BCRYPT:
        return "bcrypt:" + bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    # Fallback: SHA-256 + salt
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash. Supports both bcrypt and SHA-256+salt."""
    if not stored_hash:
        return not password  # No password set → only empty password matches
    if not password:
        return False
    # bcrypt hashes start with "bcrypt:" prefix
    if stored_hash.startswith("bcrypt:"):
        if not _HAS_BCRYPT:
            return False
        return bcrypt.checkpw(password.encode(), stored_hash[7:].encode())
    # Legacy SHA-256+salt: "salt:hash"
    parts = stored_hash.split(":", 1)
    if len(parts) != 2:
        return False
    salt, expected = parts
    h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return h == expected


def _upgrade_password_hash_if_needed(user_id: str, password: str, stored_hash: str) -> None:
    """If password was verified with legacy SHA-256 and bcrypt is available, upgrade."""
    if not _HAS_BCRYPT:
        return
    if stored_hash.startswith("bcrypt:"):
        return  # Already bcrypt
    if not password or not stored_hash:
        return
    new_hash = _hash_password(password)
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
        (new_hash, time.strftime("%Y-%m-%d %H:%M:%S"), user_id),
    )
    con.commit()
    con.close()


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
    """Validate a bearer token. Checks expiry. Returns user dict or None."""
    if not token:
        return None

    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    now = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    cur.execute("""
        SELECT u.* FROM users u
        JOIN user_sessions s ON s.user_id = u.id
        WHERE s.token = ?
          AND (s.expires_at IS NULL OR s.expires_at > ?)
    """, (token, now))

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
            "avatar_url": "",
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

    # Auto-upgrade legacy SHA-256 hashes to bcrypt on successful login
    _upgrade_password_hash_if_needed(user["id"], body.password, user.get("password_hash", ""))

    token = _create_token(user["id"])

    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "email": user["email"],
            "avatar_url": user.get("avatar_url", ""),
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
                    "avatar_url": users[0].get("avatar_url", ""),
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
            "avatar_url": user.get("avatar_url", ""),
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

    # Legacy bridge: only update global profile.json when the instance is
    # still in single-user mode.  In multi-user setups writing here would
    # let one user's onboarding overwrite another's shared profile — a
    # cross-user contamination bug.
    try:
        if count_users() <= 1:
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
        pass  # Non-fatal — legacy bridge

    # Also sync to per-user profile store (multi-user aware)
    try:
        from .user_profile_store import ensure_user_profile_tables, _save_user_profile, _get_user_profile
        ensure_user_profile_tables()
        user_profile = _get_user_profile(user["id"])
        if body.display_name:
            user_profile["display_name"] = body.display_name.strip()
        if body.preferred_tone:
            user_profile["preferred_tone"] = body.preferred_tone
        user_profile["personalization_enabled"] = True
        _save_user_profile(user["id"], user_profile)
    except Exception:
        pass  # Non-fatal — per-user profile sync is best-effort

    return {
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": body.display_name.strip() or user["display_name"],
            "avatar_url": user.get("avatar_url", ""),
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


# ---------------------------------------------------------------------------
# Avatar upload
# ---------------------------------------------------------------------------

@router.put("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    authorization: str = Header(default=""),
):
    """Upload or replace user avatar image. Stores in uploads dir, updates users.avatar_url."""
    token = authorization.replace("Bearer ", "").strip()
    user = _validate_token(token) if token else None
    if not user:
        raise HTTPException(401, "Not authenticated")

    # Validate file type
    ext = os.path.splitext(file.filename or "")[-1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(400, "Unsupported image format. Use PNG, JPG, or WebP.")

    # Read file (limit 5MB for avatars)
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(400, "Avatar image must be under 5MB")

    # Determine upload directory (reuse existing upload path logic)
    upload_dir = UPLOAD_DIR
    if not os.path.isabs(upload_dir):
        import pathlib
        _backend_dir = pathlib.Path(__file__).resolve().parents[1]
        upload_dir = str(_backend_dir / "data" / "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    # Save with unique name
    filename = f"avatar_{user['id']}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(upload_dir, filename)
    with open(filepath, "wb") as f:
        f.write(contents)

    # Build URL (relative to /files/ static mount)
    avatar_url = f"/files/{filename}"

    # Delete old avatar file if it exists (cleanup)
    old_url = user.get("avatar_url", "")
    if old_url and old_url.startswith("/files/"):
        old_path = os.path.join(upload_dir, old_url.replace("/files/", "", 1))
        try:
            if os.path.exists(old_path):
                os.remove(old_path)
        except Exception:
            pass  # Non-fatal

    # Update DB
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "UPDATE users SET avatar_url = ?, updated_at = ? WHERE id = ?",
        (avatar_url, time.strftime("%Y-%m-%d %H:%M:%S"), user["id"]),
    )
    con.commit()
    con.close()

    return {"ok": True, "avatar_url": avatar_url}


@router.delete("/avatar")
def delete_avatar(authorization: str = Header(default="")):
    """Remove user avatar."""
    token = authorization.replace("Bearer ", "").strip()
    user = _validate_token(token) if token else None
    if not user:
        raise HTTPException(401, "Not authenticated")

    # Delete file
    old_url = user.get("avatar_url", "")
    if old_url and old_url.startswith("/files/"):
        upload_dir = UPLOAD_DIR
        if not os.path.isabs(upload_dir):
            import pathlib
            _backend_dir = pathlib.Path(__file__).resolve().parents[1]
            upload_dir = str(_backend_dir / "data" / "uploads")
        old_path = os.path.join(upload_dir, old_url.replace("/files/", "", 1))
        try:
            if os.path.exists(old_path):
                os.remove(old_path)
        except Exception:
            pass

    # Clear in DB
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "UPDATE users SET avatar_url = '', updated_at = ? WHERE id = ?",
        (time.strftime("%Y-%m-%d %H:%M:%S"), user["id"]),
    )
    con.commit()
    con.close()

    return {"ok": True}
