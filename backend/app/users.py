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

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse
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

    # ---- Additive migration: federated-identity columns (non-destructive) ----
    # Two nullable columns let a HomePilot user be linked to an OllaBridge Cloud
    # identity without touching existing rows or single-user installs:
    #   auth_provider  — "local" (default) or "ollabridge"/"google" for federated
    #   cloud_user_id  — the Cloud User.id this local row is linked to (unique)
    # Guarded by PRAGMA table_info so ensure_users_tables() stays idempotent and
    # safe to call on every boot / every request.
    cur.execute("PRAGMA table_info(users)")
    existing_cols = {row[1] for row in cur.fetchall()}
    if "auth_provider" not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN auth_provider TEXT DEFAULT 'local'")
    if "cloud_user_id" not in existing_cols:
        cur.execute("ALTER TABLE users ADD COLUMN cloud_user_id TEXT")
    # Unique index on cloud_user_id (partial: NULLs are excluded so unlinked
    # local rows don't collide). SQLite honours the WHERE clause on indexes.
    cur.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cloud_user_id "
        "ON users(cloud_user_id) WHERE cloud_user_id IS NOT NULL"
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


_SESSION_COOKIE = "homepilot_session"
_SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 30 days


def _cookie_secure() -> bool:
    """Whether to set the ``Secure`` flag on the session cookie.

    Environment-aware instead of hardcoded ``False`` (which would leak the
    cookie over plain HTTP in production). Resolution:
      * ``HOMEPILOT_COOKIE_SECURE=true|false`` — explicit override, wins.
      * otherwise ``auto``: Secure when a public HTTPS base URL is configured
        (``PUBLIC_BASE_URL`` / ``APP_BASE_URL`` starts with ``https://``).
    Local dev over http://localhost keeps Secure off, so nothing regresses.
    """
    v = os.getenv("HOMEPILOT_COOKIE_SECURE", "auto").strip().lower()
    if v in ("1", "true", "yes"):
        return True
    if v in ("0", "false", "no"):
        return False
    base = (os.getenv("PUBLIC_BASE_URL", "") or os.getenv("APP_BASE_URL", "")).strip()
    return base.startswith("https://")


def _set_session_cookie(resp: JSONResponse, token: str) -> JSONResponse:
    """Attach the HttpOnly session cookie with an environment-aware Secure flag."""
    resp.set_cookie(
        key=_SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        max_age=_SESSION_MAX_AGE,
        path="/",
    )
    return resp


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


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Look up a user by email (case-insensitive), ignoring blank emails.

    Additive helper — supports the "Username **or** email" login field and the
    verified-email account-linking branch in /v1/auth/exchange. Emails are not
    guaranteed unique in the legacy schema, so this returns the *earliest*
    match deterministically; callers that need takeover-safety must additionally
    require proof (verified email + no ambiguity), which /exchange enforces.
    """
    email = (email or "").strip()
    if not email:
        return None
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM users WHERE email <> '' AND email = ? COLLATE NOCASE "
        "ORDER BY created_at LIMIT 1",
        (email,),
    )
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def count_users_by_email(email: str) -> int:
    """Number of users sharing an email (case-insensitive). Used to refuse
    linking when an email is ambiguous."""
    email = (email or "").strip()
    if not email:
        return 0
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM users WHERE email <> '' AND email = ? COLLATE NOCASE",
        (email,),
    )
    n = cur.fetchone()[0]
    con.close()
    return int(n)


def get_user_by_cloud_id(cloud_user_id: str) -> Optional[Dict[str, Any]]:
    """Look up a local user previously linked to an OllaBridge Cloud identity."""
    cloud_user_id = (cloud_user_id or "").strip()
    if not cloud_user_id:
        return None
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM users WHERE cloud_user_id = ?", (cloud_user_id,))
    row = cur.fetchone()
    con.close()
    return dict(row) if row else None


def set_cloud_link(user_id: str, cloud_user_id: str, auth_provider: str = "ollabridge") -> None:
    """Link a local user row to a Cloud identity (idempotent)."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "UPDATE users SET cloud_user_id = ?, auth_provider = ?, updated_at = ? WHERE id = ?",
        (cloud_user_id.strip(), auth_provider, time.strftime("%Y-%m-%d %H:%M:%S"), user_id),
    )
    con.commit()
    con.close()


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
    cur.execute("SELECT id, username, display_name, email, avatar_url, onboarding_complete, auth_provider, created_at FROM users ORDER BY created_at")
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

