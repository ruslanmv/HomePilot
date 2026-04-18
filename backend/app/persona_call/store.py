"""
SQLite persistence for persona_call.

Two tables, both additive and empty when the feature flag is off:

  persona_call_state       per-session runtime state (phase, turn_index,
                           ledgers, caller_context).

  persona_call_directives  shadow-mode audit: every composed directive
                           is appended here so P1 (compose but don't
                           apply) produces a reviewable trail.

Follows the same pattern as backend/app/voice_call/store.py and the
rest of HomePilot: direct sqlite3, per-call connections, lazy
``ensure_schema`` with a process-scoped guard so it's cheap after
first use.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Dict, List, Optional


def _db_path() -> str:
    from ..storage import _get_db_path
    return _get_db_path()


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    con.row_factory = sqlite3.Row
    return con


_SCHEMA_READY = False


def ensure_schema() -> None:
    """Create persona_call tables if missing. Safe to call any number
    of times. No-op on subsequent calls within the same process."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    con = _conn()
    cur = con.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS persona_call_state (
            session_id              TEXT PRIMARY KEY,
            phase                   TEXT NOT NULL DEFAULT 'opening',
            turn_index              INTEGER NOT NULL DEFAULT 0,
            skipped_how_are_you     INTEGER NOT NULL DEFAULT 0,
            asked_reason_fallback   INTEGER NOT NULL DEFAULT 0,
            reason_for_call         TEXT NOT NULL DEFAULT '',
            last_backchannel_ms     INTEGER NOT NULL DEFAULT 0,
            recent_acks             TEXT NOT NULL DEFAULT '[]',
            recent_openers          TEXT NOT NULL DEFAULT '[]',
            recent_closings         TEXT NOT NULL DEFAULT '[]',
            caller_context          TEXT NOT NULL DEFAULT '{}',
            pre_closing_trigger     TEXT,
            created_at              INTEGER NOT NULL,
            updated_at              INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS persona_call_directives (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      TEXT NOT NULL,
            turn_index      INTEGER NOT NULL,
            phase           TEXT NOT NULL,
            applied         INTEGER NOT NULL DEFAULT 1,
            system_suffix   TEXT NOT NULL,
            post_directives TEXT NOT NULL DEFAULT '[]',
            created_at      INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_pcd_session
            ON persona_call_directives (session_id, turn_index);
        """
    )
    con.commit()
    con.close()
    _SCHEMA_READY = True


def _now_ms() -> int:
    return int(time.time() * 1000)


# ── persona_call_state CRUD ───────────────────────────────────────────

def get_state(session_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM persona_call_state WHERE session_id = ?",
        (session_id,),
    )
    row = cur.fetchone()
    con.close()
    if row is None:
        return None
    d = {k: row[k] for k in row.keys()}
    # Deserialize JSON columns.
    for col in ("recent_acks", "recent_openers", "recent_closings",
                "caller_context"):
        try:
            d[col] = json.loads(d.get(col) or "[]")
        except Exception:
            d[col] = [] if col != "caller_context" else {}
    return d


def ensure_state(session_id: str) -> Dict[str, Any]:
    """Upsert-shaped: returns the existing row, or creates a fresh one
    in the 'opening' phase if this is the first turn."""
    existing = get_state(session_id)
    if existing is not None:
        return existing
    now = _now_ms()
    con = _conn()
    cur = con.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO persona_call_state
            (session_id, created_at, updated_at)
        VALUES (?, ?, ?)
        """,
        (session_id, now, now),
    )
    con.commit()
    con.close()
    return get_state(session_id)  # type: ignore[return-value]


def update_state(session_id: str, **changes: Any) -> Dict[str, Any]:
    """Apply a partial update. JSON-typed columns accept Python lists /
    dicts; everything else is a scalar."""
    if not changes:
        return ensure_state(session_id)

    json_cols = {"recent_acks", "recent_openers", "recent_closings",
                 "caller_context"}
    sets, params = [], []
    for col, val in changes.items():
        if col in json_cols:
            val = json.dumps(val, separators=(",", ":"))
        if col in ("skipped_how_are_you", "asked_reason_fallback"):
            val = 1 if val else 0
        sets.append(f"{col} = ?")
        params.append(val)
    sets.append("updated_at = ?")
    params.append(_now_ms())
    params.append(session_id)

    ensure_state(session_id)
    con = _conn()
    cur = con.cursor()
    cur.execute(
        f"UPDATE persona_call_state SET {', '.join(sets)} WHERE session_id = ?",
        params,
    )
    con.commit()
    con.close()
    return get_state(session_id)  # type: ignore[return-value]


# ── persona_call_directives (shadow-mode audit) ───────────────────────

def record_directive(
    *,
    session_id: str,
    turn_index: int,
    phase: str,
    applied: bool,
    system_suffix: str,
    post_directives: List[str],
) -> None:
    ensure_schema()
    con = _conn()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO persona_call_directives
            (session_id, turn_index, phase, applied,
             system_suffix, post_directives, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            int(turn_index),
            phase,
            1 if applied else 0,
            system_suffix,
            json.dumps(post_directives, separators=(",", ":")),
            _now_ms(),
        ),
    )
    con.commit()
    con.close()


def last_directive(session_id: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    con = _conn()
    cur = con.cursor()
    cur.execute(
        """
        SELECT session_id, turn_index, phase, applied,
               system_suffix, post_directives, created_at
          FROM persona_call_directives
         WHERE session_id = ?
         ORDER BY id DESC
         LIMIT 1
        """,
        (session_id,),
    )
    row = cur.fetchone()
    con.close()
    if row is None:
        return None
    d = {k: row[k] for k in row.keys()}
    try:
        d["post_directives"] = json.loads(d.get("post_directives") or "[]")
    except Exception:
        d["post_directives"] = []
    d["applied"] = bool(d.get("applied"))
    return d


# ── test helper ───────────────────────────────────────────────────────

def _reset_for_tests() -> None:
    ensure_schema()
    con = _conn()
    cur = con.cursor()
    cur.execute("DELETE FROM persona_call_directives")
    cur.execute("DELETE FROM persona_call_state")
    con.commit()
    con.close()
