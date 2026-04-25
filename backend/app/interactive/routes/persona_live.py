from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from .. import repo
from ..config import InteractiveConfig
from ..playback import resolve_asset_url
from ..playback import persona_asset_library as pal
from ..playback.edit_recipes import recipe_for_action
from ..playback.persona_assets import load_assets
from ..playback.persona_live_prompts import (
    compose_image_prompt,
    compose_system_prompt,
    effective_tier,
)
from ..playback.scene_planner import ScenePlan
from ..playback.video_job import get_job, render_now_async, submit_scene_job
from ...llm import chat_ollama
from ._common import current_user

log = logging.getLogger(__name__)


class PersonaLiveGenerateRequest(BaseModel):
    persona_id: str
    vibe: str
    mode: str = "image"


class PersonaLiveStartRequest(BaseModel):
    persona_id: str
    mode: str = "image"


class PersonaLiveActionRequest(BaseModel):
    action_id: str
    message: str = ""


class PersonaLiveRestoreRequest(BaseModel):
    version_id: str


class PersonaLiveChatRequest(BaseModel):
    message: str


class PersonaLiveLibraryBuildRequest(BaseModel):
    """Build-pass request for the persona pre-render pack.

    ``tier`` defaults to 1 (idles + expressions + default outfit + medium
    camera — covers ~90% of gameplay). Operators can bump to 2 or 3 for
    fuller coverage at extra GPU cost.
    """
    tier: int = 1


@dataclass
class _ActionProxy:
    intent_code: str
    category: str
    edit_recipe: Dict[str, Any]


_ACTION_CATEGORY_MAP = {
    "tease": "expression",
    "smirk": "expression",
    "blush": "expression",
    "ahegao": "expression",
    "dance": "pose",
    "closer_pose": "pose",
    "turn_around": "pose",
    "outfit_change": "outfit",
    "move_to_beach": "scene",
    "make_it_rain": "scene",
    "zoom_out": "scene",
}


# ── Intent-driven action catalog ───────────────────────────────────────────
#
# The Live Action panel used to expose CHARACTER OUTPUT names (Tease /
# Smirk / Blush / Closer Pose / Outfit Change). That made the player feel
# like they were poking animation triggers instead of talking to Lina.
# This catalog flips the model: each entry is a PLAYER INTENT (Compliment
# her, Stay quiet, Suggest a different outfit) + the character reaction
# the renderer should produce. _actions_for_level emits these labels;
# the action endpoint maps intent → reaction_intent before handing off
# to recipe_for_action so the existing edit recipes (avatar_expression_
# change / avatar_inpaint_outfit / change_background / …) still drive
# rendering with no new workflow files.
#
# Each entry carries:
#   label              — text shown on the button
#   description        — one-line hint (used for tooltips / a11y)
#   category           — expression | pose | outfit | scene
#   reaction_intent    — the legacy action_id the renderer keys on
#                        (must exist in ACTION_RECIPES)
#   delta              — additive {affection, comfort, playfulness}
#   explicit_only      — gate behind persona.allow_explicit
#   level              — unlock tier (1..5)
#
# Old action ids (tease/smirk/blush/dance/closer_pose/...) stay valid as
# fallthrough so existing sessions, programmatic API users, and tests
# don't break.
_INTENT_CATALOG: Dict[str, Dict[str, Any]] = {
    # Level 1 — opening / trust building
    "say_playful": {
        "label": "Say something playful",
        "description": "Open with a light, teasing line.",
        "category": "expression",
        "reaction_intent": "smirk",
        "delta": {"affection": 1, "comfort": 0, "playfulness": 3},
        "level": 1,
    },
    "compliment": {
        "label": "Compliment her",
        "description": "Tell her something genuine.",
        "category": "expression",
        "reaction_intent": "blush",
        "delta": {"affection": 3, "comfort": 1, "playfulness": 1},
        "level": 1,
    },
    "ask_about_her": {
        "label": "Ask about her day",
        "description": "Show interest in who she is.",
        "category": "expression",
        "reaction_intent": "tease",
        "delta": {"affection": 1, "comfort": 3, "playfulness": 0},
        "level": 1,
    },
    "stay_quiet": {
        "label": "Just be present",
        "description": "Give her space; let her lead.",
        "category": "expression",
        "reaction_intent": "tease",
        "delta": {"affection": 0, "comfort": 2, "playfulness": 1},
        "level": 1,
    },
    # Level 2 — closer + more personal
    "get_closer": {
        "label": "Get closer",
        "description": "Move into a closer frame.",
        "category": "pose",
        "reaction_intent": "closer_pose",
        "delta": {"affection": 2, "comfort": 2, "playfulness": 2},
        "level": 2,
    },
    "ask_personal": {
        "label": "Ask something personal",
        "description": "Open the door to her backstory.",
        "category": "expression",
        "reaction_intent": "blush",
        "delta": {"affection": 3, "comfort": 2, "playfulness": 0},
        "level": 2,
    },
    # Level 3 — visual variety
    "change_view": {
        "label": "Change angle",
        "description": "Ask her to turn so you see a new angle.",
        "category": "pose",
        "reaction_intent": "turn_around",
        "delta": {"affection": 0, "comfort": 0, "playfulness": 2},
        "level": 3,
    },
    "step_back": {
        "label": "Step back to see all",
        "description": "Pull the framing wider.",
        "category": "scene",
        "reaction_intent": "zoom_out",
        "delta": {"affection": 0, "comfort": 1, "playfulness": 1},
        "level": 3,
    },
    # Level 4 — outfit + location
    "suggest_outfit": {
        "label": "Suggest a different outfit",
        "description": "Hint that you'd like to see her in something else.",
        "category": "outfit",
        "reaction_intent": "outfit_change",
        "delta": {"affection": 1, "comfort": 0, "playfulness": 3},
        "level": 4,
    },
    "change_location": {
        "label": "Change the place",
        "description": "Move the scene somewhere new.",
        "category": "scene",
        "reaction_intent": "move_to_beach",
        "delta": {"affection": 0, "comfort": 2, "playfulness": 2},
        "level": 4,
    },
    # Level 5 — tier-gated finale
    "lean_in": {
        "label": "Lean into the moment",
        "description": "Close the distance and let her respond.",
        "category": "expression",
        "reaction_intent": "ahegao",
        "delta": {"affection": 4, "comfort": 1, "playfulness": 4},
        "explicit_only": True,
        "level": 5,
    },
    "playful_dare": {
        "label": "Playful dare",
        "description": "Suggest something a little wild.",
        "category": "scene",
        "reaction_intent": "make_it_rain",
        "delta": {"affection": 1, "comfort": 0, "playfulness": 5},
        "level": 5,
    },
}

