"""
Per-session barge-in token registry.

One process-local ``dict`` keyed by ``session_id``; each entry carries
a single :class:`BargeInToken` representing the currently-active
assistant turn. The token exposes an ``asyncio.Event`` the streaming
turn runner polls between chunks — when the client sends
``user.barge_in`` the WS handler calls :func:`cancel_active` which
flips the event and the generator exits cleanly on its next poll.

The module is deliberately small and state-machine-only:

  * no HTTP, no DB, no asyncio transport — unit-testable in
    milliseconds,
  * ``cancel_active`` refuses cancels for stale ``turn_id`` values so
    a barge-in racing a new turn is a silent no-op,
  * ``cancel`` is idempotent (``asyncio.Event.set()`` is idempotent),
  * ``clear`` wipes a session on WS close so a resume starts fresh.

Contract is documented in
``docs/analysis/voice-call-streaming-design.md`` § 4.3.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class BargeInToken:
    """Per-turn cancellation handle.

    Created by :func:`new_token` when the WS handler starts streaming
    an assistant turn; polled by the streaming runner; flipped by
    :func:`cancel_active` when the user barges in.
    """

    turn_id: str
    _ev: asyncio.Event = field(default_factory=asyncio.Event)

    def cancel(self) -> None:
        """Flip the event. Idempotent."""
        self._ev.set()

    def is_cancelled(self) -> bool:
        """Cheap read the streaming runner calls between chunks."""
        return self._ev.is_set()

    async def wait(self) -> None:
        """Optional helper for callers that want to ``asyncio.wait``
        on cancel rather than poll."""
        await self._ev.wait()


# ── process-local registry ────────────────────────────────────────────
# One active token per session. A single lock because the hot path
# (``cancel_active``) is O(1) — no contention worth sharding for.

_lock = threading.Lock()
_active: Dict[str, BargeInToken] = {}


def new_token(session_id: str, turn_id: str) -> BargeInToken:
    """Register ``turn_id`` as the active turn for ``session_id``.

    Any previous active token for this session is replaced — if a
    turn started without the previous one clearing (which would be
    a bug upstream) we fail gracefully rather than leak.
    """
    token = BargeInToken(turn_id=turn_id)
    with _lock:
        _active[session_id] = token
    return token


def cancel_active(session_id: str, turn_id: str) -> bool:
    """Cancel the active turn for ``session_id`` IFF its ``turn_id``
    matches the argument.

    Returns True on a successful cancel, False if the active turn has
    a different id (stale barge-in) or no turn is active.
    """
    with _lock:
        token = _active.get(session_id)
        if token is None or token.turn_id != turn_id:
            return False
    # Release the lock before setting — the event set is itself
    # thread-safe, and keeping the lock narrow keeps the hot path
    # fast under contention.
    token.cancel()
    return True


def get_active(session_id: str) -> Optional[BargeInToken]:
    """Read the currently-active token without mutating.

    Used by the WS handler to find the active ``turn_id`` when the
    client sends a ``transcript.partial`` (secondary barge-in signal)
    without an explicit ``turn_id``.
    """
    with _lock:
        return _active.get(session_id)


def clear_session(session_id: str) -> None:
    """Drop all tokens for ``session_id`` — called on WS close.

    If a turn was mid-stream we cancel it first so the streaming
    runner exits promptly; the handler is responsible for emitting
    the final envelope.
    """
    with _lock:
        token = _active.pop(session_id, None)
    if token is not None and not token.is_cancelled():
        token.cancel()


def _reset_for_tests() -> None:
    """Test hook — wipe the whole registry between cases."""
    with _lock:
        _active.clear()