def get_current_user(
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> Optional[Dict[str, Any]]:
    """
    Enterprise auth:
      - Prefer Authorization: Bearer <token>
      - Fall back to HttpOnly cookie `homepilot_session` (for <img> tags and file downloads)
    Returns user dict or None. Does NOT raise — for optional auth.
    """
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    if not token and homepilot_session:
        token = homepilot_session.strip()

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
    # Named ``username`` for backward compatibility, but the field now also
    # accepts an email address (see login() — it falls back to an email lookup
    # when the identifier contains "@"). max_length widened from 32 → 256 so a
    # full email fits; usernames themselves are still capped at 32 on register.
    username: str = Field(..., min_length=2, max_length=256)
    password: str = Field(default="", max_length=128)


class OnboardingRequest(BaseModel):
    display_name: str = Field(default="", max_length=64)
    use_cases: List[str] = Field(default_factory=list)
    preferred_tone: str = Field(default="balanced")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/register")
def register(body: RegisterRequest, request: Request):
    """Create a new user account."""
    ensure_users_tables()

    if not _rate_allowed(f"register:{_client_ip(request)}", limit=10, window_seconds=60.0):
        raise HTTPException(429, "Too many requests. Please slow down.")

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

    resp = JSONResponse({
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
    })
    _set_session_cookie(resp, token)
    return resp


@router.post("/login")
def login(body: LoginRequest, request: Request):
    """Authenticate and get a session token.

    Accepts a username **or** an email in the ``username`` field. Username
    lookup is tried first (preserves all existing behavior); only when it
    misses and the identifier looks like an email ("@") do we fall back to an
    email lookup. Federated (``auth_provider != 'local'``) accounts cannot log
    in through this password path — they authenticate via /v1/auth/exchange.
    """
    ensure_users_tables()

    if not _rate_allowed(f"login:{_client_ip(request)}", limit=20, window_seconds=60.0):
        raise HTTPException(429, "Too many requests. Please slow down.")

    identifier = body.username.strip()
    user = get_user_by_username(identifier)
    if not user and "@" in identifier:
        user = get_user_by_email(identifier)
    if not user:
        raise HTTPException(401, "Invalid username or password")

    # Federated accounts have no usable local password — block the empty-password
    # match (_verify_password("", "") is True) that would otherwise let anyone in.
    if (user.get("auth_provider") or "local") != "local":
        raise HTTPException(401, "Invalid username or password")

    if not _verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(401, "Invalid username or password")

    # Auto-upgrade legacy SHA-256 hashes to bcrypt on successful login
    _upgrade_password_hash_if_needed(user["id"], body.password, user.get("password_hash", ""))

    token = _create_token(user["id"])

    resp = JSONResponse({
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
    })
    _set_session_cookie(resp, token)
    return resp


# ---------------------------------------------------------------------------
# Federated sign-in — "Continue with OllaBridge" (token exchange + JIT provision)
# ---------------------------------------------------------------------------

# Simple in-process sliding-window rate limiter. Good enough for a single-node
# HomePilot; keyed by client IP. Not a distributed limiter — intentionally
# dependency-free so it works on offline/self-hosted installs.
import threading  # noqa: E402  (local import kept beside its only user)
from collections import defaultdict, deque

_rate_lock = threading.Lock()
_rate_hits: Dict[str, "deque[float]"] = defaultdict(deque)


def _rate_limit(key: str, *, limit: int, window_seconds: float) -> bool:
    """Return True if the call is allowed, False if the caller exceeded ``limit``
    requests within ``window_seconds``. Prunes old timestamps as it goes."""
    now = time.time()
    with _rate_lock:
        hits = _rate_hits[key]
        cutoff = now - window_seconds
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True


def _rate_allowed(key: str, *, limit: int, window_seconds: float) -> bool:
    """Endpoint-facing wrapper around ``_rate_limit``.

    Disabled under pytest (``PYTEST_CURRENT_TEST`` is auto-set per test) and via
    ``HOMEPILOT_DISABLE_RATE_LIMIT`` so a fast in-process test run — which fires
    many register/login calls from a single client IP — never trips the limiter.
    Production is unaffected (neither var is set). The limiter itself
    (``_rate_limit``) stays pure so it can be unit-tested directly.
    """
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("HOMEPILOT_DISABLE_RATE_LIMIT"):
        return True
    return _rate_limit(key, limit=limit, window_seconds=window_seconds)


def _client_ip(request: Request) -> str:
    """Best-effort client IP for rate-limit bucketing (honours X-Forwarded-For)."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _unique_username(seed: str) -> str:
    """Derive a valid, unique HomePilot username from an email local-part / name.

    Sanitises to the register() charset (letters/digits/_/-), enforces the
    2..32 length window, then de-duplicates with a numeric suffix.
    """
    base = (seed or "").split("@", 1)[0].strip().lower()
    base = "".join(ch for ch in base if ch.isalnum() or ch in ("_", "-"))
    if len(base) < 2:
        base = f"user{secrets.token_hex(2)}"
    base = base[:32]
    candidate = base
    n = 0
    while get_user_by_username(candidate) is not None:
        n += 1
        suffix = str(n)
        candidate = f"{base[:32 - len(suffix)]}{suffix}"
    return candidate


class ExchangeRequest(BaseModel):
    cloud_token: str = Field(..., min_length=8, max_length=4096)


def _fetch_cloud_userinfo(cloud_token: str) -> Optional[Dict[str, Any]]:
    """Validate a Cloud token by calling OllaBridge Cloud's userinfo endpoint.

    Introspection over a shared secret: HomePilot never needs the Cloud
    ``JWT_SECRET`` — it hands the token back to Cloud and trusts Cloud's answer.
    Returns the userinfo dict on 200, or None on any auth failure / error.
    """
    import httpx
    from . import config as _cfg

    base = (getattr(_cfg, "OLLABRIDGE_CLOUD_URL", "") or "").rstrip("/")
    if not base:
        return None
    try:
        r = httpx.get(
            f"{base}/v1/auth/me",
            headers={"Authorization": f"Bearer {cloud_token}"},
            timeout=15.0,
        )
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:
        return None


@router.post("/exchange")
def exchange(body: ExchangeRequest, request: Request):
    """Exchange an OllaBridge Cloud token for a local HomePilot session.

    Flow (JIT-provision / link):
      1. Validate ``cloud_token`` against Cloud ``GET /v1/auth/me``.
      2. If a local user is already linked to that Cloud id → log in.
      3. Else, ONLY if the Cloud email is verified AND matches exactly one
         local account → link it (set cloud_user_id + auth_provider) → log in.
      4. Else create a new passwordless federated local user → log in.

    Issues the normal ``homepilot_session`` cookie + bearer token, so every
    downstream data-layer isolation (`WHERE user_id = ?`) is unchanged.
    """
    ensure_users_tables()

    # Rate-limit: 10 attempts / minute / IP. Uniform 429, no account oracle.
    if not _rate_allowed(f"exchange:{_client_ip(request)}", limit=10, window_seconds=60.0):
        raise HTTPException(429, "Too many requests. Please slow down.")

    info = _fetch_cloud_userinfo(body.cloud_token.strip())
    if not info or not info.get("user_id"):
        # Uniform 401 — never reveal whether the token is malformed vs expired.
        raise HTTPException(401, "Could not verify OllaBridge identity")

    cloud_user_id = str(info["user_id"]).strip()
    email = (info.get("email") or "").strip()
    email_verified = bool(info.get("email_verified"))
    display_name = (info.get("display_name") or "").strip()

    # 1) Already linked → log in.
    user = get_user_by_cloud_id(cloud_user_id)

    # 2) Link an existing local account by VERIFIED, UNAMBIGUOUS email only.
    #    Verified-only + single-match guards against account takeover (a local
    #    user pre-registering someone else's unverified email cannot capture it).
    if user is None and email_verified and email and count_users_by_email(email) == 1:
        candidate = get_user_by_email(email)
        if candidate is not None and not candidate.get("cloud_user_id"):
            set_cloud_link(candidate["id"], cloud_user_id, auth_provider="ollabridge")
            user = get_user_by_id(candidate["id"])

    # 3) JIT-create a fresh passwordless federated user.
    if user is None:
        created = create_user(
            username=_unique_username(email or display_name or cloud_user_id),
            password="",  # passwordless — federated identity, not local login
            email=email,
            display_name=display_name or "",
        )
        set_cloud_link(created["id"], cloud_user_id, auth_provider="ollabridge")
        user = get_user_by_id(created["id"])

    token = _create_token(user["id"])
    resp = JSONResponse({
        "ok": True,
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name", ""),
            "email": user.get("email", ""),
            "avatar_url": user.get("avatar_url", ""),
            "onboarding_complete": bool(user.get("onboarding_complete")),
            "auth_provider": user.get("auth_provider", "ollabridge"),
        },
        "token": token,
    })
    _set_session_cookie(resp, token)
    return resp


@router.post("/logout")
def logout(authorization: str = Header(default="")):
    """Invalidate the current session token."""
    token = authorization.replace("Bearer ", "").strip()
    if token:
        _invalidate_token(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("homepilot_session", path="/")
    return resp


# ---------------------------------------------------------------------------
# Password management (additive — account security tab)
# ---------------------------------------------------------------------------

class ChangePasswordRequest(BaseModel):
    current_password: str = Field(default="", max_length=128)
    new_password: str = Field(max_length=128)
    sign_out_others: bool = Field(default=False)


_MIN_PASSWORD_LEN = 8


def _invalidate_other_sessions(user_id: str, keep_token: str) -> int:
    """Invalidate every session for ``user_id`` except ``keep_token``.

    Returns the number of sessions invalidated.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "DELETE FROM user_sessions WHERE user_id = ? AND token != ?",
        (user_id, keep_token),
    )
    count = cur.rowcount or 0
    con.commit()
    con.close()
    return count


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    authorization: str = Header(default=""),
):
    """Change the current user's password.

    Rules:
    * Caller must be authenticated (Bearer token).
    * ``current_password`` must match the stored hash, **unless** the account
      has no password yet (first-time set from a legacy auto-created user).
    * ``new_password`` must be at least ``_MIN_PASSWORD_LEN`` characters.
    * ``new_password`` must differ from the current one.
    * When ``sign_out_others`` is true, all of the user's other sessions are
      invalidated; the caller's own token stays valid.

    Returns: ``{ok: true, sessions_revoked: <int>}``
    """
    ensure_users_tables()
    token = authorization.replace("Bearer ", "").strip()
    user = _validate_token(token) if token else None
    if not user:
        raise HTTPException(401, "Not authenticated")

    # Pull the latest password hash (user dict from _validate_token may not
    # include it — read straight from the DB to be sure).
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],))
    row = cur.fetchone()
    con.close()
    stored_hash = row[0] if row else ""

    # 1. Verify current password (allow empty when the account never had one).
    if stored_hash:
        if not _verify_password(body.current_password, stored_hash):
            raise HTTPException(400, "Current password is incorrect")

    # 2. Validate new password.
    new_password = body.new_password or ""
    if len(new_password) < _MIN_PASSWORD_LEN:
        raise HTTPException(400, f"New password must be at least {_MIN_PASSWORD_LEN} characters")
    if stored_hash and _verify_password(new_password, stored_hash):
        raise HTTPException(400, "New password must differ from the current one")

    # 3. Persist.
    new_hash = _hash_password(new_password)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
        (new_hash, now, user["id"]),
    )
    con.commit()
    con.close()

    # 4. Optional: invalidate other sessions.
    revoked = 0
    if body.sign_out_others:
        revoked = _invalidate_other_sessions(user["id"], token)

    return {"ok": True, "sessions_revoked": revoked}


