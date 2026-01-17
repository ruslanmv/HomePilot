from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .config import SQLITE_PATH

# Cache the resolved path so we don't check permissions on every query
_RESOLVED_DB_PATH = None

def _get_db_path() -> str:
    """
    Returns a writable database path.
    1. Tries the configured SQLITE_PATH (e.g. /app/data/db.sqlite).
    2. If that raises PermissionError (common in local dev vs Docker), 
       falls back to a local 'data' folder relative to this file.
    """
    global _RESOLVED_DB_PATH
    if _RESOLVED_DB_PATH:
        return _RESOLVED_DB_PATH

    candidate = SQLITE_PATH
    directory = os.path.dirname(candidate) or "."

    try:
        # Try creating the directory and writing a temp file to test permissions
        os.makedirs(directory, exist_ok=True)
        test_file = os.path.join(directory, f".perm_check_{os.getpid()}")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        
        # If successful, use the configured path
        _RESOLVED_DB_PATH = candidate
        return candidate
    except (OSError, PermissionError):
        # Fallback: Use 'data' directory inside the backend folder
        # This file is in .../backend/app/storage.py, so parents[1] is .../backend
        fallback_dir = Path(__file__).resolve().parents[1] / "data"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_path = str(fallback_dir / "db.sqlite")
        
        print(f"WARNING: Permission denied for '{SQLITE_PATH}'. Using local fallback: {fallback_path}")
        _RESOLVED_DB_PATH = fallback_path
        return fallback_path


def init_db():
    path = _get_db_path()
    # Directory creation is handled inside _get_db_path, so we can just connect
    con = sqlite3.connect(path)
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


def add_message(conversation_id: str, role: str, content: str):
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO messages(conversation_id, role, content) VALUES (?,?,?)",
        (conversation_id, role, content),
    )
    con.commit()
    con.close()


def get_recent(conversation_id: str, limit: int = 24):
    path = _get_db_path()
    con = sqlite3.connect(path)
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