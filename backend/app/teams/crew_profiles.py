# backend/app/teams/crew_profiles.py
"""
Workflow profile registry for CrewAI-style task collaboration mode.

A WorkflowProfile defines:
  - stages: ordered list of workflow stages
  - output_contract: required structured output format
  - stop_rules: convergence / completion stop conditions

Profiles are registered by ID and looked up at runtime.
This module is additive — it does not touch native orchestration.
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
    max_words: int = 250


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

# ── task_planner_v1: "Date Night Planning" / generic task planning ─────
register_profile(
    WorkflowProfile(
        id="task_planner_v1",
        title="Task Planner",
        description="Plan a concrete deliverable with budget, steps, and a short message.",
        stages=[
            StageSpec(
                id="gather_requirements",
                title="Gather Requirements",
                instruction=(
                    "Identify what the user wants. Extract key constraints "
                    "(budget, time, preferences, number of people). "
                    "List open questions. Output a PLAN section with requirements "
                    "and a BUDGET section with preliminary estimates."
                ),
                preferred_tags=["romantic", "companion", "support"],
            ),
            StageSpec(
                id="draft_plan",
                title="Draft Plan",
                instruction=(
                    "Produce a concrete, step-by-step plan addressing every "
                    "requirement. Include specific names (restaurants, venues, "
                    "activities). Output PLAN with numbered steps, BUDGET with "
                    "line items and a total, and MESSAGE with a <=40-word "
                    "personal summary for the user."
                ),
                preferred_tags=["creative", "product", "romantic"],
            ),
            StageSpec(
                id="budget_check",
                title="Budget Check",
                instruction=(
                    "Review the current draft plan and budget. Verify the total "
                    "is within the stated limit. Suggest substitutions if over "
                    "budget. Output PLAN (revised if needed), BUDGET with verified "
                    "totals, and MESSAGE confirming the budget status."
                ),
                preferred_tags=["finance", "analyst"],
            ),
            StageSpec(
                id="write_message",
                title="Write Message",
                instruction=(
                    "Polish the final message to the user. It must be <=40 words, "
                    "warm but specific — mention at least one concrete detail from "
                    "the plan. Output PLAN (final version), BUDGET (final), and "
                    "MESSAGE (polished, <=40 words)."
                ),
                preferred_tags=["creative", "romantic", "companion"],
            ),
            StageSpec(
                id="finalize",
                title="Finalize",
                instruction=(
                    "Review everything. Ensure PLAN is complete, BUDGET total is "
                    "correct, and MESSAGE is <=40 words. If anything is missing, "
                    "fill it in. Output the final PLAN, BUDGET, and MESSAGE."
                ),
                preferred_tags=["product", "secretary"],
            ),
        ],
        output_contract=OutputContract(
            format="structured_text",
            required_sections=["PLAN", "BUDGET", "MESSAGE"],
            max_words=250,
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
                    "Propose 2-3 distinct, creative ideas related to the topic. "
                    "Each idea must be concrete and actionable. "
                    "Output IDEAS section with numbered items, each having a "
                    "one-line description. Output EVALUATION section rating "
                    "feasibility (high/medium/low) for each."
                ),
                preferred_tags=["creative", "product", "research"],
            ),
            StageSpec(
                id="evaluate",
                title="Evaluate & Refine",
                instruction=(
                    "Review the ideas proposed so far. Add pros and cons for each. "
                    "Suggest improvements or combinations. "
                    "Output IDEAS (refined), EVALUATION (with pros/cons), and "
                    "RECOMMENDATION with your top pick and why."
                ),
                preferred_tags=["analyst", "critic", "engineer"],
            ),
            StageSpec(
                id="finalize",
                title="Final Recommendation",
                instruction=(
                    "Synthesize all input into a final recommendation. "
                    "Output IDEAS (final list), EVALUATION (final), and "
                    "RECOMMENDATION (top 1-2 picks with reasoning)."
                ),
                preferred_tags=["product", "mentor"],
            ),
        ],
        output_contract=OutputContract(
            format="structured_text",
            required_sections=["IDEAS", "EVALUATION", "RECOMMENDATION"],
            max_words=300,
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
                    "Output OUTLINE section with numbered sections/subsections, "
                    "NOTES with key points to include, and "
                    "DRAFT with the first paragraph."
                ),
                preferred_tags=["creative", "product", "secretary"],
            ),
            StageSpec(
                id="draft",
                title="Full Draft",
                instruction=(
                    "Expand the outline into a complete draft. "
                    "Output OUTLINE (unchanged), NOTES (updated), and "
                    "DRAFT with the full text."
                ),
                preferred_tags=["creative", "companion", "romantic"],
            ),
            StageSpec(
                id="edit",
                title="Edit & Polish",
                instruction=(
                    "Review the draft for clarity, tone, and completeness. "
                    "Fix errors, improve flow, tighten language. "
                    "Output OUTLINE (final), NOTES (edit summary), and "
                    "DRAFT (polished final version)."
                ),
                preferred_tags=["critic", "mentor", "analyst"],
            ),
        ],
        output_contract=OutputContract(
            format="structured_text",
            required_sections=["OUTLINE", "NOTES", "DRAFT"],
            max_words=400,
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
