"""
Cached health + circuit breaker (PR 2).

The router must not ping every remote endpoint before every request (the design
doc is explicit about this). Instead it asks this module, which:

* caches a health result per key for ``ttl_s`` seconds, and
* trips a circuit breaker after ``fail_threshold`` consecutive failures, marking
  the key unhealthy for ``cooldown_s`` without probing at all.

It is deliberately provider-agnostic: callers pass a ``key`` (e.g.
``"device:colab"`` or ``"source:openai-x"``) and an async ``probe`` returning a
bool. A shared module-level cache is used by default so results are reused
across requests; tests construct their own ``HealthCache`` with an injected
clock for determinism.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

Probe = Callable[[], Awaitable[bool]]


@dataclass
class _Entry:
    healthy: bool = False
    checked_at: float = 0.0
    consecutive_failures: int = 0
    circuit_open_until: float = 0.0
    has_result: bool = False


@dataclass
class HealthCache:
    ttl_s: float = 15.0
    fail_threshold: int = 3
    cooldown_s: float = 60.0
    clock: Callable[[], float] = time.monotonic
    _entries: dict[str, _Entry] = field(default_factory=dict)

    def _entry(self, key: str) -> _Entry:
        e = self._entries.get(key)
        if e is None:
            e = _Entry()
            self._entries[key] = e
        return e

    def record(self, key: str, healthy: bool) -> None:
        """Feed an out-of-band health observation (e.g. a heartbeat) in."""
        now = self.clock()
        e = self._entry(key)
        e.healthy = healthy
        e.checked_at = now
        e.has_result = True
        if healthy:
            e.consecutive_failures = 0
            e.circuit_open_until = 0.0
        else:
            e.consecutive_failures += 1
            if e.consecutive_failures >= self.fail_threshold:
                e.circuit_open_until = now + self.cooldown_s

    def allows(self, key: str) -> bool:
        """Cheap, probe-free gate the router uses before *attempting* a target:
        the real call doubles as the health probe, so we only skip a target when
        the breaker is open or a recent attempt already failed (within ``ttl_s``).
        Unknown keys are allowed (optimistic — try it once)."""
        now = self.clock()
        e = self._entries.get(key)
        if e is None:
            return True
        if e.circuit_open_until and now < e.circuit_open_until:
            return False
        if e.has_result and not e.healthy and (now - e.checked_at) < self.ttl_s:
            return False
        return True

    async def healthy(self, key: str, probe: Probe) -> bool:
        """Return cached health, or probe if stale. While the circuit is open the
        probe is skipped entirely and the key is reported unhealthy."""
        now = self.clock()
        e = self._entry(key)

        # Circuit open: fail fast, don't touch the network.
        if e.circuit_open_until and now < e.circuit_open_until:
            return False

        # Fresh cache hit.
        if e.has_result and (now - e.checked_at) < self.ttl_s:
            return e.healthy

        try:
            result = bool(await probe())
        except Exception:
            result = False
        self.record(key, result)
        return result

    def invalidate(self, key: Optional[str] = None) -> None:
        if key is None:
            self._entries.clear()
        else:
            self._entries.pop(key, None)


# Shared cache used by the router in production.
_shared = HealthCache()


def shared_cache() -> HealthCache:
    return _shared
