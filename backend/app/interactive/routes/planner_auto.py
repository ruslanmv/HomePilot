"""
Stage-1 auto-planner HTTP surface.

POST /v1/interactive/plan-auto
  body   { "idea": "train new sales reps on pricing" }
  200    {
    "ok": true,
    "source": "llm" | "heuristic",
    "form": { …full WizardForm… },
    "objective": "…",
    "topic": "…",
    "scheme": "xp_level",
    "success_metric": "…",
    "seed_intents": ["greeting", …]
  }

The route is async because autoplan() awaits an LLM call when
the flag is on. Heuristic fallback means the handler never
raises on upstream failures — it always returns a usable form.

Additive: existing /plan (deterministic heuristic preview) and
/seed-graph (graph seeder) keep their shape unchanged. The
frontend's new one-box wizard will prefer /plan-auto; the old
5-step wizard still uses /plan.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import InteractiveConfig
from ..errors import InvalidInputError
from ..planner.autoplan_llm import PlanAutoResult, autoplan
from ._common import current_user, http_error_from


class PlanAutoRequest(BaseModel):
    """Body for POST /plan-auto — one short idea."""

    idea: str


def build_planner_auto_router(cfg: InteractiveConfig) -> APIRouter:
    router = APIRouter(tags=["interactive-planner"])

    @router.post("/plan-auto")
    async def plan_auto(
        req: PlanAutoRequest, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        """Turn a one-sentence idea into a full wizard pre-fill."""
        idea = (req.idea or "").strip()
        if not idea:
            raise http_error_from(InvalidInputError("idea is required"))

        result: PlanAutoResult = await autoplan(idea, cfg=cfg)
        f = result.form
        return {
            "ok": True,
            "source": result.source,
            "form": {
                "title": f.title,
                "prompt": f.prompt,
                "experience_mode": f.experience_mode,
                "policy_profile_id": f.policy_profile_id,
                "audience_role": f.audience_role,
                "audience_level": f.audience_level,
                "audience_language": f.audience_language,
                "audience_locale_hint": f.audience_locale_hint,
                "branch_count": f.branch_count,
                "depth": f.depth,
                "scenes_per_branch": f.scenes_per_branch,
            },
            "objective": result.objective,
            "topic": result.topic,
            "scheme": result.scheme,
            "success_metric": result.success_metric,
            "seed_intents": list(result.seed_intents),
        }

    return router
