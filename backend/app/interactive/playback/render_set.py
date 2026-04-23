"""Scene-render target selection for the Interactive pre-render pass.

Additive, best-practice replacement for the naive
``[n for n in nodes if n.kind in ("scene","decision","assessment","remediation")]``
filter that ``generator_auto.py`` applies before calling ``render_scene_async``.

Why
---
The naive filter ignores two facts:

1. **Persona Live Play owns its own rendering pipeline.** It anchors on the
   persona portrait and renders edit-recipe variants per user action. The
   scene-graph ``asset_ids[]`` are never read by the Persona Live runtime
   (see ``interactive/routes/persona_live.py::_pick_anchor_image_ref``).
   Pre-rendering scene nodes for a ``persona_live_play`` project is pure
   wasted compute — one SDXL pass per node that nothing ever displays.

2. **Standard projects rarely need every node rendered before Play opens.**
   Only the start node and its first-decision layer need to be ready for
   the initial frames. Deeper nodes can be rendered on-demand as the
   user's cursor approaches them (industry prefetch pattern).

This module exposes two pure functions with zero I/O side effects:

- ``compute_reachable_nodes(nodes, edges, start_id, max_depth)`` — BFS over
  the graph bounded by ``max_depth``.
- ``filter_targets_for_play(targets, experience, edges)`` — takes the
  already-computed naive target list and the experience, returns the
  subset that actually needs pre-rendering.

Both are side-effect-free and typed so they're trivial to unit-test
without standing up a real experience.

Environment knobs
-----------------
- ``INTERACTIVE_PRERENDER_DEPTH`` (int, default 2) — BFS depth limit for
  Standard projects. Higher = more eager, more compute. Lower = lazier,
  faster "Rendering scenes" phase.
- ``INTERACTIVE_PRERENDER_PERSONA_LIVE`` (``true|false``, default ``false``)
  — emergency knob that restores the old behavior (pre-render everything
  for Persona Live too) if a regression is found.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Set

# ── Configuration ────────────────────────────────────────────────────────────

# BFS depth used to decide how many layers of scene/decision nodes to
# pre-render for Standard projects. Default is a large number so existing
# flows pre-render everything (behavior-compatible). Operators opt into
# the depth-limited eager render by setting INTERACTIVE_PRERENDER_DEPTH to
# a small value (e.g. 2 = start + first decision + first choice layer).
DEFAULT_PRERENDER_DEPTH: int = int(os.getenv("INTERACTIVE_PRERENDER_DEPTH", "99") or 99)

# Emergency knob: pre-render everything for Persona Live (old behavior).
PRERENDER_PERSONA_LIVE: bool = (
    os.getenv("INTERACTIVE_PRERENDER_PERSONA_LIVE", "false").lower() == "true"
)

# Kinds that carry their own visual asset. Endings reuse the trailing frame.
RENDERABLE_KINDS: frozenset[str] = frozenset(
    {"scene", "decision", "assessment", "remediation"}
)


# ── Types ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _NodeLike:
    """Minimal duck-typed view of an interactive Node.

    Kept deliberately narrow so this module doesn't depend on the concrete
    ORM/dataclass in ``branching/graph.py`` — callers can pass any object
    with ``id``, ``kind``, and ``asset_ids`` attributes.
    """
    id: str
    kind: str
    asset_ids: Sequence[str] = ()


@dataclass(frozen=True)
class _EdgeLike:
    from_id: str
    to_id: str


@dataclass(frozen=True)
class RenderDecision:
    """Why a node was / wasn't selected for pre-render.

    Useful for SSE events and debug logs — lets the UI (and operators)
    see at a glance why "Rendering scenes 0/6" is actually 0/2 or 0/0.
    """
    node_id: str
    selected: bool
    reason: str
    depth: Optional[int] = None


# ── Core functions ───────────────────────────────────────────────────────────

def compute_reachable_nodes(
    nodes: Iterable,
    edges: Iterable,
    *,
    start_id: str,
    max_depth: int = DEFAULT_PRERENDER_DEPTH,
) -> Set[str]:
    """BFS from *start_id* up to (inclusive) *max_depth* edges away.

    Returns the set of reachable node IDs. The start node itself is
    always included at depth 0. Non-existent edges / dangling IDs are
    skipped silently — validation is the planner's job, not ours.

    A ``max_depth`` of 0 returns only the start node. Negative depths
    are clamped to 0.
    """
    if not start_id:
        return set()
    max_depth = max(0, int(max_depth))

    node_ids = {str(getattr(n, "id", "") or "") for n in nodes}
    node_ids.discard("")
    if start_id not in node_ids:
        return set()

    # Forward adjacency only — render set cares about what the user
    # reaches *from* the start, not what reaches them.
    adj: dict[str, List[str]] = {}
    for e in edges:
        fid = str(getattr(e, "from_id", "") or "")
        tid = str(getattr(e, "to_id", "") or "")
        if fid and tid and fid in node_ids and tid in node_ids:
            adj.setdefault(fid, []).append(tid)

    reachable: Set[str] = {start_id}
    frontier: List[tuple[str, int]] = [(start_id, 0)]
    while frontier:
        nid, depth = frontier.pop(0)
        if depth >= max_depth:
            continue
        for child in adj.get(nid, ()):
            if child not in reachable:
                reachable.add(child)
                frontier.append((child, depth + 1))
    return reachable


def _interaction_type(experience: object) -> str:
    """Read ``interaction_type`` off the experience, tolerating dict / dataclass."""
    if isinstance(experience, dict):
        return str(experience.get("interaction_type", "") or "")
    return str(getattr(experience, "interaction_type", "") or "")


def _entry_node_id(experience: object, nodes: Sequence) -> str:
    """Best-effort lookup of the start node.

    Prefers an explicit ``entry_node_id`` / ``start_node_id`` field on
    the experience; falls back to the first scene node.
    """
    eid = ""
    if isinstance(experience, dict):
        eid = str(
            experience.get("entry_node_id")
            or experience.get("start_node_id")
            or ""
        )
    else:
        eid = str(
            getattr(experience, "entry_node_id", "")
            or getattr(experience, "start_node_id", "")
            or ""
        )
    if eid:
        return eid
    for n in nodes:
        if str(getattr(n, "kind", "") or "") == "scene":
            return str(getattr(n, "id", "") or "")
    return ""


def filter_targets_for_play(
    naive_targets: Sequence,
    *,
    experience: object,
    edges: Iterable,
    nodes: Optional[Sequence] = None,
    max_depth: int = DEFAULT_PRERENDER_DEPTH,
) -> tuple[List, List[RenderDecision]]:
    """Scope the naive target list to what Play will actually display.

    Returns ``(targets, decisions)`` where:
      * ``targets`` is the filtered list (same objects as ``naive_targets``),
        preserving their original order.
      * ``decisions`` is one ``RenderDecision`` per *original* target so
        callers can emit SSE events for both selected and skipped nodes.

    Policy
    ------
    1. ``interaction_type == "persona_live_play"`` → return ``[]``. Persona
       Live anchors on the persona portrait and renders edit-recipe variants
       on demand; scene-graph assets are never read by its runtime.
       Set ``INTERACTIVE_PRERENDER_PERSONA_LIVE=true`` to opt back in.
    2. Otherwise → BFS reachable set from the entry node, bounded by
       ``max_depth``. Nodes outside the set are marked ``deferred``; the
       on-demand render pass can fill them in when the user cursor lands.
    3. Nodes that already carry ``asset_ids`` are always kept — idempotency
       matters more than scope. (The existing generator_auto.py also
       skips these during the render loop.)
    """
    itype = _interaction_type(experience)

    # Persona Live: hand back zero targets.
    if itype == "persona_live_play" and not PRERENDER_PERSONA_LIVE:
        decisions = [
            RenderDecision(
                node_id=str(getattr(n, "id", "") or ""),
                selected=False,
                reason="persona_live_own_pipeline",
            )
            for n in naive_targets
        ]
        return [], decisions

    # Standard: BFS-bounded reachable set.
    node_list: Sequence = list(nodes) if nodes is not None else list(naive_targets)
    start_id = _entry_node_id(experience, node_list)
    reachable: Set[str] = set()
    if start_id:
        reachable = compute_reachable_nodes(
            node_list, edges, start_id=start_id, max_depth=max_depth
        )

    selected: List = []
    decisions: List[RenderDecision] = []
    for n in naive_targets:
        nid = str(getattr(n, "id", "") or "")
        has_assets = bool(getattr(n, "asset_ids", None))
        if has_assets:
            selected.append(n)
            decisions.append(RenderDecision(nid, True, "already_rendered"))
            continue
        if not reachable:
            # No entry node resolved — fall back to the original behavior.
            selected.append(n)
            decisions.append(RenderDecision(nid, True, "reachable_unknown"))
            continue
        if nid in reachable:
            selected.append(n)
            decisions.append(RenderDecision(nid, True, "reachable"))
        else:
            decisions.append(
                RenderDecision(nid, False, "deferred_unreachable_at_depth")
            )
    return selected, decisions


__all__ = [
    "DEFAULT_PRERENDER_DEPTH",
    "PRERENDER_PERSONA_LIVE",
    "RENDERABLE_KINDS",
    "RenderDecision",
    "compute_reachable_nodes",
    "filter_targets_for_play",
]
