"""
Tests for scene_planner.plan_next_scene_async — LLM first,
heuristic fallback. The upstream compose_with_llm is
monkeypatched per-case so nothing touches a real LLM.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.interactive.playback import scene_planner
from app.interactive.playback.scene_memory import SceneMemory
from app.interactive.playback.scene_planner import (
    ScenePlan, plan_next_scene_async,
)


def _memory() -> SceneMemory:
    return SceneMemory(
        session_id="ixs_async",
        experience_id="ixe_async",
        persona_id="p",
        current_node_id="",
        mood="neutral",
        affinity_score=0.5,
        outfit_state={},
        recent_turns=[],
        total_turns=0,
        synopsis="",
        turns_since_synopsis=0,
    )


def _install_llm(monkeypatch: pytest.MonkeyPatch, result: ScenePlan | None) -> None:
    async def _fake(
        memory, text, classification, *,
        persona_hint="", duration_sec=5, config=None, **_kwargs,
    ):
        return result
    import app.interactive.playback.llm_composer as mod
    monkeypatch.setattr(mod, "compose_with_llm", _fake)


def test_llm_plan_is_returned_verbatim(monkeypatch):
    staged = ScenePlan(
        reply_text="LLM says hi",
        narration="LLM narrates",
        scene_prompt="LLM scene",
        duration_sec=6,
        mood_delta={"mood": "warm"},
        topic_continuity="hi",
        intent_code="greeting",
        confidence=0.9,
    )
    _install_llm(monkeypatch, staged)
    plan = asyncio.run(plan_next_scene_async(_memory(), "hi"))
    assert plan is staged


def test_falls_back_to_heuristic_when_llm_returns_none(monkeypatch):
    _install_llm(monkeypatch, None)
    plan = asyncio.run(plan_next_scene_async(_memory(), "hi"))
    # Heuristic path is deterministic — the greeting at affinity
    # 0.5 should produce the 'warm' tier template.
    assert plan.reply_text == "There you are — I was hoping you'd show up."
    assert "greeting" in plan.scene_prompt


def test_empty_text_uses_smalltalk_even_on_fallback(monkeypatch):
    _install_llm(monkeypatch, None)
    plan = asyncio.run(plan_next_scene_async(_memory(), ""))
    assert plan.intent_code == "smalltalk"
    assert plan.topic_continuity == ""
