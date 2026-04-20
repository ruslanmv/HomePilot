"""
Tests for the stage-1 autoplan workflow (REV-3).

Covers:

* Parsers tolerate quotes / markdown fences / JSON-ish framing.
* Validators enforce the allowed enums, length bounds, snake_case.
* Fallbacks produce sane defaults (audience/shape/seed_intents).
* End-to-end: when the flag is ON the workflow runs and produces
  a PlanAutoResult with source='llm'.
* Workflow abort on a required step falls back to heuristic.
* Feature flag: workflow_enabled respects INTERACTIVE_AUTOPLAN_WORKFLOW
  and INTERACTIVE_AUTOPLAN_LEGACY env vars.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.interactive.config import InteractiveConfig
from app.interactive.planner import autoplan_llm
from app.interactive.planner.autoplan_llm import PlanAutoResult, autoplan
from app.interactive.planner.autoplan_workflow import (
    _parse_audience_obj,
    _parse_enum,
    _parse_json_text,
    _parse_shape_obj,
    _parse_string_array,
    _parse_text,
    _validate_audience_obj,
    _validate_brief,
    _validate_mode,
    _validate_seed_intents,
    _validate_shape_obj,
    _validate_title_array,
    build_autoplan_steps,
    run_autoplan_workflow,
    workflow_enabled,
    workflow_to_plan_result,
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


def _pcfg() -> PlaybackConfig:
    return PlaybackConfig(
        llm_enabled=False, llm_timeout_s=5.0,
        llm_max_tokens=500, llm_temperature=0.5,
        render_enabled=False, render_workflow="animate",
        render_timeout_s=60.0,
    )


# ── Parsers ───────────────────────────────────────────────────

def test_parse_enum_strips_framing_quotes_and_punctuation():
    assert _parse_enum("  `enterprise_training`  ") == "enterprise_training"
    assert _parse_enum('Mode: "sfw_general".') == "sfw_general"
    assert _parse_enum("LANGUAGE_LEARNING") == "language_learning"


def test_parse_enum_empty_on_garbage():
    assert _parse_enum("") == ""
    assert _parse_enum("!!!") == ""


def test_parse_text_strips_quotes_and_collapses_whitespace():
    assert _parse_text('  "hello  world"  ') == "hello world"
    assert _parse_text("Line1\n\nLine2") == "Line1 Line2"


def test_parse_json_text_handles_bare_and_fenced():
    assert _parse_json_text('["a","b"]') == ["a", "b"]
    fenced = '```json\n{"x": 1}\n```'
    assert _parse_json_text(fenced) == {"x": 1}
    # JSON embedded in prose.
    embedded = "Sure, here you go: {\"role\": \"trainee\"} thanks"
    assert _parse_json_text(embedded) == {"role": "trainee"}


def test_parse_json_text_raises_on_no_json():
    with pytest.raises(ValueError):
        _parse_json_text("no json here at all")


def test_parse_string_array():
    assert _parse_string_array('["a", "b", "c"]') == ["a", "b", "c"]
    with pytest.raises(ValueError):
        _parse_string_array('{"not": "a list"}')


def test_parse_audience_obj():
    out = _parse_audience_obj('{"role":"trainee","level":"BEGINNER","language":"es"}')
    assert out == {"role": "trainee", "level": "beginner", "language": "es"}


def test_parse_shape_obj_rejects_bool_and_non_int():
    with pytest.raises((ValueError, TypeError)):
        _parse_shape_obj('{"branch_count": true, "depth": 2, "scenes_per_branch": 2}')
    good = _parse_shape_obj(
        '{"branch_count": 3, "depth": 2, "scenes_per_branch": 3}'
    )
    assert good == {"branch_count": 3, "depth": 2, "scenes_per_branch": 3}


# ── Validators ────────────────────────────────────────────────

def test_validate_mode():
    assert _validate_mode("sfw_general") is None
    assert _validate_mode("nope") is not None


def test_validate_title_array_requires_one_valid_candidate():
    assert _validate_title_array(["Ok Title"]) is None
    assert _validate_title_array([]) is not None
    assert _validate_title_array(["a"]) is not None  # too short
    assert _validate_title_array(["x" * 120]) is not None  # too long


def test_validate_brief_length_bounds():
    assert _validate_brief("short") is not None
    assert _validate_brief("A" * 700) is not None
    assert _validate_brief("A" * 100) is None


def test_validate_audience_obj():
    good = {"role": "trainee", "level": "beginner", "language": "en"}
    assert _validate_audience_obj(good) is None
    bad_role = {"role": "wizard", "level": "beginner", "language": "en"}
    assert _validate_audience_obj(bad_role) is not None
    bad_level = {"role": "viewer", "level": "guru", "language": "en"}
    assert _validate_audience_obj(bad_level) is not None


def test_validate_shape_obj_bounds():
    assert _validate_shape_obj(
        {"branch_count": 3, "depth": 2, "scenes_per_branch": 3},
    ) is None
    assert _validate_shape_obj(
        {"branch_count": 99, "depth": 2, "scenes_per_branch": 3},
    ) is not None


def test_validate_seed_intents_snake_case_3_to_6():
    assert _validate_seed_intents(["greeting", "choose_path", "outcome"]) is None
    assert _validate_seed_intents(["too_few"]) is not None
    assert _validate_seed_intents(["ONE", "two", "three"]) is not None


# ── Feature flag ─────────────────────────────────────────────

def test_workflow_disabled_by_default(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_AUTOPLAN_WORKFLOW", raising=False)
    monkeypatch.delenv("INTERACTIVE_AUTOPLAN_LEGACY", raising=False)
    assert workflow_enabled() is False


def test_workflow_flag_on(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_AUTOPLAN_WORKFLOW", "true")
    assert workflow_enabled() is True


def test_workflow_flag_beats_legacy_flag(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_AUTOPLAN_WORKFLOW", "1")
    monkeypatch.setenv("INTERACTIVE_AUTOPLAN_LEGACY", "1")
    assert workflow_enabled() is True


# ── Scripted LLM fixture ─────────────────────────────────────

class _Scripted:
    """Feed one response per prompt_id; used to drive end-to-end
    workflow tests without a real Ollama backend."""

    def __init__(self) -> None:
        self.map: Dict[str, List[str]] = {}

    def feed(self, prompt_id: str, *responses: str) -> None:
        self.map.setdefault(prompt_id, []).extend(responses)

    async def __call__(self, prompt, policy, **_kw):
        q = self.map.get(prompt.prompt_id)
        if not q:
            raise AssertionError(f"No scripted response for {prompt.prompt_id}")
        return {"choices": [{"message": {"content": q.pop(0)}}]}


@pytest.fixture(autouse=True)
def _refresh_autoplan_symbols():
    """See the matching fixture in test_interactive_workflow_runner.py.

    The conftest app session fixture can purge + re-import app.*
    modules, leaving our top-of-file imports pointing at a
    detached pre-purge module copy. Re-binding the symbols into
    this module's globals at fixture time keeps the runtime
    references lined up with what monkeypatch targets.
    """
    from app.interactive.planner import autoplan_llm as _al
    from app.interactive.planner import autoplan_workflow as _aw
    g = globals()
    g["autoplan_llm"] = _al
    g["autoplan"] = _al.autoplan
    g["PlanAutoResult"] = _al.PlanAutoResult
    g["run_autoplan_workflow"] = _aw.run_autoplan_workflow
    g["workflow_to_plan_result"] = _aw.workflow_to_plan_result
    g["workflow_enabled"] = _aw.workflow_enabled
    yield


@pytest.fixture
def scripted(monkeypatch):
    from app.interactive.workflows import runner as runner_mod
    s = _Scripted()
    monkeypatch.setattr(runner_mod, "call_prompt", s)
    return s


def _feed_happy_path(scripted: _Scripted) -> None:
    scripted.feed("autoplan.classify_mode", "enterprise_training")
    scripted.feed("autoplan.extract_topic", "Sales rep pricing training")
    scripted.feed(
        "autoplan.title",
        '["Pricing Tier Onboarding", "Sell Smarter on Tiers", "Tier Launch Day"]',
    )
    scripted.feed(
        "autoplan.brief",
        "Guide new sales reps through three pricing tiers with quick decision "
        "points. Scenes are short, one choice each, with instant feedback.",
    )
    scripted.feed(
        "autoplan.audience",
        '{"role":"trainee","level":"beginner","language":"en"}',
    )
    scripted.feed(
        "autoplan.shape",
        '{"branch_count": 3, "depth": 2, "scenes_per_branch": 3}',
    )
    scripted.feed(
        "autoplan.seed_intents",
        '["welcome","pricing_basics","handle_objection","call_recap"]',
    )


# ── Workflow end-to-end ───────────────────────────────────────

def test_workflow_end_to_end_produces_plan_result(scripted):
    _feed_happy_path(scripted)
    result = asyncio.run(run_autoplan_workflow(
        "train new sales reps on pricing tiers", cfg=_cfg(),
    ))
    assert not result.aborted
    mapped: PlanAutoResult = workflow_to_plan_result(result, cfg=_cfg())
    assert mapped is not None
    assert mapped.source == "llm"
    assert mapped.form.experience_mode == "enterprise_training"
    assert mapped.form.audience_role == "trainee"
    assert mapped.form.title in {
        "Pricing Tier Onboarding", "Sell Smarter on Tiers", "Tier Launch Day",
    }
    assert 2 <= mapped.form.branch_count <= 4
    assert mapped.seed_intents == [
        "welcome", "pricing_basics", "handle_objection", "call_recap",
    ]


def test_workflow_title_abort_falls_back_to_heuristic(monkeypatch, scripted):
    """When the title step exhausts retries on an abort-fallback
    prompt the workflow aborts; the top-level autoplan() should
    then take the legacy LLM path (off) → heuristic."""
    monkeypatch.setenv("INTERACTIVE_AUTOPLAN_WORKFLOW", "true")
    scripted.feed("autoplan.classify_mode", "sfw_education")
    scripted.feed("autoplan.extract_topic", "Basic Spanish greetings")
    # Title step has retries=2 → 3 attempts; feed 3 bad responses.
    scripted.feed(
        "autoplan.title",
        "not json", "still not json", "{not: valid}",
    )

    result = asyncio.run(autoplan(
        "teach basic spanish greetings",
        cfg=_cfg(), playback_cfg=_pcfg(),
    ))
    # Title aborted → workflow aborted → falls through to heuristic.
    assert result.source == "heuristic"
    # Heuristic still honours the mode from keywords.
    assert result.form.experience_mode in {
        "sfw_education", "language_learning",
    }


def test_workflow_uses_fallback_for_audience(monkeypatch, scripted):
    """Audience has fallback=default_audience; feed bad responses
    and confirm the fallback value lands in the result."""
    monkeypatch.setenv("INTERACTIVE_AUTOPLAN_WORKFLOW", "true")
    scripted.feed("autoplan.classify_mode", "sfw_general")
    scripted.feed("autoplan.extract_topic", "Casual chat topic")
    scripted.feed(
        "autoplan.title",
        '["Hello There", "Friendly Chat", "Warm Welcome"]',
    )
    scripted.feed(
        "autoplan.brief",
        "Say hi and let the viewer pick where the chat goes next. "
        "Short scenes, one choice per beat, friendly tone throughout.",
    )
    # Audience step: feed 3 bad responses (retries=2 → 3 attempts)
    scripted.feed(
        "autoplan.audience", "broken", "still broken", "yet another",
    )
    scripted.feed(
        "autoplan.shape",
        '{"branch_count": 2, "depth": 2, "scenes_per_branch": 2}',
    )
    scripted.feed(
        "autoplan.seed_intents", '["greeting", "choose_path", "wrap_up"]',
    )

    result = asyncio.run(autoplan(
        "hi there, just say hello",
        cfg=_cfg(), playback_cfg=_pcfg(),
    ))
    # Fallback kicked in; workflow completed successfully.
    assert result.source == "llm"
    # Heuristic-derived audience for "hi there" defaults to viewer + beginner.
    assert result.form.audience_role == "viewer"


def test_workflow_flag_off_uses_legacy_path(monkeypatch, scripted):
    """With the flag off call_prompt must NOT be invoked. The
    scripted fixture asserts on calls with no queued response, so
    the test proves the workflow path is skipped."""
    monkeypatch.delenv("INTERACTIVE_AUTOPLAN_WORKFLOW", raising=False)
    monkeypatch.setenv("INTERACTIVE_AUTOPLAN_LEGACY", "true")
    # Scripted fixture is installed but unused by the legacy path.
    result = asyncio.run(autoplan(
        "hello world",
        cfg=_cfg(), playback_cfg=_pcfg(),  # llm_enabled=False
    ))
    assert result.source == "heuristic"
