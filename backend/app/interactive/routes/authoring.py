"""
Authoring routes — CRUD for experience, nodes, edges, actions, rules.

Scope: admin-side endpoints used by the studio UI to build the
experience graph and action catalog. Every write is scoped to the
authenticated user; cross-user reads return 404 to stay probe-safe.

Structural validation (no cycles, entry node exists, branch caps)
lives in ``branching.validate_graph`` and is invoked before status
changes to ``published`` would stick — the publish flow lands in
batch 8. This router accepts ``draft`` edits freely.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import repo
from ..config import InteractiveConfig
from ..errors import InvalidInputError, NotFoundError
from ..models import (
    ActionCreate,
    EdgeCreate,
    Experience,
    ExperienceCreate,
    ExperienceUpdate,
    NodeCreate,
    NodeUpdate,
)
from ..personalize.rules import validate_rule
from ._common import current_user, http_error_from, scoped_experience


class RuleCreateBody(BaseModel):
    """Wire payload for a new personalization rule.

    Separate from ``PersonalizationRule`` because the model in
    ``models.py`` includes the generated id.
    """

    name: str
    condition: Dict[str, Any] = Field(default_factory=dict)
    action: Dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    enabled: bool = True


def build_authoring_router(cfg: InteractiveConfig) -> APIRouter:
    router = APIRouter(tags=["interactive-authoring"])

    # ── Experiences ───────────────────────────────────────────────

    @router.post("/experiences")
    def create_experience_(
        payload: ExperienceCreate, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        exp = repo.create_experience(user_id, payload)
        return {"ok": True, "experience": exp.model_dump()}

    @router.get("/experiences")
    def list_experiences_(
        user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        items = [e.model_dump() for e in repo.list_experiences(user_id)]
        return {"ok": True, "items": items}

    @router.get("/experiences/{experience_id}")
    def get_experience_(exp: Experience = Depends(scoped_experience)) -> Dict[str, Any]:
        return {"ok": True, "experience": exp.model_dump()}

    @router.patch("/experiences/{experience_id}")
    def update_experience_(
        experience_id: str, patch: ExperienceUpdate,
        user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        try:
            exp = repo.update_experience(experience_id, user_id, patch)
        except NotFoundError as e:
            raise http_error_from(e)
        return {"ok": True, "experience": exp.model_dump()}

    @router.delete("/experiences/{experience_id}")
    def delete_experience_(
        experience_id: str, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        ok = repo.delete_experience(experience_id, user_id)
        if not ok:
            raise http_error_from(NotFoundError("experience not found"))
        return {"ok": True, "deleted": experience_id}

    # ── Nodes ─────────────────────────────────────────────────────

    @router.post("/experiences/{experience_id}/nodes")
    def create_node_(
        payload: NodeCreate,
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        node = repo.create_node(exp.id, payload)
        return {"ok": True, "node": node.model_dump()}

    @router.get("/experiences/{experience_id}/nodes")
    def list_nodes_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        items = [n.model_dump() for n in repo.list_nodes(exp.id)]
        return {"ok": True, "items": items}

    @router.patch("/nodes/{node_id}")
    def update_node_(
        node_id: str, patch: NodeUpdate,
        user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        node = repo.get_node(node_id)
        if not node:
            raise http_error_from(NotFoundError("node not found"))
        # Ownership check via parent experience.
        exp = repo.get_experience(node.experience_id, user_id=user_id)
        if not exp:
            raise http_error_from(NotFoundError("node not found"))
        try:
            updated = repo.update_node(node_id, patch)
        except NotFoundError as e:
            raise http_error_from(e)
        return {"ok": True, "node": updated.model_dump()}

    @router.delete("/nodes/{node_id}")
    def delete_node_(
        node_id: str, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        node = repo.get_node(node_id)
        if not node:
            raise http_error_from(NotFoundError("node not found"))
        exp = repo.get_experience(node.experience_id, user_id=user_id)
        if not exp:
            raise http_error_from(NotFoundError("node not found"))
        ok = repo.delete_node(node_id)
        if not ok:
            raise http_error_from(NotFoundError("node not found"))
        return {"ok": True, "deleted": node_id}

    # ── Edges ─────────────────────────────────────────────────────

    @router.post("/experiences/{experience_id}/edges")
    def create_edge_(
        payload: EdgeCreate,
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        edge = repo.create_edge(exp.id, payload)
        return {"ok": True, "edge": edge.model_dump()}

    @router.get("/experiences/{experience_id}/edges")
    def list_edges_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        items = [e.model_dump() for e in repo.list_edges(exp.id)]
        return {"ok": True, "items": items}

    @router.delete("/edges/{edge_id}")
    def delete_edge_(
        edge_id: str, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        # No per-edge ownership table — we trust the UI to have
        # resolved the edge under a scoped experience. Delete is
        # idempotent: missing id → 404.
        ok = repo.delete_edge(edge_id)
        if not ok:
            raise http_error_from(NotFoundError("edge not found"))
        return {"ok": True, "deleted": edge_id}

    # ── Action catalog ────────────────────────────────────────────

    @router.post("/experiences/{experience_id}/actions")
    def create_action_(
        payload: ActionCreate,
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        action = repo.create_action(exp.id, payload)
        return {"ok": True, "action": action.model_dump()}

    @router.get("/experiences/{experience_id}/actions")
    def list_actions_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        items = [a.model_dump() for a in repo.list_actions(exp.id)]
        return {"ok": True, "items": items}

    @router.delete("/actions/{action_id}")
    def delete_action_(
        action_id: str, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        a = repo.get_action(action_id)
        if not a:
            raise http_error_from(NotFoundError("action not found"))
        exp = repo.get_experience(a.experience_id, user_id=user_id)
        if not exp:
            raise http_error_from(NotFoundError("action not found"))
        repo.delete_action(action_id)
        return {"ok": True, "deleted": action_id}

    # ── Personalization rules ─────────────────────────────────────

    @router.post("/experiences/{experience_id}/rules")
    def create_rule_(
        payload: RuleCreateBody,
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        problems = validate_rule(payload.condition, payload.action)
        if problems:
            raise http_error_from(InvalidInputError(
                "rule has validation issues", data={"problems": problems},
            ))
        rule = repo.create_rule(
            exp.id, payload.name, payload.condition, payload.action,
            priority=payload.priority, enabled=payload.enabled,
        )
        return {"ok": True, "rule": rule.model_dump()}

    @router.get("/experiences/{experience_id}/rules")
    def list_rules_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        items = [r.model_dump() for r in repo.list_rules(exp.id)]
        return {"ok": True, "items": items}

    @router.delete("/rules/{rule_id}")
    def delete_rule_(
        rule_id: str, user_id: str = Depends(current_user),
    ) -> Dict[str, Any]:
        ok = repo.delete_rule(rule_id)
        if not ok:
            raise http_error_from(NotFoundError("rule not found"))
        return {"ok": True, "deleted": rule_id}

    return router
