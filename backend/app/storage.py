from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .config import SQLITE_PATH as CONFIG_SQLITE_PATH

# Cache resolved path so we don't recompute every request
_RESOLVED_SQLITE_PATH: str | None = None


def _resolve_sqlite_path() -> str:
    """
    Resolve a writable SQLITE_PATH for both:
      - Docker (/app/data/homegrok.db)
      - Local dev (./data/homepilot.db)

    If CONFIG_SQLITE_PATH is not writable, fall back to ./data/homepilot.db.
    """
    global _RESOLVED_SQLITE_PATH
    if _RESOLVED_SQLITE_PATH:
        return _RESOLVED_SQLITE_PATH

    configured = Path(CONFIG_SQLITE_PATH)

    # If it's just a filename without a directory, make it relative to cwd
    if configured.parent == Path("."):
        configured = Path.cwd() / configured

    # Try configured path first
    try:
        configured.parent.mkdir(parents=True, exist_ok=True)

        # Write test to ensure directory is writable
        test_file = configured.parent / ".write_test"
        test_file.write_text("ok")
        test_file.unlink(missing_ok=True)

        _RESOLVED_SQLITE_PATH = str(configured)
        return _RESOLVED_SQLITE_PATH
    except Exception:
        # Fall back to local project-relative data dir
        fallback_dir = Path.cwd() / "data"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback = fallback_dir / "homepilot.db"
        _RESOLVED_SQLITE_PATH = str(fallback)
        return _RESOLVED_SQLITE_PATH


def _connect() -> sqlite3.Connection:
    path = _resolve_sqlite_path()
    return sqlite3.connect(path)


def init_db() -> None:
    """
    Initialize database schema.
    """
    # Ensure directory exists for resolved path
    path = _resolve_sqlite_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    con = _connect()
    cur = con.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT,
            role TEXT,
            content TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    con.commit()
    con.close()


def add_message(conversation_id: str, role: str, content: str) -> None:
    con = _connect()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO messages(conversation_id, role, content) VALUES (?,?,?)",
        (conversation_id, role, content),
    )
    con.commit()
    con.close()


def get_recent(conversation_id: str, limit: int = 24):
    con = _connect()
    cur = con.cursor()
    cur.execute(
        """
        SELECT role, content FROM messages
        WHERE conversation_id=?
        ORDER BY id DESC
        LIMIT ?
        """,
        (conversation_id, limit),
    )
    rows = cur.fetchall()
    con.close()
    return list(reversed(rows))
