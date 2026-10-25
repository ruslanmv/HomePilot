"""Linked connector accounts, one row per user and connector, in HomePilot's SQLite database.

The secret (an access token) is written here and read only by the server; no route returns
it. It is not encrypted at rest — the database already holds the user's sessions — so the
database file is what to protect, as for everything else HomePilot stores.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional


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
    return con


def save(user_id: str, connector_id: str, secret: str, account: str = "", meta: Optional[Dict[str, Any]] = None) -> None:
    con = _db()
    con.execute(
        "INSERT OR REPLACE INTO user_connectors(user_id, connector_id, secret, account, meta, connected_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, connector_id, secret, account, json.dumps(meta or {}), time.time()),
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
        "SELECT secret FROM user_connectors WHERE user_id = ? AND connector_id = ?", (user_id, connector_id)
    ).fetchone()
    con.close()
    return row["secret"] if row else ""


def linked(user_id: str) -> List[Dict[str, Any]]:
    """What the browser may see about this user's connectors: never the secret."""
    con = _db()
    rows = con.execute(
        "SELECT connector_id, account, meta, connected_at FROM user_connectors WHERE user_id = ?", (user_id,)
    ).fetchall()
    con.close()
    out = []
    for r in rows:
        try:
            meta = json.loads(r["meta"] or "{}")
        except ValueError:
            meta = {}
        out.append({"id": r["connector_id"], "account": r["account"], "meta": meta, "connected_at": r["connected_at"]})
    return out
