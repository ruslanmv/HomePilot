# backend/app/teams/locks.py
"""
One lock per room to prevent overlapping run-turn calls.
Simple, in-memory.  Safe for a single backend instance.
"""
from __future__ import annotations

import asyncio
from typing import Dict

_room_locks: Dict[str, asyncio.Lock] = {}


def get_room_lock(room_id: str) -> asyncio.Lock:
    """Return (or create) the asyncio.Lock for *room_id*."""
    lock = _room_locks.get(room_id)
    if lock is None:
        lock = asyncio.Lock()
        _room_locks[room_id] = lock
    return lock