# Reverse view: extend the legacy category map with the intent ids so
# any caller that still keys off _ACTION_CATEGORY_MAP keeps working.
for _intent_id, _entry in _INTENT_CATALOG.items():
    _ACTION_CATEGORY_MAP.setdefault(_intent_id, str(_entry.get("category") or "expression"))


def _intent_to_render_key(action_id: str) -> str:
    """Translate a player intent into the legacy renderer action key.

    Existing edit recipes (ACTION_RECIPES in edit_recipes.py) key on the
    OLD action ids — tease, smirk, closer_pose, outfit_change, etc. The
    renderer doesn't need to know the player clicked "Compliment her";
    it just needs "blush" so the right workflow + denoise lands. Falls
    through to the original ``action_id`` when no intent mapping exists,
    so legacy callers and tests stay green.
    """
    entry = _INTENT_CATALOG.get((action_id or "").strip().lower())
    if entry and entry.get("reaction_intent"):
        return str(entry["reaction_intent"])
    return action_id

_SCENE_LIBRARY: Dict[str, Dict[str, str]] = {
    "apartment": {
        "id": "apartment",
        "label": "Her apartment",
        "icon": "🏠",
        "prompt": "cozy apartment interior, warm practical light, tasteful details",
        "category": "private",
    },
    "beach": {
        "id": "beach",
        "label": "Beach at sunset",
        "icon": "🌴",
        "prompt": "sunset beach, warm golden light, ocean waves, soft breeze",
        "category": "outdoor",
    },
    "supermarket": {
        "id": "supermarket",
        "label": "Supermarket aisle",
        "icon": "🛒",
        "prompt": "clean supermarket aisle, fluorescent fill light, high detail shelves",
        "category": "public",
    },
    "rainstreet": {
        "id": "rainstreet",
        "label": "Rainy city street",
        "icon": "🌧️",
        "prompt": "city street in rain, reflective pavement, moody neon highlights",
        "category": "public",
    },
}

_JOB_RESULTS: Dict[str, Dict[str, Any]] = {}


