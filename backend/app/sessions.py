"""
Persona Session Management — Companion-Grade

Manages sessions (conversation threads) within persona projects.
Each persona project can have multiple sessions (voice or text).
Sessions share the same Long-Term Memory (LTM) — the persona's "soul".

Key concepts:
  - One persona project → many sessions → one shared LTM
  - Each session = one conversation_id in the messages table
  - Sessions track mode (voice/text), timestamps, message counts, summaries
  - Resume algorithm is deterministic and crash-safe

Golden rule: ADDITIVE ONLY — never breaks existing conversation/project flows.
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from .config import SQLITE_PATH


def _get_db_path() -> str:
    """Reuse the same DB path resolution as storage.py."""
    from .storage import _get_db_path as _storage_db_path
    return _storage_db_path()


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def create_session(
    project_id: str,
    mode: str = "text",
    title: Optional[str] = None,
    conversation_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new session for a persona project.

    Returns the created session dict.
    """
    session_id = str(uuid.uuid4())
    cid = conversation_id or str(uuid.uuid4())
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO persona_sessions(id, project_id, conversation_id, mode, title, started_at, message_count)
        VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (session_id, project_id, cid, mode, title, now),
    )
    con.commit()
    con.close()

    # Update project metadata with active session pointer
    _set_active_session(project_id, session_id)

    return {
        "id": session_id,
        "project_id": project_id,
        "conversation_id": cid,
        "mode": mode,
        "title": title,
        "started_at": now,
        "ended_at": None,
        "message_count": 0,
        "summary": None,
    }


def end_session(session_id: str) -> bool:
    """
    End a session (set ended_at). Returns True if session was found and ended.
    Does NOT delete anything — session remains browseable.
    """
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "UPDATE persona_sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
        (now, session_id),
    )
    changed = cur.rowcount > 0
    con.commit()

    # Get project_id to clear active pointer
    if changed:
        cur.execute("SELECT project_id FROM persona_sessions WHERE id = ?", (session_id,))
        row = cur.fetchone()
        if row:
            _clear_active_session_if_matches(row[0], session_id)

    con.close()
    return changed


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get a single session by ID."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("SELECT * FROM persona_sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    con.close()
    if not row:
        return None
    session = dict(row)
    _enrich_message_counts([session])
    return session


def get_session_by_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """Get session by its conversation_id."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM persona_sessions WHERE conversation_id = ?",
        (conversation_id,),
    )
    row = cur.fetchone()
    con.close()
    if not row:
        return None
    session = dict(row)
    # Skip enrichment here to avoid extra DB hit on every chat message.
    # The orchestrator calls this on every turn — keep it lightweight.
    return session


def list_sessions(
    project_id: str, limit: int = 50, include_ended: bool = True
) -> List[Dict[str, Any]]:
    """
    List sessions for a persona project, most recent first.
    """
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    if include_ended:
        cur.execute(
            """
            SELECT * FROM persona_sessions
            WHERE project_id = ?
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (project_id, limit),
        )
    else:
        cur.execute(
            """
            SELECT * FROM persona_sessions
            WHERE project_id = ? AND ended_at IS NULL
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (project_id, limit),
        )

    rows = cur.fetchall()
    con.close()
    sessions = [dict(r) for r in rows]
    return _enrich_message_counts(sessions)


def update_session_message_count(session_id: str, delta: int = 1) -> None:
    """Increment message count for a session."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "UPDATE persona_sessions SET message_count = message_count + ? WHERE id = ?",
        (delta, session_id),
    )
    con.commit()
    con.close()


