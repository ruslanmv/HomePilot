"""In-process completion event stream for optional Routines clients.

The durable source of truth remains routine_runs in SQLite. This bounded stream
only provides low-latency delivery to active HomePilot/companion clients; clients
can reconnect and recover state from the run-history API.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, Deque, Dict, List


_events: Deque[Dict[str, Any]] = deque(maxlen=200)
_sequence = 0
_condition = asyncio.Condition()


async def publish(user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    global _sequence
    async with _condition:
        _sequence += 1
        event = {
            "seq": _sequence,
            "_user_id": user_id,
            **payload,
        }
        _events.append(event)
        _condition.notify_all()
        return {key: value for key, value in event.items() if key != "_user_id"}


def after(user_id: str, sequence: int) -> List[Dict[str, Any]]:
    return [
        {key: value for key, value in event.items() if key != "_user_id"}
        for event in list(_events)
        if event.get("_user_id") == user_id and int(event.get("seq") or 0) > sequence
    ]


async def wait_after(
    user_id: str,
    sequence: int,
    *,
    timeout: float = 15.0,
) -> List[Dict[str, Any]]:
    ready = after(user_id, sequence)
    if ready:
        return ready
    try:
        async with _condition:
            await asyncio.wait_for(_condition.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        return []
    return after(user_id, sequence)
