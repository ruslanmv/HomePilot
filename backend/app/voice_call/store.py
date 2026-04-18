"""
SQLite access for voice_call.

Follows the same pattern as backend/app/storage.py and users.py:
direct sqlite3 calls, no ORM, per-call connections. Tables are created
lazily by :func:`ensure_schema` — no separate migration file, no side
effects on import. If the feature is disabled, this module is never
loaded and no tables are created.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from typing import Any, Dict, List, Optional


# Re-use the same DB path the rest of HomePilot uses.
def _db_path() -> str:
    from ..storage import _get_db_path  # lazy import, avoids cycles
    return _get_db_path()


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    return con


_SCHEMA_READY = False


def ensure_schema() -> None:
    """Create voice_call tables if they don't exist. Safe to call repeatedly."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    con = _conn()
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS voice_call_sessions (
            id              TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL,
            conversation_id TEXT,
            persona_id      TEXT,
            entry_mode      TEXT NOT NULL,
            status          TEXT NOT NULL,
            resume_token    TEXT NOT NULL,
            started_at      INTEGER NOT NULL,
            ended_at        INTEGER,
            ended_reason    TEXT,
            client_platform TEXT,
            app_version     TEXT,
            created_at      INTEGER NOT NULL,
            updated_at      INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_vcs_user_started
            ON voice_call_sessions (user_id, started_at DESC);
        CREATE INDEX IF NOT EXISTS ix_vcs_user_status
            ON voice_call_sessions (user_id, status);

        CREATE TABLE IF NOT EXISTS voice_call_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            seq         INTEGER NOT NULL,
            event_type  TEXT NOT NULL,
            event_ts    INTEGER NOT NULL,
            payload     TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS ix_vce_session_seq
            ON voice_call_events (session_id, seq);
        """
    )
    con.commit()
    con.close()
    _SCHEMA_READY = True


# ── session CRUD ──────────────────────────────────────────────────────

def new_session_id() -> str:
    return "vcs_" + secrets.token_urlsafe(16)


def new_resume_token() -> str:
    return secrets.token_urlsafe(24)


def _now_ms() -> int:
    return int(time.time() * 1000)


def create_session(
    *,
    user_id: str,
    conversation_id: Optional[str],
    persona_id: Optional[str],
    entry_mode: str,
    client_platform: Optional[str],
    app_version: Optional[str],
) -> Dict[str, Any]:
    """Insert a session row in the ``connecting`` state and return it."""
    ensure_schema()
    sid = new_session_id()
    token = new_resume_token()
    now = _now_ms()
    con = _conn()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO voice_call_sessions
            (id, user_id, conversation_id, persona_id, entry_mode, status,
             resume_token, started_at, ended_at, ended_reason,
             client_platform, app_version, created_at, updated_at)
        VALUES
            (?, ?, ?, ?, ?, 'connecting', ?, ?, NULL, NULL, ?, ?, ?, ?)
        """,
        (sid, user_id, conversation_id, persona_id, entry_mode, token,
         now, client_platform, app_version, now, now),
    )
    con.commit()
    con.close()
    return _select_session(sid)  # type: ignore[return-value]


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    d = {k: row[k] for k in row.keys()}
    return d


def _select_session(sid: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    con = _conn()
    cur = con.cursor()
    cur.execute("SELECT * FROM voice_call_sessions WHERE id = ?", (sid,))
    row = cur.fetchone()
    con.close()
    return _row_to_dict(row) if row else None


def get_session_for_owner(sid: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a session ONLY if it belongs to ``user_id``.

    Returns ``None`` for both "not found" and "wrong owner" so callers
    cannot probe session ids they don't own. Matches the pattern used
    by studio render jobs.
    """
    row = _select_session(sid)
    if row and row["user_id"] == user_id:
        return row
    return None


def count_active_sessions_for_user(user_id: str) -> int:
    """Count sessions that are still 'live' or 'connecting' or 'interrupted'."""
    ensure_schema()
    con = _conn()
    cur = con.cursor()
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM voice_call_sessions
         WHERE user_id = ?
           AND status IN ('connecting', 'live', 'interrupted')
        """,
        (user_id,),
    )
    n = int(cur.fetchone()["n"])
    con.close()
    return n


def recent_session_creates_for_user(user_id: str, window_sec: int) -> int:
    """Session creates by ``user_id`` in the last ``window_sec`` seconds."""
    ensure_schema()
    con = _conn()
    cur = con.cursor()
    since = _now_ms() - int(window_sec * 1000)
    cur.execute(
        """
        SELECT COUNT(*) AS n FROM voice_call_sessions
         WHERE user_id = ? AND created_at >= ?
        """,
        (user_id, since),
    )
    n = int(cur.fetchone()["n"])
    con.close()
    return n


def update_session_status(
    sid: str,
    status: str,
    *,
    ended_reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    ensure_schema()
    now = _now_ms()
    con = _conn()
    cur = con.cursor()
    if status == "ended":
        cur.execute(
            """
            UPDATE voice_call_sessions
               SET status = 'ended', ended_at = ?, ended_reason = ?, updated_at = ?
             WHERE id = ?
            """,
            (now, ended_reason or "user_ended", now, sid),
        )
    else:
        cur.execute(
            """
            UPDATE voice_call_sessions
               SET status = ?, updated_at = ?
             WHERE id = ?
            """,
            (status, now, sid),
        )
    con.commit()
    con.close()
    return _select_session(sid)


# ── events ────────────────────────────────────────────────────────────

def append_event(
    *,
    session_id: str,
    seq: int,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """Append a structured event row. Payload defaults to {} — DO NOT
    pass raw audio or full user text here unless privacy flag allows it."""
    ensure_schema()
    con = _conn()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO voice_call_events (session_id, seq, event_type, event_ts, payload)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            session_id,
            int(seq),
            event_type,
            _now_ms(),
            json.dumps(payload or {}, separators=(",", ":")),
        ),
    )
    con.commit()
    con.close()


def list_events(session_id: str, limit: int = 500) -> List[Dict[str, Any]]:
    ensure_schema()
    con = _conn()
    cur = con.cursor()
    cur.execute(
        """
        SELECT session_id, seq, event_type, event_ts, payload
          FROM voice_call_events
         WHERE session_id = ?
         ORDER BY seq ASC
         LIMIT ?
        """,
        (session_id, int(limit)),
    )
    rows = cur.fetchall()
    con.close()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        try:
            d["payload"] = json.loads(d.get("payload") or "{}")
        except Exception:
            d["payload"] = {}
        out.append(d)
    return out


# ── test helper ───────────────────────────────────────────────────────

def _reset_for_tests() -> None:
    """DELETE every voice_call row. Only used by pytest fixtures."""
    ensure_schema()
    con = _conn()
    cur = con.cursor()
    cur.execute("DELETE FROM voice_call_events")
    cur.execute("DELETE FROM voice_call_sessions")
    con.commit()
    con.close()
