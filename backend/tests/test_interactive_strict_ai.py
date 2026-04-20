"""
Tests for the strict-AI content-fallback gate (REV-6).

When ``INTERACTIVE_STRICT_AI=true``:

* Autoplan seed_intents: preset fallback refuses to run → workflow
  aborts → caller falls back to heuristic only if the env lets
  heuristic run. In strict mode a failing seed_intents step
  surfaces an abort (since the preset-based default is the last
  line of defence for content-shaped output).
* Autogen per-scene script: the topic-aware default raises
  StepFailure, aborting the stage-2 run so the user sees a real
  error rather than hardcoded "Welcome — <topic>" prose.

Strict mode defaults OFF so offline installs with no LLM keep
working. REV-7 flips the workflow default ON but leaves strict
OFF; operators opt into strict after telemetry confirms the LLM
reliably answers every prompt.
"""
from __future__ import annotations

import asyncio
import types
from typing import Any, Dict, List

import pytest


@pytest.fixture(autouse=True)
def _refresh_symbols():
    from app.interactive.planner import autoplan_workflow as _aw
    from app.interactive.planner import autogen_workflow as _ag
    g = globals()
    g["autoplan_workflow"] = _aw
    g["autogen_workflow"] = _ag
    g["run_autoplan_workflow"] = _aw.run_autoplan_workflow
    g["run_autogen_workflow"] = _ag.run_autogen_workflow
    yield


@pytest.fixture
def scripted(monkeypatch):
    from app.interactive.workflows import runner as runner_mod

    class _Scripted:
        def __init__(self):
            self.map: Dict[str, List[str]] = {}

        def feed(self, prompt_id: str, *responses: str) -> None:
            self.map.setdefault(prompt_id, []).extend(responses)

        async def __call__(self, prompt, policy, **_kw):
            q = self.map.get(prompt.prompt_id)
            if not q:
                raise AssertionError(f"No scripted response for {prompt.prompt_id}")
            return {"choices": [{"message": {"content": q.pop(0)}}]}

    s = _Scripted()
    monkeypatch.setattr(runner_mod, "call_prompt", s)
    return s


def _cfg():
    from app.interactive.config import InteractiveConfig
    return InteractiveConfig(
        enabled=True, max_branches=6, max_depth=4,
        max_nodes_per_experience=100, llm_model="llama3:8b",
        storage_root="", require_consent_for_mature=True,
        enforce_region_block=True, moderate_mature_narration=True,
        region_block=[], runtime_latency_target_ms=200,
    )


# ── Flag defaults OFF ──────────────────────────────────────────

def test_strict_ai_defaults_off(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_STRICT_AI", raising=False)
    assert autoplan_workflow.strict_ai_enabled() is False
    assert autogen_workflow.strict_ai_enabled() is False


def test_strict_ai_flag_is_shared(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_STRICT_AI", "true")
    assert autoplan_workflow.strict_ai_enabled() is True
    assert autogen_workflow.strict_ai_enabled() is True


# ── Autoplan strict behaviour ──────────────────────────────────

def _feed_autoplan_up_to_seed(scripted):
    scripted.feed("autoplan.classify_mode", "sfw_general")
    scripted.feed("autoplan.extract_topic", "Chat")
    scripted.feed(
        "autoplan.title",
        '["Warm Hello", "Friendly Start", "Gentle Intro"]',
    )
    scripted.feed(
        "autoplan.brief",
        "Let the viewer pick where the chat goes next. Short scenes, "
        "one choice per beat, friendly tone throughout.",
    )
    scripted.feed(
        "autoplan.audience",
        '{"role":"viewer","level":"beginner","language":"en"}',
    )
    scripted.feed(
        "autoplan.shape",
        '{"branch_count": 2, "depth": 2, "scenes_per_branch": 2}',
    )


def test_autoplan_strict_mode_aborts_on_seed_intents_fallback(
    monkeypatch, scripted,
):
    monkeypatch.setenv("INTERACTIVE_STRICT_AI", "true")
    _feed_autoplan_up_to_seed(scripted)
    # seed_intents has retries=2 → 3 attempts; all invalid.
    scripted.feed(
        "autoplan.seed_intents",
        "not-an-array", "{bad}", '["JUST", "ONE"]',
    )
    result = asyncio.run(run_autoplan_workflow("hi", cfg=_cfg()))
    assert result.aborted
    assert "strict_ai" in (result.error or "")


def test_autoplan_non_strict_mode_uses_preset_fallback(
    monkeypatch, scripted,
):
    monkeypatch.delenv("INTERACTIVE_STRICT_AI", raising=False)
    _feed_autoplan_up_to_seed(scripted)
    scripted.feed(
        "autoplan.seed_intents",
        "not-an-array", "{bad}", '["JUST", "ONE"]',
    )
    result = asyncio.run(run_autoplan_workflow("hi", cfg=_cfg()))
    assert not result.aborted
    # Preset fallback fired; intents came from the sfw_general preset.
    intents = result.context["seed_intents"]
    assert isinstance(intents, list) and len(intents) >= 2


# ── Autogen strict behaviour ───────────────────────────────────

_SPINE_OK = (
    '{"start":"intro","scenes":['
    '{"id":"intro","kind":"scene","next":["pick"]},'
    '{"id":"pick","kind":"decision","next":["a1","b1"],'
    ' "choice_labels":["Path A","Path B"]},'
    '{"id":"a1","kind":"scene","next":["a_end"]},'
    '{"id":"a_end","kind":"ending"},'
    '{"id":"b1","kind":"scene","next":["b_end"]},'
    '{"id":"b_end","kind":"ending"}]}'
)


def _make_experience():
    return types.SimpleNamespace(
        title="Test Project",
        description="Hello world interactive pilot.",
        objective="Show the strict path",
        experience_mode="sfw_general",
        branch_count=2, depth=2, scenes_per_branch=2,
    )


def test_autogen_strict_mode_aborts_on_script_fallback(monkeypatch, scripted):
    monkeypatch.setenv("INTERACTIVE_STRICT_AI", "true")
    scripted.feed("autogen.scene_spine", _SPINE_OK)
    # First scene's script fails all 3 attempts → fallback runs →
    # strict mode raises StepFailure → run_autogen_workflow returns None.
    for _ in range(3):
        scripted.feed("autogen.scene_script", "not-json")

    plan = asyncio.run(run_autogen_workflow(_make_experience()))
    assert plan is None


def test_autogen_non_strict_mode_uses_template_fallback(
    monkeypatch, scripted,
):
    monkeypatch.delenv("INTERACTIVE_STRICT_AI", raising=False)
    scripted.feed("autogen.scene_spine", _SPINE_OK)
    # Scene 1 fails → template fallback; rest succeed.
    for _ in range(3):
        scripted.feed("autogen.scene_script", "not-json")
    for sid in ["pick", "a1", "a_end", "b1", "b_end"]:
        scripted.feed(
            "autogen.scene_script",
            '{"title":"Valid Title","narration":"A valid narration string."}',
        )

    plan = asyncio.run(run_autogen_workflow(_make_experience()))
    assert plan is not None
    intro = next(n for n in plan.nodes if n.local_id == "intro")
    assert intro.title  # templated fallback produced something
