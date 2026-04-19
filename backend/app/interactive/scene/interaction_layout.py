"""
Interaction-UI placement per node.

For each node the runtime needs to know:
  - where choice buttons go (bottom-full-bar | bottom-right-stack)
  - where hotspots live (x/y as normalized 0..1 coords if any)
  - whether a text chat box is visible
  - any timer overlay (auto-advance after N seconds)

The frontend reads ``ix_nodes.interaction_layout`` and renders
accordingly. This module writes sensible defaults; designers can
override per-node in the editor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class InteractionLayout:
    # Where choice chips render
    choices_placement: str = "bottom_bar"   # bottom_bar | right_stack | overlay_center
    # Chat input visible for free text?
    chat_visible: bool = True
    # Hotspots — list of {x, y, w, h, edge_id} where coords are 0..1 normalized
    hotspots: List[Dict[str, Any]] = field(default_factory=list)
    # Auto-advance timer (0 = disabled)
    auto_advance_sec: int = 0
    # Show the action catalog right-panel?
    show_action_panel: bool = True
    # Show the progression (XP/mastery) meter?
    show_progress_meter: bool = True


def plan_interaction_layout(
    node_kind: str, *, mode: str, branch_count: int = 0,
) -> InteractionLayout:
    """Choose a sensible default layout for a node.

    Teaching / enterprise modes hide the right-panel action catalog
    to keep the learner focused on the scene's task; social /
    mature modes show it so viewers can use level-gated actions.
    """
    show_panel = mode in ("social_romantic", "mature_gated", "sfw_general")
    show_progress = mode != "sfw_general"  # general doesn't use a scheme by default

    if node_kind == "decision":
        return InteractionLayout(
            choices_placement="bottom_bar",
            chat_visible=False,  # decisions are chip-driven
            auto_advance_sec=0,
            show_action_panel=show_panel,
            show_progress_meter=show_progress,
        )
    if node_kind == "ending":
        return InteractionLayout(
            choices_placement="overlay_center",
            chat_visible=False,
            auto_advance_sec=0,
            show_action_panel=False,
            show_progress_meter=show_progress,
        )
    if node_kind == "assessment":
        return InteractionLayout(
            choices_placement="right_stack",
            chat_visible=True,
            auto_advance_sec=0,
            show_action_panel=False,
            show_progress_meter=show_progress,
        )
    if node_kind == "remediation":
        return InteractionLayout(
            choices_placement="bottom_bar",
            chat_visible=True,
            auto_advance_sec=0,
            show_action_panel=False,
            show_progress_meter=show_progress,
        )
    # default — scene / merge
    return InteractionLayout(
        choices_placement="bottom_bar",
        chat_visible=True,
        auto_advance_sec=0,
        show_action_panel=show_panel,
        show_progress_meter=show_progress,
    )


def to_dict(layout: InteractionLayout) -> Dict[str, Any]:
    return {
        "choices_placement": layout.choices_placement,
        "chat_visible": layout.chat_visible,
        "hotspots": list(layout.hotspots),
        "auto_advance_sec": layout.auto_advance_sec,
        "show_action_panel": layout.show_action_panel,
        "show_progress_meter": layout.show_progress_meter,
    }
