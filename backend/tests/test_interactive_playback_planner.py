"""
Tests for playback.scene_planner — heuristic composer.

Deterministic by design: no randomness, no LLM, so every
assertion pins exact template output keyed by (intent, affinity
tier, mood).
"""
from __future__ import annotations

from typing import List

from app.interactive.playback.scene_memory import SceneMemory, TurnSnapshot
from app.interactive.playback.scene_planner import (
    plan_next_scene,
    synthesize_synopsis,
)


def _memory(
    *, mood: str = "neutral", affinity: float = 0.5,
    outfit: dict | None = None, turns: List[TurnSnapshot] | None = None,
    synopsis: str = "", turns_since: int = 0,
) -> SceneMemory:
    return SceneMemory(
        session_id="ixs_test",
        experience_id="ixe_test",
        persona_id="persona_dark",
        current_node_id="ixn_1",
        mood=mood,
        affinity_score=affinity,
        outfit_state=dict(outfit or {}),
        recent_turns=list(turns or []),
        total_turns=len(turns or []),
        synopsis=synopsis,
        turns_since_synopsis=turns_since,
    )


# ── plan_next_scene ─────────────────────────────────────────────

def test_greeting_stranger_uses_friendly_opener():
    mem = _memory(affinity=0.0)
    plan = plan_next_scene(mem, "hi")
    assert plan.intent_code == "greeting"
    assert plan.reply_text == "Hi there — good to finally see you."
    assert "greeting" in plan.scene_prompt
    assert 'responding to: "hi"' in plan.scene_prompt


def test_greeting_close_affinity_uses_close_opener():
    mem = _memory(affinity=0.85)
    plan = plan_next_scene(mem, "hi")
    assert plan.reply_text == "Hey trouble, come sit with me."


def test_flirt_bumps_mood_and_affinity():
    mem = _memory(mood="neutral", affinity=0.5)
    plan = plan_next_scene(mem, "you're beautiful tonight, tease me")
    assert plan.intent_code in ("flirt", "tease", "compliment")
    # whichever intent the classifier returns, mood_delta should
    # either move mood toward flirty/playful/warm, or bump affinity
    assert plan.mood_delta.get("affinity", 0) > 0


def test_mood_tag_flows_into_scene_prompt():
    mem = _memory(mood="flirty")
    plan = plan_next_scene(mem, "tell me a secret")
    assert "mood flirty" in plan.scene_prompt
    assert "slow half-smile" in plan.scene_prompt  # flirty tag


def test_persona_hint_seeds_scene_prompt():
    mem = _memory()
    plan = plan_next_scene(
        mem, "hi",
        persona_hint="dark goth girl, violet eyes, cross choker",
    )
    assert plan.scene_prompt.startswith("dark goth girl, violet eyes, cross choker")


def test_outfit_state_appears_in_scene_prompt():
    mem = _memory(outfit={"top": "black lace blouse", "hair": "long straight"})
    plan = plan_next_scene(mem, "hi")
    assert "top black lace blouse" in plan.scene_prompt
    assert "hair long straight" in plan.scene_prompt


def test_topic_continuity_quotes_viewer_verbatim_clamped():
    long_msg = "tell me about that time you " + ("ran " * 50)
    mem = _memory()
    plan = plan_next_scene(mem, long_msg)
    assert plan.topic_continuity.startswith("tell me about that time")
    assert plan.topic_continuity.endswith("…")
    assert len(plan.topic_continuity) <= 121


def test_empty_viewer_text_defaults_to_smalltalk():
    mem = _memory()
    plan = plan_next_scene(mem, "")
    assert plan.intent_code == "smalltalk"
    assert plan.reply_text  # still emits *something*
    assert plan.topic_continuity == ""


def test_duration_is_clamped():
    mem = _memory()
    plan = plan_next_scene(mem, "hi", duration_sec=999)
    assert plan.duration_sec == 15
    plan2 = plan_next_scene(mem, "hi", duration_sec=0)
    assert plan2.duration_sec == 2


# ── synthesize_synopsis ─────────────────────────────────────────

def test_synopsis_empty_when_no_turns():
    assert synthesize_synopsis(_memory()) == ""


def test_synopsis_captures_opener_and_last_reply():
    turns = [
        TurnSnapshot(role="viewer", text="Hey — first time here."),
        TurnSnapshot(role="character", text="Welcome in."),
        TurnSnapshot(role="viewer", text="Tell me about yourself."),
        TurnSnapshot(role="character", text="I grew up near the coast."),
    ]
    mem = _memory(turns=turns, mood="warm", affinity=0.6)
    s = synthesize_synopsis(mem)
    assert "Hey — first time here." in s
    assert "I grew up near the coast." in s
    assert "Mood warm" in s
    assert "60%" in s
