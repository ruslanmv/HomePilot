"""
QA + publish + analytics routes.

Endpoints
---------
POST  /experiences/{id}/qa-run          Run QA checks + persist a report
GET   /experiences/{id}/qa-reports      Fetch the most recent QA report
POST  /experiences/{id}/publish         Publish (or re-publish unchanged)
GET   /experiences/{id}/publications    List published versions
GET   /experiences/{id}/analytics       Experience-wide rollups
GET   /sessions/{sid}/analytics         Per-session summary
GET   /experiences/{id}/manifest        Assembled manifest preview (no DB write)
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from .. import repo
from ..analytics import experience_summary, session_summary
from ..assembly import build_manifest, package_experience
from ..config import InteractiveConfig
from ..errors import NotFoundError
from ..models import Experience
from ..publish import publish
from ..publish.publisher import list_publications
from ..qa import run_qa
from ..qa.report import latest_report
from ._common import current_user, http_error_from, scoped_experience


class PublishRequest(BaseModel):
    channel: str = "web_embed"


def build_lifecycle_router(cfg: InteractiveConfig) -> APIRouter:
    router = APIRouter(tags=["interactive-lifecycle"])

    # ── Assembly preview ──────────────────────────────────────────

    @router.get("/experiences/{experience_id}/manifest")
    def preview_manifest_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        packaged = package_experience(exp)
        return {
            "ok": True,
            "digest": packaged.digest,
            "manifest": packaged.manifest,
        }

    # ── QA ────────────────────────────────────────────────────────

    @router.post("/experiences/{experience_id}/qa-run")
    def run_qa_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        summary = run_qa(exp)
        return {
            "ok": True,
            "verdict": summary.verdict,
            "counts": summary.counts,
            "issues": summary.issues,
            "report_id": summary.report_id,
        }

    @router.get("/experiences/{experience_id}/qa-reports")
    def latest_qa_report_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        report = latest_report(exp.id)
        return {"ok": True, "report": report}

    # ── Publish ───────────────────────────────────────────────────

    @router.post("/experiences/{experience_id}/publish")
    def publish_(
        req: PublishRequest, exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        result = publish(exp, channel=req.channel)
        out: Dict[str, Any] = {
            "ok": True,
            "status": result.status,
            "channel": result.channel,
            "detail": result.detail,
        }
        if result.publication is not None:
            out["publication"] = result.publication.model_dump()
        if result.qa is not None:
            out["qa"] = {
                "verdict": result.qa.verdict,
                "counts": result.qa.counts,
                "issues": result.qa.issues,
            }
        return out

    @router.get("/experiences/{experience_id}/publications")
    def list_publications_(
        channel: str = Query(default=""),
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        ch = channel.strip() or None
        items = [p.model_dump() for p in list_publications(exp.id, channel=ch)]
        return {"ok": True, "items": items}

    # ── Analytics ─────────────────────────────────────────────────

    @router.get("/experiences/{experience_id}/analytics")
    def experience_analytics_(
        exp: Experience = Depends(scoped_experience),
    ) -> Dict[str, Any]:
        s = experience_summary(exp.id)
        return {
            "ok": True,
            "experience_id": s.experience_id,
            "session_count": s.session_count,
            "completed_sessions": s.completed_sessions,
            "completion_rate": s.completion_rate,
            "total_turns": s.total_turns,
            "total_events": s.total_events,
            "popular_actions": list(s.popular_actions),
            "block_rate": s.block_rate,
        }

    @router.get("/sessions/{session_id}/analytics")
    def session_analytics_(
        session_id: str, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        summary = session_summary(session_id)
        if summary is None:
            raise http_error_from(NotFoundError("session not found"))
        return {
            "ok": True,
            "session_id": summary.session_id,
            "experience_id": summary.experience_id,
            "turns": summary.turns,
            "events": summary.events,
            "action_uses": dict(summary.action_uses),
            "decisions": dict(summary.decisions),
            "intents": dict(summary.intents),
            "final_node_id": summary.final_node_id,
            "final_mood": summary.final_mood,
            "final_affinity": summary.final_affinity,
            "progress": {k: dict(v) for k, v in summary.progress.items()},
            "completed": summary.completed,
        }

    return router