def build_persona_live_router(_cfg: InteractiveConfig) -> APIRouter:
    router = APIRouter(tags=["interactive-persona-live"])

    @router.post("/persona-live/generate")
    @router.post("/api/persona-live/generate")
    def generate(req: PersonaLiveGenerateRequest, _user: str = Depends(current_user)) -> Dict[str, Any]:
        persona = _load_persona(req.persona_id)
        levels = _default_levels(vibe=req.vibe, allow_explicit=_allow_explicit(req.persona_id))
        rules = {
            "mode": "video" if str(req.mode).lower() == "video" else "image",
            "allow_explicit": _allow_explicit(req.persona_id),
            "identity_locked": True,
        }
        return {
            "persona": persona,
            "vibe": (req.vibe or "").strip(),
            "levels": levels,
            "rules": rules,
        }

    @router.post("/persona-live/start")
    @router.post("/api/persona-live/start")
    def start(req: PersonaLiveStartRequest, _user: str = Depends(current_user)) -> Dict[str, Any]:
        mode = "video" if str(req.mode).lower() == "video" else "image"
        session = repo.create_persona_session(req.persona_id, mode=mode)
        return {"ok": True, "session": session}

    @router.get("/persona-live/session/{session_id}")
    @router.get("/api/persona-live/session/{session_id}")
    def session(session_id: str, _user: str = Depends(current_user)) -> Dict[str, Any]:
        sess = repo.get_persona_session(session_id)
        if not sess:
            return {"ok": False, "error": "session_not_found"}
        versions = repo.list_persona_versions(session_id, limit=8)
        level = int(sess.get("current_level") or 1)
        xp = int(sess.get("xp") or 0)
        xp_to_next = max(0, ((level * 35) - xp))
        persona = _load_persona(str(sess.get("persona_id") or ""))
        current_version_id = str(sess.get("current_version_id") or "")
        current_version = repo.get_persona_version(current_version_id) if current_version_id else None
        media_url = str((current_version or {}).get("image_url") or persona.get("avatar_url") or "")
        scene_context = _normalize_scene(sess.get("scene_context"))
        scene_memory = _normalize_memory(sess.get("scene_memory"), scene_context)
        emotional_state = _normalize_emotion(sess.get("emotional_state"))
        rules = _default_levels(vibe="", allow_explicit=_allow_explicit(str(sess.get("persona_id") or "")))
        actions = _actions_for_level(level, rules)
        return {
            "ok": True,
            "persona": {**persona, "mode": str(sess.get("mode") or "image")},
            "session": {
                "id": str(sess.get("id") or ""),
                "level": level,
                "xp": xp,
                "xp_to_next": xp_to_next,
                "current_version_id": current_version_id,
            },
            "scene_context": scene_context,
            "scene_memory": scene_memory,
            "emotional_state": emotional_state,
            "current_media": {
                "type": str(sess.get("mode") or "image"),
                "url": media_url,
                "status": "ready" if media_url else "idle",
            },
            "dialogue": {"text": str(sess.get("last_dialogue") or "")},
            "actions": actions,
            "versions": [
                {
                    "id": str(v.get("id") or ""),
                    "thumb_url": str(v.get("thumb_url") or ""),
                    "active": str(v.get("id") or "") == current_version_id,
                }
                for v in versions
            ],
        }

    @router.post("/persona-live/session/{session_id}/action")
    @router.post("/api/persona-live/session/{session_id}/action")
    async def action(session_id: str, req: PersonaLiveActionRequest, _user: str = Depends(current_user)) -> Dict[str, Any]:
        sess = repo.get_persona_session(session_id)
        if not sess:
            return {"ok": False, "error": "session_not_found"}
        persona_id = str(sess.get("persona_id") or "")
        allow_explicit = _allow_explicit(persona_id)

        scene_context = _normalize_scene(sess.get("scene_context"))
        scene_memory = _normalize_memory(sess.get("scene_memory"), scene_context)
        emotional_state = _normalize_emotion(sess.get("emotional_state"))

        action_id = (req.action_id or "").strip().lower()

        # Gate explicit-only intents AND legacy explicit reaction keys
        # behind the persona's safety profile. The legacy "ahegao" check
        # used to live here as a hardcoded set; the catalog now owns the
        # gating decision so adding a new mature intent doesn't require
        # touching this branch.
        intent_entry = _INTENT_CATALOG.get(action_id) or {}
        is_explicit_intent = bool(intent_entry.get("explicit_only"))
        if not allow_explicit and (is_explicit_intent or action_id in {"ahegao"}):
            dialogue = "Not yet — keep it playful for now."
            repo.update_persona_session_runtime_state(
                session_id,
                dialogue=dialogue,
                scene_context=scene_context,
                scene_memory=scene_memory,
                emotional_state=emotional_state,
            )
            return {"ok": True, "render_skipped": True, "dialogue": {"text": dialogue}}

        persona = _load_persona(persona_id)
        turn = await _compose_turn(
            message=req.message,
            action_id=action_id,
            scene_context=scene_context,
            emotional_state=emotional_state,
            scene_memory=scene_memory,
            persona=persona,
            adult_llm=str(persona.get("adult_llm") or "").strip() or None,
        )
        scene_change_id = str(turn.get("scene_change") or "")
        if scene_change_id:
            scene_context = _scene_by_id(scene_change_id)

        # Library-first fast path (opt-in via PERSONA_LIVE_LIBRARY_LOOKUP).
        # If the persona has a pre-rendered asset for this intent, serve
        # it instantly and skip the live render + job-poll loop. Dialogue
        # still comes from _compose_turn so the conversation stays fresh;
        # only the visual reaction is cached. Misses (library empty for
        # this intent, or lookup flag off) fall through to the existing
        # render path with no behaviour change.
        if pal.lookup_enabled():
            pre_url = pal.resolve_asset_url_for_intent(
                persona_id, action_id, allow_explicit=allow_explicit,
            )
            if pre_url:
                emotional_state = _apply_emotion_delta(
                    emotional_state, action_id=action_id,
                    scene_category=scene_context["category"],
                )
                scene_memory = _apply_memory_update(scene_memory, scene_context, action_id)
                version = repo.save_persona_version(
                    persona_id=persona_id,
                    session_id=session_id,
                    image_url=pre_url,
                    thumb_url=pre_url,
                    recipe={"source": "library", "intent": action_id},
                )
                # ``save_persona_version`` already stamps
                # current_version_id on the session row (repo.py
                # ~line 696), so the runtime-state update here is
                # only for dialogue / scene_context / scene_memory /
                # emotional_state. Passing current_version_id used
                # to TypeError: update_persona_session_runtime_state
                # got an unexpected keyword argument
                # 'current_version_id' — surfaced to the user as a
                # 500 on /persona-live/session/{id}/action.
                version_id = str(version.get("id") or "")
                repo.update_persona_session_runtime_state(
                    session_id,
                    dialogue=turn["dialogue"],
                    scene_context=scene_context,
                    scene_memory=scene_memory,
                    emotional_state=emotional_state,
                )
                # Award XP for the action. The library-fast-path used
                # to skip this — the live-render branch (line ~1331)
                # was the only place ``update_persona_session_progress``
                # got called, so once a persona's library was warm,
                # every action returned instantly with ``xp`` stuck at
                # 0 and the user could never level up via taps. Match
                # the live-render delta (10 per action) so the
                # progress bar advances regardless of which path
                # served the photo.
                before_progress = repo.get_persona_session(session_id) or {}
                before_level = int(before_progress.get("current_level") or 1)
                progressed = repo.update_persona_session_progress(
                    session_id, xp_delta=10,
                ) or before_progress
                new_xp = int(progressed.get("xp") or 0)
                new_level = int(progressed.get("current_level") or before_level)
                xp_to_next = max(0, (new_level * 35) - new_xp)
                new_unlocks: List[Dict[str, Any]] = []
                if new_level > before_level:
                    levels = _default_levels(
                        vibe="", allow_explicit=allow_explicit,
                    )
                    for block in levels:
                        if int(block.get("level") or 1) == new_level:
                            new_unlocks.extend([
                                {"id": aid, "label": str(aid).replace("_", " ").title()}
                                for aid in list(block.get("actions") or [])
                            ])
                synth_job_id = f"lib_{version_id}" if version_id else f"lib_{action_id}"
                _JOB_RESULTS[synth_job_id] = {
                    "status": "ready",
                    "media": {"type": "image", "url": pre_url, "status": "ready"},
                    "version_id": version_id,
                    "source": "library",
                }
                return {
                    "ok": True,
                    "job_id": synth_job_id,
                    "status": "ready",
                    "scene_context": scene_context,
                    "scene_memory": scene_memory,
                    "emotional_state": emotional_state,
                    "dialogue": {"text": turn["dialogue"]},
                    "media": {"type": "image", "url": pre_url, "status": "ready"},
                    "source": "library",
                    "xp": new_xp,
                    "level": new_level,
                    "xp_to_next": xp_to_next,
                    "xp_delta": 10,
                    "new_unlocks": new_unlocks,
                }

        # Translate the player INTENT into the renderer's expected key
        # (smirk / blush / closer_pose / outfit_change / …). Recipes in
        # edit_recipes.ACTION_RECIPES still key on those legacy ids — we
        # only changed the player-facing labels above.
        render_key = _intent_to_render_key(action_id)
        action_proxy = _ActionProxy(
            intent_code=render_key,
            category=_ACTION_CATEGORY_MAP.get(render_key, "expression"),
            edit_recipe={},
        )
        media_mode = str(sess.get("mode") or "image")
        recipe = recipe_for_action(action_proxy, turn.get("edit_hint"), mode=media_mode)
        recipe["workflow_id"] = str(recipe.get("workflow_id") or "edit").replace(".json", "")
        assets = load_assets(persona_id)

        current_version_id = str(sess.get("current_version_id") or "")
        current = repo.get_persona_version(current_version_id) if current_version_id else None
        image_ref = _pick_anchor_image_ref(
            current_image_url=str((current or {}).get("image_url") or ""),
            persona_avatar_url=str(persona.get("avatar_url") or ""),
            resolved_portrait=str(assets.get("portrait") or ""),
        )
        if not image_ref:
            return {
                "ok": False,
                "error": "persona_anchor_missing",
                "message": "Persona portrait is required before rendering actions.",
                "dialogue": {"text": turn["dialogue"]},
            }

        recipe.setdefault("inputs", {})
        recipe["inputs"]["image_ref"] = image_ref
        recipe["inputs"]["source_image"] = image_ref
        recipe["inputs"]["input_image"] = image_ref
        recipe["inputs"]["image"] = image_ref
        recipe["inputs"]["instantid_embedding"] = assets["embedding"]
        recipe["inputs"]["positive_prompt"] = f"{turn['scene_prompt']}, {scene_context['prompt']}"
        recipe["inputs"]["negative_prompt"] = assets["negative_prompt"]

        if action_proxy.category == "scene":
            recipe["workflow_id"] = "change_background"
            recipe["inputs"]["background_prompt"] = scene_context["prompt"]

        locks = recipe.get("locks") if isinstance(recipe.get("locks"), list) else []
        if "face" in locks:
            recipe["inputs"]["mask_ref"] = assets["face_mask"]
        elif "background" in locks:
            recipe["inputs"]["mask_ref"] = assets["outfit_mask"]
        elif "subject" in locks:
            recipe["inputs"]["mask_ref"] = assets["bg_mask"]

        if recipe.get("controlnet") == "openpose":
            recipe["inputs"]["controlnet"] = assets["pose_skeleton"]

        recipe.setdefault("params", {})
        if str(recipe["params"].get("mode") or "").lower() == "txt2img":
            recipe["params"]["mode"] = "img2img"
        if not allow_explicit:
            recipe["loras"] = [
                l for l in list(recipe.get("loras") or []) if "nsfw" not in str(l).lower()
            ]

        emotional_state = _apply_emotion_delta(emotional_state, action_id=action_id, scene_category=scene_context["category"])
        scene_memory = _apply_memory_update(scene_memory, scene_context, action_id)

        plan = ScenePlan(
            reply_text=turn["dialogue"],
            narration=turn["dialogue"],
            scene_prompt=turn["scene_prompt"],
            duration_sec=5,
            mood_delta={},
            topic_continuity=req.message or action_id,
            intent_code=action_id,
            confidence=1.0,
            edit_recipe=None,
        )
        job = submit_scene_job(session_id, turn_id=f"action_{action_id}", plan=plan)
        _JOB_RESULTS[job.id] = {"status": "queued"}
        repo.update_persona_session_runtime_state(
            session_id,
            dialogue=turn["dialogue"],
            scene_context=scene_context,
            scene_memory=scene_memory,
            emotional_state=emotional_state,
        )

        asyncio.create_task(
            _run_persona_job(
                job_id=job.id,
                session_id=session_id,
                persona_id=persona_id,
                media_mode=media_mode,
                recipe=recipe,
            ),
        )
        return {
            "ok": True,
            "job_id": job.id,
            "status": "queued",
            "scene_context": scene_context,
            "scene_memory": scene_memory,
            "emotional_state": emotional_state,
            "dialogue": {"text": turn["dialogue"]},
        }

    @router.get("/persona-live/jobs/{job_id}")
    @router.get("/api/persona-live/jobs/{job_id}")
    def job(job_id: str, _user: str = Depends(current_user)) -> Dict[str, Any]:
        cached = _JOB_RESULTS.get(job_id)
        if cached:
            return cached
        j = get_job(job_id)
        if not j:
            return {"ok": False, "error": "job_not_found"}
        if j.status == "ready":
            return {
                "status": "completed",
                "result": {
                    "version_id": "",
                    "media_url": resolve_asset_url(j.asset_id) if j.asset_id else "",
                    "xp_delta": 0,
                    "new_unlocks": [],
                },
            }
        return {"status": j.status}

    # ── Asset library (pre-render pack) ──────────────────────────────────
    #
    # The library is the cache that turns "compliment her → blush" from a
    # 5-15s GPU wait into an instant response. Fast path reads from
    # persona_appearance.asset_library; build pass populates it.
    # Everything is additive — the live-render path keeps working when
    # the library is empty or PERSONA_LIVE_LIBRARY_LOOKUP is off.

    @router.get("/persona-live/{persona_id}/library")
    @router.get("/api/persona-live/{persona_id}/library")
    def library_status(persona_id: str, _user: str = Depends(current_user)) -> Dict[str, Any]:
        """Report what's in the library + what's missing per tier.

        Useful for the persona editor UI: render a coverage bar per tier
        ("Tier 1: 7/9 ready — 2 missing, click to build"). No rendering
        happens here — this is a pure read. Coverage is reported for both
        the SFW plan AND (when the persona allows) the NSFW plan, so the
        UI can show two separate coverage bars ("Base: 8/9", "Mature: 3/4").
        """
        allow_explicit = _allow_explicit(persona_id)
        built = pal.load_library(persona_id)
        sfw_coverage: Dict[str, Any] = {}
        for tier in (1, 2, 3):
            planned = pal.plan_library(tier, allow_explicit=False)
            missing = [s.asset_id for s in planned if s.asset_id not in built]
            sfw_coverage[f"tier_{tier}"] = {
                "planned": len(planned),
                "built": len(planned) - len(missing),
                "missing": missing,
            }

        nsfw_coverage: Dict[str, Any] = {}
        if allow_explicit:
            for tier in (1, 2, 3):
                # Only the explicit rows for this layer — compare against
                # the SFW plan so the UI can show "Mature: built/total"
                # as a delta on top of the baseline count.
                planned_full = pal.plan_library(tier, allow_explicit=True)
                planned_sfw = pal.plan_library(tier, allow_explicit=False)
                sfw_ids = {s.asset_id for s in planned_sfw}
                explicit_only = [s for s in planned_full if s.asset_id not in sfw_ids]
                missing = [s.asset_id for s in explicit_only if s.asset_id not in built]
                nsfw_coverage[f"tier_{tier}"] = {
                    "planned": len(explicit_only),
                    "built": len(explicit_only) - len(missing),
                    "missing": missing,
                }

        return {
            "ok": True,
            "persona_id": persona_id,
            "allow_explicit": allow_explicit,
            "lookup_enabled": pal.lookup_enabled(),
            "library": built,
            "coverage": {
                "sfw": sfw_coverage,
                "nsfw": nsfw_coverage,
            },
        }

    @router.post("/persona-live/{persona_id}/library/build")
    @router.post("/api/persona-live/{persona_id}/library/build")
    async def library_build(
        persona_id: str,
        req: PersonaLiveLibraryBuildRequest,
        user: str = Depends(current_user),
    ) -> Dict[str, Any]:
        """Render every missing asset in the requested tier (idempotent).

        Wraps ``pal.build_library`` with a render callback that routes
        each AssetSpec through the same ``render_scene_async`` adapter
        the live-play path uses, anchored on the persona's portrait via
        img2img — so identity stays locked across the whole pack.

        Blocks until the pass finishes. Per-asset failures are non-fatal
        and reported in the response ``failures`` list.
        """
        from ..playback.render_adapter import render_scene_async  # late import

        persona = _load_persona(persona_id)
        if not persona or not persona.get("avatar_url"):
            return {"ok": False, "error": "persona_missing_portrait"}

        allow_explicit = bool(persona.get("allow_explicit"))
        persona_hint = ", ".join([
            str(persona.get("name") or "").strip(),
            str(persona.get("archetype") or "").strip(),
        ]).strip(", ")

        async def _render_one(spec: pal.AssetSpec) -> Optional["pal.RenderResult"]:
            """Build a per-spec edit recipe + submit to the renderer."""
            # composition routes to avatar_expression_change because
            # edit_inpaint_cn needs a face mask + ControlNet input we
            # don't have here — same fix applied in generator_auto.
            workflow_map = {
                "expression":    "avatar_expression_change",
                "pose":          "avatar_body_pose",
                "outfit":        "avatar_inpaint_outfit",
                "bg":            "change_background",
                "composition":   "avatar_expression_change",
            }
            edit_recipe = {
                "workflow_id": workflow_map.get(spec.edit_hint, "edit"),
                "category": spec.kind,
                "params": {"mode": "img2img", "steps": 28, "cfg": 5.0, "denoise": 0.45},
                "locks": ["face"] if spec.edit_hint == "expression" else [],
            }
            scene_prompt = f"{spec.prompt_fragment}, identity locked, same subject, tasteful"
            try:
                asset_id = await render_scene_async(
                    scene_prompt=scene_prompt,
                    duration_sec=5,
                    session_id=f"lib_{persona_id}",
                    persona_hint=persona_hint,
                    media_type="image",
                    edit_recipe=edit_recipe,
                    persona_project_id=persona_id,
                    user_id=user,
                )
            except Exception as exc:  # noqa: BLE001 — reported per-asset
                log.warning(
                    "persona_library_render_error asset=%s: %s",
                    spec.asset_id, str(exc)[:200],
                )
                return None
            if not asset_id:
                return None
            url = str(resolve_asset_url(asset_id) or "")
            if not url:
                return None
            return pal.RenderResult(asset_id=asset_id, url=url)

        stats = await pal.build_library(
            persona_id,
            render_fn=_render_one,
            max_tier=int(req.tier or 1),
            allow_explicit=allow_explicit,
        )
        return {
            "ok": True,
            "persona_id": persona_id,
            "tier": int(req.tier or 1),
            "allow_explicit": allow_explicit,
            "stats": {
                "total": stats.total,
                "rendered": stats.rendered,
                "skipped": stats.skipped,
                "failed": stats.failed,
            },
            "failures": stats.failures,
        }

    @router.post("/persona-live/session/{session_id}/restore")
    @router.post("/api/persona-live/session/{session_id}/restore")
    def restore(session_id: str, req: PersonaLiveRestoreRequest, _user: str = Depends(current_user)) -> Dict[str, Any]:
        state = repo.restore_persona_version(session_id, req.version_id)
        version = repo.get_persona_version(req.version_id)
        return {
            "ok": bool(state and version),
            "current_version_id": str((state or {}).get("current_version_id") or ""),
            "media_url": str((version or {}).get("image_url") or ""),
            "session": state or {},
            "version": version or {},
        }

    @router.post("/persona-live/session/{session_id}/chat")
    @router.post("/api/persona-live/session/{session_id}/chat")
    async def chat(session_id: str, req: PersonaLiveChatRequest, _user: str = Depends(current_user)) -> Dict[str, Any]:
        sess = repo.get_persona_session(session_id)
        if not sess:
            return {"ok": False, "error": "session_not_found"}

        scene_context = _normalize_scene(sess.get("scene_context"))
        scene_memory = _normalize_memory(sess.get("scene_memory"), scene_context)
        emotional_state = _normalize_emotion(sess.get("emotional_state"))

        persona = _load_persona(str(sess.get("persona_id") or ""))
        turn = await _compose_turn(
            message=req.message,
            action_id="chat",
            scene_context=scene_context,
            emotional_state=emotional_state,
            scene_memory=scene_memory,
            persona=persona,
            adult_llm=str(persona.get("adult_llm") or "").strip() or None,
        )
        scene_change_id = str(turn.get("scene_change") or "")
        if scene_change_id:
            scene_context = _scene_by_id(scene_change_id)
            scene_memory = _apply_memory_update(scene_memory, scene_context, "scene_change")

        emotional_state = _apply_emotion_delta(
            emotional_state,
            action_id="chat",
            scene_category=scene_context["category"],
        )
        repo.update_persona_session_runtime_state(
            session_id,
            dialogue=turn["dialogue"],
            scene_context=scene_context,
            scene_memory=scene_memory,
            emotional_state=emotional_state,
        )

        # Chat earns a smaller XP delta than tap-actions — actions
        # are higher-intent, multi-modal beats (text + photo) and
        # should pay more. Without ANY chat XP, free-form
        # conversation felt unrewarding: the bar didn't move while
        # the user was talking, only when they tapped a Live Action.
        # 2 XP per chat keeps action taps the dominant path to
        # leveling up while still acknowledging conversation.
        before_chat = repo.get_persona_session(session_id) or {}
        before_level_chat = int(before_chat.get("current_level") or 1)
        progressed = repo.update_persona_session_progress(
            session_id, xp_delta=2,
        ) or before_chat
        new_xp_chat = int(progressed.get("xp") or 0)
        new_level_chat = int(progressed.get("current_level") or before_level_chat)
        xp_to_next_chat = max(0, (new_level_chat * 35) - new_xp_chat)

        suggestion = _suggest_action(req.message)
        return {
            "ok": True,
            "dialogue": {"text": turn["dialogue"]},
            "scene_context": scene_context,
            "scene_memory": scene_memory,
            "emotional_state": emotional_state,
            "optional_action_suggestion": suggestion,
            "xp": new_xp_chat,
            "level": new_level_chat,
            "xp_to_next": xp_to_next_chat,
            "xp_delta": 2,
        }

    return router