@router.get("/sessions")
def list_sessions(authorization: str = Header(default="")):
    """List active sessions for the current user (count + current flag).

    Returns ``{current_session_id, sessions: [{id, created_at, expires_at,
    is_current}]}``. Session tokens themselves are never returned — only
    truncated public IDs so the UI can show "Log out other sessions".
    """
    ensure_users_tables()
    token = authorization.replace("Bearer ", "").strip()
    user = _validate_token(token) if token else None
    if not user:
        raise HTTPException(401, "Not authenticated")

    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "SELECT token, created_at, expires_at FROM user_sessions WHERE user_id = ? AND expires_at > datetime('now') ORDER BY created_at DESC",
        (user["id"],),
    )
    rows = cur.fetchall()
    con.close()

    sessions = []
    for row_token, created_at, expires_at in rows:
        public_id = row_token[:8]  # just enough to identify; never the full token
        sessions.append(
            {
                "id": public_id,
                "created_at": created_at,
                "expires_at": expires_at,
                "is_current": row_token == token,
            }
        )
    current = next((s["id"] for s in sessions if s["is_current"]), None)
    return {"current_session_id": current, "sessions": sessions}


@router.post("/sessions/revoke-others")
def revoke_other_sessions(authorization: str = Header(default="")):
    """Invalidate every session except the caller's own."""
    ensure_users_tables()
    token = authorization.replace("Bearer ", "").strip()
    user = _validate_token(token) if token else None
    if not user:
        raise HTTPException(401, "Not authenticated")
    revoked = _invalidate_other_sessions(user["id"], token)
    return {"ok": True, "sessions_revoked": revoked}


