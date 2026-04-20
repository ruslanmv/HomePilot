"""
LLM-backed scene composer (phase-2 swap for scene_planner._compose).

Takes the same inputs as the heuristic composer — SceneMemory,
viewer text, IntentMatch, persona hint — and returns the same
``ScenePlan`` dataclass. The only difference is where the reply
text + scene prompt come from: a chat call to the configured
Ollama / OpenAI-compatible backend, with strict JSON mode.

Contract:
  compose_with_llm(...) -> ScenePlan | None
     None means "couldn't reach the LLM, or the response was
     malformed" — callers fall back to the heuristic composer.

Keeping the return type nullable lets the call-site stay a
one-liner: `plan = await compose_with_llm(...) or heuristic(...)`.
No exceptions escape this module; every failure is translated
into a None with a structured log line so operators can see why
the fallback fired.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from ...llm import chat_ollama
from ..policy.classifier import IntentMatch
from ..prompts import PromptLibraryError, default_library
from .edit_recipes import EDIT_HINTS, pick_recipe
from .persona_profile import load_persona_prompt_vars
from .playback_config import PlaybackConfig, load_playback_config
from .scene_memory import SceneMemory, TurnSnapshot
from .scene_planner import ScenePlan


log = logging.getLogger(__name__)


# Strict whitelist of mood tokens the runtime will apply.
_ALLOWED_MOODS = {"neutral", "shy", "flirty", "playful", "warm", "cold"}

# Per-turn affinity clamp so a single misbehaving reply can't
# jump the viewer to intimate in one message.
_MAX_AFFINITY_DELTA = 0.2


async def compose_with_llm(
    memory: SceneMemory,
    text: str,
    classification: IntentMatch,
    *,
    persona_hint: str = "",
    duration_sec: int = 5,
    config: Optional[PlaybackConfig] = None,
    persona_project_id: str = "",
    persona_label: str = "",
    synopsis: str = "",
    allow_explicit: bool = False,
) -> Optional[ScenePlan]:
    """Ask the LLM for the next scene. Returns None on failure.

    When ``persona_project_id`` is provided, the prompt is rendered
    from the ``personaplay.turn_compose`` YAML in the prompt library
    — it injects the persona's role, objective, traits, style
    weights, backstory, outfit and the current affinity tier, so
    the reply stays in-character across turns. Without a persona id
    (e.g. standard branching projects), we fall back to the generic
    inline prompt that ships reply + scene cues without persona
    grounding.
    """
    cfg = config or load_playback_config()
    if not cfg.llm_enabled:
        return None

    messages = _build_messages(
        memory=memory, text=text, classification=classification,
        persona_hint=persona_hint, duration_sec=duration_sec,
        persona_project_id=persona_project_id,
        persona_label=persona_label,
        synopsis=synopsis,
    )
    try:
        response = await asyncio.wait_for(
            chat_ollama(
                messages,
                temperature=cfg.llm_temperature,
                max_tokens=cfg.llm_max_tokens,
                response_format="json",
            ),
            timeout=cfg.llm_timeout_s,
        )
    except asyncio.TimeoutError:
        log.warning(
            "playback_llm_timeout after %.1fs",
            cfg.llm_timeout_s,
            extra={"session_id": memory.session_id},
        )
        return None
    except Exception as exc:  # noqa: BLE001 — any upstream failure → fallback
        log.warning(
            "playback_llm_error: %s",
            str(exc)[:400],
            extra={"session_id": memory.session_id},
        )
        return None

    content = _extract_content(response)
    if not content:
        log.warning(
            "playback_llm_empty_content (response had no message.content)",
            extra={"session_id": memory.session_id},
        )
        return None

    payload = _parse_json(content)
    if payload is None:
        log.warning(
            "playback_llm_malformed_json — first 200 chars: %r",
            content[:200],
            extra={"session_id": memory.session_id},
        )
        return None

    plan = _to_scene_plan(
        payload=payload, memory=memory, text=text,
        classification=classification, duration_sec=duration_sec,
        allow_explicit=allow_explicit,
    )
    return plan


# ── Prompt construction ─────────────────────────────────────────

def _build_messages(
    *, memory: SceneMemory, text: str, classification: IntentMatch,
    persona_hint: str, duration_sec: int,
    persona_project_id: str = "", persona_label: str = "",
    synopsis: str = "",
) -> List[Dict[str, Any]]:
    """Assemble an Ollama-style messages array.

    If a persona project is linked, try to render the
    ``personaplay.turn_compose`` prompt — that prompt is purpose-
    built for live-play mode and emits the exact same JSON shape.
    Any failure (missing prompt, missing persona project, render
    error) falls back to the generic inline system prompt so this
    path can't break standard playback.
    """
    system = _persona_system_prompt(
        memory=memory,
        persona_project_id=persona_project_id,
        persona_label=persona_label,
        viewer_text=text,
        intent_code=classification.intent_code or "",
        synopsis=synopsis,
        duration_sec=duration_sec,
    ) or _system_prompt(
        memory=memory, persona_hint=persona_hint, duration_sec=duration_sec,
    )
    context: List[Dict[str, Any]] = [{"role": "system", "content": system}]

    if memory.synopsis:
        context.append({
            "role": "system",
            "content": f"Story so far: {memory.synopsis}",
        })

    # Up to the last 6 turns verbatim, chronological.
    for turn in memory.recent_turns[-6:]:
        role = _turn_role_for_llm(turn)
        if role and turn.text:
            context.append({"role": role, "content": turn.text})

    # Current viewer turn + classification hint.
    current_content = text or "(empty)"
    hint = classification.intent_code or ""
    if hint:
        current_content += f"\n\n(intent hint: {hint})"
    context.append({"role": "user", "content": current_content})

    # Forcing JSON output format via explicit final instruction
    # so even models without native JSON mode still comply.
    context.append({
        "role": "system",
        "content": (
            'Respond with ONLY a JSON object on the fields: '
            '{"reply_text": str, "narration": str, "scene_prompt": str, '
            '"duration_sec": int, "mood_shift": str, "affinity_delta": float}. '
            "No prose. No markdown fences. Strict JSON."
        ),
    })
    return context


def _persona_system_prompt(
    *, memory: SceneMemory, persona_project_id: str, persona_label: str,
    viewer_text: str, intent_code: str, synopsis: str, duration_sec: int,
) -> str:
    """Render ``personaplay.turn_compose`` for the current turn.

    Returns an empty string on any failure so the caller falls back
    to the generic system prompt. This means a missing/corrupt
    persona never blocks a live-play session — the viewer still
    gets a reply, just without the persona-specific grounding.
    """
    if not persona_project_id and not persona_label:
        return ""
    try:
        vars_ = load_persona_prompt_vars(
            persona_project_id,
            persona_label=persona_label,
            persona_emotion=memory.mood or "neutral",
            affinity_score=memory.affinity_score,
            synopsis=synopsis or memory.synopsis or "",
            viewer_message=viewer_text or "",
            intent_hint=intent_code or "",
            duration_sec=duration_sec,
        )
        if not vars_:
            return ""
        rendered = default_library().render(
            "personaplay.turn_compose", **vars_,
        )
    except (PromptLibraryError, Exception) as exc:  # noqa: BLE001
        log.warning(
            "persona_live_play prompt render failed: %s", str(exc)[:200],
            extra={"session_id": memory.session_id},
        )
        return ""
    # Combine system + user into a single system block — the LLM
    # client below will still append the conversation turns as
    # separate messages. Keeping both halves together preserves the
    # prompt authors' intent without restructuring the messages
    # array contract.
    return rendered.system + "\n\n" + rendered.user


def _system_prompt(*, memory: SceneMemory, persona_hint: str, duration_sec: int) -> str:
    mood = memory.mood or "neutral"
    tier = _affinity_tier(memory.affinity_score)
    persona = persona_hint.strip() or "warm, engaged conversational partner"
    outfit = _outfit_sentence(memory.outfit_state)
    return (
        "You are an AI character in an interactive video experience. "
        f"Persona: {persona}. Current mood: {mood}. "
        f"Viewer affinity: {tier} ({int(memory.affinity_score * 100)}%). "
        f"{outfit}"
        "\nYour job: respond in character AND describe the next ~"
        f"{max(2, min(int(duration_sec), 15))}s scene that should play behind the reply. "
        "Allowed mood_shift values: neutral, shy, flirty, playful, warm, cold. "
        "affinity_delta must be between -0.2 and +0.2. "
        "Keep reply_text to 1-3 short sentences. "
        "Keep scene_prompt to a comma-separated list of visual cues (face, lighting, pose, outfit). "
        "Never describe minors, violence, or non-consensual content. "
        "If the viewer's message is ambiguous, ask a short clarifying question in character."
    )


def _outfit_sentence(outfit: Dict[str, Any]) -> str:
    if not outfit:
        return ""
    bits: List[str] = []
    for key in ("top", "bottom", "accessory", "hair"):
        val = outfit.get(key)
        if isinstance(val, str) and val:
            bits.append(f"{key} {val}")
    if not bits:
        return ""
    return f"Wearing: {', '.join(bits)}. "


_AFFINITY_TIERS = (
    (0.75, "close"),
    (0.5, "warm"),
    (0.2, "friendly"),
    (0.0, "stranger"),
)


def _affinity_tier(score: float) -> str:
    for threshold, label in _AFFINITY_TIERS:
        if score >= threshold:
            return label
    return "stranger"


def _turn_role_for_llm(turn: TurnSnapshot) -> str:
    """Map stored turn_role → chat-completion role."""
    role = (turn.role or "").lower()
    if role in ("user", "viewer"):
        return "user"
    if role in ("assistant", "character"):
        return "assistant"
    if role == "system":
        return "system"
    return ""


# ── Response parsing ────────────────────────────────────────────

def _extract_content(response: Dict[str, Any]) -> str:
    """Dig ``content`` out of a chat-completion response envelope."""
    choices = response.get("choices") if isinstance(response, dict) else None
    if not choices or not isinstance(choices, list):
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    message = first.get("message") or {}
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    return ""


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json(content: str) -> Optional[Dict[str, Any]]:
    """Tolerate LLM quirks: strip code fences, pull out the first JSON block."""
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        # Drop an optional language tag (```json …)
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].lstrip()
    match = _JSON_BLOCK.search(stripped)
    if not match:
        return None
    try:
        payload = json.loads(match.group(0))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _to_scene_plan(
    *, payload: Dict[str, Any], memory: SceneMemory, text: str,
    classification: IntentMatch, duration_sec: int,
    allow_explicit: bool = False,
) -> Optional[ScenePlan]:
    reply_text = _trimmed_string(payload.get("reply_text"), max_len=600)
    scene_prompt = _trimmed_string(payload.get("scene_prompt"), max_len=400)
    if not reply_text or not scene_prompt:
        log.warning(
            "playback_llm_missing_fields — got keys %s (need reply_text + scene_prompt)",
            sorted(payload.keys()),
            extra={"session_id": memory.session_id},
        )
        return None

    narration = _trimmed_string(payload.get("narration"), max_len=400) or reply_text

    raw_duration = payload.get("duration_sec")
    try:
        duration = int(raw_duration) if raw_duration is not None else duration_sec
    except (TypeError, ValueError):
        duration = duration_sec
    duration = max(2, min(duration, 15))

    mood_delta: Dict[str, Any] = {}
    mood_shift = str(payload.get("mood_shift") or "").strip().lower()
    if mood_shift and mood_shift in _ALLOWED_MOODS:
        mood_delta["mood"] = mood_shift

    try:
        affinity_delta = float(payload.get("affinity_delta") or 0.0)
    except (TypeError, ValueError):
        affinity_delta = 0.0
    if affinity_delta:
        clamped = max(-_MAX_AFFINITY_DELTA, min(_MAX_AFFINITY_DELTA, affinity_delta))
        mood_delta["affinity"] = clamped

    continuity = _trimmed_string(text, max_len=120)

    # Persona Live Play extension: when the LLM tagged the turn
    # with a valid edit_hint, resolve it through the recipe router
    # so the render adapter can swap to the matching img2img /
    # inpaint workflow on the persona's canonical portrait. An
    # unknown / missing hint leaves ``edit_recipe=None`` and the
    # standard txt2img path runs as before.
    raw_hint = str(payload.get("edit_hint") or "").strip().lower()
    edit_recipe = None
    if raw_hint in EDIT_HINTS:
        edit_recipe = pick_recipe(raw_hint, allow_explicit=allow_explicit)

    return ScenePlan(
        reply_text=reply_text,
        narration=narration,
        scene_prompt=scene_prompt,
        duration_sec=duration,
        mood_delta=mood_delta,
        topic_continuity=continuity,
        intent_code=classification.intent_code or "smalltalk",
        confidence=float(classification.confidence or 0.0),
        edit_recipe=edit_recipe,
    )


def _trimmed_string(value: Any, *, max_len: int) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text