def _scene_by_id(scene_id: str) -> Dict[str, str]:
    key = (scene_id or "").strip().lower()
    return dict(_SCENE_LIBRARY.get(key) or _SCENE_LIBRARY["apartment"])


def _normalize_scene(raw: Any) -> Dict[str, str]:
    if isinstance(raw, dict) and raw.get("id") in _SCENE_LIBRARY:
        return _scene_by_id(str(raw.get("id") or ""))
    return _scene_by_id("apartment")


def _normalize_memory(raw: Any, scene_context: Dict[str, str]) -> Dict[str, Any]:
    base = {
        "current_scene": scene_context["id"],
        "previous_scenes": [],
        "last_actions": [],
        "emotional_state": {"mood": "guarded", "intensity": 25},
    }
    if not isinstance(raw, dict):
        return base
    prev_scenes = [str(x) for x in list(raw.get("previous_scenes") or []) if x]
    actions = [str(x) for x in list(raw.get("last_actions") or []) if x]
    mood_state = raw.get("emotional_state") if isinstance(raw.get("emotional_state"), dict) else {}
    return {
        "current_scene": str(raw.get("current_scene") or scene_context["id"]),
        "previous_scenes": prev_scenes[-8:],
        "last_actions": actions[-6:],
        "emotional_state": {
            "mood": str(mood_state.get("mood") or "guarded"),
            "intensity": max(0, min(100, int(mood_state.get("intensity") or 25))),
        },
    }


