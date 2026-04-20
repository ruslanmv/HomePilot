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

POST /v1/interactive/plan-auto/stream (REV-5)
  body   { "idea": "…" }
  200    text/event-stream.
         Emits one SSE frame per WorkflowEvent from the runner,
         then a final ``{"type":"result", "payload": {…}}`` frame
         with the same shape as POST /plan-auto, then
         ``{"type":"done"}``. On abort the stream emits
         ``{"type":"error", "payload":{…}}`` and terminates.

The non-streaming route is async because autoplan() awaits an
LLM call when the flag is on. Heuristic fallback means the
handler never raises on upstream failures — it always returns
a usable form.

Additive: existing /plan (deterministic heuristic preview) and
/seed-graph (graph seeder) keep their shape unchanged. The
frontend's new one-box wizard will prefer /plan-auto; the old
5-step wizard still uses /plan.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..config import InteractiveConfig
from ..errors import InvalidInputError
from ..planner.autoplan_llm import PlanAutoResult, autoplan
from ._common import current_user, http_error_from


log = logging.getLogger(__name__)


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
        return _serialise_plan(result)

    @router.post("/plan-auto/stream")
    async def plan_auto_stream(
        req: PlanAutoRequest, _user: str = Depends(current_user),
    ) -> StreamingResponse:
        """SSE stream of workflow events for the stage-1 autoplan.

        Always runs the multi-prompt workflow path (ignores the
        ``INTERACTIVE_AUTOPLAN_WORKFLOW`` flag) so clients that
        opt into streaming get the new progress surface
        regardless of the global default. The same result shape
        as POST /plan-auto is emitted in a final ``result``
        frame, so frontends can drop in without an extra call.
        """
        idea = (req.idea or "").strip()
        if not idea:
            raise http_error_from(InvalidInputError("idea is required"))

        return StreamingResponse(
            _autoplan_event_stream(idea, cfg=cfg),
            media_type="text/event-stream",
            headers={
                # Disable intermediary buffering so events flush
                # promptly; the dev nginx config already respects
                # X-Accel-Buffering=no.
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return router


# ── SSE plumbing ───────────────────────────────────────────────

def _serialise_plan(result: PlanAutoResult) -> Dict[str, Any]:
    """The JSON payload shared by POST /plan-auto and the final
    ``result`` frame of the stream endpoint."""
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


async def _autoplan_event_stream(
    idea: str, *, cfg: InteractiveConfig,
) -> AsyncGenerator[bytes, None]:
    """Run the stage-1 workflow and yield SSE frames.

    The workflow runner emits events synchronously through a hook
    callback; we bridge into an asyncio.Queue so the generator
    can ``await`` and cooperatively yield frames as they arrive.
    """
    from ..planner.autoplan_workflow import (
        run_autoplan_workflow, workflow_to_plan_result,
    )
    from ..planner.autoplan_llm import _heuristic_result  # late

    queue: "asyncio.Queue[Optional[Dict[str, Any]]]" = asyncio.Queue()

    def _hook(ev) -> None:  # noqa: ANN001 — WorkflowEvent typed up the stack
        try:
            queue.put_nowait({
                "type": ev.kind,
                "ts_ms": ev.ts_ms,
                "payload": dict(ev.payload or {}),
            })
        except Exception:  # noqa: BLE001
            log.exception("sse event enqueue failed")

    async def _runner_task():
        try:
            return await run_autoplan_workflow(idea, cfg=cfg, on_event=_hook)
        finally:
            # Sentinel terminates the draining loop below.
            await queue.put(None)

    task = asyncio.create_task(_runner_task())

    # Drain events as they arrive.
    while True:
        item = await queue.get()
        if item is None:
            break
        yield _sse_frame(item).encode("utf-8")

    # Resolve the runner result.
    try:
        wf_result = await task
    except Exception as exc:  # noqa: BLE001
        log.exception("autoplan stream crashed")
        yield _sse_frame({
            "type": "error",
            "payload": {
                "reason": f"{exc.__class__.__name__}: {str(exc)[:200]}",
            },
        }).encode("utf-8")
        yield _sse_frame({"type": "done"}).encode("utf-8")
        return

    plan = workflow_to_plan_result(wf_result, cfg=cfg) if wf_result else None
    if plan is None:
        # Workflow aborted — fall back to the heuristic path so the
        # client still gets a usable form. This matches POST /plan-auto
        # semantics and keeps the UX consistent across both routes.
        plan = _heuristic_result(idea, cfg)
        yield _sse_frame({
            "type": "fallback",
            "payload": {
                "reason": (wf_result.error if wf_result else "workflow failed")
                          or "workflow aborted",
                "source": "heuristic",
            },
        }).encode("utf-8")

    yield _sse_frame({
        "type": "result",
        "payload": _serialise_plan(plan),
    }).encode("utf-8")
    yield _sse_frame({"type": "done"}).encode("utf-8")


def _sse_frame(obj: Dict[str, Any]) -> str:
    """Render one SSE frame. Each frame is a ``data:`` line plus
    a blank line terminator — the minimum shape EventSource
    expects."""
    return f"data: {json.dumps(obj, separators=(',', ':'))}\n\n"
