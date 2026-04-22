from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class MetricEvent:
    ok: bool
    latency_ms: int


class SLOMonitor:
    def __init__(self) -> None:
        self._events: List[MetricEvent] = []

    def record(self, ok: bool, latency_ms: int) -> None:
        self._events.append(MetricEvent(ok=ok, latency_ms=latency_ms))
        if len(self._events) > 5000:
            self._events = self._events[-5000:]

    def snapshot(self) -> dict:
        if not self._events:
            return {"error_rate": 0.0, "p95_ms": 0, "count": 0}

        errs = sum(1 for e in self._events if not e.ok)
        lats = sorted(e.latency_ms for e in self._events)
        idx = min(len(lats) - 1, int(len(lats) * 0.95))
        return {
            "error_rate": errs / len(self._events),
            "p95_ms": lats[idx],
            "count": len(self._events),
        }
