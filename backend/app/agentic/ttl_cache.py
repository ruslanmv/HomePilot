"""Simple in-memory TTL cache.

Additive: safe to include without changing existing behavior.
Used by AgenticCatalogService to reduce redundant Forge calls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass
class CacheEntry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    """Single-value TTL cache with sync get/set and async get_or_set."""

    def __init__(self, ttl_seconds: float = 15.0):
        self.ttl_seconds = float(ttl_seconds)
        self._entry: Optional[CacheEntry[T]] = None

    def get(self) -> Optional[T]:
        if not self._entry:
            return None
        if time.time() >= self._entry.expires_at:
            self._entry = None
            return None
        return self._entry.value

    def set(self, value: T) -> T:
        self._entry = CacheEntry(value=value, expires_at=time.time() + self.ttl_seconds)
        return value

    def invalidate(self) -> None:
        self._entry = None

    async def get_or_set_async(self, builder: Callable[[], Awaitable[T]]) -> T:
        cached = self.get()
        if cached is not None:
            return cached
        value = await builder()
        return self.set(value)
