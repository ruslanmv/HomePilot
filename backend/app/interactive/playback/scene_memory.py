"""
Scene memory — rolling context for the real-time scene planner.

PLAY-1/8. Pure, synchronous snapshot builder — no LLM calls here.
PLAY-2's scene planner will read from this module on every turn
and call ``set_synopsis`` when it decides the rolling one-liner
needs a refresh.

Persistence model:
  - Character state (mood / affinity / outfit) comes from
    ``ix_character_state``.
  - Transcript turns come from ``ix_session_turns``.
  - The rolling synopsis lives in a module-level cache keyed by
    session id — the same in-process pattern used by
    ``interaction/cooldown.py``. Short live-play sessions don't
    need DB-backed continuity; if that changes, promoting this
    dict to an additive DB column is a single-patch swap that
    keeps the public API stable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .. import repo, store


_DEFAULT_RECENT_N = 6
_DEFAULT_REFRESH_EVERY = 6


@dataclass(frozen=True)
class TurnSnapshot:
    """One row from ``ix_session_turns``, prompt-friendly."""

    role: str  # 'viewer' | 'character' | 'system'
    text: str
    action_id: str = ""
    node_id: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class SceneMemory:
    """Everything the scene planner needs, in one bundle.

    Frozen so the planner can't accidentally mutate the snapshot
    between turns.
    """

    session_id: str
    experience_id: str
    persona_id: str
    current_node_id: str
    mood: str
    affinity_score: float
    outfit_state: Dict[str, Any]
    recent_turns: List[TurnSnapshot]
    total_turns: int
    synopsis: str
    turns_since_synopsis: int


# ``(synopsis_text, total_turns_at_time_of_set)``
_SYNOPSIS_CACHE: Dict[str, Tuple[str, int]] = {}


def build_scene_memory(
    session_id: str, *, recent_n: int = _DEFAULT_RECENT_N,
) -> Optional[SceneMemory]:
    """Assemble a snapshot or return ``None`` if the session is gone."""
    sess = repo.get_session(session_id)
    if not sess:
        return None

    cs = _fetch_character_state(session_id)
    turns = _fetch_recent_turns(session_id, recent_n)
    total = _count_turns(session_id)

    synopsis_text, at_count = _SYNOPSIS_CACHE.get(session_id, ("", 0))
    turns_since = max(0, total - at_count)

    mood = str((cs.get("mood") if cs else None) or "neutral")
    affinity = float((cs.get("affinity_score") if cs else None) or 0.5)
    outfit = dict((cs.get("outfit_state") if cs else None) or {})
    persona = str((cs.get("persona_id") if cs else None) or "")

    return SceneMemory(
        session_id=session_id,
        experience_id=sess.experience_id,
        persona_id=persona,
        current_node_id=sess.current_node_id or "",
        mood=mood,
        affinity_score=affinity,
        outfit_state=outfit,
        recent_turns=turns,
        total_turns=total,
        synopsis=synopsis_text,
        turns_since_synopsis=turns_since,
    )


def set_synopsis(session_id: str, synopsis: str, at_turn_count: int) -> None:
    """Store a freshly-generated synopsis for this session."""
    _SYNOPSIS_CACHE[session_id] = (synopsis, int(at_turn_count))


def should_refresh_synopsis(
    memory: SceneMemory, *, every: int = _DEFAULT_REFRESH_EVERY,
) -> bool:
    """Tell the caller whether enough new turns have accumulated.

    Bootstrap: the very first refresh fires at half the cadence so
    the planner gets an early anchor instead of a completely
    context-less first few scenes.
    """
    if every <= 0:
        return False
    if not memory.synopsis:
        return memory.total_turns >= max(1, every // 2)
    return memory.turns_since_synopsis >= every


def reset_session(session_id: str) -> None:
    """Drop the synopsis cache entry for a session (useful in tests)."""
    _SYNOPSIS_CACHE.pop(session_id, None)


# ── Internals ───────────────────────────────────────────────────

def _fetch_character_state(session_id: str) -> Optional[Dict[str, Any]]:
    store.ensure_schema()
    with store._conn() as con:
        row = con.execute(
            "SELECT * FROM ix_character_state WHERE session_id = ?", (session_id,),
        ).fetchone()
    if not row:
        return None
    return store.row_to_dict(row, json_fields=("outfit_state", "recent_flags"))


def _fetch_recent_turns(session_id: str, n: int) -> List[TurnSnapshot]:
    store.ensure_schema()
    with store._conn() as con:
        rows = con.execute(
            "SELECT turn_role, text, action_id, node_id, created_at "
            "FROM ix_session_turns WHERE session_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (session_id, max(1, min(n, 50))),
        ).fetchall()
    out: List[TurnSnapshot] = []
    for r in rows:
        d = dict(r)
        out.append(TurnSnapshot(
            role=str(d.get("turn_role") or ""),
            text=str(d.get("text") or ""),
            action_id=str(d.get("action_id") or ""),
            node_id=str(d.get("node_id") or ""),
            created_at=str(d.get("created_at") or ""),
        ))
    out.reverse()  # chronological for prompt building
    return out


def _count_turns(session_id: str) -> int:
    store.ensure_schema()
    with store._conn() as con:
        row = con.execute(
            "SELECT COUNT(*) AS c FROM ix_session_turns WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return int(row["c"] if row else 0)
