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

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from .. import repo
from ..config import InteractiveConfig
from ..errors import InvalidInputError, NotFoundError
from ..interaction.state import upsert_character_state
from ..playback import (
    build_scene_memory,
    list_jobs,
    plan_next_scene_async,
    render_now_async,
    resolve_asset_url,
    set_synopsis,
    should_refresh_synopsis,
    submit_scene_job,
    synthesize_synopsis,
)
from ..playback.video_job import SceneJob
from ..policy import check_free_input
from ._common import current_user, http_error_from


class ChatRequest(BaseModel):
    """Body of POST /play/sessions/{sid}/chat."""

    text: str
    viewer_region: str = ""


def build_playback_router(cfg: InteractiveConfig) -> APIRouter:
    router = APIRouter(tags=["interactive-playback"])

    @router.post("/play/sessions/{session_id}/chat")
    async def chat(
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
        persona_project_id, persona_label = _persona_project_from_experience(exp)
        plan = await plan_next_scene_async(
            memory, text,
            persona_hint=persona_hint,
            duration_sec=_target_duration_from_cfg(cfg),
            persona_project_id=persona_project_id,
            persona_label=persona_label,
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

        # ── Submit + render ──────────────────────────────────────
        # render_now_async picks the real Animate pipeline when
        # INTERACTIVE_PLAYBACK_RENDER is on and gracefully falls
        # back to the phase-1 stub otherwise, so this handler
        # never has to branch on flags itself.
        #
        # media_type reads the wizard-stamped audience_profile flag;
        # 'image' swaps to the fast still-image workflow for GPU-
        # constrained operators, 'video' keeps the current clip
        # pipeline. Default stays 'video' so legacy experiences keep
        # their existing look.
        job = submit_scene_job(session_id, character_turn_id, plan)
        media_type = _media_type_from_experience(exp)
        completed = await render_now_async(
            job.id, persona_hint=persona_hint, media_type=media_type,
        )
        job_status = completed.status if completed else job.status
        asset_id = completed.asset_id if completed else ""
        asset_url = resolve_asset_url(asset_id) if asset_id else None

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
            "video_asset_url": asset_url or "",
        }

    @router.get("/play/sessions/{session_id}/pending")
    def pending(
        session_id: str,
        since_id: str = Query(default="", description="Return jobs created after this id"),
        limit: int = Query(default=50, ge=1, le=500),
        _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        """Return scene jobs newer than ``since_id``.

        The player polls this at a low cadence (e.g. every 1–2 s)
        while a job is rendering. Each job carries its current
        status, which lets the UI transition idle-loop →
        crossfade → next-clip as soon as ``status == 'ready'``.

        Upgrading to SSE later is a drop-in: the handler signature
        stays the same, a streaming variant registers under
        ``/stream`` and emits the same event payloads. For
        phase-1 the polling path is simpler and works everywhere
        without the reconnect edge cases of long-lived streams.
        """
        sess = repo.get_session(session_id)
        if not sess:
            raise http_error_from(NotFoundError("session not found"))
        jobs = list_jobs(session_id, since_id=since_id or None, limit=limit)
        return {
            "ok": True,
            "items": [_job_to_dict(j) for j in jobs],
            "cursor": jobs[-1].id if jobs else since_id,
        }

    return router


# ── Helpers ─────────────────────────────────────────────────────

def _job_to_dict(job: SceneJob) -> Dict[str, Any]:
    # Resolve the URL per row. Stub ids return None and we emit
    # an empty string so the frontend shape stays stable without
    # branching on presence.
    asset_url = resolve_asset_url(job.asset_id) if job.asset_id else None
    return {
        "id": job.id,
        "session_id": job.session_id,
        "turn_id": job.turn_id,
        "status": job.status,
        "job_id": job.job_id,
        "asset_id": job.asset_id,
        "asset_url": asset_url or "",
        "prompt": job.prompt,
        "duration_sec": job.duration_sec,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }

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


def _persona_project_from_experience(exp: Any) -> tuple[str, str]:
    """Pull the ``audience_profile.persona_project_id`` + ``persona_label``
    stamped by the wizard when the user picks Persona Live Play.

    Returns ``("", "")`` for standard-project experiences so the
    composer takes the generic path.
    """
    ap = getattr(exp, "audience_profile", None) or {}
    if not isinstance(ap, dict):
        return "", ""
    if str(ap.get("interaction_type") or "").strip() != "persona_live_play":
        return "", ""
    pid = str(ap.get("persona_project_id") or "").strip()
    label = str(ap.get("persona_label") or "").strip()
    return pid, label


def _media_type_from_experience(exp: Any) -> str:
    """Read ``audience_profile.render_media_type`` off the experience.

    The wizard stamps either ``"video"`` (full ComfyUI clip) or
    ``"image"`` (fast still-image feasibility path). Unknown or
    missing values fall back to ``"video"`` so pre-flag experiences
    keep their existing pipeline.
    """
    ap = getattr(exp, "audience_profile", None) or {}
    if not isinstance(ap, dict):
        return "video"
    raw = str(ap.get("render_media_type") or "").strip().lower()
    return "image" if raw == "image" else "video"


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
