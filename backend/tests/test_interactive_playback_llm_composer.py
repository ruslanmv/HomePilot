"""
Tests for llm_composer.compose_with_llm.

The upstream chat_ollama call is monkey-patched in every test so
nothing hits a real LLM. We only verify the shaping / parsing /
fallback contract.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.interactive.playback import llm_composer
from app.interactive.playback.llm_composer import compose_with_llm
from app.interactive.playback.playback_config import PlaybackConfig
from app.interactive.playback.scene_memory import SceneMemory, TurnSnapshot
from app.interactive.policy.classifier import IntentMatch


def _config(
    *, llm_enabled: bool = True, timeout: float = 5.0,
) -> PlaybackConfig:
    return PlaybackConfig(
        llm_enabled=llm_enabled, llm_timeout_s=timeout,
        llm_max_tokens=256, llm_temperature=0.5,
        render_enabled=False, render_workflow="animate", image_workflow="avatar_txt2img",
        render_timeout_s=60.0,
    )


def _memory(**overrides: Any) -> SceneMemory:
    base = dict(
        session_id="ixs_test", experience_id="ixe_test",
        persona_id="persona_dark", current_node_id="",
        mood="neutral", affinity_score=0.5, outfit_state={},
        recent_turns=[], total_turns=0, synopsis="", turns_since_synopsis=0,
    )
    base.update(overrides)
    return SceneMemory(**base)


def _intent(code: str = "greeting", confidence: float = 0.7) -> IntentMatch:
    return IntentMatch(intent_code=code, confidence=confidence, matched_pattern="")


def _install_mock_chat(
    monkeypatch: pytest.MonkeyPatch,
    response: Dict[str, Any] | Exception,
    captured_messages: List[List[Dict[str, Any]]] | None = None,
) -> None:
    async def _fake_chat(messages: List[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
        if captured_messages is not None:
            captured_messages.append(list(messages))
        if isinstance(response, Exception):
            raise response
        return response
    monkeypatch.setattr(llm_composer, "chat_ollama", _fake_chat)


def _run(coro):
    return asyncio.run(coro)


# ── Happy path ──────────────────────────────────────────────────

def test_returns_scene_plan_on_clean_json_response(monkeypatch):
    payload = (
        '{"reply_text": "Hey, come sit with me.",'
        ' "narration": "She beckons you over.",'
        ' "scene_prompt": "warm smile, soft rim light, leaning forward",'
        ' "duration_sec": 5, "mood_shift": "warm", "affinity_delta": 0.05}'
    )
    captured: List[List[Dict[str, Any]]] = []
    _install_mock_chat(
        monkeypatch,
        {"choices": [{"message": {"content": payload}}]},
        captured,
    )
    plan = _run(compose_with_llm(
        _memory(mood="neutral", affinity_score=0.5),
        "hi there",
        _intent("greeting"),
        persona_hint="dark goth girl",
        duration_sec=5,
        config=_config(),
    ))
    assert plan is not None
    assert plan.reply_text == "Hey, come sit with me."
    assert "warm smile" in plan.scene_prompt
    assert plan.duration_sec == 5
    assert plan.mood_delta.get("mood") == "warm"
    assert plan.mood_delta.get("affinity") == 0.05
    # Messages include a system frame + the user turn.
    assert captured and captured[0][0]["role"] == "system"


def test_handles_code_fence_wrapped_json(monkeypatch):
    content = (
        "```json\n"
        '{"reply_text": "Sure.", "narration": "She nods.",'
        ' "scene_prompt": "soft light, direct gaze",'
        ' "duration_sec": 4}\n'
        "```"
    )
    _install_mock_chat(monkeypatch, {"choices": [{"message": {"content": content}}]})
    plan = _run(compose_with_llm(
        _memory(), "ok?", _intent(), config=_config(),
    ))
    assert plan is not None
    assert plan.reply_text == "Sure."


def test_injects_synopsis_and_recent_turns_into_messages(monkeypatch):
    captured: List[List[Dict[str, Any]]] = []
    _install_mock_chat(
        monkeypatch,
        {"choices": [{"message": {"content": (
            '{"reply_text": "…", "narration": "…",'
            ' "scene_prompt": "scene cues", "duration_sec": 5}'
        )}}]},
        captured,
    )
    turns = [
        TurnSnapshot(role="user", text="Nice to meet you."),
        TurnSnapshot(role="assistant", text="Likewise."),
    ]
    _run(compose_with_llm(
        _memory(recent_turns=turns, synopsis="Just met — friendly tone."),
        "Tell me more", _intent(), config=_config(),
    ))
    msgs = captured[0]
    assert any(m["role"] == "system" and "Just met" in m["content"] for m in msgs)
    assert any(m["role"] == "user" and "Nice to meet you." in m["content"] for m in msgs)
    assert any(m["role"] == "assistant" and "Likewise." in m["content"] for m in msgs)


# ── Fallback paths ──────────────────────────────────────────────

def test_returns_none_when_llm_disabled(monkeypatch):
    _install_mock_chat(monkeypatch, {"choices": []})  # never called
    plan = _run(compose_with_llm(
        _memory(), "hi", _intent(),
        config=_config(llm_enabled=False),
    ))
    assert plan is None


def test_returns_none_on_timeout(monkeypatch):
    async def _slow(messages, **kwargs):
        await asyncio.sleep(10)
        return {"choices": [{"message": {"content": "{}"}}]}
    monkeypatch.setattr(llm_composer, "chat_ollama", _slow)
    plan = _run(compose_with_llm(
        _memory(), "hi", _intent(),
        config=_config(timeout=0.05),
    ))
    assert plan is None


def test_returns_none_on_upstream_exception(monkeypatch):
    _install_mock_chat(monkeypatch, RuntimeError("connection refused"))
    plan = _run(compose_with_llm(
        _memory(), "hi", _intent(), config=_config(),
    ))
    assert plan is None


def test_returns_none_on_malformed_json(monkeypatch):
    _install_mock_chat(
        monkeypatch,
        {"choices": [{"message": {"content": "not json at all"}}]},
    )
    plan = _run(compose_with_llm(
        _memory(), "hi", _intent(), config=_config(),
    ))
    assert plan is None


def test_returns_none_on_empty_required_field(monkeypatch):
    _install_mock_chat(
        monkeypatch,
        {"choices": [{"message": {"content": '{"reply_text": "x"}'}}]},
    )
    plan = _run(compose_with_llm(
        _memory(), "hi", _intent(), config=_config(),
    ))
    assert plan is None


# ── Validation / clamping ───────────────────────────────────────

def test_unknown_mood_shift_is_dropped(monkeypatch):
    payload = (
        '{"reply_text": "x", "narration": "y",'
        ' "scene_prompt": "z",'
        ' "duration_sec": 5, "mood_shift": "maniacal", "affinity_delta": 0.03}'
    )
    _install_mock_chat(monkeypatch, {"choices": [{"message": {"content": payload}}]})
    plan = _run(compose_with_llm(
        _memory(), "hi", _intent(), config=_config(),
    ))
    assert plan is not None
    assert "mood" not in plan.mood_delta
    assert plan.mood_delta.get("affinity") == 0.03


def test_affinity_delta_is_clamped(monkeypatch):
    payload = (
        '{"reply_text": "x", "narration": "y",'
        ' "scene_prompt": "z",'
        ' "duration_sec": 5, "affinity_delta": 0.95}'
    )
    _install_mock_chat(monkeypatch, {"choices": [{"message": {"content": payload}}]})
    plan = _run(compose_with_llm(
        _memory(), "hi", _intent(), config=_config(),
    ))
    assert plan is not None
    assert plan.mood_delta.get("affinity") == 0.2  # clamped to +/- 0.2


def test_duration_is_clamped_to_valid_range(monkeypatch):
    payload = (
        '{"reply_text": "x", "narration": "y",'
        ' "scene_prompt": "z", "duration_sec": 999}'
    )
    _install_mock_chat(monkeypatch, {"choices": [{"message": {"content": payload}}]})
    plan = _run(compose_with_llm(
        _memory(), "hi", _intent(), duration_sec=5, config=_config(),
    ))
    assert plan is not None
    assert plan.duration_sec == 15
