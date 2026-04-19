"""
Runtime state snapshot for a session.

Pulls together current node + character state + progress metrics
in one immutable struct that the router / evaluator can reason
about without N additional SQLite reads.

``build_runtime_state(session_id)`` is the one read-heavy function
— it loads all the needed rows in one batch, then subsequent logic
is pure.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .. import store


@dataclass(frozen=True)
class RuntimeState:
    """Full runtime snapshot for one session."""

    session_id: str
    experience_id: str
    current_node_id: str
    language: str
    consent_version: str
    personalization: Dict[str, Any]
    character_mood: str
    affinity_score: float
    outfit_state: Dict[str, Any]
    recent_flags: List[str]
    progress: Dict[str, Dict[str, float]]   # scheme → {metric_key: value}
    uses_by_action: Dict[str, int]          # action_id → uses-so-far-this-session


def _load_progress(con: sqlite3.Connection, session_id: str) -> Dict[str, Dict[str, float]]:
    rows = con.execute(
        "SELECT scheme, metric_key, metric_value FROM ix_session_progress "
        "WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    out: Dict[str, Dict[str, float]] = {}
    for r in rows:
        out.setdefault(str(r[0]), {})[str(r[1])] = float(r[2])
    return out


def _load_uses_by_action(con: sqlite3.Connection, session_id: str) -> Dict[str, int]:
    rows = con.execute(
        "SELECT action_id, COUNT(*) FROM ix_session_events "
        "WHERE session_id = ? AND action_id != '' "
        "GROUP BY action_id",
        (session_id,),
    ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def build_runtime_state(session_id: str) -> Optional[RuntimeState]:
    """Single read pass that assembles a RuntimeState.

    Returns None if the session doesn't exist.
    """
    store.ensure_schema()
    with store._conn() as con:
        srow = con.execute(
            "SELECT * FROM ix_sessions WHERE id = ?", (session_id,),
        ).fetchone()
        if not srow:
            return None

        char_row = con.execute(
            "SELECT * FROM ix_character_state WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        progress = _load_progress(con, session_id)
        uses = _load_uses_by_action(con, session_id)

    # JSON fields
    def _jparse(val: Any, default: Any) -> Any:
        if val is None or val == "":
            return default
        if isinstance(val, (dict, list)):
            return val
        try:
            return json.loads(val)
        except (TypeError, ValueError):
            return default

    personalization = _jparse(srow["personalization"], {})
    if char_row:
        mood = str(char_row["mood"] or "neutral")
        affinity = float(char_row["affinity_score"] or 0.5)
        outfit = _jparse(char_row["outfit_state"], {})
        flags = _jparse(char_row["recent_flags"], [])
    else:
        mood = "neutral"
        affinity = 0.5
        outfit = {}
        flags = []

    return RuntimeState(
        session_id=str(srow["id"]),
        experience_id=str(srow["experience_id"]),
        current_node_id=str(srow["current_node_id"] or ""),
        language=str(srow["language"] or "en"),
        consent_version=str(srow["consent_version"] or ""),
        personalization=personalization,
        character_mood=mood,
        affinity_score=affinity,
        outfit_state=outfit,
        recent_flags=flags,
        progress=progress,
        uses_by_action=uses,
    )


# ─────────────────────────────────────────────────────────────────
# Mutators (used by router on hot path)
# ─────────────────────────────────────────────────────────────────

def upsert_character_state(
    session_id: str, persona_id: str,
    *,
    mood: Optional[str] = None,
    affinity_score: Optional[float] = None,
    outfit_state: Optional[Dict[str, Any]] = None,
    recent_flags: Optional[List[str]] = None,
    language: Optional[str] = None,
) -> None:
    """Insert/update the character-state row for a session."""
    store.ensure_schema()
    with store._conn() as con:
        existing = con.execute(
            "SELECT id FROM ix_character_state WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if existing:
            sets: List[str] = []
            params: List[Any] = []
            if mood is not None:
                sets.append("mood = ?")
                params.append(mood)
            if affinity_score is not None:
                sets.append("affinity_score = ?")
                params.append(float(affinity_score))
            if outfit_state is not None:
                sets.append("outfit_state = ?")
                params.append(store._dump_json(outfit_state))
            if recent_flags is not None:
                sets.append("recent_flags = ?")
                params.append(store._dump_json(recent_flags))
            if language is not None:
                sets.append("language = ?")
                params.append(language)
            if not sets:
                return
            sets.append("updated_at = ?")
            params.append(store.now_iso())
            params.append(session_id)
            con.execute(
                f"UPDATE ix_character_state SET {', '.join(sets)} WHERE session_id = ?",
                tuple(params),
            )
        else:
            con.execute(
                """
                INSERT INTO ix_character_state (
                    id, session_id, persona_id, mood, affinity_score,
                    outfit_state, recent_flags, language
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    store.new_id("ixc"),
                    session_id,
                    persona_id,
                    mood or "neutral",
                    float(affinity_score if affinity_score is not None else 0.5),
                    store._dump_json(outfit_state or {}),
                    store._dump_json(recent_flags or []),
                    language or "en",
                ),
            )
        con.commit()


def upsert_progress(
    session_id: str, scheme: str, metric_key: str, new_value: float,
) -> None:
    """Set a progression metric. Replaces the value (not additive)."""
    store.ensure_schema()
    with store._conn() as con:
        con.execute(
            """
            INSERT INTO ix_session_progress (id, session_id, scheme, metric_key, metric_value)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id, scheme, metric_key) DO UPDATE
            SET metric_value = excluded.metric_value,
                updated_at = CURRENT_TIMESTAMP
            """,
            (store.new_id("ixp"), session_id, scheme, metric_key, float(new_value)),
        )
        con.commit()
