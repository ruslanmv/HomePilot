from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\+?[0-9][0-9\- ]{7,}[0-9]")


@dataclass
class MemoryRow:
    role: str
    content: str
    ts: int


class SqliteMemoryStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS expert_memory(
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    ts INTEGER NOT NULL
                )
                """
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_expert_memory_session_ts ON expert_memory(session_id, ts)")

    def append(self, session_id: str, role: str, content: str) -> None:
        safe = redact_pii(content)
        with self._conn() as c:
            c.execute(
                "INSERT INTO expert_memory(session_id, role, content, ts) VALUES (?, ?, ?, ?)",
                (session_id, role, safe, int(time.time())),
            )

    def recall(self, session_id: str, limit: int = 8) -> List[MemoryRow]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT role, content, ts FROM expert_memory WHERE session_id = ? ORDER BY ts DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [MemoryRow(role=r[0], content=r[1], ts=r[2]) for r in reversed(rows)]


def redact_pii(text: str) -> str:
    text = _EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = _PHONE_RE.sub("[REDACTED_PHONE]", text)
    return text
