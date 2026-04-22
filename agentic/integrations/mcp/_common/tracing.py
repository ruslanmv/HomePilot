from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Iterator


@contextmanager
def trace_span(name: str) -> Iterator[dict[str, float]]:
    start = perf_counter()
    meta = {'name': name, 'start': start}
    try:
        yield meta
    finally:
        meta['duration_s'] = perf_counter() - start
