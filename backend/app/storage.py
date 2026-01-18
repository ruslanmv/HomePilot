from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Tuple

from .config import SQLITE_PATH

_RESOLVED_DB_PATH = None

def _get_db_path() -> str:
    global _RESOLVED_DB_PATH
    if _RESOLVED_DB_PATH:
        return _RESOLVED_DB_PATH

    candidate = SQLITE_PATH
    directory = os.path.dirname(candidate) or "."

    try:
        os.makedirs(directory, exist_ok=True)
        test_file = os.path.join(directory, f".perm_check_{os.getpid()}")
        with open(test_file, "w") as f:
            f.write("ok")
        os.remove(test_file)
        _RESOLVED_DB_PATH = candidate
        return candidate
    except (OSError, PermissionError):
        fallback_dir = Path(__file__).resolve().parents[1] / "data"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_path = str(fallback_dir / "db.sqlite")
        print(f"WARNING: Permission denied for '{SQLITE_PATH}'. Using local fallback: {fallback_path}")
        _RESOLVED_DB_PATH = fallback_path
        return fallback_path


def init_db():
    path = _get_db_path()
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


def get_recent(conversation_id: str, limit: int = 24) -> List[Tuple[str, str]]:
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


def list_conversations(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Returns most recent conversations, with last message preview.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        SELECT m.conversation_id,
               MAX(m.id) as max_id
        FROM messages m
        GROUP BY m.conversation_id
        ORDER BY max_id DESC
        LIMIT ?
        """,
        (limit,),
    )
    convs = cur.fetchall()

    out: List[Dict[str, Any]] = []
    for conversation_id, max_id in convs:
        cur.execute(
            "SELECT role, content, created_at FROM messages WHERE id=?",
            (max_id,),
        )
        row = cur.fetchone()
        if row:
            role, content, created_at = row
            out.append(
                {
                    "conversation_id": conversation_id,
                    "last_role": role,
                    "last_content": content,
                    "updated_at": created_at,
                }
            )
    con.close()
    return out


def get_messages(conversation_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        SELECT role, content, created_at
        FROM messages
        WHERE conversation_id=?
        ORDER BY id ASC
        LIMIT ?
        """,
        (conversation_id, limit),
    )
    rows = cur.fetchall()
    con.close()
    return [{"role": r, "content": c, "created_at": t} for (r, c, t) in rows]
