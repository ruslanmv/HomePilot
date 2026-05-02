"""
Branching subsystem — graph construction, validation, simulation.

Submodules:

  graph.py       Pure data structures (BranchGraph / GraphNode /
                 GraphEdge) + validation helpers. No persistence.
  builder.py     build_graph(intent) → BranchGraph
                 Deterministic heuristic today; LLM-swap-in point.
  merge.py       Merge-point detection: collapses same-content
                 leaf siblings into a single shared ending.
  simulator.py   walk_paths(graph) → every viewer path the runtime
                 could produce. Used by QA + analytics preview.

All modules work on in-memory BranchGraph objects; persistence is
a separate concern (repo.create_node / create_edge).
"""
from .builder import build_graph
from .graph import (
    BranchGraph,
    GraphEdge,
    GraphNode,
    GraphValidationError,
    validate_graph,
)
from .merge import collapse_merge_points
from .simulator import enumerate_paths, walk_paths

__all__ = [
    "BranchGraph",
    "GraphEdge",
    "GraphNode",
    "GraphValidationError",
    "validate_graph",
    "build_graph",
    "collapse_merge_points",
    "enumerate_paths",
    "walk_paths",
]