def _normalize_emotion(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {
            "trust": 35, "intensity": 25, "mood": "guarded",
            "affection": 20, "comfort": 50, "playfulness": 25,
        }
    trust = max(0, min(100, int(raw.get("trust") or 35)))
    intensity = max(0, min(100, int(raw.get("intensity") or 25)))
    mood = str(raw.get("mood") or _mood_for_trust(trust))
    # Hidden stats (additive — older sessions defaulted to None and we
    # back-fill so the catalog deltas have a sensible starting point).
    affection = max(0, min(100, int(raw.get("affection") if raw.get("affection") is not None else max(0, trust - 15))))
    comfort = max(0, min(100, int(raw.get("comfort") if raw.get("comfort") is not None else min(100, trust + 15))))
    playfulness = max(0, min(100, int(raw.get("playfulness") or 25)))
    return {
        "trust": trust,
        "intensity": intensity,
        "mood": mood,
        "affection": affection,
        "comfort": comfort,
        "playfulness": playfulness,
    }


async def _compose_turn(
    *,
    message: str,
    action_id: str,
    scene_context: Dict[str, str],
    emotional_state: Dict[str, Any],
    scene_memory: Dict[str, Any],
    persona: Optional[Dict[str, Any]] = None,
    adult_llm: Optional[str] = None,
) -> Dict[str, Any]:
    fallback = _compose_turn_fallback(
        message=message,
        action_id=action_id,
        scene_context=scene_context,
        emotional_state=emotional_state,
        scene_memory=scene_memory,
        persona=persona,
    )
    persona_name = str((persona or {}).get("name") or "persona")
    persona_archetype = str((persona or {}).get("archetype") or "companion")
    persona_style = str((persona or {}).get("style_hint") or "").strip()
    allow_explicit = bool((persona or {}).get("allow_explicit", False))
    # Tier precedence: explicit override on emotional_state (set when
    # the caller ties the experience's audience_profile.nsfw_ceiling in)
    # → persona's allow_explicit opt-in (→ "explicit") → Persona Live
    # baseline of "suggestive" (fan-service but clothed). The safety
    # gate further clamps the final render if the workflow emits a
    # prompt above the configured ceiling.
    requested_tier = str(emotional_state.get("nsfw_tier") or "").lower()
    if not requested_tier:
        requested_tier = "explicit" if allow_explicit else "suggestive"
    tier = effective_tier(requested_tier, allow_explicit=allow_explicit)
    safe_action = (action_id or "chat").strip().lower()
    safe_message = (message or "").strip()
    system_prompt = compose_system_prompt(
        tier=tier,
        allow_explicit=allow_explicit,
        persona_archetype=persona_archetype,
        persona_style_hint=persona_style,
    )
    user_prompt = (
        f"persona_name={persona_name}\n"
        f"persona_archetype={persona_archetype}\n"
        f"persona_style={persona_style}\n"
        f"action_id={safe_action}\n"
        f"user_message={safe_message}\n"
        f"scene={scene_context.get('label')}\n"
        f"scene_prompt={scene_context.get('prompt')}\n"
        f"mood={emotional_state.get('mood')}\n"
        f"trust={emotional_state.get('trust')}\n"
        f"recent_actions={list(scene_memory.get('last_actions') or [])[-3:]}\n"
        f"previous_scenes={list(scene_memory.get('previous_scenes') or [])[-3:]}\n"
        "Return JSON only."
    )
    try:
        # ``adult_llm`` is the per-experience model override for
        # mature_gated runs — operator picked it in Step 0 to bypass
        # the default Llama 3 / 3.2's "I cannot create content..."
        # refusal. Empty / None means "use the server default" which
        # chat_ollama resolves itself.
        response = await chat_ollama(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            max_tokens=320,
            model=adult_llm or None,
            response_format="json",
        )
        content = ""
        choices = response.get("choices") if isinstance(response, dict) else None
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message_block = first.get("message") if isinstance(first.get("message"), dict) else {}
            content = str(message_block.get("content") or "").strip()
        payload = json.loads(content) if content else {}
        if not isinstance(payload, dict):
            return fallback
        dialogue = str(payload.get("dialogue") or "").strip() or fallback["dialogue"]
        scene_prompt = str(payload.get("scene_prompt") or "").strip() or fallback["scene_prompt"]
        if "same subject" not in scene_prompt.lower():
            scene_prompt = f"{scene_prompt}, same subject, identity locked"
        edit_hint = str(payload.get("edit_hint") or "").strip().lower()
        if edit_hint not in {"expression", "pose", "outfit", "bg"}:
            edit_hint = fallback["edit_hint"]
        scene_change = str(payload.get("scene_change") or "").strip().lower()
        if scene_change and scene_change not in _SCENE_LIBRARY:
            scene_change = ""
        return {
            "scene_prompt": scene_prompt,
            "dialogue": dialogue,
            "edit_hint": edit_hint,
            "scene_change": scene_change or None,
        }
    except Exception as exc:
        log.warning("persona_live_turn_llm_failed: %s", str(exc)[:240])
        return fallback


def _compose_turn_fallback(
    *,
    message: str,
    action_id: str,
    scene_context: Dict[str, str],
    emotional_state: Dict[str, Any],
    scene_memory: Dict[str, Any],
    persona: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    text = (message or "").strip()
    aid = (action_id or "").strip().lower()
    mood = str(emotional_state.get("mood") or "guarded")
    tone = _tone_for_scene(scene_context["category"], mood)
    lower = text.lower()

    scene_change = ""
    if aid == "move_to_beach" or "outside" in lower or "beach" in lower:
        scene_change = "beach"
    elif "store" in lower or "market" in lower:
        scene_change = "supermarket"
    elif aid == "make_it_rain" or "rain" in lower:
        scene_change = "rainstreet"

    action_words = aid.replace("_", " ") if aid else "talk"
    memory_hint = ""
    previous_scenes = list(scene_memory.get("previous_scenes") or [])
    if previous_scenes:
        memory_hint = f" You were quieter back in {previous_scenes[-1].replace('_', ' ')}."

    persona_name = str((persona or {}).get("name") or "persona")
    persona_archetype = str((persona or {}).get("archetype") or "companion")
    persona_style = str((persona or {}).get("style_hint") or "").strip()
    allow_explicit = bool((persona or {}).get("allow_explicit", False))
    fallback_tier = effective_tier(
        str(emotional_state.get("nsfw_tier") or "").lower()
        or ("explicit" if allow_explicit else "suggestive"),
        allow_explicit=allow_explicit,
    )

    dialogue = (
        f"{tone} {text}." if text else f"{tone} I can {action_words} right here."
    ).strip()
    dialogue = dialogue + memory_hint

    edit_hint = _edit_hint_for_action(aid)

    # Deterministic scene prompt: pick ladder position from trust
    # (0-100 → 0-4) so the fallback still varies outfit / pose /
    # expression over time instead of repeating the same caption.
    trust_score = int(emotional_state.get("trust") or 35)
    emotional_level = max(0, min(4, trust_score // 20))
    axis_map: Dict[str, str] = {
        "expression": "expression",
        "pose": "pose",
        "outfit": "outfit",
        "bg": "environment",
    }
    base_subject = (
        f"{persona_name}, {persona_archetype}, identity locked, same subject"
    )
    if persona_style:
        base_subject = f"{base_subject}, style={persona_style}"
    scene_prompt = compose_image_prompt(
        base_subject=base_subject,
        axis=axis_map.get(edit_hint, "expression"),  # type: ignore[arg-type]
        tier=fallback_tier,
        allow_explicit=allow_explicit,
        emotional_level=emotional_level,
        environment_key=_env_key_for(scene_context.get("id") or ""),
    )
    if scene_change:
        scene_prompt = f"{scene_prompt}, scene_change={scene_change}"
    if aid == "chat" and scene_change:
        edit_hint = "bg"

    return {
        "scene_prompt": scene_prompt,
        "dialogue": dialogue,
        "edit_hint": edit_hint,
        "scene_change": scene_change or None,
    }


def _env_key_for(scene_id: str) -> str:
    """Map _SCENE_LIBRARY ids to ENVIRONMENT_LIB keys so the shared
    vocabulary ladder produces identity-consistent backgrounds. Unknown
    scenes fall through to an empty string (no environment fragment)."""
    mapping = {
        "apartment": "livingroom",
        "beach": "beach",
        "supermarket": "kitchen",
        "rainstreet": "nightcity",
    }
    return mapping.get((scene_id or "").strip().lower(), "")


def _edit_hint_for_action(action_id: str) -> str:
    aid = (action_id or "").strip().lower()
    if aid in {"tease", "smirk", "blush", "ahegao"}:
        return "expression"
    if aid in {"dance", "closer_pose", "turn_around"}:
        return "pose"
    if aid in {"outfit_change"}:
        return "outfit"
    if aid in {"move_to_beach", "make_it_rain", "zoom_out", "scene_change"}:
        return "bg"
    return "expression"


def _tone_for_scene(scene_category: str, mood: str) -> str:
    if scene_category == "public":
        return "Here? Behave."
    if mood in {"warm", "confident"}:
        return "Come closer"
    if mood == "playful":
        return "You are trouble"
    return "Careful"


def _mood_for_trust(trust: int) -> str:
    if trust < 35:
        return "guarded"
    if trust < 70:
        return "playful"
    return "warm"


def _apply_emotion_delta(emotion: Dict[str, Any], *, action_id: str, scene_category: str) -> Dict[str, Any]:
    """Apply per-action stat deltas with the new intent catalog.

    Three new hidden stats — ``affection`` (does she like you),
    ``comfort`` (does she feel safe), ``playfulness`` (teasing energy)
    — track the dimensions the user asked for. The legacy ``trust``
    field stays as a derived alias of ``affection + comfort`` so any
    caller / test that reads emotion.trust keeps working with a value
    that means the same thing it always did.
    """
    aid = (action_id or "").strip().lower()
    affection = int(emotion.get("affection") or 0)
    comfort = int(emotion.get("comfort") or 0)
    playfulness = int(emotion.get("playfulness") or 0)
    intensity = int(emotion.get("intensity") or 0)

    # Catalog wins; legacy actions fall through to a small per-id table
    # so existing sessions / tests with raw "tease" / "smirk" / "dance"
    # ids keep producing the same behaviour they always did.
    catalog_entry = _INTENT_CATALOG.get(aid) or {}
    delta = dict(catalog_entry.get("delta") or {})
    if not delta:
        legacy_delta = {
            "tease": {"affection": 1, "comfort": 0, "playfulness": 3},
            "smirk": {"affection": 1, "comfort": 0, "playfulness": 2},
            "blush": {"affection": 2, "comfort": 1, "playfulness": 1},
            "dance": {"affection": 1, "comfort": 0, "playfulness": 4},
            "closer_pose": {"affection": 2, "comfort": 2, "playfulness": 2},
            "turn_around": {"affection": 0, "comfort": 0, "playfulness": 1},
            "outfit_change": {"affection": 0, "comfort": -1, "playfulness": 2},
            "chat": {"affection": 1, "comfort": 1, "playfulness": 0},
        }.get(aid, {"affection": 1, "comfort": 0, "playfulness": 0})
        delta = dict(legacy_delta)

    intensity_delta = {
        "tease": 4, "blush": 3, "dance": 5, "closer_pose": 4,
        "turn_around": 3, "make_it_rain": 1, "chat": 2,
    }.get(aid, max(2, sum(delta.values())))

    # Public-scene safety clamp — intimacy doesn't level up at the
    # supermarket. Applies to both legacy and new intent ids.
    if scene_category == "public" and aid in {
        "closer_pose", "get_closer", "lean_in", "ahegao",
    }:
        for key in ("affection", "comfort", "playfulness"):
            delta[key] = min(0, int(delta.get(key, 0)))
        intensity_delta = max(0, intensity_delta - 3)

    affection = max(0, min(100, affection + int(delta.get("affection", 0))))
    comfort = max(0, min(100, comfort + int(delta.get("comfort", 0))))
    playfulness = max(0, min(100, playfulness + int(delta.get("playfulness", 0))))
    intensity = max(0, min(100, intensity + intensity_delta))

    # Trust = halfway between affection and comfort. Keeps the legacy
    # field shape; readers get a value with the same semantics as before.
    trust = max(0, min(100, (affection + comfort) // 2))

    return {
        "trust": trust,
        "intensity": intensity,
        "mood": _mood_for_trust(trust),
        "affection": affection,
        "comfort": comfort,
        "playfulness": playfulness,
    }


def _apply_memory_update(memory: Dict[str, Any], scene_context: Dict[str, str], action_id: str) -> Dict[str, Any]:
    previous = [str(x) for x in list(memory.get("previous_scenes") or []) if x]
    current_scene = str(memory.get("current_scene") or "")
    new_scene = scene_context["id"]
    if current_scene and current_scene != new_scene:
        previous.append(current_scene)

    actions = [str(x) for x in list(memory.get("last_actions") or []) if x]
    if action_id:
        actions.append(action_id)

    emo = memory.get("emotional_state") if isinstance(memory.get("emotional_state"), dict) else {}
    return {
        "current_scene": new_scene,
        "previous_scenes": previous[-8:],
        "last_actions": actions[-6:],
        "emotional_state": {
            "mood": str(emo.get("mood") or "guarded"),
            "intensity": max(0, min(100, int(emo.get("intensity") or 25))),
        },
    }


def _suggest_action(message: str) -> Optional[Dict[str, str]]:
    lower = (message or "").lower()
    if "outside" in lower or "beach" in lower:
        return {"id": "move_to_beach", "label": "Go outside"}
    if "closer" in lower:
        return {"id": "closer_pose", "label": "Come closer"}
    if "dance" in lower:
        return {"id": "dance", "label": "Dance"}
    return None


def _pick_anchor_image_ref(*, current_image_url: str, persona_avatar_url: str, resolved_portrait: str) -> str:
    local_like: List[str] = []
    for candidate in (current_image_url, persona_avatar_url, resolved_portrait):
        c = str(candidate or "").strip()
        if not c:
            continue
        if c.startswith("/files/") or os.path.isfile(c):
            local_like.append(c)
            continue
    for c in local_like:
        if c.startswith("/files/"):
            return c
        if os.path.isfile(c):
            return c
    return ""


def _load_persona(persona_id: str) -> Dict[str, Any]:
    try:
        from ... import projects

        data = projects.get_project_by_id(persona_id) or {}
    except Exception:
        data = {}
    appearance = data.get("persona_appearance") if isinstance(data, dict) else {}
    selected_filename = ""
    if isinstance(appearance, dict):
        selected_filename = str(appearance.get("selected_filename") or "")
    archetype = ""
    persona_agent = data.get("persona_agent") if isinstance(data, dict) else {}
    if isinstance(persona_agent, dict):
        archetype = str(persona_agent.get("persona_class") or "")
    style_hint = ""
    if isinstance(persona_agent, dict):
        style_hint = str(
            persona_agent.get("response_style", {}).get("tone")
            if isinstance(persona_agent.get("response_style"), dict) else "",
        ).strip()
    safety = persona_agent.get("safety") if isinstance(persona_agent, dict) else {}
    allow_explicit = bool((safety or {}).get("allow_explicit", False))
    # Per-persona LLM override — populated by the wizard's Phase 3
    # when the operator picked a Storyteller LLM in Step 0 for a
    # Mature (gated) experience. Falls back to the server default
    # when empty. Persists on the persona project so subsequent
    # Persona Live sessions for this persona reuse the override
    # without the operator re-selecting it.
    adult_llm = ""
    if isinstance(persona_agent, dict):
        adult_llm = str(persona_agent.get("llm_override") or "").strip()
    return {
        "id": persona_id,
        "name": str((data or {}).get("name") or (persona_agent or {}).get("label") or "Persona"),
        "avatar_url": f"/files/{selected_filename}" if selected_filename else "",
        "archetype": archetype or "companion",
        "style_hint": style_hint,
        "allow_explicit": allow_explicit,
        "adult_llm": adult_llm,
    }


def _allow_explicit(persona_id: str) -> bool:
    try:
        from ... import projects

        data = projects.get_project_by_id(persona_id) or {}
    except Exception:
        return False
    agent = data.get("persona_agent") if isinstance(data, dict) else {}
    safety = agent.get("safety") if isinstance(agent, dict) else {}
    return bool((safety or {}).get("allow_explicit", False))


def _default_levels(vibe: str, allow_explicit: bool) -> List[Dict[str, Any]]:
    """Intent-driven action ladder.

    Each level lists PLAYER INTENTS (Compliment her / Stay quiet /
    Suggest a different outfit), not character output names. The
    renderer translates intent → reaction_intent at action time so the
    existing edit recipes still apply — see ``_intent_to_render_key``.
    """
    base = [
        {"level": 1, "actions": ["say_playful", "compliment", "ask_about_her", "stay_quiet"]},
        {"level": 2, "actions": ["get_closer", "ask_personal"]},
        {"level": 3, "actions": ["change_view", "step_back"]},
        {"level": 4, "actions": ["suggest_outfit", "change_location"]},
    ]
    if allow_explicit and "explicit" in (vibe or "").lower():
        base.append({"level": 5, "actions": ["lean_in"]})
    else:
        base.append({"level": 5, "actions": ["playful_dare"]})
    return base


def _actions_for_level(level: int, levels: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Surface available + locked actions for the current viewer level.

    Labels and descriptions come from ``_INTENT_CATALOG`` so the panel
    shows the player-facing intent text ("Say something playful") and
    not the renderer key ("smirk") or a title-cased action_id.
    """
    available: List[Dict[str, Any]] = []
    locked: List[Dict[str, Any]] = []
    for block in levels:
        lv = int(block.get("level") or 1)
        for action_id in list(block.get("actions") or []):
            entry = _INTENT_CATALOG.get(action_id, {})
            label = str(entry.get("label") or action_id.replace("_", " ").title())
            description = str(entry.get("description") or "")
            category = str(entry.get("category") or _ACTION_CATEGORY_MAP.get(action_id, "expression"))
            item: Dict[str, Any] = {
                "id": action_id,
                "label": label,
                "category": category,
            }
            if description:
                item["description"] = description
            if lv <= level:
                available.append(item)
            else:
                locked.append({**item, "unlock_level": lv})
    return {"available": available, "locked": locked}


async def _run_persona_job(*, job_id: str, session_id: str, persona_id: str, media_mode: str, recipe: Dict[str, Any]) -> None:
    _JOB_RESULTS[job_id] = {"status": "rendering"}
    before = repo.get_persona_session(session_id) or {}
    before_level = int(before.get("current_level") or 1)
    completed = await render_now_async(
        job_id,
        media_type="video" if media_mode == "video" else "image",
        recipe=recipe,
        persona_project_id=persona_id,
    )
    asset_id = str((completed.asset_id if completed else "") or "")
    asset_url = resolve_asset_url(asset_id) if asset_id else ""
    version_id = ""
    if asset_url:
        version = repo.save_persona_version(
            persona_id=persona_id,
            session_id=session_id,
            image_url=asset_url,
            thumb_url=asset_url,
            recipe=recipe,
        )
        version_id = str(version.get("id") or "")
    after = repo.update_persona_session_progress(session_id, xp_delta=10) or before
    after_level = int(after.get("current_level") or before_level)
    new_unlocks: List[Dict[str, Any]] = []
    if after_level > before_level:
        levels = _default_levels(vibe="", allow_explicit=_allow_explicit(persona_id))
        for block in levels:
            if int(block.get("level") or 1) == after_level:
                new_unlocks.extend([
                    {"id": aid, "label": str(aid).replace("_", " ").title()}
                    for aid in list(block.get("actions") or [])
                ])
    _JOB_RESULTS[job_id] = {
        "status": "completed",
        "result": {
            "version_id": version_id,
            "media_url": asset_url,
            "xp_delta": 10,
            "level": after_level,
            "xp": int(after.get("xp") or 0),
            "xp_to_next": max(0, (after_level * 35) - int(after.get("xp") or 0)),
            "new_unlocks": new_unlocks,
        },
    }
