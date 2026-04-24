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
        if not allow_explicit and action_id in {"ahegao"}:
            dialogue = "Not happening here. Keep it playful."
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
        )
        scene_change_id = str(turn.get("scene_change") or "")
        if scene_change_id:
            scene_context = _scene_by_id(scene_change_id)

        action_proxy = _ActionProxy(
            intent_code=action_id,
            category=_ACTION_CATEGORY_MAP.get(action_id, "expression"),
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

        suggestion = _suggest_action(req.message)
        return {
            "ok": True,
            "dialogue": {"text": turn["dialogue"]},
            "scene_context": scene_context,
            "scene_memory": scene_memory,
            "emotional_state": emotional_state,
            "optional_action_suggestion": suggestion,
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
        return {"trust": 35, "intensity": 25, "mood": "guarded"}
    trust = max(0, min(100, int(raw.get("trust") or 35)))
    intensity = max(0, min(100, int(raw.get("intensity") or 25)))
    mood = str(raw.get("mood") or _mood_for_trust(trust))
    return {"trust": trust, "intensity": intensity, "mood": mood}


async def _compose_turn(
    *,
    message: str,
    action_id: str,
    scene_context: Dict[str, str],
    emotional_state: Dict[str, Any],
    scene_memory: Dict[str, Any],
    persona: Optional[Dict[str, Any]] = None,
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
        response = await chat_ollama(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.6,
            max_tokens=320,
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
    trust = int(emotion.get("trust") or 0)
    intensity = int(emotion.get("intensity") or 0)
    aid = (action_id or "").strip().lower()

    trust_delta = {
        "tease": 2,
        "smirk": 1,
        "blush": 2,
        "dance": 3,
        "closer_pose": 4,
        "outfit_change": -1,
        "chat": 1,
    }.get(aid, 1)
    intensity_delta = {
        "tease": 4,
        "blush": 3,
        "dance": 5,
        "closer_pose": 4,
        "turn_around": 3,
        "make_it_rain": 1,
        "chat": 2,
    }.get(aid, 2)

    if scene_category == "public" and aid in {"closer_pose", "ahegao"}:
        trust_delta = min(trust_delta, 0)
        intensity_delta = max(0, intensity_delta - 3)

    trust = max(0, min(100, trust + trust_delta))
    intensity = max(0, min(100, intensity + intensity_delta))
    return {
        "trust": trust,
        "intensity": intensity,
        "mood": _mood_for_trust(trust),
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
    return {
        "id": persona_id,
        "name": str((data or {}).get("name") or (persona_agent or {}).get("label") or "Persona"),
        "avatar_url": f"/files/{selected_filename}" if selected_filename else "",
        "archetype": archetype or "companion",
        "style_hint": style_hint,
        "allow_explicit": allow_explicit,
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
    base = [
        {"level": 1, "actions": ["tease", "smirk", "blush"]},
        {"level": 2, "actions": ["dance", "closer_pose"]},
        {"level": 3, "actions": ["turn_around", "zoom_out"]},
        {"level": 4, "actions": ["outfit_change", "move_to_beach"]},
    ]
    if allow_explicit and "explicit" in (vibe or "").lower():
        base.append({"level": 5, "actions": ["ahegao"]})
    else:
        base.append({"level": 5, "actions": ["make_it_rain"]})
    return base


def _actions_for_level(level: int, levels: List[Dict[str, Any]]) -> Dict[str, Any]:
    available: List[Dict[str, Any]] = []
    locked: List[Dict[str, Any]] = []
    for block in levels:
        lv = int(block.get("level") or 1)
        for action_id in list(block.get("actions") or []):
            item = {
                "id": action_id,
                "label": action_id.replace("_", " ").title(),
                "category": _ACTION_CATEGORY_MAP.get(action_id, "expression"),
            }
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