@router.get("/me")
def get_me(
    authorization: str = Header(default=""),
    homepilot_session: Optional[str] = Cookie(default=None),
):
    """Get the current authenticated user."""
    ensure_users_tables()

    # Support both Bearer header and HttpOnly cookie
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token and homepilot_session:
        token = homepilot_session.strip()
    user = _validate_token(token) if token else None

    if not user:
        # Auto-login for single-user / no-password setups
        users = list_users()
        if not users:
            # No users at all — first boot
            return {"ok": True, "user": None, "needs_setup": True}
        if (
            len(users) == 1
            and not users[0].get("password_hash")
            and (users[0].get("auth_provider") or "local") == "local"
        ):
            # Single LOCAL user, no password — auto-login (backward-compat
            # single-user bootstrap). A federated (ollabridge) lone account is
            # excluded: it must prove identity through /v1/auth/exchange, never
            # via a passwordless auto-login that anyone loading the page hits.
            auto_token = _create_token(users[0]["id"])
            resp = JSONResponse({
                "ok": True,
                "user": {
                    "id": users[0]["id"],
                    "username": users[0]["username"],
                    "display_name": users[0]["display_name"],
                    "email": users[0]["email"],
                    "avatar_url": users[0].get("avatar_url", ""),
                    "onboarding_complete": bool(users[0].get("onboarding_complete")),
                    # Always false on the auto-login branch (entered only
                    # when the lone user has no password set).
                    "has_password": False,
                },
                "token": auto_token,
            })
            resp.set_cookie(
                key="homepilot_session",
                value=auto_token,
                httponly=True,
                samesite="lax",
                secure=False,
                max_age=30 * 24 * 60 * 60,
                path="/",
            )
            return resp
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
            # Additive: lets the Security tab render "Set password" vs
            # "Change password" without a second round-trip. False for the
            # default admin created on first boot (no password set yet).
            "has_password": bool(user.get("password_hash")),
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
