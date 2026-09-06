"""The tab that takes the picture (batch RS1, path A).

The consent-preserving way to photograph this machine is not to photograph it at all: it is
to ask a HomePilot tab that *already holds a screen-share grant* for one frame off the stream
the user can see themselves sharing. No new prompt, no new permission, and the browser's own
"Sharing your screen" bar is the indicator — the one the user already trusts.

That tab cannot be called; it has no address. So it calls us: it long-polls :func:`take`'s
counterpart, waits for a request to appear, grabs a frame, and posts it back. This module is
the meeting point — a request id, an :class:`asyncio.Event`, and a place to put the bytes.

**A tab that has stopped polling is not there.** Freshness is checked, not assumed; the
capture route falls straight through to path B rather than waiting out a timeout for a tab
that closed an hour ago.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

from . import config


@dataclass
class _Pending:
    request_id: str
    reason: str
    created: float
    done: asyncio.Event = field(default_factory=asyncio.Event)
    data: Optional[bytes] = None
    error: str = ""


_pending: Dict[str, _Pending] = {}
_queue: list[str] = []
_last_poll: float = 0.0


def agent_seen(now: Optional[float] = None) -> None:
    """Record that a tab is listening. Called on every poll, including the ones that time out."""
    global _last_poll
    _last_poll = now if now is not None else time.time()


def agent_present(now: Optional[float] = None) -> bool:
    """Is a HomePilot tab listening right now?"""
    when = now if now is not None else time.time()
    return _last_poll > 0 and (when - _last_poll) <= config.agent_fresh_s()


def last_seen() -> float:
    """Seconds since a tab last polled; ``-1`` when none ever has."""
    if _last_poll <= 0:
        return -1.0
    return max(0.0, time.time() - _last_poll)


async def request(reason: str = "") -> Optional[bytes]:
    """Ask the listening tab for one frame. ``None`` when nothing answers in time.

    The pending entry is removed in a ``finally`` whatever happens, so a tab that dies
    mid-request leaves no queue entry behind for the next capture to trip over.
    """
    if not agent_present():
        return None
    entry = _Pending(request_id=uuid.uuid4().hex, reason=str(reason or "")[:200], created=time.time())
    _pending[entry.request_id] = entry
    _queue.append(entry.request_id)
    try:
        await asyncio.wait_for(entry.done.wait(), timeout=config.agent_wait_s())
    except asyncio.TimeoutError:
        return None
    finally:
        _pending.pop(entry.request_id, None)
        try:
            _queue.remove(entry.request_id)
        except ValueError:
            pass
    return entry.data


async def poll(wait_s: float) -> Optional[Dict[str, str]]:
    """The tab's side: block until there is something to photograph, or time out.

    Returns ``{"request_id": ..., "reason": ...}`` or ``None``. A ``None`` is not an error —
    it is how a long poll ends, and the tab simply calls again.
    """
    agent_seen()
    deadline = time.time() + max(0.5, float(wait_s or 0))
    while time.time() < deadline:
        while _queue:
            key = _queue.pop(0)
            entry = _pending.get(key)
            if entry is not None and not entry.done.is_set():
                return {"request_id": entry.request_id, "reason": entry.reason}
        await asyncio.sleep(0.15)
    agent_seen()
    return None


def deliver(request_id: str, data: bytes) -> bool:
    """The tab's answer. False when the request is gone — it timed out, or never existed."""
    entry = _pending.get(str(request_id or ""))
    if entry is None or entry.done.is_set():
        return False
    entry.data = data
    entry.done.set()
    return True


def reset() -> None:
    """Drop every pending request and forget the last poll. Tests only."""
    global _last_poll
    _pending.clear()
    _queue.clear()
    _last_poll = 0.0
