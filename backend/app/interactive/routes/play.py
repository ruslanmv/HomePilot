"""
Play (runtime) routes — session lifecycle + action catalog + turn resolution.

Endpoints
---------
POST   /play/sessions                    Start a new viewer session
GET    /play/sessions/{sid}              Fetch current session + runtime state
GET    /play/sessions/{sid}/catalog      Action catalog with per-action unlock state
POST   /play/sessions/{sid}/resolve      Resolve one viewer turn
GET    /play/sessions/{sid}/progress     Progress snapshot + level description
POST   /play/sessions/{sid}/end          Mark session completed

The catalog endpoint is what the studio UI + live-play page uses to
render level-gated action buttons with a lock icon + reason
("Level 3 required").

Unlike the authoring router, ``/play`` allows anonymous viewers in
the single-user-install case (the default user from the auth
resolver still works), but still 404s if the experience isn't
published or doesn't belong to any reachable user.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .. import repo
from ..config import InteractiveConfig
from ..errors import InvalidInputError, NotFoundError
from ..interaction.router import ActionPayload, resolve_next
from ..interaction.state import build_runtime_state
from ..interaction.types import TransitionKind
from ..playback.persona_assets import resolve_persona_assets
from ..progression import describe_level, is_action_unlocked
from ._common import current_user, http_error_from
from ._persona_opening import _persona_fields, maybe_generate_opening_turn


class SessionStartRequest(BaseModel):
    experience_id: str
    viewer_ref: str = ""
    language: str = "en"
    personalization: Dict[str, Any] = Field(default_factory=dict)


class TurnRequest(BaseModel):
    """Either action_id or free_text — or both if the action has a
    free-text component. The runtime prefers action_id."""

    action_id: str = ""
    free_text: str = ""
    viewer_region: str = ""
    client_ts_ms: int = 0


def _require_session(sid: str):
    sess = repo.get_session(sid)
    if not sess:
        raise http_error_from(NotFoundError("session not found"))
    return sess


def _require_experience_for_session(sess) -> Any:
    exp = repo.get_experience(sess.experience_id)
    if not exp:
        raise http_error_from(NotFoundError("experience not found"))
    return exp


def build_play_router(cfg: InteractiveConfig) -> APIRouter:
    router = APIRouter(tags=["interactive-play"])

    @router.post("/play/sessions")
    def start_session_(
        req: SessionStartRequest, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        exp = repo.get_experience(req.experience_id)
        if not exp:
            raise http_error_from(NotFoundError("experience not found"))
        sess = repo.create_session(
            exp.id, viewer_ref=req.viewer_ref or "anon",
            language=req.language, personalization=req.personalization,
        )
        # Default current node = entry scene (first node of kind='scene').
        nodes = repo.list_nodes(exp.id)
        entry = next((n for n in nodes if n.kind == "scene"), None)
        if entry:
            repo.set_session_current_node(sess.id, entry.id)
            sess = repo.get_session(sess.id)
        repo.append_event(sess.id, "session_started")
        # Persona Live Play: generate the in-character opening bubble
        # so the overlay has something to show before the viewer types.
        # Non-blocking by contract — any failure logs and returns cleanly
        # because losing the greeting must never block the Play button.
        opening = maybe_generate_opening_turn(exp, sess)
        payload: Dict[str, Any] = {"ok": True, "session": sess.model_dump()}
        if opening:
            payload["opening_turn"] = opening
        # Stage hint — the persona's canonical portrait + the wizard-
        # stamped render_media_type. The frontend uses these so the
        # VideoStage shows the persona's actual photo (not a black
        # backdrop) the moment Play opens, regardless of whether the
        # opening-turn LLM render succeeded. In image mode the stage
        # stays a still photo between turns; in video mode each turn
        # produces an img2vid clip derived from the same portrait.
        persona_pid, _ = _persona_fields(exp)
        if persona_pid:
            assets = resolve_persona_assets(persona_pid)
            if assets:
                payload["persona_portrait_url"] = assets.portrait_url
        ap = getattr(exp, "audience_profile", None) or {}
        if isinstance(ap, dict):
            media_type = str(ap.get("render_media_type") or "").strip().lower()
            if media_type in ("image", "video"):
                payload["render_media_type"] = media_type
        return payload

    @router.get("/play/sessions/{session_id}")
    def get_session_(
        session_id: str, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        sess = _require_session(session_id)
        state = build_runtime_state(session_id)
        state_dump: Dict[str, Any] = {}
        if state is not None:
            state_dump = {
                "current_node_id": state.current_node_id,
                "language": state.language,
                "mood": state.character_mood,
                "affinity_score": state.affinity_score,
                "outfit_state": dict(state.outfit_state),
                "progress": {k: dict(v) for k, v in state.progress.items()},
                "uses_by_action": dict(state.uses_by_action),
                "recent_flags": list(state.recent_flags),
            }
        return {
            "ok": True,
            "session": sess.model_dump(),
            "state": state_dump,
        }

    @router.get("/play/sessions/{session_id}/catalog")
    def get_catalog_(
        session_id: str, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        sess = _require_session(session_id)
        actions = repo.list_actions(sess.experience_id)
        state = build_runtime_state(session_id)
        progress: Dict[str, Dict[str, float]] = state.progress if state else {}
        items: List[Dict[str, Any]] = []
        for a in actions:
            unlocked, reason = is_action_unlocked(a, progress)
            items.append({
                "id": a.id,
                "label": a.label,
                "intent_code": a.intent_code,
                "required_level": a.required_level,
                "required_scheme": a.required_scheme,
                "cooldown_sec": a.cooldown_sec,
                "xp_award": a.xp_award,
                "ordinal": a.ordinal,
                "unlocked": unlocked,
                "lock_reason": reason,
            })
        return {"ok": True, "items": items}

    @router.get("/play/sessions/{session_id}/progress")
    def get_progress_(
        session_id: str, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        sess = _require_session(session_id)
        state = build_runtime_state(session_id)
        if state is None:
            raise http_error_from(NotFoundError("session state missing"))
        # Surface a LevelDescription for each scheme the session has
        # any progress in — the studio meters render from here.
        descriptions: Dict[str, Dict[str, Any]] = {}
        for scheme, metrics in state.progress.items():
            d = describe_level(scheme, metrics)
            descriptions[scheme] = {
                "level": d.level,
                "label": d.label,
                "display": d.display,
                "current_value": d.current_value,
                "next_threshold": d.next_threshold,
            }
        return {
            "ok": True,
            "progress": {k: dict(v) for k, v in state.progress.items()},
            "descriptions": descriptions,
            "mood": state.character_mood,
            "affinity_score": state.affinity_score,
        }

    @router.post("/play/sessions/{session_id}/resolve")
    def resolve_(
        session_id: str, req: TurnRequest, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        if not (req.action_id or req.free_text):
            raise http_error_from(InvalidInputError(
                "either action_id or free_text is required",
            ))
        sess = _require_session(session_id)
        exp = _require_experience_for_session(sess)

        action = repo.get_action(req.action_id) if req.action_id else None
        if req.action_id and not action:
            raise http_error_from(NotFoundError("action not found"))
        if action and action.experience_id != exp.id:
            raise http_error_from(NotFoundError("action not in this experience"))

        resolved = resolve_next(
            cfg, exp, sess,
            ActionPayload(
                action_id=req.action_id, free_text=req.free_text,
                viewer_region=req.viewer_region, client_ts_ms=req.client_ts_ms,
            ),
            action=action,
        )

        # Persist the chat turn + event log + current-node advance.
        if req.free_text:
            repo.append_turn(session_id, "viewer", req.free_text, action_id=req.action_id)
        if resolved.decision.is_allow() and resolved.transition.to_node_id:
            if resolved.transition.to_node_id != sess.current_node_id:
                repo.set_session_current_node(session_id, resolved.transition.to_node_id)
        repo.append_event(
            session_id,
            "turn_resolved",
            node_id=resolved.transition.to_node_id,
            action_id=req.action_id,
            payload={
                "decision": resolved.decision.decision,
                "reason_code": resolved.decision.reason_code,
                "intent_code": resolved.intent_code,
                "transition_kind": resolved.transition.kind.value if hasattr(resolved.transition.kind, "value") else str(resolved.transition.kind),
                "matched_rule_id": resolved.matched_rule_id,
            },
        )

        return {
            "ok": True,
            "resolved": {
                "session_id": resolved.session_id,
                "decision": {
                    "decision": resolved.decision.decision,
                    "reason_code": resolved.decision.reason_code,
                    "message": getattr(resolved.decision, "message", ""),
                },
                "transition": {
                    "to_node_id": resolved.transition.to_node_id,
                    "kind": resolved.transition.kind.value if hasattr(resolved.transition.kind, "value") else str(resolved.transition.kind),
                    "label": resolved.transition.label,
                    "payload": dict(resolved.transition.payload or {}),
                },
                "intent_code": resolved.intent_code,
                "reward_deltas": dict(resolved.reward_deltas or {}),
                "level_description": {
                    "display": resolved.level_description_display,
                    "level": resolved.level_description_level,
                },
                "mood": resolved.mood,
                "affinity_score": resolved.affinity_score,
                "matched_rule_id": resolved.matched_rule_id,
            },
        }

    @router.post("/play/sessions/{session_id}/end")
    def end_session_(
        session_id: str, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        sess = _require_session(session_id)
        from .. import store
        with store._conn() as con:
            con.execute(
                "UPDATE ix_sessions SET completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (session_id,),
            )
            con.commit()
        repo.append_event(session_id, "session_ended")
        return {"ok": True, "session_id": session_id}

    return router
