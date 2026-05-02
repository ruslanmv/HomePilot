"""
Aggregate session events into compact analytics summaries.

Two scopes:

  session_summary     one session — turn count, per-action
                      use counts, final node, mood/affinity end
                      state, per-scheme progress.
  experience_summary  all sessions of one experience —
                      completion rate, total turns, popular
                      actions, action block rate.

No percentile / histogram work here — that belongs in the studio
dashboard if / when it needs it. These summaries are the minimum
viable signal for the ship-readiness review.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .. import store


@dataclass(frozen=True)
class SessionSummary:
    """Per-session analytic snapshot."""

    session_id: str
    experience_id: str
    turns: int
    events: int
    action_uses: Dict[str, int]
    decisions: Dict[str, int]  # 'allow' | 'block' → count
    intents: Dict[str, int]
    final_node_id: str
    final_mood: str
    final_affinity: float
    progress: Dict[str, Dict[str, float]]
    completed: bool


@dataclass(frozen=True)
class ExperienceSummary:
    """Aggregate across every session of one experience."""

    experience_id: str
    session_count: int
    completed_sessions: int
    completion_rate: float
    total_turns: int
    total_events: int
    popular_actions: List[Dict[str, Any]]  # [{'action_id': ..., 'uses': int}, ...]
    block_rate: float  # fraction of turns blocked by policy


def _parse_payload(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def session_summary(session_id: str) -> Optional[SessionSummary]:
    """Compute the summary for one session. Returns None if missing."""
    store.ensure_schema()
    with store._conn() as con:
        sess = con.execute(
            "SELECT * FROM ix_sessions WHERE id = ?", (session_id,),
        ).fetchone()
        if not sess:
            return None
        turns = con.execute(
            "SELECT COUNT(*) FROM ix_session_turns WHERE session_id = ?", (session_id,),
        ).fetchone()[0]
        events = con.execute(
            "SELECT event_kind, payload, action_id FROM ix_session_events WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        cs = con.execute(
            "SELECT * FROM ix_character_state WHERE session_id = ?", (session_id,),
        ).fetchone()
        progress_rows = con.execute(
            "SELECT scheme, metric_key, metric_value FROM ix_session_progress "
            "WHERE session_id = ?",
            (session_id,),
        ).fetchall()

    action_uses: Counter = Counter()
    decisions: Counter = Counter()
    intents: Counter = Counter()
    for ev in events:
        if ev["event_kind"] != "turn_resolved":
            continue
        if ev["action_id"]:
            action_uses[ev["action_id"]] += 1
        payload = _parse_payload(ev["payload"])
        if "decision" in payload:
            decisions[str(payload["decision"])] += 1
        if "intent_code" in payload and payload["intent_code"]:
            intents[str(payload["intent_code"])] += 1

    progress: Dict[str, Dict[str, float]] = {}
    for row in progress_rows:
        progress.setdefault(row["scheme"], {})[row["metric_key"]] = float(row["metric_value"])

    mood = cs["mood"] if cs else "neutral"
    aff = float(cs["affinity_score"]) if cs else 0.5

    return SessionSummary(
        session_id=session_id,
        experience_id=str(sess["experience_id"]),
        turns=int(turns),
        events=len(events),
        action_uses=dict(action_uses),
        decisions=dict(decisions),
        intents=dict(intents),
        final_node_id=str(sess["current_node_id"] or ""),
        final_mood=str(mood),
        final_affinity=aff,
        progress=progress,
        completed=sess["completed_at"] is not None,
    )


def experience_summary(experience_id: str) -> ExperienceSummary:
    """Aggregate across every session of ``experience_id``."""
    store.ensure_schema()
    with store._conn() as con:
        sessions = con.execute(
            "SELECT id, completed_at FROM ix_sessions WHERE experience_id = ?",
            (experience_id,),
        ).fetchall()
        total_turns = con.execute(
            "SELECT COUNT(*) FROM ix_session_turns t "
            "JOIN ix_sessions s ON t.session_id = s.id "
            "WHERE s.experience_id = ?",
            (experience_id,),
        ).fetchone()[0]
        events = con.execute(
            "SELECT e.payload, e.action_id FROM ix_session_events e "
            "JOIN ix_sessions s ON e.session_id = s.id "
            "WHERE s.experience_id = ? AND e.event_kind = 'turn_resolved'",
            (experience_id,),
        ).fetchall()

    sc = len(sessions)
    completed = sum(1 for s in sessions if s["completed_at"] is not None)
    action_uses: Counter = Counter()
    decisions: Counter = Counter()
    for ev in events:
        if ev["action_id"]:
            action_uses[ev["action_id"]] += 1
        payload = _parse_payload(ev["payload"])
        if "decision" in payload:
            decisions[str(payload["decision"])] += 1
    popular = [{"action_id": aid, "uses": n} for aid, n in action_uses.most_common(10)]
    total_decisions = sum(decisions.values())
    block_rate = 0.0
    if total_decisions > 0:
        block_rate = decisions.get("block", 0) / total_decisions

    return ExperienceSummary(
        experience_id=experience_id,
        session_count=sc,
        completed_sessions=completed,
        completion_rate=(completed / sc) if sc > 0 else 0.0,
        total_turns=int(total_turns),
        total_events=len(events),
        popular_actions=popular,
        block_rate=block_rate,
    )
