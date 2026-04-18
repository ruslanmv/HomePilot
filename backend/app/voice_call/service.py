"""
Pure-Python state machine for a voice-call session.

No HTTP or WebSocket imports here — the router/WS layers consume this
module. That separation lets the unit tests drive the state machine
end-to-end without spinning up FastAPI.

State flow (from the design doc, collapsed for MVP):

    connecting  →  live  →  ending  →  ended
         │             │
         │             ├─ interrupted  (WS dropped, within resume window)
         │             │       │
         │             │       └─→ live again (on resume)
         │             │       └─→ ended (resume window expired)
         │
         └─ ended (ws never opens)
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from . import store
from .config import VoiceCallConfig
from .policy import PolicyError, check_session_create


_TERMINAL_STATES = {"ended"}
_LIVE_STATES = {"connecting", "live", "interrupted"}


def _now_ms() -> int:
    return int(time.time() * 1000)


# ── create / end ─────────────────────────────────────────────────────

def create_session(
    *,
    user_id: str,
    conversation_id: Optional[str],
    persona_id: Optional[str],
    entry_mode: str,
    client_platform: Optional[str],
    app_version: Optional[str],
    cfg: VoiceCallConfig,
) -> Dict[str, Any]:
    """Gate through policy, then insert a new session row.

    The returned dict includes the ``resume_token`` which the router
    will forward to the client. Callers MUST strip this from any
    response that ends up in an observability log.
    """
    check_session_create(user_id=user_id, cfg=cfg)
    row = store.create_session(
        user_id=user_id,
        conversation_id=conversation_id,
        persona_id=persona_id,
        entry_mode=entry_mode,
        client_platform=client_platform,
        app_version=app_version,
    )
    store.append_event(
        session_id=row["id"],
        seq=0,
        event_type="session.created",
        payload={"entry_mode": entry_mode},
    )
    return row


def end_session(
    *,
    sid: str,
    user_id: str,
    reason: str = "user_ended",
) -> Optional[Dict[str, Any]]:
    """Mark a session ``ended``. Idempotent: calling twice returns the
    same row on the second call. Returns ``None`` if the session doesn't
    exist OR doesn't belong to ``user_id`` (probe-safe)."""
    row = store.get_session_for_owner(sid, user_id)
    if row is None:
        return None
    if row["status"] in _TERMINAL_STATES:
        return row  # already ended; idempotent
    updated = store.update_session_status(sid, "ended", ended_reason=reason)
    if updated is not None:
        store.append_event(
            session_id=sid,
            seq=_next_event_seq(sid),
            event_type="session.ended",
            payload={"reason": reason},
        )
    return updated


def get(sid: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Owner-bound getter. Mirrors :func:`store.get_session_for_owner`
    so callers don't import store directly."""
    return store.get_session_for_owner(sid, user_id)


# ── internal state transitions (called from ws.py) ───────────────────

def mark_live(sid: str) -> Optional[Dict[str, Any]]:
    """Transition from ``connecting`` → ``live``. Called when the WS
    opens with a valid resume token."""
    return store.update_session_status(sid, "live")


def mark_interrupted(sid: str) -> Optional[Dict[str, Any]]:
    return store.update_session_status(sid, "interrupted")


def mark_ended_by_timeout(sid: str, reason: str) -> Optional[Dict[str, Any]]:
    return store.update_session_status(sid, "ended", ended_reason=reason)


# ── sequence bookkeeping ─────────────────────────────────────────────

# The server emits events with a monotonically-increasing ``seq``. We
# keep a tiny per-process cache to avoid a SELECT MAX() on every write.
# The cache is seeded on first use by reading the current max seq for
# the session — so it recovers cleanly across process restarts.

from threading import Lock
_seq_cache: Dict[str, int] = {}
_seq_lock = Lock()


def _next_event_seq(session_id: str) -> int:
    with _seq_lock:
        if session_id in _seq_cache:
            _seq_cache[session_id] += 1
            return _seq_cache[session_id]
        events = store.list_events(session_id, limit=1000)
        current_max = max((e["seq"] for e in events), default=-1)
        _seq_cache[session_id] = current_max + 1
        return _seq_cache[session_id]


def _reset_for_tests() -> None:
    with _seq_lock:
        _seq_cache.clear()
