# backend/app/teams/crewai_outputs.py
"""
Pydantic output models for CrewAI structured output.

Each workflow profile gets a Pydantic model that CrewAI will try to
coerce LLM output into.  When the LLM can't produce valid JSON/Pydantic,
we fall back to raw text.

The ``render_output`` function converts a structured model (or raw text)
back into human-readable chat text with section headings — keeping the
UI appearance consistent with the legacy crew engine.
"""
from __future__ import annotations

from typing import List, Optional, Type

from pydantic import BaseModel, Field


# ── Output schemas (one per workflow profile) ──────────────────────────


class TaskPlannerOutput(BaseModel):
    steps: List[str] = Field(..., description="Ordered actionable steps.")
    details: str = Field(..., description="Expanded explanation, constraints, or budget notes.")
    summary: str = Field(..., description="Short summary (under 60 words).")


class BrainstormOutput(BaseModel):
    ideas: List[str] = Field(..., description="List of creative ideas.")
    evaluation: List[str] = Field(..., description="Pros/cons or ranking for each idea.")
    recommendation: str = Field(..., description="Final recommendation or next step.")


class DraftAndEditOutput(BaseModel):
    outline: List[str] = Field(..., description="Outline bullets or section headings.")
    notes: List[str] = Field(default_factory=list, description="Editing notes or considerations.")
    draft: str = Field(..., description="Full draft content.")


# ── Registry ───────────────────────────────────────────────────────────


_PROFILE_MODELS: dict[str, Type[BaseModel]] = {
    "task_planner_v1": TaskPlannerOutput,
    "brainstorm_v1": BrainstormOutput,
    "draft_and_edit_v1": DraftAndEditOutput,
}


def output_model_for_profile(profile_id: str) -> Optional[Type[BaseModel]]:
    """Return the Pydantic output model for *profile_id*, or ``None``."""
    return _PROFILE_MODELS.get(profile_id)


# ── Renderer (structured model → chat text) ────────────────────────────


def render_output(profile_id: str, obj: BaseModel | str) -> str:
    """Convert a structured Pydantic model (or raw string) into readable chat text.

    We keep section headings so the UI stays visually consistent with the
    legacy crew engine.  If *obj* is already a plain string, return it as-is.
    """
    if isinstance(obj, str):
        return obj.strip()

    if isinstance(obj, TaskPlannerOutput):
        steps = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(obj.steps))
        return f"STEPS:\n{steps}\n\nDETAILS:\n{obj.details}\n\nSUMMARY:\n{obj.summary}".strip()

    if isinstance(obj, BrainstormOutput):
        ideas = "\n".join(f"- {x}" for x in obj.ideas)
        evals = "\n".join(f"- {x}" for x in obj.evaluation)
        return f"IDEAS:\n{ideas}\n\nEVALUATION:\n{evals}\n\nRECOMMENDATION:\n{obj.recommendation}".strip()

    if isinstance(obj, DraftAndEditOutput):
        outline = "\n".join(f"- {x}" for x in obj.outline)
        notes = "\n".join(f"- {x}" for x in obj.notes) if obj.notes else "(none)"
        return f"OUTLINE:\n{outline}\n\nNOTES:\n{notes}\n\nDRAFT:\n{obj.draft}".strip()

    # Unknown model — dump as JSON
    return obj.model_dump_json(indent=2)
