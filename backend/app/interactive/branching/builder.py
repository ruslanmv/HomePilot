"""
Graph builder — Intent → BranchGraph.

Phase 1: deterministic tree/graph construction from the Intent's
branch_count + depth + node-kind rotation. Produces the same graph
given the same Intent — great for tests and reproducible demos.

Phase 2 (later): swap the internal helpers here for LLM-generated
nodes/edges without changing ``build_graph``'s signature.

Output graph shape:

  entry (scene)
     │
     decision
     │ ├─ branch 0
     │ │    scene → … → ending
     │ ├─ branch 1
     │ │    scene → … → ending
     │ └─ branch N
     │      scene → … → ending

``merge_points=True`` (the default) collapses all branch endings
into a single shared "epilogue" ending node — matches the merge
step the spec requires.
"""
from __future__ import annotations

import uuid
from typing import List

from ..planner.intent import Intent
from .graph import BranchGraph, GraphEdge, GraphNode


def _nid(prefix: str) -> str:
    """Short deterministic-ish id. (Uses uuid4 — tests assert on
    graph shape, not exact ids.)"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _kind_for_slot(kinds: List[str], slot: int) -> str:
    """Rotate through the preset's node-kind list, capped to
    'ending' at the last slot."""
    if not kinds:
        return "scene"
    return kinds[slot % len(kinds)]


def build_graph(intent: Intent, *, merge_points: bool = True) -> BranchGraph:
    """Construct a BranchGraph from an Intent.

    The builder respects ``intent.branch_count`` and ``intent.depth``
    strictly — these have already been capped by the planner to
    ``cfg.max_branches`` / ``cfg.max_depth``.
    """
    graph = BranchGraph()

    # Node-kind rotation from the preset (stored in intent.raw_hints).
    from ..planner.presets import get_preset
    preset = get_preset(intent.mode)
    kinds = list(preset.default_node_kinds) if preset else ["scene", "decision", "scene", "ending"]

    # ── Entry node ───────────────────────────────────────────────
    entry = GraphNode(
        id=_nid("n"),
        kind="scene",
        title="Introduction",
        narration=f"Opening for: {intent.objective}",
        is_entry=True,
        metadata={"slot": 0, "purpose": "entry"},
    )
    graph.add_node(entry)

    # ── Decision hub ─────────────────────────────────────────────
    hub = GraphNode(
        id=_nid("n"),
        kind="decision",
        title="Choose a path",
        metadata={"slot": 1, "purpose": "hub"},
    )
    graph.add_node(hub)
    graph.add_edge(GraphEdge(
        from_id=entry.id, to_id=hub.id,
        trigger_kind="auto", label="continue",
    ))

    # ── Shared ending (only when merge_points=True) ──────────────
    shared_ending = None
    if merge_points:
        shared_ending = GraphNode(
            id=_nid("n"),
            kind="ending",
            title="Epilogue",
            narration="Summary and next steps",
            metadata={"purpose": "shared_ending"},
        )
        graph.add_node(shared_ending)

    # ── Branches ─────────────────────────────────────────────────
    for b in range(max(1, intent.branch_count)):
        previous_id = hub.id

        # depth - 1 internal scenes (first outbound from hub +
        # intermediate scenes); the LAST node per branch is an
        # ending — shared if merge_points else per-branch.
        internal_steps = max(1, intent.depth - 1)
        for slot in range(internal_steps):
            kind = _kind_for_slot(kinds, slot + 2)  # +2: skip entry+hub slots
            # Don't place 'ending' in the middle of a branch.
            if kind == "ending":
                kind = "scene"
            node = GraphNode(
                id=_nid("n"),
                kind=kind,
                title=f"Branch {b} step {slot + 1}",
                metadata={"branch": b, "slot": slot + 1},
            )
            graph.add_node(node)

            label = f"choose-{b}" if slot == 0 else "continue"
            trigger = "choice" if slot == 0 else "auto"
            graph.add_edge(GraphEdge(
                from_id=previous_id,
                to_id=node.id,
                trigger_kind=trigger,
                label=label,
                ordinal=b if slot == 0 else 0,
            ))
            previous_id = node.id

        # Link to ending
        if merge_points:
            graph.add_edge(GraphEdge(
                from_id=previous_id,
                to_id=shared_ending.id,  # type: ignore[arg-type]
                trigger_kind="auto",
                label="finale",
            ))
        else:
            ending = GraphNode(
                id=_nid("n"),
                kind="ending",
                title=f"Branch {b} ending",
                metadata={"branch": b, "purpose": "per_branch_ending"},
            )
            graph.add_node(ending)
            graph.add_edge(GraphEdge(
                from_id=previous_id,
                to_id=ending.id,
                trigger_kind="auto",
                label="finale",
            ))

    return graph
