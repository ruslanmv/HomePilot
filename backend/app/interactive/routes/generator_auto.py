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

Idempotent: if the experience already has any nodes, the route
returns ``already_generated: true`` without mutating anything.
Owners can re-run generation by clearing the graph via the
authoring API first.

Non-destructive: the existing ``/seed-graph`` authoring route is
unchanged — it's the deterministic path the 5-step wizard uses.
``/auto-generate`` is the one-shot Stage-2 path the new one-box
wizard uses after Stage-1's ``/plan-auto`` populated the project.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from .. import repo
from ..config import InteractiveConfig
from ..errors import CapacityError
from ..models import ActionCreate, EdgeCreate, Experience, NodeCreate
from ..planner.autogen_llm import (
    ActionSpec, EdgeSpec, GraphPlan, NodeSpec, generate_graph,
)
from ._common import http_error_from, scoped_experience


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
        existing = repo.list_nodes(exp.id)
        if existing:
            existing_edges = repo.list_edges(exp.id)
            existing_actions = repo.list_actions(exp.id)
            return {
                "ok": True,
                "source": "existing",
                "already_generated": True,
                "node_count": len(existing),
                "edge_count": len(existing_edges),
                "action_count": len(existing_actions),
            }

        plan: GraphPlan = await generate_graph(exp, cfg=cfg)
        if len(plan.nodes) > cfg.max_nodes_per_experience:
            raise http_error_from(CapacityError(
                "generated graph exceeds node cap",
                data={"nodes": len(plan.nodes), "cap": cfg.max_nodes_per_experience},
            ))

        # Persist: nodes first, remember local→persisted id map,
        # then edges + actions that reference it.
        id_map = _persist_nodes(exp.id, plan.nodes)
        _persist_edges(exp.id, plan.edges, id_map)
        _persist_actions(exp.id, plan.actions)

        return {
            "ok": True,
            "source": plan.source,
            "already_generated": False,
            "node_count": len(plan.nodes),
            "edge_count": len(plan.edges),
            "action_count": len(plan.actions),
            "warnings": list(plan.warnings),
        }

    return router


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