def _enrich_message_counts(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Replace the stored message_count with the actual count from the messages table.
    This is more reliable than relying solely on the increment counter.
    """
    if not sessions:
        return sessions
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    for s in sessions:
        cid = s.get("conversation_id")
        if cid:
            cur.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (cid,),
            )
            row = cur.fetchone()
            real_count = row[0] if row else 0
            stored_count = s.get("message_count") or 0
            s["message_count"] = real_count
            # Sync DB if stored count diverged from actual
            if real_count != stored_count:
                cur.execute(
                    "UPDATE persona_sessions SET message_count = ? WHERE id = ?",
                    (real_count, s["id"]),
                )
    con.commit()
    con.close()
    return sessions


def update_session_summary(session_id: str, summary: str) -> None:
    """Store an LLM-generated session summary."""
    path = _get_db_path()
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.execute(
        "UPDATE persona_sessions SET summary = ? WHERE id = ?",
        (summary, session_id),
    )
    con.commit()
    con.close()


# ---------------------------------------------------------------------------
# Resume Algorithm (bulletproof, crash-safe)
# ---------------------------------------------------------------------------

def resolve_session(project_id: str) -> Optional[Dict[str, Any]]:
    """
    Deterministic resume algorithm:

    1. If project has active_session_id AND that session exists + not ended → resume it
    2. Else find most recent session with ended_at IS NULL → resume it
    3. Else find most recent session by started_at → resume it
    4. Else → return None (caller should create a new session)

    This is the ONLY entry point for "which session should I use?"
    """
    # Step 1: Check project's active_session_id pointer
    active_sid = _get_active_session_id(project_id)
    if active_sid:
        session = get_session(active_sid)
        if session and session.get("ended_at") is None:
            return session

    # Step 2: Most recent open session
    path = _get_db_path()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    cur.execute(
        """
        SELECT * FROM persona_sessions
        WHERE project_id = ? AND ended_at IS NULL
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (project_id,),
    )
    row = cur.fetchone()
    if row:
        session = dict(row)
        con.close()
        # Fix the pointer
        _set_active_session(project_id, session["id"])
        _enrich_message_counts([session])
        return session

    # Step 3: Most recent ended session (allow resume of closed sessions)
    cur.execute(
        """
        SELECT * FROM persona_sessions
        WHERE project_id = ?
        ORDER BY started_at DESC
        LIMIT 1
        """,
        (project_id,),
    )
    row = cur.fetchone()
    con.close()
    if row:
        session = dict(row)
        _enrich_message_counts([session])
        return session

    # Step 4: No sessions exist yet
    return None


def get_or_create_session(
    project_id: str, mode: str = "text"
) -> Dict[str, Any]:
    """
    Convenience: resolve existing session or create a new one.
    This is the main entry point used by the orchestrator.
    """
    session = resolve_session(project_id)
    if session:
        return session
    return create_session(project_id, mode=mode)


# ---------------------------------------------------------------------------
# Project metadata helpers (active_session_id pointer)
# ---------------------------------------------------------------------------

def _set_active_session(project_id: str, session_id: str) -> None:
    """Set the active_session_id pointer on the project metadata."""
    try:
        from .projects import _load_projects_db, _save_projects_db
        db = _load_projects_db()
        project = db.get(project_id)
        if project:
            project["active_session_id"] = session_id
            db[project_id] = project
            _save_projects_db(db)
    except Exception as e:
        print(f"[SESSIONS] Warning: Could not set active_session_id: {e}")


def _get_active_session_id(project_id: str) -> Optional[str]:
    """Get the active_session_id from project metadata."""
    try:
        from .projects import get_project_by_id
        project = get_project_by_id(project_id)
        if project:
            return project.get("active_session_id")
    except Exception:
        pass
    return None


def _clear_active_session_if_matches(project_id: str, session_id: str) -> None:
    """Clear active_session_id if it matches the given session_id."""
    try:
        from .projects import _load_projects_db, _save_projects_db
        db = _load_projects_db()
        project = db.get(project_id)
        if project and project.get("active_session_id") == session_id:
            project["active_session_id"] = None
            db[project_id] = project
            _save_projects_db(db)
    except Exception as e:
        print(f"[SESSIONS] Warning: Could not clear active_session_id: {e}")
