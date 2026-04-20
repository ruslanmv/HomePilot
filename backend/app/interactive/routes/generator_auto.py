"""
Stage-2 auto-generator HTTP surface.

POST /v1/interactive/experiences/{id}/auto-generate
  body   {}        (may be extended with overrides later)
  200    {
    "ok": true,
    "source": "llm" | "heuristic",
    "already_generated": false,
    "node_count": 9,
    "edge_count": 11,
    "action_count": 4
  }

GET /v1/interactive/experiences/{id}/auto-generate/stream (PIPE-2)
  200    text/event-stream.
         Emits one SSE frame per generation phase (generating_graph,
         persisting_nodes, persisting_edges, persisting_actions,
         seeding_rule, running_qa) then a final ``result`` frame
         with the same payload as POST /auto-generate, then
         ``done``. Lets the wizard spinner show real progress
         instead of a timer-driven animation.

Idempotent: if the experience already has any nodes, both routes
return ``already_generated: true`` without mutating anything.
Owners can re-run generation by clearing the graph via the
authoring API first.

Non-destructive: the existing ``/seed-graph`` authoring route is
unchanged — it's the deterministic path the 5-step wizard uses.
``/auto-generate`` is the one-shot Stage-2 path the new one-box
wizard uses after Stage-1's ``/plan-auto`` populated the project.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncGenerator, Awaitable, Callable, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from .. import repo
from ..config import InteractiveConfig
from ..errors import CapacityError
from ..models import ActionCreate, EdgeCreate, Experience, NodeCreate
from ..planner.autogen_llm import (
    ActionSpec, EdgeSpec, GraphPlan, NodeSpec, generate_graph,
)
from ..qa import run_qa
from ._common import http_error_from, scoped_experience


log = logging.getLogger(__name__)


# Event callback used by the shared auto-generate body. Accepts
# the event kind (plain string) + a small JSON-able payload dict.
EventHook = Callable[[str, Dict[str, Any]], None]


def build_generator_auto_router(cfg: InteractiveConfig) -> APIRouter:
    router = APIRouter(tags=["interactive-planner"])

    @router.post("/experiences/{experience_id}/auto-generate")
    async def auto_generate(
        experience_id: str,  # noqa: ARG001 — scoped_experience consumes it
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        """Generate + persist a full scene graph from the experience
        brief. Idempotent on repeat calls while the graph exists.
        """
        return await _run_auto_generate(exp, cfg, on_event=_noop_hook)

    @router.get("/experiences/{experience_id}/auto-generate/stream")
    async def auto_generate_stream(
        experience_id: str,  # noqa: ARG001 — scoped_experience consumes it
        exp: Experience = Depends(scoped_experience),
    ) -> StreamingResponse:
        """SSE stream mirroring the non-streaming route's result
        shape. Emits one frame per generation phase so the wizard
        spinner can surface real progress to the author.
        """
        return StreamingResponse(
            _auto_generate_event_stream(exp, cfg),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return router


def _noop_hook(_kind: str, _payload: Dict[str, Any]) -> None:
    """Default event hook for the non-streaming path — the HTTP
    response already carries the final result, so the hook has
    nothing to do."""
    return None


# ── Shared body ────────────────────────────────────────────────

async def _run_auto_generate(
    exp: Experience, cfg: InteractiveConfig,
    *, on_event: EventHook,
) -> Dict[str, Any]:
    """End-to-end stage-2 generation body shared by both the POST
    and streaming routes. Emits phase events through ``on_event``
    so the SSE handler can forward them to the client.

    Raises the same typed HTTPException the POST route raised
    before — the streaming path converts that to an ``error``
    frame on its side.
    """
    on_event("started", {"experience_id": exp.id})

    existing = repo.list_nodes(exp.id)
    if existing:
        existing_edges = repo.list_edges(exp.id)
        existing_actions = repo.list_actions(exp.id)
        payload = {
            "ok": True,
            "source": "existing",
            "already_generated": True,
            "node_count": len(existing),
            "edge_count": len(existing_edges),
            "action_count": len(existing_actions),
        }
        on_event("already_generated", {
            "node_count": len(existing),
            "edge_count": len(existing_edges),
            "action_count": len(existing_actions),
        })
        return payload

    on_event("generating_graph", {})
    plan: GraphPlan = await generate_graph(exp, cfg=cfg)
    on_event("graph_generated", {
        "source": plan.source,
        "node_count": len(plan.nodes),
        "edge_count": len(plan.edges),
    })

    if len(plan.nodes) > cfg.max_nodes_per_experience:
        raise http_error_from(CapacityError(
            "generated graph exceeds node cap",
            data={"nodes": len(plan.nodes), "cap": cfg.max_nodes_per_experience},
        ))

    on_event("persisting_nodes", {"count": len(plan.nodes)})
    id_map = _persist_nodes(exp.id, plan.nodes)

    on_event("persisting_edges", {"count": len(plan.edges)})
    _persist_edges(exp.id, plan.edges, id_map)

    actions = list(plan.actions)
    if not actions:
        actions = list(_default_actions())
    on_event("persisting_actions", {"count": len(actions)})
    _persist_actions(exp.id, actions)

    on_event("seeding_rule", {})
    rule_count = _persist_default_rule(exp.id)

    on_event("running_qa", {})
    qa_verdict = ""
    qa_issues: List[Dict[str, Any]] = []
    qa_counts: Dict[str, int] = {}
    try:
        summary = run_qa(exp)
        qa_verdict = summary.verdict
        qa_issues = list(summary.issues)
        qa_counts = dict(summary.counts)
    except Exception:  # noqa: BLE001 — QA is best-effort
        qa_verdict = "skipped"
    on_event("qa_done", {"verdict": qa_verdict, "counts": qa_counts})

    return {
        "ok": True,
        "source": plan.source,
        "already_generated": False,
        "node_count": len(plan.nodes),
        "edge_count": len(plan.edges),
        "action_count": len(actions),
        "rule_count": rule_count,
        "qa": {
            "verdict": qa_verdict,
            "counts": qa_counts,
            "issues": qa_issues,
        },
        "warnings": list(plan.warnings),
    }


# ── SSE plumbing ──────────────────────────────────────────────

async def _auto_generate_event_stream(
    exp: Experience, cfg: InteractiveConfig,
) -> AsyncGenerator[bytes, None]:
    """Run the shared body and yield SSE frames per phase event.

    Bridges the sync ``on_event`` callback to an asyncio queue so
    the generator can ``await`` and yield frames as phases tick.
    """
    queue: "asyncio.Queue[Optional[Dict[str, Any]]]" = asyncio.Queue()

    def _hook(kind: str, payload: Dict[str, Any]) -> None:
        try:
            queue.put_nowait({"type": kind, "payload": dict(payload or {})})
        except Exception:  # noqa: BLE001
            log.exception("auto-generate sse enqueue failed")

    async def _task() -> Optional[Dict[str, Any]]:
        try:
            return await _run_auto_generate(exp, cfg, on_event=_hook)
        finally:
            await queue.put(None)

    runner = asyncio.create_task(_task())

    # Drain phase events.
    while True:
        item = await queue.get()
        if item is None:
            break
        yield _sse_frame(item).encode("utf-8")

    # Resolve the result (or surface the error).
    try:
        final = await runner
    except Exception as exc:  # noqa: BLE001
        log.exception("auto-generate stream crashed")
        yield _sse_frame({
            "type": "error",
            "payload": {
                "reason": f"{exc.__class__.__name__}: {str(exc)[:200]}",
            },
        }).encode("utf-8")
        yield _sse_frame({"type": "done"}).encode("utf-8")
        return

    if final is not None:
        yield _sse_frame({"type": "result", "payload": final}).encode("utf-8")
    yield _sse_frame({"type": "done"}).encode("utf-8")


def _sse_frame(obj: Dict[str, Any]) -> str:
    return f"data: {json.dumps(obj, separators=(',', ':'))}\n\n"


def _default_actions() -> List[ActionSpec]:
    """Minimal action set so every generated project can be played."""
    return [
        ActionSpec(label="Continue", intent_code="continue", xp_award=5),
        ActionSpec(label="Ask for a hint", intent_code="request_hint", xp_award=3),
    ]


def _persist_default_rule(experience_id: str) -> int:
    """Seed one personalization rule so the feature is visibly
    wired on first open. Warm-up rule: when affinity is low (a
    fresh viewer), prefer a warm tone so the first scene lands
    friendly. Returns the rule count actually created (always 1,
    but pattern-compatible with future multi-rule seeding).
    """
    try:
        repo.create_rule(
            experience_id,
            name="Warm up new viewers",
            condition={"max_affinity": 0.3},
            action={"prefer_tone": "warm", "bump_affinity": 0.01},
            priority=100,
            enabled=True,
        )
        return 1
    except Exception:  # noqa: BLE001 — rule seeding is best-effort
        return 0


# ── Persistence helpers ───────────────────────────────────────

def _persist_nodes(
    experience_id: str, nodes: List[NodeSpec],
) -> Dict[str, str]:
    id_map: Dict[str, str] = {}
    for n in nodes:
        created = repo.create_node(experience_id, NodeCreate(
            kind=n.kind, title=n.title, narration=n.narration,
        ))
        id_map[n.local_id] = created.id
    return id_map


def _persist_edges(
    experience_id: str, edges: List[EdgeSpec], id_map: Dict[str, str],
) -> None:
    for e in edges:
        src = id_map.get(e.from_local_id)
        dst = id_map.get(e.to_local_id)
        if not src or not dst:
            continue  # autogen already dedup'd, but be safe
        trigger_payload: Dict[str, Any] = {}
        if e.label:
            trigger_payload["label"] = e.label
        repo.create_edge(experience_id, EdgeCreate(
            from_node_id=src, to_node_id=dst,
            trigger_kind=e.trigger_kind,
            trigger_payload=trigger_payload,
            ordinal=int(e.ordinal or 0),
        ))


def _persist_actions(
    experience_id: str, actions: List[ActionSpec],
) -> None:
    for i, a in enumerate(actions):
        repo.create_action(experience_id, ActionCreate(
            label=a.label,
            intent_code=a.intent_code or "choice",
            required_level=1,
            required_scheme="xp_level",
            required_metric_key="level",
            xp_award=int(a.xp_award or 0),
            cooldown_sec=0,
            ordinal=i,
        ))
