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
from ..qa import run_qa
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

        # Guarantee a baseline action so every generated project is
        # actually interactive. If the LLM / heuristic already
        # produced ≥1 action (likely via decision options), we keep
        # them and add a 'Continue' as a safe default.
        actions = list(plan.actions)
        if not actions:
            actions = list(_default_actions())
        _persist_actions(exp.id, actions)

        # Seed one gentle personalization rule so the editor's
        # Rules tab isn't stranded empty. Priority 100 + enabled so
        # it fires at runtime; condition is permissive enough that
        # viewers with no measured affinity still match.
        rule_count = _persist_default_rule(exp.id)

        # Auto-run QA so authors see a verdict banner on landing
        # in the editor, instead of an empty 'Run QA' page.
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

    return router


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
