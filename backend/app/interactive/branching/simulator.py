"""
Path simulator — enumerate every viewer-path through a graph.

Used by:
  - QA walker (``qa/path_walker.py`` in batch 8) to verify every
    path terminates and has all required assets
  - Analytics preview to estimate maximum viewer variety

Safety caps prevent runaway enumeration on malformed graphs:
  - max_paths: hard stop after N complete paths
  - max_steps: hard stop after N total edge-traversals
These defaults are generous but finite.
"""
from __future__ import annotations

from typing import Iterator, List, Optional

from .graph import BranchGraph


def walk_paths(
    graph: BranchGraph,
    *,
    max_paths: int = 500,
    max_steps: int = 10_000,
) -> Iterator[List[str]]:
    """Yield every simple path from entry to an ending, as a list
    of node ids (including both endpoints).

    'Simple' = no repeated nodes within a single path. Since the
    graph is validated acyclic, simple paths exhaust reachable
    endings without infinite loops.

    Stops cleanly at either cap and silently returns the partial
    enumeration — use ``enumerate_paths`` when you need the count
    with a cap indicator.
    """
    entry = graph.entry()
    if not entry:
        return

    # Adjacency map keyed by from_id; ordered by (ordinal, then insertion).
    adj: dict = {}
    for e in graph.edges:
        adj.setdefault(e.from_id, []).append(e)
    for from_id, es in adj.items():
        es.sort(key=lambda x: (x.ordinal, 0))

    steps = 0
    paths_yielded = 0
    stack: List[List[str]] = [[entry.id]]

    while stack:
        if paths_yielded >= max_paths:
            return
        if steps >= max_steps:
            return

        path = stack.pop()
        tail_id = path[-1]
        tail = graph.node(tail_id)
        if tail is None:
            continue

        # Ending nodes → yield the path and don't expand.
        if tail.kind == "ending":
            yield list(path)
            paths_yielded += 1
            continue

        outs = adj.get(tail_id, [])
        if not outs:
            # Dead end (shouldn't happen on a validated graph, but
            # don't crash — treat as a path terminus).
            yield list(path)
            paths_yielded += 1
            continue

        # Iterate in reverse so leftmost ordinal is processed first
        # when popped off the stack.
        for e in reversed(outs):
            steps += 1
            if e.to_id in path:
                # Simple-path invariant — skip revisits.
                continue
            stack.append(list(path) + [e.to_id])


def enumerate_paths(
    graph: BranchGraph, *, max_paths: int = 500, max_steps: int = 10_000,
) -> dict:
    """Count enumeration with cap indicators.

    Returns a dict: ``{'paths': [...], 'count': int, 'truncated': bool}``
    where ``truncated=True`` means the walker hit one of the caps.
    """
    collected: List[List[str]] = []
    count = 0
    for p in walk_paths(graph, max_paths=max_paths, max_steps=max_steps):
        collected.append(p)
        count += 1

    # Heuristic for 'truncated': if we returned exactly the cap,
    # there were probably more paths.
    truncated = count >= max_paths
    return {"paths": collected, "count": count, "truncated": truncated}
