"""
Merge-point optimiser for branch graphs.

Prevents exponential blow-up by detecting structurally-identical
endings and folding them into a single shared ending. Operates
in-place on a BranchGraph.

Detection rules (phase 1 — simple & safe):
  M1 Merge endings with the same ``kind == 'ending'`` and same
     ``title`` — they represent the same narrative beat.
  M2 Any edge whose ``to_id`` pointed at a merged-away ending is
     rewritten to the surviving ending.
  M3 Nodes with zero inbound edges after merging are NOT deleted
     (could be legitimate alternate entry points added later by
     the designer). Pruning is a separate concern.

Future: structural hashing that compares whole sub-trees (not just
single nodes). Today's implementation is deliberately conservative
so it never corrupts a hand-authored graph.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from .graph import BranchGraph, GraphEdge, GraphNode


def _ending_key(node: GraphNode) -> str:
    """Canonical key for merge-candidate endings."""
    return f"{node.kind}::{node.title.strip().lower()}"


def collapse_merge_points(graph: BranchGraph) -> int:
    """Collapse structurally-identical ending nodes.

    Returns the number of nodes removed — 0 means nothing merged
    (either nothing to merge or the graph was already optimal).
    """
    # Group ending nodes by canonical key.
    groups: Dict[str, List[GraphNode]] = defaultdict(list)
    for n in graph.nodes:
        if n.kind == "ending":
            groups[_ending_key(n)].append(n)

    id_map: Dict[str, str] = {}
    removed = 0
    for key, nodes in groups.items():
        if len(nodes) < 2:
            continue
        survivor = nodes[0]
        for loser in nodes[1:]:
            id_map[loser.id] = survivor.id
            removed += 1

    if not id_map:
        return 0

    # Rewrite edges pointing to any loser.
    new_edges: List[GraphEdge] = []
    seen_pairs: set = set()
    for e in graph.edges:
        to_id = id_map.get(e.to_id, e.to_id)
        pair = (e.from_id, to_id, e.trigger_kind)
        # Dedupe edges that now land on the same survivor from the
        # same source via the same trigger.
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        new_edges.append(GraphEdge(
            from_id=e.from_id,
            to_id=to_id,
            trigger_kind=e.trigger_kind,
            label=e.label,
            payload=e.payload,
            ordinal=e.ordinal,
        ))
    graph.edges = new_edges

    # Drop merged-away nodes.
    graph.nodes = [n for n in graph.nodes if n.id not in id_map]

    return removed
