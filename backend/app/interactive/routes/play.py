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

Production fixes in this version:
- Prefer a persisted/frozen persona portrait from audience_profile.
- Fall back to persisted avatar if no portrait exists.
- Only resolve dynamic persona assets when no frozen image was saved.
- Preserve render_media_type from audience_profile when present.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

from .. import repo
from ..config import InteractiveConfig
from ..errors import InvalidInputError, NotFoundError
from ..interaction.router import ActionPayload, resolve_next
from ..interaction.state import build_runtime_state
from ..models import NodeUpdate
from ..playback import resolve_asset_url
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
    free-text component. The runtime prefers action_id.
    """

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
    async def start_session_(
        req: SessionStartRequest, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        exp = repo.get_experience(req.experience_id)
        if not exp:
            raise http_error_from(NotFoundError("experience not found"))

        sess = repo.create_session(
            exp.id,
            viewer_ref=req.viewer_ref or "anon",
            language=req.language,
            personalization=req.personalization,
        )

        # Default current node = best entry scene.
        # Prefer a scene that already has a playable asset URL so the
        # stage can render immediately; otherwise fall back to any scene
        # with an asset id, then any scene at all. Root-cause fix for
        # "clicked Play → warming up → empty screen" when the planner
        # left an unrendered prologue at index 0 but later scenes were
        # fully rendered.
        nodes = repo.list_nodes(exp.id)
        entry = _pick_entry_scene(nodes)
        # Debug trace: "Play shows empty" bugs usually live at one of
        # three seams — (1) no entry picked, (2) entry has no asset
        # ids, (3) asset id doesn't resolve to a URL. Emit a single
        # structured line with all three so the next failure tells us
        # which seam snapped without another round-trip.
        _log_entry_scene_trace(exp, nodes, entry)
        initial_scene: Optional[Dict[str, Any]] = None
        if entry:
            repo.set_session_current_node(sess.id, entry.id)
            sess = repo.get_session(sess.id)
            # Lazy entry-scene render: when generate-all hasn't (yet)
            # populated the entry node's asset_ids — most often because
            # the operator clicked Play before the wizard's render pass
            # completed, or because ComfyUI was unreachable when it ran
            # — try once inline. Failure is non-fatal: we fall through
            # to the "pending" payload below so the player at least
            # shows "Generating scene…" with a reason in the logs
            # instead of "Scene not available yet."
            #
            # Skipped entirely for Persona Live projects: their entry
            # scene is a publish/QA placeholder, not something the
            # runtime ever displays. The Live Action panel draws from
            # the persona_asset_library instead. Without this guard,
            # Persona Live /play/sessions would fire a txt2img/video
            # render on the generic scene narration — wasted GPU work
            # that can also explode on missing model files.
            project_type = str(getattr(exp, "project_type", "") or "").strip().lower()
            if (
                project_type != "persona_live"
                and not list(getattr(entry, "asset_ids", []) or [])
            ):
                refreshed = await _try_render_entry_scene(exp, entry, sess.id)
                if refreshed is not None:
                    entry = refreshed
            initial_scene = _build_initial_scene(entry)

        repo.append_event(sess.id, "session_started")

        # Persona Live Play: generate the in-character opening bubble
        # so the overlay has something to show before the viewer types.
        # Non-blocking by contract — any failure logs and returns cleanly
        # because losing the greeting must never block the Play button.
        opening = maybe_generate_opening_turn(exp, sess)

        payload: Dict[str, Any] = {"ok": True, "session": sess.model_dump()}
        if opening:
            payload["opening_turn"] = opening

        # Stage hint — prefer the persisted portrait frozen into the
        # experience. If absent, fall back to persisted avatar, and only
        # then resolve the current canonical portrait from the linked
        # persona project.
        portrait_url, avatar_url = _persisted_persona_image_urls(exp)
        if portrait_url:
            payload["persona_portrait_url"] = portrait_url
        elif avatar_url:
            payload["persona_portrait_url"] = avatar_url
        else:
            persona_pid, _ = _persona_fields(exp)
            if persona_pid:
                assets = resolve_persona_assets(persona_pid)
                if assets and getattr(assets, "portrait_url", None):
                    payload["persona_portrait_url"] = str(assets.portrait_url or "").strip()

        # Keep the wizard-stamped render_media_type if present.
        ap = getattr(exp, "audience_profile", None) or {}
        if isinstance(ap, dict):
            media_type = str(ap.get("render_media_type") or "").strip().lower()
            if media_type in ("image", "video"):
                payload["render_media_type"] = media_type

        payload["initial_scene"] = initial_scene
        if initial_scene is not None:
            log.info(
                "play_session_initial_scene exp=%s sess=%s status=%s "
                "media_kind=%s asset_id=%s has_url=%s",
                exp.id, sess.id,
                initial_scene.get("status") or "(missing)",
                initial_scene.get("media_kind") or "(missing)",
                initial_scene.get("asset_id") or "(empty)",
                bool(initial_scene.get("asset_url")),
            )
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
        def _slug(value: str) -> str:
            import re
            raw = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
            return raw[:80]

        sess = _require_session(session_id)
        actions = repo.list_actions(sess.experience_id)
        state = build_runtime_state(session_id)
        progress: Dict[str, Dict[str, float]] = state.progress if state else {}
        # Additive preview enrichment for Standard mode selector:
        # map action intent -> destination scene media so cards can
        # show actual thumbnails (and future audio preview hooks)
        # instead of generic gradients.
        preview_by_intent: Dict[str, Dict[str, Any]] = {}
        preview_by_ordinal: List[Dict[str, Any]] = []
        try:
            current_node_id = str(sess.current_node_id or "").strip()
            edges = [
                e for e in repo.list_edges(sess.experience_id)
                if e.from_node_id == current_node_id
            ]
            edges = sorted(edges, key=lambda e: (int(getattr(e, "ordinal", 0) or 0), str(e.id)))
            node_by_id = {
                n.id: n for n in repo.list_nodes(sess.experience_id)
            }
            for e in edges:
                label = str((e.trigger_payload or {}).get("label") or "").strip()
                to_node = node_by_id.get(e.to_node_id)
                if to_node is None:
                    continue
                asset_ids = list(getattr(to_node, "asset_ids", []) or [])
                aid = str(asset_ids[0] or "").strip() if asset_ids else ""
                url = _resolve_scene_asset_url(aid) if aid else ""
                preview = {
                    "destination_node_id": to_node.id,
                    "asset_preview_url": url,
                    "asset_thumbnail_url": url,
                }
                preview_by_ordinal.append(preview)
                if label:
                    # Match on both raw label and slug(label) so cards
                    # can resolve previews whether the action carries
                    # the human label or the slugged intent_code.
                    preview_by_intent[label] = preview
                    label_slug = _slug(label)
                    if label_slug:
                        preview_by_intent[label_slug] = preview
        except Exception:
            log.exception("catalog preview enrichment failed")

        items: List[Dict[str, Any]] = []
        ordered_actions = sorted(actions, key=lambda a: (int(a.ordinal or 0), str(a.created_at or "")))
        for idx, a in enumerate(ordered_actions):
            unlocked, reason = is_action_unlocked(a, progress)
            intent = str(a.intent_code or "").strip()
            label = str(a.label or "").strip()
            preview = (
                preview_by_intent.get(intent)
                or preview_by_intent.get(_slug(intent))
                or preview_by_intent.get(label)
                or preview_by_intent.get(_slug(label))
                or (preview_by_ordinal[idx] if idx < len(preview_by_ordinal) else {})
            )
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
                "destination_node_id": preview.get("destination_node_id", ""),
                "asset_preview_url": preview.get("asset_preview_url", ""),
                "asset_thumbnail_url": preview.get("asset_thumbnail_url", ""),
            })
        return {"ok": True, "items": items}

    @router.get("/play/sessions/{session_id}/progress")
    def get_progress_(
        session_id: str, _user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        _require_session(session_id)
        state = build_runtime_state(session_id)
        if state is None:
            raise http_error_from(NotFoundError("session state missing"))

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
            raise http_error_from(
                InvalidInputError("either action_id or free_text is required")
            )

        sess = _require_session(session_id)
        exp = _require_experience_for_session(sess)

        action = repo.get_action(req.action_id) if req.action_id else None
        if req.action_id and not action:
            raise http_error_from(NotFoundError("action not found"))
        if action and action.experience_id != exp.id:
            raise http_error_from(NotFoundError("action not in this experience"))

        resolved = resolve_next(
            cfg,
            exp,
            sess,
            ActionPayload(
                action_id=req.action_id,
                free_text=req.free_text,
                viewer_region=req.viewer_region,
                client_ts_ms=req.client_ts_ms,
            ),
            action=action,
        )

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
                "transition_kind": (
                    resolved.transition.kind.value
                    if hasattr(resolved.transition.kind, "value")
                    else str(resolved.transition.kind)
                ),
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
                    "kind": (
                        resolved.transition.kind.value
                        if hasattr(resolved.transition.kind, "value")
                        else str(resolved.transition.kind)
                    ),
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
        _require_session(session_id)
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


def _build_initial_scene(entry_node: Any) -> Optional[Dict[str, Any]]:
    """Translate the entry node into the shape the player expects.

    Returns a ``status: "pending"`` stub instead of ``None`` when the
    node has no resolved asset yet — the player branches on this
    status to show "Generating scene…" rather than the dead-end
    "Scene not available yet." message that older builds emitted.
    The pending payload keeps the node id and title so the player
    can re-fetch the session later (page refresh / Play again) and
    pick up the rendered asset once the background pass completes.
    """
    node_id = str(getattr(entry_node, "id", "") or "")
    title = str(getattr(entry_node, "title", "") or "")
    # Narration is the long-form scene text the planner writes —
    # surfaced here so the Standard player's visual-novel caption
    # overlay can render it without a second roundtrip. Empty
    # string is fine; the caption layer falls back to the title.
    narration = str(getattr(entry_node, "narration", "") or "")
    # Subtitles is an author-overridable shorter caption. Defaults
    # to empty (planner doesn't write it today); reserved for the
    # subtitle layer when the author wants different display text
    # vs. the planner's full narration.
    subtitles = str(getattr(entry_node, "subtitles", "") or "")
    duration = int(getattr(entry_node, "duration_sec", 0) or 0)
    if duration <= 0:
        duration = 5

    asset_ids = list(getattr(entry_node, "asset_ids", []) or [])
    asset_id = str(asset_ids[0] or "").strip() if asset_ids else ""
    asset_url = _resolve_scene_asset_url(asset_id) if asset_id else ""

    if not asset_id or not asset_url:
        return {
            "node_id": node_id,
            "title": title,
            "narration": narration,
            "subtitles": subtitles,
            "duration_sec": duration,
            "asset_id": "",
            "asset_url": "",
            "media_kind": "",
            "status": "pending",
        }

    return {
        "node_id": node_id,
        "asset_id": asset_id,
        "asset_url": asset_url,
        "media_kind": _media_kind_from_url(asset_url),
        "duration_sec": duration,
        "title": title,
        "narration": narration,
        "subtitles": subtitles,
        "status": "ready",
    }


def _log_entry_scene_trace(
    exp: Any, nodes: List[Any], entry: Optional[Any],
) -> None:
    """Structured debug trace for the 'Play shows empty' class of bugs.

    Dumps the experience id, total scene count, and for the chosen
    entry (if any): its id, whether it carries asset_ids, the first
    asset id, and whether that id resolves to a URL. Three fail modes
    produce visibly different traces so the next "empty Play" report
    says exactly which link snapped:

      * ``entry=None``                — ``_pick_entry_scene`` found no
        scene nodes; graph is malformed or the wizard skipped scene
        persistence.
      * ``asset_ids=[]``              — the scene exists but never
        rendered; the wizard's Phase 2 render pass skipped or failed
        for this node.
      * ``resolved_url=""``           — the asset id is registered but
        ``resolve_asset_url`` returned None (asset_registry row
        missing or storage_key empty).
      * full trace with resolved_url  — backend's side is fine; the
        gap is in the frontend payload wiring.
    """
    scene_count = sum(1 for n in nodes if getattr(n, "kind", "") == "scene")
    if entry is None:
        log.info(
            "play_entry_trace exp=%s scenes=%d entry=None (no scene nodes found)",
            getattr(exp, "id", ""), scene_count,
        )
        return
    asset_ids = list(getattr(entry, "asset_ids", []) or [])
    first_id = str(asset_ids[0] or "").strip() if asset_ids else ""
    resolved = _resolve_scene_asset_url(first_id) if first_id else ""
    log.info(
        "play_entry_trace exp=%s scenes=%d entry_id=%s kind=%s "
        "asset_ids=%d first_asset_id=%s resolved_url=%s",
        getattr(exp, "id", ""),
        scene_count,
        getattr(entry, "id", ""),
        getattr(entry, "kind", ""),
        len(asset_ids),
        first_id or "(none)",
        resolved or "(empty)",
    )


def _pick_entry_scene(nodes: List[Any]) -> Optional[Any]:
    """Pick the best entry scene for session start.

    Priority:
      1) first scene with an already-resolvable asset URL
      2) first scene with any asset id
      3) first scene node

    This avoids black-stage starts when the planner left an unrendered
    prologue scene at index 0 but later scenes were fully rendered.
    """
    scenes = [n for n in (nodes or []) if getattr(n, "kind", "") == "scene"]
    if not scenes:
        return None

    def _first_asset_id(node: Any) -> str:
        asset_ids = list(getattr(node, "asset_ids", []) or [])
        return str(asset_ids[0] or "").strip() if asset_ids else ""

    for n in scenes:
        aid = _first_asset_id(n)
        if aid and _resolve_scene_asset_url(aid):
            return n
    for n in scenes:
        if _first_asset_id(n):
            return n
    return scenes[0]


async def _try_render_entry_scene(
    exp: Any, entry_node: Any, session_id: str,
) -> Optional[Any]:
    """Best-effort inline render of the entry scene.

    Re-uses the same adapter the wizard's generate-all pass calls, so
    the workflow + variables + asset registration stay identical (no
    new render path to maintain). Returns the refreshed node row on
    success, ``None`` on any failure / when the playback config has
    rendering disabled — callers fall through to the pending payload
    in that case.

    Bounded to ``cfg.render_timeout_s`` (already enforced inside the
    adapter), so a misconfigured ComfyUI never wedges /play/sessions.
    """
    from ..playback.render_adapter import render_scene_async  # late import — heavy
    from ..playback.playback_config import load_playback_config

    cfg = load_playback_config()
    if not getattr(cfg, "render_enabled", False):
        # Render is gated off — nothing to do here. The player will
        # show "Generating scene…" but the operator needs to flip
        # the flag (or run generate-all manually) for it to fill.
        return None

    scene_prompt = (
        str(getattr(entry_node, "narration", "") or "").strip()
        or str(getattr(entry_node, "title", "") or "").strip()
        or "Scene"
    )
    media_type = "image"
    ap = getattr(exp, "audience_profile", None) or {}
    if isinstance(ap, dict):
        raw_media = str(ap.get("render_media_type") or "").strip().lower()
        if raw_media in ("image", "video"):
            media_type = raw_media
    persona_hint = str(getattr(exp, "description", "") or "").strip()

    try:
        asset_id = await render_scene_async(
            scene_prompt=scene_prompt,
            duration_sec=int(getattr(entry_node, "duration_sec", 0) or 0) or 5,
            session_id=f"play_entry_{session_id}",
            persona_hint=persona_hint,
            media_type=media_type,
            user_id=str(getattr(exp, "user_id", "") or ""),
        )
    except Exception:  # noqa: BLE001 — adapter failures are non-fatal
        return None
    if not asset_id:
        return None

    try:
        repo.update_node(entry_node.id, NodeUpdate(asset_ids=[asset_id]))
    except Exception:  # noqa: BLE001 — registration succeeded; player
        # will still load this asset by id even if the patch failed.
        return None

    return repo.get_node(entry_node.id)


def _persisted_persona_image_urls(exp: Any) -> Tuple[str, str]:
    """
    Return the frozen persona image URLs saved on the experience.

    Order:
      - persona_portrait_url
      - persona_avatar_url

    The caller decides how to use them.
    """
    ap = getattr(exp, "audience_profile", None) or {}
    if not isinstance(ap, dict):
        return "", ""

    portrait = str(ap.get("persona_portrait_url") or "").strip()
    avatar = str(ap.get("persona_avatar_url") or "").strip()
    return portrait, avatar


def _media_kind_from_url(url: str) -> str:
    u = (url or "").lower()
    # Accept the extension at any of:
    #   - end of string         ".../foo.png"
    #   - just before a query   ".../foo.png?x=1"
    #   - inside a query value  ".../view?filename=foo.png&type=output"
    # The third form is what ComfyUI's /view endpoint emits and was the
    # cause of the "Standard player loads black" bug — without matching
    # ``.png&`` and ``.png#`` here the kind dropped to "unknown" and
    # both frontend regex paths fell through to the empty placeholder.
    _VIDEO_EXTS = (".mp4", ".webm", ".mov", ".mkv", ".m4v")
    _IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif")
    def _has_ext(haystack: str, ext: str) -> bool:
        return (
            haystack.endswith(ext)
            or f"{ext}?" in haystack
            or f"{ext}&" in haystack
            or f"{ext}#" in haystack
        )
    if any(_has_ext(u, ext) for ext in _VIDEO_EXTS):
        return "video"
    # AVIF added 2026-04 — some ComfyUI pipelines (and any browser-side
    # re-encode path) emit .avif scene assets. Without listing it here,
    # the initial-scene payload dropped to media_kind="unknown" and the
    # Standard player fell through to "Scene not available yet." instead
    # of rendering the image.
    if any(_has_ext(u, ext) for ext in _IMAGE_EXTS):
        return "image"
    return "unknown"


def _resolve_scene_asset_url(asset_id: str) -> str:
    """
    Resolve both registry ids and direct file/URL references.

    Older authored standard projects may store scene media directly in
    ``asset_ids`` as a `/files/...` path or absolute URL instead of a
    row-backed asset-registry id. Prefer registry resolution but fall
    back to direct references so the player never renders a black stage.
    """
    resolved = str(resolve_asset_url(asset_id) or "").strip()
    if resolved:
        return resolved

    raw = str(asset_id or "").strip()
    if raw.startswith("/files/") or raw.startswith("http://") or raw.startswith("https://"):
        return raw
    if raw.startswith("/view?") or raw.startswith("view?"):
        try:
            from ..media_router import resolve_current_comfy_base_url
            base = str(resolve_current_comfy_base_url() or "").strip()
        except Exception:
            base = ""
        if base:
            return f"{base.rstrip('/')}/{raw.lstrip('/')}"

    return ""
