"""
Server-enforced policy for voice-call sessions.

Never trust the client; every cap here is enforced before a session row
is inserted or a WebSocket is accepted. Counters live in the DB via
``store`` so they survive process restarts and apply across workers.
"""
from __future__ import annotations

from . import store
from .config import VoiceCallConfig


class PolicyError(Exception):
    """Raised when a caller violates a policy cap. Carries an HTTP status
    and a short machine-readable code so the router can return a clean
    JSON error without leaking internals."""

    def __init__(self, http_status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.http_status = http_status
        self.code = code
        self.detail = detail


def check_session_create(*, user_id: str, cfg: VoiceCallConfig) -> None:
    """Called before :func:`store.create_session`. Raises ``PolicyError``
    on any violation.

    Checks applied, in order of cheapness:
      1. ``VOICE_CALL_ENABLED`` — feature gate.
      2. Concurrent session cap (default 2). Stops the "infinite parallel
         calls" abuse vector.
      3. Rate limit on session creates (default 10 / 60 s). Stops script
         kiddies from hammering ``/sessions``.
    """
    if not cfg.enabled:
        raise PolicyError(
            http_status=404, code="voice_call_disabled",
            detail="Voice call feature is not enabled on this server.",
        )

    active = store.count_active_sessions_for_user(user_id)
    if active >= cfg.max_concurrent_per_user:
        raise PolicyError(
            http_status=409, code="too_many_active_sessions",
            detail=(
                f"You already have {active} active voice call(s). "
                f"End one before starting a new one."
            ),
        )

    recent = store.recent_session_creates_for_user(
        user_id, window_sec=60,
    )
    if recent >= cfg.session_create_rate_per_min:
        raise PolicyError(
            http_status=429, code="rate_limited",
            detail=(
                f"Too many voice call starts in the last minute "
                f"(limit {cfg.session_create_rate_per_min})."
            ),
        )


def session_hard_cap_exceeded(session_row: dict, cfg: VoiceCallConfig) -> bool:
    """True if the session has exceeded its hard duration cap.
    The WS orchestrator checks this every heartbeat to force ``ending``."""
    started = int(session_row.get("started_at") or 0)
    if started <= 0:
        return False
    now_ms = int(__import__("time").time() * 1000)
    return (now_ms - started) >= cfg.max_duration_sec * 1000
