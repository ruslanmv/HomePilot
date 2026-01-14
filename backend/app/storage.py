from __future__ import annotations

import os
import sqlite3

from .config import SQLITE_PATH


def init_db():
    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)

    con = sqlite3.connect(SQLITE_PATH)
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
    con = sqlite3.connect(SQLITE_PATH)
    cur = con.cursor()
    cur.execute(
        "INSERT INTO messages(conversation_id, role, content) VALUES (?,?,?)",
        (conversation_id, role, content),
    )
    con.commit()
    con.close()


def get_recent(conversation_id: str, limit: int = 24):
    con = sqlite3.connect(SQLITE_PATH)
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
