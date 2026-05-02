"""
Planner routes — prompt + mode → ``Intent`` + ``PlanningPreset``.

One endpoint, ``POST /plan``. The studio UI calls it to preview
what the planner would produce for a given prompt before
committing — no DB write happens here; the caller decides whether
to create an experience and seed the graph with the returned
intent.

The separate "seed graph" endpoint lives here too: ``POST
/experiences/{id}/seed-graph`` takes an experience already created
via the authoring router and populates nodes/edges deterministically
using ``branching.build_graph``. Idempotent when the experience
already has nodes — returns the existing graph unchanged.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import repo
from ..branching import build_graph, validate_graph
from ..branching.graph import GraphValidationError
from ..config import InteractiveConfig
from ..errors import GraphError, InvalidInputError
from ..models import EdgeCreate, Experience, NodeCreate
from ..planner import list_presets, parse_prompt
from ._common import current_user, http_error_from, scoped_experience


class PlanRequest(BaseModel):
    """Body for POST /plan."""

    prompt: str
    mode: str = "sfw_general"
    audience_hints: Optional[Dict[str, Any]] = Field(default=None)


def build_planner_router(cfg: InteractiveConfig) -> APIRouter:
    router = APIRouter(tags=["interactive-planner"])

    @router.get("/presets")
    def list_presets_(_user: str = Depends(current_user)) -> Dict[str, Any]:
        """List all planning presets the service knows about."""
        items: List[Dict[str, Any]] = []
        for p in list_presets():
            items.append({
                "mode": p.mode,
                "objective_template": p.objective_template,
                "default_branch_count": p.default_branch_count,
                "default_depth": p.default_depth,
                "default_scenes_per_branch": p.default_scenes_per_branch,
                "default_topology": p.default_topology,
                "default_scheme": p.default_scheme,
                "seed_intents": list(p.seed_intents),
            })
        return {"ok": True, "items": items}

    @router.post("/plan")
    def plan_(
        req: PlanRequest, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        """Parse a prompt into an Intent without touching the DB."""
        if not req.prompt.strip():
            raise http_error_from(InvalidInputError("prompt is empty"))
        try:
            intent = parse_prompt(
                req.prompt, cfg=cfg, mode=req.mode,
                audience_hints=req.audience_hints,
            )
        except ValueError as e:
            raise http_error_from(InvalidInputError(str(e)))
        return {
            "ok": True,
            "intent": {
                "prompt": intent.prompt,
                "mode": intent.mode,
                "objective": intent.objective,
                "topic": intent.topic,
                "branch_count": intent.branch_count,
                "depth": intent.depth,
                "scenes_per_branch": intent.scenes_per_branch,
                "success_metric": intent.success_metric,
                "seed_intents": list(intent.seed_intents),
                "scheme": intent.scheme,
                "audience": {
                    "role": intent.audience.role,
                    "level": intent.audience.level,
                    "language": intent.audience.language,
                    "locale_hint": intent.audience.locale_hint,
                    "interests": list(intent.audience.interests),
                },
                "raw_hints": dict(intent.raw_hints),
            },
        }

    @router.post("/experiences/{experience_id}/seed-graph")
    def seed_graph_(
        req: PlanRequest, exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        """Generate and persist a starter graph for this experience.

        Idempotent: if nodes already exist, returns them without
        mutating. Otherwise runs the planner + branching builder
        and inserts nodes + edges in one shot.
        """
        existing_nodes = repo.list_nodes(exp.id)
        if existing_nodes:
            return {
                "ok": True,
                "already_seeded": True,
                "node_count": len(existing_nodes),
                "edge_count": len(repo.list_edges(exp.id)),
            }

        if not req.prompt.strip():
            raise http_error_from(InvalidInputError("prompt is empty"))
        try:
            intent = parse_prompt(
                req.prompt, cfg=cfg, mode=req.mode or exp.experience_mode,
                audience_hints=req.audience_hints,
            )
        except ValueError as e:
            raise http_error_from(InvalidInputError(str(e)))
        graph = build_graph(intent)
        try:
            validate_graph(
                graph,
                max_depth=cfg.max_depth,
                max_nodes=cfg.max_nodes_per_experience,
            )
        except GraphValidationError as e:
            raise http_error_from(GraphError(
                "graph validation failed", data={"issues": list(e.issues)},
            ))

        # Persist nodes, remembering the id mapping so edges can
        # resolve source/target via the builder's internal node keys.
        id_map: Dict[str, str] = {}
        for n in graph.nodes:
            created = repo.create_node(exp.id, NodeCreate(
                kind=n.kind, title=n.title, narration=n.narration,
            ))
            id_map[n.id] = created.id

        for e in graph.edges:
            src = id_map.get(e.from_id)
            dst = id_map.get(e.to_id)
            if not src or not dst:
                continue  # builder should never emit dangling ids
            payload = dict(e.payload or {})
            if e.label and "label" not in payload:
                payload["label"] = e.label
            repo.create_edge(exp.id, EdgeCreate(
                from_node_id=src, to_node_id=dst,
                trigger_kind=e.trigger_kind,
                trigger_payload=payload,
                ordinal=int(e.ordinal or 0),
            ))

        return {
            "ok": True,
            "already_seeded": False,
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
        }

    return router
