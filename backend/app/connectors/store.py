"""Linked connector accounts, one row per user and connector, in HomePilot's SQLite database.

The secret (an access token) is written here and read only by the server; no route returns
it, and no log line includes it.

Encryption at rest
------------------
Secrets are stored encrypted (Fernet: AES-128-CBC + HMAC-SHA256) as ``enc:v1:<token>``.

Keys come from ``HOMEPILOT_CONNECTOR_SECRET_KEYS`` — a comma-separated list of Fernet keys.
The **first** key encrypts; every key in the list can decrypt. To rotate: put a new key
first, keep the old one after it, restart, then run
``python -m app.connectors.store rotate`` to re-encrypt every row with the new key; the old
key can then be removed.

Without that variable a key is generated once and kept in ``connector_secret.key`` beside
the database (mode 600). That protects secrets in database copies and backups that do not
include the key file, but not against someone who can read the whole data directory — set
the variable from a secret store in production. ``/compute/readiness`` reports which is in use.

Rows written by earlier versions (plaintext) are re-encrypted the first time the store
opens. A row that no key can decrypt is treated as not linked, so the user is asked to
connect again rather than being sent a broken credential.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("homepilot.connectors.store")

ENC_PREFIX = "enc:v1:"
KEYS_ENV = "HOMEPILOT_CONNECTOR_SECRET_KEYS"
_crypto_lock = threading.Lock()
_crypto_cache: Dict[str, Any] = {}
_migrated_dbs: set = set()


def _key_file() -> Path:
    from ..storage import _get_db_path
    return Path(_get_db_path()).with_name("connector_secret.key")


def key_source() -> str:
    """``env`` (keys supplied by the operator) or ``file`` (generated beside the database)."""
    return "env" if (os.getenv(KEYS_ENV) or "").strip() else "file"


def _keys() -> List[bytes]:
    raw = (os.getenv(KEYS_ENV) or "").strip()
    if raw:
        return [k.strip().encode() for k in raw.split(",") if k.strip()]
    path = _key_file()
    if not path.exists():
        from cryptography.fernet import Fernet
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(Fernet.generate_key())
    return [path.read_bytes().strip()]


def _cipher():
    """A MultiFernet over the configured keys (cached per key set)."""
    from cryptography.fernet import Fernet, MultiFernet
    keys = _keys()
    cache_key = "|".join(k.decode() for k in keys)
    with _crypto_lock:
        cipher = _crypto_cache.get(cache_key)
        if cipher is None:
            cipher = MultiFernet([Fernet(k) for k in keys])
            _crypto_cache.clear()
            _crypto_cache[cache_key] = cipher
    return cipher


def encrypt(plain: str) -> str:
    return ENC_PREFIX + _cipher().encrypt(plain.encode()).decode()


def decrypt(stored: str) -> Optional[str]:
    """The secret, or ``None`` when no configured key can open it."""
    if not stored.startswith(ENC_PREFIX):
        return stored                      # legacy plaintext (re-encrypted on open)
    from cryptography.fernet import InvalidToken
    try:
        return _cipher().decrypt(stored[len(ENC_PREFIX):].encode()).decode()
    except (InvalidToken, ValueError):
        return None


def _encrypt_legacy_rows(con: sqlite3.Connection) -> None:
    rows = con.execute(
        "SELECT user_id, connector_id, secret FROM user_connectors WHERE secret NOT LIKE ?",
        (ENC_PREFIX + "%",)).fetchall()
    for r in rows:
        con.execute("UPDATE user_connectors SET secret = ? WHERE user_id = ? AND connector_id = ?",
                    (encrypt(r["secret"]), r["user_id"], r["connector_id"]))
    if rows:
        con.commit()
        logger.info("Encrypted %d connector secret(s) stored by an earlier version", len(rows))


def rotate() -> int:
    """Re-encrypt every secret with the first configured key. Returns the count."""
    con = _db()
    try:
        rows = con.execute("SELECT user_id, connector_id, secret FROM user_connectors").fetchall()
        cipher, done = _cipher(), 0
        for r in rows:
            if not r["secret"].startswith(ENC_PREFIX):
                continue
            try:
                fresh = cipher.rotate(r["secret"][len(ENC_PREFIX):].encode()).decode()
            except Exception:
                logger.warning("A connector secret for connector %s could not be rotated "
                               "(no configured key opens it)", r["connector_id"])
                continue
            con.execute("UPDATE user_connectors SET secret = ? WHERE user_id = ? AND connector_id = ?",
                        (ENC_PREFIX + fresh, r["user_id"], r["connector_id"]))
            done += 1
        con.commit()
        return done
    finally:
        con.close()


def _db() -> sqlite3.Connection:
    from ..storage import _get_db_path

    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS user_connectors(
            user_id TEXT NOT NULL,
            connector_id TEXT NOT NULL,
            secret TEXT NOT NULL,
            account TEXT DEFAULT '',
            meta TEXT DEFAULT '{}',
            connected_at REAL NOT NULL,
            PRIMARY KEY(user_id, connector_id)
        )
        """
    )
    from ..storage import _get_db_path
    path = _get_db_path()
    if path not in _migrated_dbs:
        _encrypt_legacy_rows(con)
        _migrated_dbs.add(path)
    return con


def save(user_id: str, connector_id: str, secret: str, account: str = "", meta: Optional[Dict[str, Any]] = None) -> None:
    con = _db()
    con.execute(
        "INSERT OR REPLACE INTO user_connectors(user_id, connector_id, secret, account, meta, connected_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, connector_id, encrypt(secret), account, json.dumps(meta or {}), time.time()),
    )
    con.commit()
    con.close()


def remove(user_id: str, connector_id: str) -> None:
    con = _db()
    con.execute("DELETE FROM user_connectors WHERE user_id = ? AND connector_id = ?", (user_id, connector_id))
    con.commit()
    con.close()


def secret(user_id: str, connector_id: str) -> str:
    if not user_id:
        return ""
    con = _db()
    row = con.execute(
        "SELECT secret, meta FROM user_connectors WHERE user_id = ? AND connector_id = ?", (user_id, connector_id)
    ).fetchone()
    con.close()
    if not row or _expired(_meta(row["meta"])):
        return ""
    return decrypt(row["secret"]) or ""


def _meta(raw: Optional[str]) -> Dict[str, Any]:
    try:
        meta = json.loads(raw or "{}")
    except ValueError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _expired(meta: Dict[str, Any]) -> bool:
    """A token from "Sign in with …" carries its expiry; a pasted token has none."""
    exp = meta.get("expires_at")
    return bool(exp) and float(exp) <= time.time()


def linked(user_id: str) -> List[Dict[str, Any]]:
    """What the browser may see about this user's connectors: never the secret."""
    con = _db()
    rows = con.execute(
        "SELECT connector_id, account, meta, connected_at FROM user_connectors WHERE user_id = ?", (user_id,)
    ).fetchall()
    con.close()
    out = []
    for r in rows:
        meta = _meta(r["meta"])
        out.append({"id": r["connector_id"], "account": r["account"], "meta": meta,
                    "connected_at": r["connected_at"], "expired": _expired(meta)})
    return out


if __name__ == "__main__":  # python -m app.connectors.store rotate
    import sys
    if sys.argv[1:] == ["rotate"]:
        print(f"re-encrypted {rotate()} connector secret(s)")
    else:
        print("usage: python -m app.connectors.store rotate")
