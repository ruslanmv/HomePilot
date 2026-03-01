# backend/app/teams/crew_profiles.py
"""
Workflow profile registry for CrewAI-style task collaboration mode.

A WorkflowProfile defines:
  - stages: ordered list of workflow stages
  - output_contract: required structured output format
  - stop_rules: convergence / completion stop conditions

Profiles are registered by ID and looked up at runtime.
This module is additive — it does not touch native orchestration.

IMPORTANT: Profiles are topic-generic. The stage instructions reference
"the topic" rather than hardcoding a specific use-case. The crew engine
fills in the actual topic from room.topic / room.description.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class StageSpec:
    """One workflow stage."""

    id: str
    title: str
    instruction: str
    preferred_tags: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class OutputContract:
    """Required structured output format for each step."""

    format: str = "structured_text"
    required_sections: List[str] = field(default_factory=list)
    max_words: int = 75


@dataclass(frozen=True)
class StopRules:
    """Convergence / completion stop conditions."""

    stop_when_complete: bool = True
    stop_on_low_novelty: bool = True
    low_novelty_window: int = 4
    low_novelty_threshold: float = 0.25
    max_no_progress_steps: int = 3


@dataclass(frozen=True)
class WorkflowProfile:
    """Complete workflow profile definition."""

    id: str
    title: str
    description: str
    stages: List[StageSpec]
    output_contract: OutputContract
    stop_rules: StopRules


# ── Profile registry ─────────────────────────────────────────────────────

_PROFILES: Dict[str, WorkflowProfile] = {}


def register_profile(profile: WorkflowProfile) -> None:
    """Register a workflow profile by ID."""
    _PROFILES[profile.id] = profile


def get_profile(profile_id: str) -> Optional[WorkflowProfile]:
    """Look up a registered profile. Returns None if not found."""
    return _PROFILES.get(profile_id)


def list_profiles() -> List[Dict[str, Any]]:
    """Return summary list of all registered profiles."""
    return [
        {
            "id": p.id,
            "title": p.title,
            "description": p.description,
            "stages": [s.id for s in p.stages],
        }
        for p in _PROFILES.values()
    ]


# ── Built-in profiles ────────────────────────────────────────────────────

# ── task_planner_v1: generic task planning (works for any topic) ──────
register_profile(
    WorkflowProfile(
        id="task_planner_v1",
        title="Task Planner",
        description="Plan a concrete deliverable with steps, details, and a summary.",
        stages=[
            StageSpec(
                id="gather_requirements",
                title="Gather Requirements",
                instruction=(
                    "Discuss what needs to be done for this topic. "
                    "Share your ideas, ask questions, and identify key requirements. "
                    "Be specific and concrete — mention real details."
                ),
                preferred_tags=["analyst", "product", "support", "companion"],
            ),
            StageSpec(
                id="draft_plan",
                title="Draft Plan",
                instruction=(
                    "Propose a concrete plan based on what's been discussed. "
                    "Include specific steps, quantities, and details. "
                    "Build on ideas from the previous discussion."
                ),
                preferred_tags=["creative", "product", "engineer", "companion"],
            ),
            StageSpec(
                id="review",
                title="Review & Refine",
                instruction=(
                    "Review the plan so far. What works? What's missing? "
                    "Suggest specific improvements and be constructive."
                ),
                preferred_tags=["critic", "analyst", "mentor"],
            ),
            StageSpec(
                id="finalize",
                title="Finalize",
                instruction=(
                    "Wrap up with a clear, actionable summary. "
                    "Make sure the key steps are concrete and doable."
                ),
                preferred_tags=["product", "secretary", "companion"],
            ),
        ],
        output_contract=OutputContract(
            format="structured_text",
            required_sections=[],
            max_words=75,
        ),
        stop_rules=StopRules(
            stop_when_complete=True,
            stop_on_low_novelty=True,
            low_novelty_window=4,
            low_novelty_threshold=0.25,
            max_no_progress_steps=3,
        ),
    )
)

# ── brainstorm_v1: open-ended ideation ────────────────────────────────
register_profile(
    WorkflowProfile(
        id="brainstorm_v1",
        title="Brainstorm",
        description="Generate diverse ideas around a topic with pros/cons.",
        stages=[
            StageSpec(
                id="ideate",
                title="Generate Ideas",
                instruction=(
                    "Propose 2-3 creative, concrete ideas related to the topic. "
                    "Explain why each idea is interesting or useful."
                ),
                preferred_tags=["creative", "product", "research"],
            ),
            StageSpec(
                id="evaluate",
                title="Evaluate & Refine",
                instruction=(
                    "Review the ideas so far. Add pros and cons for each. "
                    "Suggest improvements or combinations. Pick your favorite."
                ),
                preferred_tags=["analyst", "critic", "engineer"],
            ),
            StageSpec(
                id="finalize",
                title="Final Recommendation",
                instruction=(
                    "Give your final recommendation. Pick the best 1-2 ideas "
                    "and explain why, with a clear next step."
                ),
                preferred_tags=["product", "mentor"],
            ),
        ],
        output_contract=OutputContract(
            format="structured_text",
            required_sections=[],
            max_words=75,
        ),
        stop_rules=StopRules(
            stop_when_complete=True,
            stop_on_low_novelty=True,
            low_novelty_window=3,
            low_novelty_threshold=0.30,
            max_no_progress_steps=3,
        ),
    )
)

# ── draft_and_edit_v1: collaborative writing ──────────────────────────
register_profile(
    WorkflowProfile(
        id="draft_and_edit_v1",
        title="Draft & Edit",
        description="Collaboratively draft and refine written content.",
        stages=[
            StageSpec(
                id="outline",
                title="Outline",
                instruction=(
                    "Create a structured outline for the requested content. "
                    "Explain your approach and list key sections."
                ),
                preferred_tags=["creative", "product", "secretary"],
            ),
            StageSpec(
                id="draft",
                title="Full Draft",
                instruction=(
                    "Write the actual content based on the outline. "
                    "Be concrete — write the real text, not just a plan."
                ),
                preferred_tags=["creative", "companion", "writer"],
            ),
            StageSpec(
                id="edit",
                title="Edit & Polish",
                instruction=(
                    "Review the draft for clarity and tone. "
                    "Fix errors, improve flow, and tighten the language."
                ),
                preferred_tags=["critic", "mentor", "analyst"],
            ),
        ],
        output_contract=OutputContract(
            format="structured_text",
            required_sections=[],
            max_words=100,
        ),
        stop_rules=StopRules(
            stop_when_complete=True,
            stop_on_low_novelty=True,
            low_novelty_window=3,
            low_novelty_threshold=0.30,
            max_no_progress_steps=2,
        ),
    )
)
