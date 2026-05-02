"""
In-memory branch-graph data structure.

Domain types (separate from pydantic models in ``models.py`` — these
are mutation-friendly; pydantic models are serialization-friendly).

  GraphNode   — one scene / decision / merge / ending
  GraphEdge   — directed transition
  BranchGraph — container + convenience accessors

Validation rules (enforced by ``validate_graph``):
  V1 Exactly one entry node (kind='scene', marked via ``is_entry``).
  V2 Every node except entry has at least one inbound edge.
  V3 Every non-ending node has at least one outbound edge.
  V4 No cycles (branching graphs are DAGs by design — merge points
     are fine, loops aren't).
  V5 No dangling edge references (from/to must exist in the graph).
  V6 Max depth and node count within configured caps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Set


class GraphValidationError(Exception):
    """Raised when ``validate_graph`` finds a structural issue.

    ``issues`` is a list of dicts so callers can surface multiple
    issues to the user at once (one per node/edge).
    """

    def __init__(self, message: str, issues: Optional[List[dict]] = None) -> None:
        super().__init__(message)
        self.issues = list(issues or [])


@dataclass
class GraphNode:
    """One node in the branch graph."""

    id: str
    kind: str = "scene"  # scene | decision | merge | ending | assessment | remediation
    title: str = ""
    narration: str = ""
    is_entry: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class GraphEdge:
    """One directed transition between nodes."""

    from_id: str
    to_id: str
    trigger_kind: str = "auto"  # auto | choice | hotspot | timer | fallback | intent
    label: str = ""
    payload: dict = field(default_factory=dict)
    ordinal: int = 0


@dataclass
class BranchGraph:
    """Container for nodes + edges + lookup helpers."""

    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)

    # ── Lookup helpers ────────────────────────────────────────────

    def node(self, node_id: str) -> Optional[GraphNode]:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def entry(self) -> Optional[GraphNode]:
        for n in self.nodes:
            if n.is_entry:
                return n
        return None

    def outbound(self, node_id: str) -> List[GraphEdge]:
        return [e for e in self.edges if e.from_id == node_id]

    def inbound(self, node_id: str) -> List[GraphEdge]:
        return [e for e in self.edges if e.to_id == node_id]

    def add_node(self, node: GraphNode) -> GraphNode:
        self.nodes.append(node)
        return node

    def add_edge(self, edge: GraphEdge) -> GraphEdge:
        self.edges.append(edge)
        return edge

    def count_depth(self) -> int:
        """Longest path from entry to any reachable node.

        Uses plain DFS with a visited set — correct for acyclic
        graphs, and on a cyclic graph returns a finite answer
        without infinite looping (cycles still get flagged by
        ``_detect_cycles`` in validate_graph).

        Complexity O(V+E); bounded by the node count because each
        id is only inserted into ``visited`` once.
        """
        entry = self.entry()
        if not entry:
            return 0
        visited: Set[str] = set()
        best: Dict[str, int] = {}

        def dfs(nid: str, depth: int) -> int:
            # On a cycle we'd revisit — bail out to keep O(V+E).
            if nid in visited:
                return best.get(nid, depth)
            visited.add(nid)
            best[nid] = depth
            max_d = depth
            for e in self.outbound(nid):
                child = dfs(e.to_id, depth + 1)
                if child > max_d:
                    max_d = child
            return max_d

        return dfs(entry.id, 0)

    def __iter__(self) -> Iterator[GraphNode]:
        return iter(self.nodes)


# ─────────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────────

def _detect_cycles(graph: BranchGraph) -> List[List[str]]:
    """DFS-based cycle detection. Returns the list of cycles as
    lists of node ids; empty list = acyclic."""
    cycles: List[List[str]] = []
    color: Dict[str, str] = {n.id: "white" for n in graph.nodes}
    stack_path: List[str] = []

    def dfs(nid: str) -> None:
        color[nid] = "gray"
        stack_path.append(nid)
        for e in graph.outbound(nid):
            next_id = e.to_id
            if color.get(next_id, "white") == "white":
                dfs(next_id)
            elif color.get(next_id) == "gray":
                idx = stack_path.index(next_id)
                cycles.append(list(stack_path[idx:]) + [next_id])
        stack_path.pop()
        color[nid] = "black"

    for n in graph.nodes:
        if color.get(n.id) == "white":
            dfs(n.id)
    return cycles


def validate_graph(
    graph: BranchGraph,
    *,
    max_depth: int = 6,
    max_nodes: int = 200,
) -> None:
    """Apply V1-V6 rules. Raises ``GraphValidationError`` with all
    issues collected — callers get the full list, not just the
    first failure."""
    issues: List[dict] = []

    # V1 — exactly one entry node
    entries = [n for n in graph.nodes if n.is_entry]
    if len(entries) == 0:
        issues.append({"rule": "V1", "detail": "no entry node marked is_entry=True"})
    elif len(entries) > 1:
        issues.append({
            "rule": "V1",
            "detail": f"multiple entry nodes: {[n.id for n in entries]}",
        })

    # V6 — size caps
    if len(graph.nodes) > max_nodes:
        issues.append({
            "rule": "V6",
            "detail": f"{len(graph.nodes)} nodes exceeds max {max_nodes}",
        })

    depth = graph.count_depth()
    if depth > max_depth:
        issues.append({
            "rule": "V6",
            "detail": f"depth {depth} exceeds max {max_depth}",
        })

    # V5 — dangling edges
    node_ids: Set[str] = {n.id for n in graph.nodes}
    for e in graph.edges:
        if e.from_id not in node_ids:
            issues.append({
                "rule": "V5", "edge": (e.from_id, e.to_id),
                "detail": f"edge from_id '{e.from_id}' has no matching node",
            })
        if e.to_id not in node_ids:
            issues.append({
                "rule": "V5", "edge": (e.from_id, e.to_id),
                "detail": f"edge to_id '{e.to_id}' has no matching node",
            })

    # V2 / V3 — inbound/outbound expectations
    entry_id = entries[0].id if len(entries) == 1 else None
    for n in graph.nodes:
        if n.is_entry:
            continue
        if not graph.inbound(n.id):
            issues.append({
                "rule": "V2", "node": n.id,
                "detail": f"node '{n.id}' has no inbound edges",
            })
    for n in graph.nodes:
        if n.kind == "ending":
            continue
        if not graph.outbound(n.id):
            issues.append({
                "rule": "V3", "node": n.id,
                "detail": f"non-ending node '{n.id}' has no outbound edges",
            })

    # V4 — cycles
    cycles = _detect_cycles(graph)
    for cy in cycles:
        issues.append({
            "rule": "V4",
            "cycle": cy,
            "detail": f"cycle detected: {' → '.join(cy)}",
        })

    if issues:
        raise GraphValidationError(
            f"Graph invalid ({len(issues)} issue(s))",
            issues=issues,
        )
