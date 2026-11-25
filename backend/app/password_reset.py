"""
Local-account password reset — additive module.

By default a local password is reset **only from a terminal on the HomePilot
host** (see the CLI below). The sign-in page then just shows that command; it
cannot change a local password.

An owner who wants the sign-in page to offer a reset can opt in with
``HOMEPILOT_PASSWORD_RESET=1``. That web flow still proves the person **can
reach the machine HomePilot runs on**, the same way Jupyter and Grafana do it:

  1. ``POST /v1/auth/password-reset/request`` with a username or email.
     If it names a local account, the server makes a one-time code and puts it
     where only the host owner can read it:
        * the backend console / log, and
        * a file in ``<data dir>/password-reset/<username>.txt``.
     The code never goes back to the browser, and the response is the same
     whether or not the account exists.
  2. ``POST /v1/auth/password-reset/confirm`` with the identifier, the code and
     a new password. On success the password is replaced, every existing
     session of that account is signed out, the code is burned and the caller
     is signed in.

Codes are 10 characters (~50 bits), stored only as a SHA-256 hash, live for 15
minutes and allow 5 wrong tries before they are burned.

The command line, run in a shell on the host, always works:

    cd backend && python -m app.password_reset <username> --set-password  # set it now
    cd backend && python -m app.password_reset <username>   # print a code (only useful with the web flow on)

With the web flow on, set
``HOMEPILOT_PASSWORD_RESET_LOG=0`` to keep codes out of the console and only
write the file.

Federated (OllaBridge) accounts are never touched: their password lives in the
Cloud and is reset there.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import users as _users

logger = logging.getLogger("homepilot.password_reset")

router = APIRouter(prefix="/v1/auth/password-reset", tags=["auth"])

CODE_TTL_SECONDS = 15 * 60
MAX_ATTEMPTS = 5
REISSUE_COOLDOWN_SECONDS = 60
# No 0/O/1/I/L so a code read off a terminal is easy to type back in.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 10

_GENERIC_REQUEST_REPLY = {
    "ok": True,
    "message": (
        "If that is a local account on this HomePilot, a reset code was written "
        "to the server console and to the password-reset folder in its data "
        "directory. The code expires in 15 minutes."
    ),
    "expires_in": CODE_TTL_SECONDS,
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _flag(name: str, default: bool = True) -> bool:
    v = os.getenv(name, "").strip().lower()
    if not v:
        return default
    return v not in ("0", "false", "no", "off")


def web_reset_enabled() -> bool:
    # Off unless the owner opts in: local passwords are reset from a terminal on the host.
    return _flag("HOMEPILOT_PASSWORD_RESET", False)


def _log_codes() -> bool:
    return _flag("HOMEPILOT_PASSWORD_RESET_LOG", True)


def reset_dir() -> str:
    """Folder that holds pending reset codes: next to the SQLite database."""
    db_dir = os.path.dirname(os.path.abspath(_users._get_db_path())) or "."
    return os.path.join(db_dir, "password-reset")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def ensure_reset_table() -> None:
    con = sqlite3.connect(_users._get_db_path())
    con.execute("""
        CREATE TABLE IF NOT EXISTS password_resets(
            user_id TEXT PRIMARY KEY,
            code_hash TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0
        )
    """)
    con.commit()
    con.close()


def _hash_code(code: str) -> str:
    return hashlib.sha256(_normalize_code(code).encode()).hexdigest()


def _normalize_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def _new_code() -> str:
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))
    return f"{raw[:5]}-{raw[5:]}"


def _safe_name(username: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", username or "account")[:64] or "account"


def _code_file(user: Dict[str, Any]) -> str:
    return os.path.join(reset_dir(), f"{_safe_name(user.get('username', ''))}.txt")


def _remove_code_file(user: Dict[str, Any]) -> None:
    try:
        os.remove(_code_file(user))
    except OSError:
        pass


def _get_row(user_id: str) -> Optional[sqlite3.Row]:
    con = sqlite3.connect(_users._get_db_path())
    con.row_factory = sqlite3.Row
    row = con.execute(
        "SELECT * FROM password_resets WHERE user_id = ?", (user_id,)
    ).fetchone()
    con.close()
    return row


def _delete_row(user_id: str) -> None:
    con = sqlite3.connect(_users._get_db_path())
    con.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Core operations (shared by the API and the CLI)
# ---------------------------------------------------------------------------

def find_local_user(identifier: str) -> Optional[Dict[str, Any]]:
    """Resolve a username or an unambiguous email to a *local* account."""
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    _users.ensure_users_tables()
    user = _users.get_user_by_username(identifier)
    if not user and "@" in identifier:
        if _users.count_users_by_email(identifier) == 1:
            user = _users.get_user_by_email(identifier)
    if not user:
        return None
    if (user.get("auth_provider") or "local") != "local":
        return None
    return user


def issue_code(user: Dict[str, Any], *, announce: bool = True) -> str:
    """Make a fresh code for ``user`` (replacing any older one) and deliver it
    to the host: a file in the data directory, plus the console unless turned
    off. Returns the plain code so the CLI can print it."""
    ensure_reset_table()
    code = _new_code()
    now = time.time()
    con = sqlite3.connect(_users._get_db_path())
    con.execute(
        "INSERT OR REPLACE INTO password_resets(user_id, code_hash, created_at, expires_at, attempts) "
        "VALUES (?, ?, ?, ?, 0)",
        (user["id"], _hash_code(code), now, now + CODE_TTL_SECONDS),
    )
    con.commit()
    con.close()

    expires_local = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now + CODE_TTL_SECONDS))
    path = _code_file(user)
    try:
        os.makedirs(reset_dir(), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(
                "HomePilot password reset\n"
                f"Account: {user.get('username', '')}\n"
                f"Code:    {code}\n"
                f"Expires: {expires_local}\n\n"
                "Enter this code on the sign-in page under 'Forgot password?'.\n"
                "If you did not ask for it, delete this file; the code expires on its own.\n"
            )
    except OSError as e:
        logger.warning("password reset: could not write %s: %s", path, e)

    if announce and _log_codes():
        logger.warning(
            "\n================ HomePilot password reset ================\n"
            "  Account: %s\n  Code:    %s\n  Expires: %s (15 minutes)\n"
            "  Also saved to: %s\n"
            "==========================================================",
            user.get("username", ""), code, expires_local, path,
        )
    return code


def check_code(user: Dict[str, Any], code: str) -> bool:
    """True when ``code`` is the live code for ``user``. Wrong tries count
    against the code; after ``MAX_ATTEMPTS`` or expiry it is burned."""
    ensure_reset_table()
    row = _get_row(user["id"])
    if not row:
        return False
    if time.time() > float(row["expires_at"]) or int(row["attempts"]) >= MAX_ATTEMPTS:
        _delete_row(user["id"])
        _remove_code_file(user)
        return False
    if hmac.compare_digest(row["code_hash"], _hash_code(code)):
        return True
    con = sqlite3.connect(_users._get_db_path())
    con.execute(
        "UPDATE password_resets SET attempts = attempts + 1 WHERE user_id = ?", (user["id"],)
    )
    con.commit()
    con.close()
    if int(row["attempts"]) + 1 >= MAX_ATTEMPTS:
        _delete_row(user["id"])
        _remove_code_file(user)
    return False


def set_password(user: Dict[str, Any], new_password: str) -> int:
    """Replace the password, sign out every session, and burn any reset code.
    Returns how many sessions were signed out."""
    con = sqlite3.connect(_users._get_db_path())
    cur = con.cursor()
    cur.execute(
        "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
        (_users._hash_password(new_password), time.strftime("%Y-%m-%d %H:%M:%S"), user["id"]),
    )
    cur.execute("DELETE FROM user_sessions WHERE user_id = ?", (user["id"],))
    revoked = cur.rowcount or 0
    con.commit()
    con.close()
    ensure_reset_table()
    _delete_row(user["id"])
    _remove_code_file(user)
    return revoked


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

class ResetRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=256)


class ResetConfirm(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=256)
    code: str = Field(..., min_length=1, max_length=64)
    new_password: str = Field(..., max_length=128)


def _require_enabled() -> None:
    if not web_reset_enabled():
        raise HTTPException(
            403,
            "Local passwords are reset from a terminal on the HomePilot machine: "
            "`cd backend` then `python -m app.password_reset <username> --set-password`.",
        )


@router.get("/status")
def reset_status():
    """Lets the sign-in page know whether to offer the local reset form."""
    return {"enabled": web_reset_enabled(), "expires_in": CODE_TTL_SECONDS}


@router.post("/request")
def request_reset(body: ResetRequest, request: Request):
    _require_enabled()
    ip = _users._client_ip(request)
    if not _users._rate_allowed(f"pwreset-req:{ip}", limit=5, window_seconds=60.0):
        raise HTTPException(429, "Too many requests. Please slow down.")

    user = find_local_user(body.identifier)
    if user:
        ensure_reset_table()
        row = _get_row(user["id"])
        fresh = row is not None and time.time() - float(row["created_at"]) < REISSUE_COOLDOWN_SECONDS
        # Within a minute of the last code, keep it: repeat clicks would
        # otherwise replace a code the owner is already reading.
        if not fresh:
            issue_code(user)
    return dict(_GENERIC_REQUEST_REPLY)


@router.post("/confirm")
def confirm_reset(body: ResetConfirm, request: Request):
    _require_enabled()
    ip = _users._client_ip(request)
    if not _users._rate_allowed(f"pwreset-confirm:{ip}", limit=10, window_seconds=60.0):
        raise HTTPException(429, "Too many requests. Please slow down.")

    min_len = _users._MIN_PASSWORD_LEN
    if len(body.new_password or "") < min_len:
        raise HTTPException(400, f"New password must be at least {min_len} characters")

    user = find_local_user(body.identifier)
    if not user or not check_code(user, body.code):
        raise HTTPException(400, "That code is wrong or has expired. Request a new one.")

    set_password(user, body.new_password)
    token = _users._create_token(user["id"])
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
    _users._set_session_cookie(resp, token)
    return resp


# ---------------------------------------------------------------------------
# CLI:  python -m app.password_reset <username> [--set-password]
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    import argparse
    import getpass

    parser = argparse.ArgumentParser(
        prog="python -m app.password_reset",
        description="Reset the password of a local HomePilot account. Run it on the HomePilot host.",
    )
    parser.add_argument("account", help="username or email of the local account")
    parser.add_argument(
        "--set-password", action="store_true",
        help="type a new password now instead of printing a one-time code",
    )
    args = parser.parse_args(argv)

    user = find_local_user(args.account)
    if not user:
        print(f"No local account named '{args.account}'. OllaBridge accounts reset on OllaBridge Cloud.")
        return 1

    if args.set_password:
        min_len = _users._MIN_PASSWORD_LEN
        pw = getpass.getpass("New password: ")
        if len(pw) < min_len:
            print(f"Password must be at least {min_len} characters.")
            return 2
        if getpass.getpass("Repeat it: ") != pw:
            print("The two passwords do not match.")
            return 2
        revoked = set_password(user, pw)
        print(f"Password for '{user['username']}' updated. Signed out {revoked} session(s).")
        return 0

    code = issue_code(user, announce=False)
    print(f"Reset code for '{user['username']}': {code}")
    print("Enter it on the sign-in page under 'Forgot password?' within 15 minutes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
