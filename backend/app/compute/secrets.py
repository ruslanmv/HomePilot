"""
Compute credential store (PR 2).

Sources that talk to a remote endpoint (an OpenAI-compatible API, a hosted
provider) need a credential. We never keep that in the frontend or in the
``ComputeSource`` row — the source stores only a ``credential_ref`` (an opaque
key), and the actual secret lives here, server-side.

Encryption is opt-in and mirrors ``app.cloud_tokens``: if ``cryptography`` is
installed and ``HOMEPILOT_COMPUTE_SECRET_KEY`` (a Fernet key) is set, values are
encrypted at rest ("f:"); otherwise they are stored server-side as-is ("p:").
Either way the secret is out of the browser — the primary goal.
"""

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from typing import Optional

from ..storage import _get_db_path

_TABLE = "compute_secrets"
_fernet_cache: object = None


def _fernet():
    global _fernet_cache
    if _fernet_cache is not None:
        return _fernet_cache or None
    key = os.getenv("HOMEPILOT_COMPUTE_SECRET_KEY", "").strip()
    if not key:
        _fernet_cache = False
        return None
    try:
        from cryptography.fernet import Fernet
        _fernet_cache = Fernet(key.encode())
        return _fernet_cache
    except Exception:
        _fernet_cache = False
        return None


def _encode(secret: str) -> str:
    f = _fernet()
    if f:
        try:
            return "f:" + f.encrypt(secret.encode()).decode()
        except Exception:
            pass
    return "p:" + secret


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
    return stored  # legacy plaintext


def ensure_table() -> None:
    con = sqlite3.connect(_get_db_path())
    try:
        con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                ref        TEXT PRIMARY KEY,
                secret_enc TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        con.commit()
    finally:
        con.close()


def put_secret(secret: str, *, ref: Optional[str] = None) -> str:
    """Store (upsert) a secret and return its ref. Generates a ref if omitted."""
    ref = ref or f"cred_{uuid.uuid4().hex[:16]}"
    if not secret:
        return ref
    ensure_table()
    con = sqlite3.connect(_get_db_path())
    try:
        con.execute(
            f"INSERT INTO {_TABLE}(ref, secret_enc, updated_at) VALUES (?,?,?) "
            f"ON CONFLICT(ref) DO UPDATE SET secret_enc=excluded.secret_enc, "
            f"updated_at=excluded.updated_at",
            (ref, _encode(secret), time.time()),
        )
        con.commit()
    finally:
        con.close()
    return ref


def get_secret(ref: Optional[str]) -> Optional[str]:
    """Return the secret for ``ref`` (decrypted), or None. Never raises."""
    if not ref:
        return None
    try:
        ensure_table()
        con = sqlite3.connect(_get_db_path())
        try:
            row = con.execute(
                f"SELECT secret_enc FROM {_TABLE} WHERE ref = ?", (ref,)
            ).fetchone()
        finally:
            con.close()
    except Exception:
        return None
    if not row or not row[0]:
        return None
    return _decode(row[0])


def delete_secret(ref: Optional[str]) -> None:
    if not ref:
        return
    try:
        ensure_table()
        con = sqlite3.connect(_get_db_path())
        try:
            con.execute(f"DELETE FROM {_TABLE} WHERE ref = ?", (ref,))
            con.commit()
        finally:
            con.close()
    except Exception:
        pass
