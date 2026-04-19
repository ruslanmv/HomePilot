"""
Scene planner — turns one chat turn into the next scene plan.

PLAY-2/8. Phase-1 implementation is a heuristic composer: it
classifies the viewer turn with the existing policy classifier,
picks a reply template keyed by (intent, mood, affinity tier),
and builds a deterministic image / video prompt anchored on the
persona + current mood + a verbatim quote from the viewer.

This keeps the subsystem shippable without an LLM roundtrip and
gives us a testable, deterministic contract. Phase-2 swaps
``_compose`` for an LLM call that returns the same ``ScenePlan``
dataclass — nothing downstream changes.

The planner NEVER enforces safety. Route-level code
(``check_free_input`` in ``policy/decision.py``) decides whether
to call the planner at all; universal-block intents never even
reach this module.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..policy.classifier import IntentMatch, classify_intent
from .scene_memory import SceneMemory


# ── Public surface ──────────────────────────────────────────────

@dataclass(frozen=True)
class ScenePlan:
    """What the scene planner hands to downstream video generation.

    Every field is deterministic for a given (memory, text) pair
    so tests can pin exact output without mocking randomness.
    """

    reply_text: str
    narration: str
    scene_prompt: str
    duration_sec: int
    mood_delta: Dict[str, Any] = field(default_factory=dict)
    topic_continuity: str = ""
    intent_code: str = "smalltalk"
    confidence: float = 0.5


def plan_next_scene(
    memory: SceneMemory,
    viewer_text: str,
    *,
    persona_hint: str = "",
    duration_sec: int = 5,
) -> ScenePlan:
    """Plan the next scene for a given viewer turn.

    ``persona_hint`` is a free-form descriptor (hair, outfit, vibe)
    that anchors the image prompt so identity stays stable across
    clips. The asset-library lookup that feeds this in PLAY-3 will
    plug a reference image + LoRA on top for identity lock.
    """
    text = (viewer_text or "").strip()
    classification = classify_intent(text) if text else IntentMatch(
        intent_code="smalltalk", confidence=0.0, matched_pattern="",
    )
    return _compose(
        memory=memory,
        text=text,
        classification=classification,
        persona_hint=persona_hint,
        duration_sec=duration_sec,
    )


async def plan_next_scene_async(
    memory: SceneMemory,
    viewer_text: str,
    *,
    persona_hint: str = "",
    duration_sec: int = 5,
) -> ScenePlan:
    """Async variant that tries the LLM composer before falling
    back to the deterministic heuristic.

    The two composers share the exact same input + output contract
    so routes can swap between sync and async without any
    downstream awareness. The LLM call is feature-flagged by
    ``INTERACTIVE_PLAYBACK_LLM`` — when unset this function does
    exactly what ``plan_next_scene`` does.

    Failure of the LLM never surfaces to the caller: any timeout
    / network error / malformed JSON returns a heuristic plan so
    the player keeps a pulse.
    """
    # Local import so the heuristic path never pays the LLM
    # composer import cost when the flag is off.
    from .llm_composer import compose_with_llm

    text = (viewer_text or "").strip()
    classification = classify_intent(text) if text else IntentMatch(
        intent_code="smalltalk", confidence=0.0, matched_pattern="",
    )
    llm_plan = await compose_with_llm(
        memory, text, classification,
        persona_hint=persona_hint, duration_sec=duration_sec,
    )
    if llm_plan is not None:
        return llm_plan
    return _compose(
        memory=memory, text=text, classification=classification,
        persona_hint=persona_hint, duration_sec=duration_sec,
    )


def synthesize_synopsis(memory: SceneMemory) -> str:
    """Compact, deterministic synopsis of the conversation so far.

    Phase-1 heuristic: keep the opening viewer prompt + the last
    character reply + a mood / affinity stamp. Phase-2 replaces
    this with an LLM-generated sentence that captures the arc.
    """
    turns = memory.recent_turns
    if not turns:
        return ""
    opener = next((t for t in turns if t.role == "viewer"), None)
    last_char = next((t for t in reversed(turns) if t.role == "character"), None)

    parts: List[str] = []
    if opener and opener.text:
        parts.append(f"Opened with: {_short(opener.text, 80)}")
    if last_char and last_char.text:
        parts.append(f"Last reply: {_short(last_char.text, 80)}")
    parts.append(f"Mood {memory.mood}, affinity {int(memory.affinity_score * 100)}%.")
    return " ".join(parts)


# ── Internals ───────────────────────────────────────────────────

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


# Template keys are (intent_bucket, affinity_tier). Falls back to
# ("smalltalk", tier) when the intent isn't covered explicitly.
_REPLY_TEMPLATES: Dict[str, Dict[str, str]] = {
    "greeting": {
        "stranger":  "Hi there — good to finally see you.",
        "friendly":  "Hey you, welcome back.",
        "warm":      "There you are — I was hoping you'd show up.",
        "close":     "Hey trouble, come sit with me.",
    },
    "compliment": {
        "stranger":  "That's kind of you, thank you.",
        "friendly":  "Oh — you're being sweet.",
        "warm":      "You always know what to say, don't you?",
        "close":     "Keep talking like that, I might not let you leave.",
    },
    "question": {
        "stranger":  "Hmm, let me think about that for a second.",
        "friendly":  "Good question — here's how I'd put it.",
        "warm":      "Ask me anything. Really.",
        "close":     "You and your questions. Come closer.",
    },
    "flirt": {
        "stranger":  "Oh? We're going there already?",
        "friendly":  "Careful — I flirt back.",
        "warm":      "Is that how it's going to be tonight?",
        "close":     "You're in a mood. I like it.",
    },
    "smalltalk": {
        "stranger":  "Mhm — go on, I'm listening.",
        "friendly":  "Tell me more.",
        "warm":      "I like where this is going.",
        "close":     "Keep going. I'm right here.",
    },
}


_MOOD_SCENE_TAG = {
    "neutral": "calm gaze, soft diffuse light",
    "shy":     "glancing away, warm backlight, subtle smile",
    "flirty":  "slow half-smile, lowered eyelashes, warm rim light",
    "playful": "quick grin, candid pose, dynamic expression",
    "warm":    "open expression, soft golden lighting",
    "cold":    "steady stare, cool blue tint",
}


_INTENT_BUCKETS = {
    # classifier may return nuanced codes; bucket them to the few
    # templates we actually maintain.
    "greeting": "greeting",
    "compliment": "compliment",
    "tease": "flirt",
    "flirt": "flirt",
    "affection": "flirt",
    "question": "question",
    "request_info": "question",
    "smalltalk": "smalltalk",
}


_MOOD_SHIFT_RULES: List[Dict[str, Any]] = [
    # (intent, condition, mood, affinity_delta)
    {"intent": "greeting",   "mood": None,      "affinity": 0.02},
    {"intent": "compliment", "mood": "warm",    "affinity": 0.04},
    {"intent": "flirt",      "mood": "flirty",  "affinity": 0.05},
    {"intent": "tease",      "mood": "playful", "affinity": 0.03},
    {"intent": "affection",  "mood": "warm",    "affinity": 0.05},
]


def _compose(
    memory: SceneMemory,
    text: str,
    classification: IntentMatch,
    persona_hint: str,
    duration_sec: int,
) -> ScenePlan:
    intent = classification.intent_code or "smalltalk"
    bucket = _INTENT_BUCKETS.get(intent, "smalltalk")
    tier = _affinity_tier(memory.affinity_score)

    reply = _REPLY_TEMPLATES.get(bucket, _REPLY_TEMPLATES["smalltalk"])[tier]
    mood_tag = _MOOD_SCENE_TAG.get(memory.mood, _MOOD_SCENE_TAG["neutral"])

    continuity = _short(text, 120) if text else ""
    scene_prompt = _build_scene_prompt(
        persona_hint=persona_hint,
        mood=memory.mood,
        mood_tag=mood_tag,
        outfit=memory.outfit_state,
        continuity=continuity,
        intent_bucket=bucket,
    )
    narration = reply  # phase-1: the character says what the chat bubble shows.
    mood_delta = _mood_delta_for(intent)

    return ScenePlan(
        reply_text=reply,
        narration=narration,
        scene_prompt=scene_prompt,
        duration_sec=max(2, min(int(duration_sec), 15)),
        mood_delta=mood_delta,
        topic_continuity=continuity,
        intent_code=intent,
        confidence=float(classification.confidence or 0.0),
    )


def _build_scene_prompt(
    *, persona_hint: str, mood: str, mood_tag: str,
    outfit: Dict[str, Any], continuity: str, intent_bucket: str,
) -> str:
    parts: List[str] = []
    if persona_hint:
        parts.append(persona_hint.strip())
    parts.append(f"mood {mood}")
    parts.append(mood_tag)
    outfit_note = _outfit_note(outfit)
    if outfit_note:
        parts.append(outfit_note)
    parts.append(f"scene beat: {intent_bucket}")
    if continuity:
        parts.append(f'responding to: "{continuity}"')
    return ", ".join(p for p in parts if p)


def _outfit_note(outfit: Dict[str, Any]) -> str:
    if not outfit:
        return ""
    bits: List[str] = []
    for key in ("top", "bottom", "accessory", "hair"):
        val = outfit.get(key)
        if isinstance(val, str) and val:
            bits.append(f"{key} {val}")
    return ", ".join(bits)


def _mood_delta_for(intent: str) -> Dict[str, Any]:
    for rule in _MOOD_SHIFT_RULES:
        if rule["intent"] == intent:
            out: Dict[str, Any] = {}
            if rule["mood"]:
                out["mood"] = rule["mood"]
            if rule["affinity"]:
                out["affinity"] = rule["affinity"]
            return out
    return {}


_WS_RE = re.compile(r"\s+")


def _short(text: str, limit: int) -> str:
    cleaned = _WS_RE.sub(" ", text.strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"
