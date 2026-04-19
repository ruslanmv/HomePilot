"""
Live-play HTTP surface.

PLAY-4/8. One new route today: ``POST /play/sessions/{sid}/chat``.
The viewer types a message; the service classifies intent, runs
the existing free-input policy gate, plans the next scene, records
the chat turn pair, updates character state, enqueues a render
job, and (phase-1) completes the job synchronously with a stub
asset id so the player gets an immediate URL.

This is additive: nothing in ``routes/play.py`` or the existing
``/resolve`` flow changes. Authors can continue to drive the
action-catalog UI via ``/resolve`` while live-play viewers hit
``/chat`` — both coexist on the same session record.

The SSE ``/stream`` route lands in PLAY-5.
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import repo
from ..config import InteractiveConfig
from ..errors import InvalidInputError, NotFoundError
from ..interaction.state import upsert_character_state
from ..playback import (
    build_scene_memory,
    plan_next_scene,
    render_now,
    set_synopsis,
    should_refresh_synopsis,
    submit_scene_job,
    synthesize_synopsis,
)
from ..policy import check_free_input
from ._common import current_user, http_error_from


class ChatRequest(BaseModel):
    """Body of POST /play/sessions/{sid}/chat."""

    text: str
    viewer_region: str = ""


def build_playback_router(cfg: InteractiveConfig) -> APIRouter:
    router = APIRouter(tags=["interactive-playback"])

    @router.post("/play/sessions/{session_id}/chat")
    def chat(
        session_id: str, req: ChatRequest, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        sess = repo.get_session(session_id)
        if not sess:
            raise http_error_from(NotFoundError("session not found"))
        exp = repo.get_experience(sess.experience_id)
        if not exp:
            raise http_error_from(NotFoundError("experience not found"))

        text = (req.text or "").strip()
        if not text:
            raise http_error_from(InvalidInputError("text is required"))

        # ── Policy gate ──────────────────────────────────────────
        decision = check_free_input(
            cfg, text, exp, sess, viewer_region=req.viewer_region,
        )
        if not decision.is_allow():
            # Record the blocked turn + event so authors can see it
            # in analytics, but never run the planner or render job.
            # Canonical turn roles: 'user' | 'assistant' | 'system'
            # (see models.TurnRole) — the UI maps these to viewer /
            # character labels at render time.
            repo.append_turn(session_id, "user", text)
            repo.append_event(
                session_id, "chat_blocked",
                payload={
                    "reason_code": decision.reason_code,
                    "intent_code": decision.intent_code,
                },
            )
            return {
                "ok": True,
                "status": "blocked",
                "decision": {
                    "decision": decision.decision,
                    "reason_code": decision.reason_code,
                    "message": decision.message,
                    "intent_code": decision.intent_code,
                },
                "reply_text": "",
                "video_job_id": "",
            }

        # ── Append viewer turn + build memory ────────────────────
        viewer_turn_id = repo.append_turn(session_id, "user", text)
        memory = build_scene_memory(session_id)
        if memory is None:
            raise http_error_from(NotFoundError("session state missing"))

        persona_hint = _persona_hint_from_experience(exp, sess)
        plan = plan_next_scene(
            memory, text,
            persona_hint=persona_hint,
            duration_sec=_target_duration_from_cfg(cfg),
        )

        # ── Apply character state delta ──────────────────────────
        mood_delta = plan.mood_delta or {}
        new_mood = str(mood_delta.get("mood") or memory.mood)
        new_affinity = memory.affinity_score + float(mood_delta.get("affinity") or 0.0)
        new_affinity = max(0.0, min(1.0, new_affinity))
        upsert_character_state(
            session_id,
            persona_id=memory.persona_id or "",
            mood=new_mood,
            affinity_score=new_affinity,
        )

        # ── Append character reply turn ──────────────────────────
        character_turn_id = repo.append_turn(
            session_id, "assistant", plan.reply_text,
        )

        # ── Refresh rolling synopsis if the memory says it's time ─
        if should_refresh_synopsis(memory):
            set_synopsis(
                session_id,
                synthesize_synopsis(memory),
                at_turn_count=memory.total_turns + 2,
            )

        # ── Submit + (phase-1) synchronously render ──────────────
        job = submit_scene_job(session_id, character_turn_id, plan)
        completed = render_now(job.id)
        job_status = completed.status if completed else job.status
        asset_id = completed.asset_id if completed else ""

        repo.append_event(
            session_id, "chat_resolved",
            payload={
                "viewer_turn_id": viewer_turn_id,
                "character_turn_id": character_turn_id,
                "scene_job_id": job.id,
                "intent_code": plan.intent_code,
                "mood": new_mood,
            },
        )

        return {
            "ok": True,
            "status": "ok",
            "decision": {
                "decision": "allow", "reason_code": "", "message": "",
                "intent_code": plan.intent_code,
            },
            "reply_text": plan.reply_text,
            "scene_prompt": plan.scene_prompt,
            "duration_sec": plan.duration_sec,
            "topic_continuity": plan.topic_continuity,
            "intent_code": plan.intent_code,
            "mood": new_mood,
            "affinity_score": new_affinity,
            "viewer_turn_id": viewer_turn_id,
            "character_turn_id": character_turn_id,
            "video_job_id": job.id,
            "video_job_status": job_status,
            "video_asset_id": asset_id,
        }

    return router


# ── Helpers ─────────────────────────────────────────────────────

def _persona_hint_from_experience(exp: Any, sess: Any) -> str:
    """Best-effort persona hint for the image prompt.

    Pulls first from the session's personalization blob (authors
    can set a ``persona_hint`` there when seeding), then from the
    experience description, then from the title. Returns "" if
    nothing usable is set.
    """
    personalization: Dict[str, Any] = {}
    raw = getattr(sess, "personalization", None)
    if isinstance(raw, dict):
        personalization = raw
    hint = str(personalization.get("persona_hint") or "").strip()
    if hint:
        return hint
    desc = str(getattr(exp, "description", "") or "").strip()
    if desc:
        return desc
    return str(getattr(exp, "title", "") or "").strip()


def _target_duration_from_cfg(cfg: InteractiveConfig) -> int:
    """Map config latency target → a sane clip duration.

    Short latency targets → short clips, so the idle loop gap stays
    tolerable. Defaults to 5 s when nothing else is set.
    """
    latency_ms = int(getattr(cfg, "runtime_latency_target_ms", 0) or 0)
    if latency_ms <= 150:
        return 3
    if latency_ms <= 400:
        return 5
    return 7
