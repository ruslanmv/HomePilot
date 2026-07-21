"""
Server-side per-user OllaBridge cloud token store (Batch 7 — BFF session).

Moves the user's long-lived cloud credential OUT of the browser and into the
HomePilot Web backend, keyed to the HomePilot user. The Account Mirror BFF and
the cloud-relay chat path read it here instead of receiving it from the client.

Storage: a single additive table in the app DB. At-rest encryption is OPT-IN:
if ``cryptography`` is installed AND ``HOMEPILOT_CLOUD_TOKEN_KEY`` (a Fernet
key) is set, values are encrypted ("f:" prefix); otherwise they are stored
server-side as-is ("p:" prefix). Either way the token never lives in browser
storage — the primary security goal. Legacy/unprefixed values are read as
plaintext for forward-compat.

ADDITIVE: new module + new table. Nothing else changes. All writes are gated by
the caller (only invoked when HOMEPILOT_BFF_SESSION_ENABLED is on).
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Optional

from .storage import _get_db_path

_TABLE = "user_cloud_tokens"

# Tri-state cache: None = not resolved, False = unavailable, object = Fernet.
_fernet_cache: object = None


def _fernet():
    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache or None
    key = os.getenv("HOMEPILOT_CLOUD_TOKEN_KEY", "").strip()
    if not key:
        _fernet_cache = False
        return None
    try:
        from cryptography.fernet import Fernet
        _fernet_cache = Fernet(key.encode())
        return _fernet_cache
    except Exception:
        # Library missing or bad key — degrade to server-side plaintext.
        _fernet_cache = False
        return None


def _encode(token: str) -> str:
    f = _fernet()
    if f:
        try:
            return "f:" + f.encrypt(token.encode()).decode()
        except Exception:
            pass
    return "p:" + token


def _decode(stored: str) -> Optional[str]:
    if stored.startswith("f:"):
        f = _fernet()
        if not f:
            return None
        try:
            return f.decrypt(stored[2:].encode()).decode()
        except Exception:
            return None
    if stored.startswith("p:"):
        return stored[2:]
    return stored  # legacy unprefixed plaintext


def ensure_table() -> None:
    con = sqlite3.connect(_get_db_path())
    try:
        con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                user_id    TEXT PRIMARY KEY,
                token_enc  TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()


def set_cloud_token(user_id: str, token: str) -> None:
    """Persist (upsert) the user's cloud token, server-side only."""
    if not user_id or not token:
        return
    ensure_table()
    con = sqlite3.connect(_get_db_path())
    try:
        con.execute(
            f"INSERT INTO {_TABLE}(user_id, token_enc, updated_at) VALUES (?,?,?) "
            f"ON CONFLICT(user_id) DO UPDATE SET token_enc=excluded.token_enc, updated_at=excluded.updated_at",
            (str(user_id), _encode(token), time.time()),
        )
        con.commit()
    finally:
        con.close()


def get_cloud_token(user_id: str) -> Optional[str]:
    """Return the user's cloud token, or None. Never raises."""
    if not user_id:
        return None
    try:
        ensure_table()
        con = sqlite3.connect(_get_db_path())
        try:
            row = con.execute(
                f"SELECT token_enc FROM {_TABLE} WHERE user_id = ?", (str(user_id),)
            ).fetchone()
        finally:
            con.close()
    except Exception:
        return None
    if not row or not row[0]:
        return None
    return _decode(row[0])


def clear_cloud_token(user_id: str) -> None:
    if not user_id:
        return
    try:
        ensure_table()
        con = sqlite3.connect(_get_db_path())
        try:
            con.execute(f"DELETE FROM {_TABLE} WHERE user_id = ?", (str(user_id),))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass
