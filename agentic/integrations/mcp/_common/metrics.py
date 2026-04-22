from __future__ import annotations

from collections import defaultdict

_COUNTERS: dict[str, int] = defaultdict(int)


def inc(metric: str, by: int = 1) -> None:
    _COUNTERS[metric] += by


def snapshot() -> dict[str, int]:
    return dict(_COUNTERS)
