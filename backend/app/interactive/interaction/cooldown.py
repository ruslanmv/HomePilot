"""
Per-session action cooldown tracking.

Lives in-memory in a ``CooldownTracker`` keyed by (session_id,
action_id). The tracker is optional — cooldown decisions can also
be made directly from the ix_session_events table (query last use
of this action) — but the in-memory path is faster on the hot
path.

``check_cooldown`` and ``mark_used`` are pure helpers; the router
module decides when to consult / update them.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class CooldownTracker:
    """In-process per-session cooldown map."""

    entries: Dict[Tuple[str, str], float] = field(default_factory=dict)

    def clear(self, session_id: str) -> None:
        self.entries = {k: v for k, v in self.entries.items() if k[0] != session_id}


# Module-level singleton (fine for single-process; swap for Redis later).
_TRACKER = CooldownTracker()


def _now_ms() -> int:
    return int(time.time() * 1000)


def check_cooldown(
    session_id: str, action_id: str, cooldown_sec: int, *, now_ms: Optional[int] = None,
) -> float:
    """Return remaining cooldown seconds (0.0 if ready).

    If ``cooldown_sec`` is 0 or negative the action is always
    ready — returns 0.0. Likewise, an action that has never been
    used in this session is always ready.
    """
    if cooldown_sec <= 0:
        return 0.0
    key = (session_id, action_id)
    if key not in _TRACKER.entries:
        return 0.0  # never used → ready
    now = now_ms if now_ms is not None else _now_ms()
    last = _TRACKER.entries[key]
    elapsed_s = (now - last) / 1000.0
    if elapsed_s >= cooldown_sec:
        return 0.0
    return max(0.0, float(cooldown_sec) - elapsed_s)


def mark_used(
    session_id: str, action_id: str, *, now_ms: Optional[int] = None,
) -> None:
    """Record that an action fired just now."""
    now = now_ms if now_ms is not None else _now_ms()
    _TRACKER.entries[(session_id, action_id)] = now


def reset_session(session_id: str) -> None:
    """Clear all cooldown entries for a session (on end / restart)."""
    _TRACKER.clear(session_id)
