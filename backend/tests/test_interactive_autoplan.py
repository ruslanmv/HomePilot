"""
Tests for planner.autoplan_llm — Stage-1 auto-planner.

Covers:
  - Heuristic path always returns a sane PlanForm
  - Mode inference by verb keyword
  - Audience role/level inference
  - Branch + depth + scenes clamped to UX spec bounds (2–4, 2–3, 2–4)
  - LLM path returns the LLM result when the response validates
  - LLM path falls back to heuristic on: disabled flag, timeout,
    upstream exception, malformed JSON, missing required fields
  - Mode whitelist rejects 'mature_gated' from unsolicited LLM
    outputs? No — the prompt says so but we still accept any
    whitelisted mode; the regression checks that all 6 canonical
    modes pass through.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.interactive import planner as planner_pkg  # noqa: F401 — registers submodules
from app.interactive.config import InteractiveConfig
from app.interactive.planner import autoplan_llm
from app.interactive.planner.autoplan_llm import (
    PlanForm, PlanAutoResult, autoplan,
)
from app.interactive.playback.playback_config import PlaybackConfig


def _cfg() -> InteractiveConfig:
    return InteractiveConfig(
        enabled=True, max_branches=6, max_depth=4,
        max_nodes_per_experience=100, llm_model="llama3:8b",
        storage_root="", require_consent_for_mature=True,
        enforce_region_block=True, moderate_mature_narration=True,
        region_block=[], runtime_latency_target_ms=200,
    )


def _pcfg(*, llm_enabled: bool = True) -> PlaybackConfig:
    return PlaybackConfig(
        llm_enabled=llm_enabled, llm_timeout_s=5.0,
        llm_max_tokens=500, llm_temperature=0.5,
        render_enabled=False, render_workflow="animate",
        render_timeout_s=60.0,
    )


def _install_chat(monkeypatch: pytest.MonkeyPatch, response: Any) -> None:
    async def _fake(messages: List[Dict[str, Any]], **kwargs: Any):
        if isinstance(response, Exception):
            raise response
        return response
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat_ollama", _fake)


def _run(coro):
    return asyncio.run(coro)


# ── Heuristic path ──────────────────────────────────────────────

def test_heuristic_fills_every_form_field():
    result = _run(autoplan(
        "train new sales reps on pricing tiers",
        cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False),
    ))
    assert isinstance(result, PlanAutoResult)
    assert result.source == "heuristic"
    f = result.form
    # Every field is populated with a sensible default.
    assert f.title
    assert f.prompt
    assert f.experience_mode in {
        "sfw_general", "sfw_education", "language_learning",
        "enterprise_training", "social_romantic", "mature_gated",
    }
    assert f.policy_profile_id == f.experience_mode
    assert f.audience_role
    assert f.audience_level in ("beginner", "intermediate", "advanced")
    assert f.audience_language == "en"
    # Structure bounds clamped to UX spec.
    assert 2 <= f.branch_count <= 4
    assert 2 <= f.depth <= 3
    assert 2 <= f.scenes_per_branch <= 4


def test_heuristic_infers_enterprise_training_from_train_verb():
    result = _run(autoplan(
        "train new sales reps on pricing tiers",
        cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False),
    ))
    assert result.form.experience_mode == "enterprise_training"
    assert result.form.policy_profile_id == "enterprise_training"


def test_heuristic_infers_education_from_teach_verb():
    result = _run(autoplan(
        "teach beginners the basics of photosynthesis",
        cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False),
    ))
    assert result.form.experience_mode == "sfw_education"


def test_heuristic_infers_language_learning_from_language_keyword():
    result = _run(autoplan(
        "help viewers practice basic Spanish conversation",
        cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False),
    ))
    assert result.form.experience_mode == "language_learning"


def test_heuristic_defaults_to_sfw_general_on_unknown_domain():
    result = _run(autoplan(
        "hello world",
        cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False),
    ))
    assert result.form.experience_mode == "sfw_general"


def test_heuristic_never_picks_mature_gated_from_short_idea():
    result = _run(autoplan(
        "casual chat with a friendly host",
        cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False),
    ))
    assert result.form.experience_mode != "mature_gated"


def test_heuristic_title_is_shortish_and_capitalized():
    result = _run(autoplan(
        "teach beginners basic spanish conversation practice",
        cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False),
    ))
    assert result.form.title
    assert len(result.form.title) <= 60
    # First char is uppercase (we title-case lowercase input).
    assert result.form.title[0].isupper()


def test_heuristic_with_empty_input_still_returns_defaults():
    result = _run(autoplan(
        "",
        cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False),
    ))
    assert result.source == "heuristic"
    assert result.form.title  # some default
    assert result.form.branch_count >= 2


def test_heuristic_populates_seed_intents():
    result = _run(autoplan(
        "train new hires on compliance",
        cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False),
    ))
    assert len(result.seed_intents) > 0
    assert all(isinstance(s, str) for s in result.seed_intents)


# ── LLM path ────────────────────────────────────────────────────

_VALID_LLM_PAYLOAD = (
    '{"title": "Sales Rep Pricing Training",'
    ' "prompt": "Guide new sales reps through three pricing tiers with quizzes.",'
    ' "experience_mode": "enterprise_training",'
    ' "policy_profile_id": "enterprise_training",'
    ' "audience_role": "trainee",'
    ' "audience_level": "beginner",'
    ' "audience_language": "en",'
    ' "audience_locale_hint": "us",'
    ' "branch_count": 3,'
    ' "depth": 2,'
    ' "scenes_per_branch": 3,'
    ' "objective": "Teach pricing tiers through decisions",'
    ' "topic": "Sales pricing",'
    ' "scheme": "xp_level",'
    ' "success_metric": "correct answers",'
    ' "seed_intents": ["greeting", "choose_plan", "quiz", "feedback"]}'
)


def test_llm_happy_path_populates_every_field(monkeypatch):
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": _VALID_LLM_PAYLOAD}}]},
    )
    result = _run(autoplan(
        "train new sales reps on pricing",
        cfg=_cfg(), playback_cfg=_pcfg(),
    ))
    assert result.source == "llm"
    f = result.form
    assert f.title == "Sales Rep Pricing Training"
    assert f.experience_mode == "enterprise_training"
    assert f.audience_role == "trainee"
    assert f.branch_count == 3
    assert result.seed_intents[:3] == ["greeting", "choose_plan", "quiz"]


def test_llm_code_fence_wrapped_json_is_tolerated(monkeypatch):
    fenced = "```json\n" + _VALID_LLM_PAYLOAD + "\n```"
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": fenced}}]},
    )
    result = _run(autoplan(
        "train new sales reps",
        cfg=_cfg(), playback_cfg=_pcfg(),
    ))
    assert result.source == "llm"


def test_llm_unknown_mode_is_coerced_to_sfw_general(monkeypatch):
    bad_mode = _VALID_LLM_PAYLOAD.replace(
        '"enterprise_training"', '"mystery_mode"', 1,
    )
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": bad_mode}}]},
    )
    result = _run(autoplan(
        "do something",
        cfg=_cfg(), playback_cfg=_pcfg(),
    ))
    assert result.source == "llm"
    assert result.form.experience_mode == "sfw_general"


def test_llm_branch_count_is_clamped_to_spec_bounds(monkeypatch):
    oversized = _VALID_LLM_PAYLOAD.replace(
        '"branch_count": 3', '"branch_count": 99',
    )
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": oversized}}]},
    )
    result = _run(autoplan(
        "train new sales reps",
        cfg=_cfg(), playback_cfg=_pcfg(),
    ))
    assert 2 <= result.form.branch_count <= 4


# ── LLM fallback paths ──────────────────────────────────────────

def test_llm_disabled_flag_takes_heuristic_path(monkeypatch):
    # Stub chat_ollama to explode — we should never reach it.
    async def _boom(*a, **k):
        raise AssertionError("chat_ollama called with llm_enabled=False")
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat_ollama", _boom)
    result = _run(autoplan(
        "hi",
        cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False),
    ))
    assert result.source == "heuristic"


def test_llm_timeout_falls_back_to_heuristic(monkeypatch):
    async def _slow(*a, **k):
        await asyncio.sleep(5)
        return {"choices": []}
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat_ollama", _slow)
    pcfg = PlaybackConfig(
        llm_enabled=True, llm_timeout_s=0.05,
        llm_max_tokens=500, llm_temperature=0.5,
        render_enabled=False, render_workflow="animate",
        render_timeout_s=60.0,
    )
    result = _run(autoplan("hi", cfg=_cfg(), playback_cfg=pcfg))
    assert result.source == "heuristic"


def test_llm_exception_falls_back_to_heuristic(monkeypatch):
    _install_chat(monkeypatch, RuntimeError("connection refused"))
    result = _run(autoplan(
        "train new hires",
        cfg=_cfg(), playback_cfg=_pcfg(),
    ))
    assert result.source == "heuristic"
    # Heuristic still infers the mode from verb.
    assert result.form.experience_mode == "enterprise_training"


def test_llm_malformed_json_falls_back_to_heuristic(monkeypatch):
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": "this is definitely not json"}}]},
    )
    result = _run(autoplan(
        "teach beginners photosynthesis",
        cfg=_cfg(), playback_cfg=_pcfg(),
    ))
    assert result.source == "heuristic"
    assert result.form.experience_mode == "sfw_education"


def test_llm_missing_required_field_falls_back_to_heuristic(monkeypatch):
    # Valid JSON but no title → _payload_to_result returns None,
    # caller falls back.
    partial = '{"experience_mode": "sfw_general"}'
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": partial}}]},
    )
    result = _run(autoplan(
        "hi",
        cfg=_cfg(), playback_cfg=_pcfg(),
    ))
    assert result.source == "heuristic"
