"""
Mode-specific planning presets.

Each preset declares planner defaults for a given experience mode:
  - objective template
  - default branch topology (linear / tree / graph)
  - default node kinds the builder should instantiate
  - default interaction catalog to seed new experiences

Presets are loaded from in-code dicts by default. A later batch
can add YAML overrides at ``planner/presets/*.yaml`` without
changing this file — the same pattern used by ``policy/profiles``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class PlanningPreset:
    """Per-mode planning defaults."""

    mode: str
    objective_template: str = ""
    default_topology: str = "tree"   # linear | tree | graph
    default_node_kinds: List[str] = field(default_factory=list)
    default_branch_count: int = 3
    default_depth: int = 3
    default_scenes_per_branch: int = 3
    seed_intents: List[str] = field(default_factory=list)
    default_scheme: str = "xp_level"


_BUILTIN: Dict[str, PlanningPreset] = {
    "sfw_general": PlanningPreset(
        mode="sfw_general",
        objective_template="Engage the viewer with a short branching story",
        default_topology="tree",
        default_node_kinds=["scene", "decision", "scene", "ending"],
        default_branch_count=2,
        default_depth=3,
        default_scenes_per_branch=2,
        seed_intents=["greeting", "continue", "choose"],
        default_scheme="xp_level",
    ),
    "sfw_education": PlanningPreset(
        mode="sfw_education",
        objective_template="Teach {topic} through interactive scenarios",
        default_topology="tree",
        default_node_kinds=[
            "scene", "assessment", "remediation", "scene", "ending",
        ],
        default_branch_count=3,
        default_depth=4,
        default_scenes_per_branch=3,
        seed_intents=[
            "greeting", "answer_attempt", "request_hint",
            "request_example", "skip_topic",
        ],
        default_scheme="mastery",
    ),
    "language_learning": PlanningPreset(
        mode="language_learning",
        objective_template="Teach CEFR {level} vocabulary + basic dialogue",
        default_topology="tree",
        default_node_kinds=[
            "scene", "assessment", "remediation", "scene", "ending",
        ],
        default_branch_count=4,
        default_depth=4,
        default_scenes_per_branch=2,
        seed_intents=[
            "greeting", "pronounce_request", "request_translation",
            "answer_attempt", "request_hint", "switch_language",
        ],
        default_scheme="cefr",
    ),
    "enterprise_training": PlanningPreset(
        mode="enterprise_training",
        objective_template="Train employees on {topic} using scenario-based learning",
        default_topology="graph",
        default_node_kinds=[
            "scene", "assessment", "remediation", "scene",
            "scene", "assessment", "ending",
        ],
        default_branch_count=3,
        default_depth=5,
        default_scenes_per_branch=3,
        seed_intents=[
            "greeting", "quiz_response", "request_hint", "answer_attempt",
        ],
        default_scheme="certification",
    ),
    "social_romantic": PlanningPreset(
        mode="social_romantic",
        objective_template="Build rapport through a branching conversation",
        default_topology="tree",
        default_node_kinds=["scene", "decision", "scene", "ending"],
        default_branch_count=3,
        default_depth=4,
        default_scenes_per_branch=2,
        seed_intents=[
            "greeting", "flirt", "compliment", "tease", "ask_personal",
        ],
        default_scheme="affinity_tier",
    ),
    "mature_gated": PlanningPreset(
        mode="mature_gated",
        objective_template="Build tension through escalating interaction tiers",
        default_topology="tree",
        default_node_kinds=["scene", "decision", "scene", "scene", "ending"],
        default_branch_count=3,
        default_depth=5,
        default_scenes_per_branch=2,
        seed_intents=[
            "greeting", "flirt", "tease", "compliment",
            "request_action", "explicit_request",
        ],
        default_scheme="xp_level",
    ),
}


def get_preset(mode: str) -> Optional[PlanningPreset]:
    return _BUILTIN.get(mode)


def list_presets() -> List[PlanningPreset]:
    return list(_BUILTIN.values())
