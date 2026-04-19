"""
Storyboard planner.

Takes a filled BranchGraph and populates each node's
``storyboard`` metadata dict with shot + interaction-layout specs.
The result is ready to persist via the repo (``storyboard`` column
on ``ix_nodes``).

Idempotent on re-run: nodes that already have a ``storyboard`` key
in their metadata are skipped so designer overrides are preserved.
"""
from __future__ import annotations

from ..branching.graph import BranchGraph, GraphNode
from ..planner.intent import Intent
from .interaction_layout import plan_interaction_layout, to_dict as layout_to_dict
from .shot import select_shot, to_dict as shot_to_dict


def plan_storyboard(graph: BranchGraph, intent: Intent) -> BranchGraph:
    """Attach a storyboard dict + interaction_layout dict to every
    node's metadata. Returns the same graph (mutated in place).

    Structure of the stored dict:
      {
        "shot": { camera, move, mood, ... },
        "interaction": { choices_placement, chat_visible, ... },
      }

    The router that persists the graph maps these into the ix_nodes
    ``storyboard`` + ``interaction_layout`` JSON columns.
    """
    for node in graph.nodes:
        if node.metadata.get("storyboard"):
            continue  # preserve hand-authored storyboard

        duration = int(node.metadata.get("duration_sec") or 5)
        shot = select_shot(node.kind, mode=intent.mode, duration_sec=duration)
        layout = plan_interaction_layout(
            node.kind, mode=intent.mode, branch_count=intent.branch_count,
        )

        node.metadata["storyboard"] = {
            "shot": shot_to_dict(shot),
            "interaction": layout_to_dict(layout),
        }
    return graph
