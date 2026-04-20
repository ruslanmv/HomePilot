"""
Tests for the stage-2 autogen workflow (REV-4).

Covers:

* Spine parser + validator round-trip (unique ids, kinds,
  choice_labels length match, reachability).
* Script parser + validator length bounds.
* End-to-end: spine + 7 scripts produce a complete GraphPlan.
* Spine abort surfaces as ``plan is None`` (legacy path takes over).
* Per-scene script fallback keeps the graph intact when a
  single script call fails.
* Feature flag: INTERACTIVE_AUTOGEN_WORKFLOW / _LEGACY priority.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest


# Lazy imports via autouse fixture — see the sister test files
# for why this is required.

@pytest.fixture(autouse=True)
def _refresh_symbols():
    from app.interactive.planner import autogen_workflow as _aw
    from app.interactive.planner import autogen_llm as _al
    g = globals()
    g["autogen_workflow"] = _aw
    g["run_autogen_workflow"] = _aw.run_autogen_workflow
    g["workflow_enabled"] = _aw.workflow_enabled
    g["_parse_spine"] = _aw._parse_spine
    g["_parse_script"] = _aw._parse_script
    g["_validate_spine"] = _aw._validate_spine
    g["_validate_script"] = _aw._validate_script
    g["GraphPlan"] = _al.GraphPlan
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


def _make_experience(**overrides) -> Any:
    """Lightweight stand-in for the Experience pydantic model.

    The workflow only reads specific string/int attributes; a
    namespace object keeps the test independent of schema drift
    in the real models module.
    """
    import types
    base = dict(
        title="Pricing Tier Onboarding",
        description="Train new sales reps on three pricing tiers.",
        objective="Teach pricing tiers through decisions",
        experience_mode="enterprise_training",
        branch_count=2,
        depth=2,
        scenes_per_branch=2,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


# ── Parsers + validators ───────────────────────────────────────

_SPINE_OK = (
    '{"start":"intro","scenes":['
    '{"id":"intro","kind":"scene","next":["pick"]},'
    '{"id":"pick","kind":"decision","next":["a1","b1"],'
    ' "choice_labels":["Take path A","Take path B"]},'
    '{"id":"a1","kind":"scene","next":["a_end"]},'
    '{"id":"a_end","kind":"ending"},'
    '{"id":"b1","kind":"scene","next":["b_end"]},'
    '{"id":"b_end","kind":"ending"}'
    ']}'
)


def test_parse_spine_accepts_valid_payload():
    spine = _parse_spine(_SPINE_OK)
    assert spine["start"] == "intro"
    assert {s["id"] for s in spine["scenes"]} == {
        "intro", "pick", "a1", "a_end", "b1", "b_end",
    }


def test_parse_spine_raises_on_garbage():
    with pytest.raises(ValueError):
        _parse_spine("not even close to json")


def test_validate_spine_catches_unreachable_scenes():
    spine = _parse_spine(
        '{"start":"intro","scenes":['
        '{"id":"intro","kind":"scene","next":["end"]},'
        '{"id":"end","kind":"ending"},'
        '{"id":"lonely","kind":"scene","next":["end"]}'
        ']}'
    )
    err = _validate_spine(spine)
    assert err is not None and "unreachable" in err


def test_validate_spine_catches_dangling_next():
    spine = _parse_spine(
        '{"start":"intro","scenes":['
        '{"id":"intro","kind":"scene","next":["missing"]},'
        '{"id":"end","kind":"ending"}'
        ']}'
    )
    err = _validate_spine(spine)
    assert err is not None


def test_validate_spine_catches_bad_choice_label_length():
    spine = _parse_spine(
        '{"start":"d","scenes":['
        '{"id":"d","kind":"decision","next":["a","b"],'
        ' "choice_labels":["only one"]},'
        '{"id":"a","kind":"ending"},{"id":"b","kind":"ending"}]}'
    )
    err = _validate_spine(spine)
    assert err is not None and "choice_labels" in err


def test_parse_script_and_validate():
    ok = _parse_script(
        '{"title":"Welcome","narration":"This scene sets the stage."}'
    )
    assert ok == {"title": "Welcome", "narration": "This scene sets the stage."}
    assert _validate_script(ok) is None


def test_validate_script_rejects_too_short_narration():
    assert _validate_script({"title": "Ok Title", "narration": "eh"}) is not None


# ── Feature flag ───────────────────────────────────────────────

def test_autogen_workflow_enabled_by_default(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_AUTOGEN_WORKFLOW", raising=False)
    monkeypatch.delenv("INTERACTIVE_AUTOGEN_LEGACY", raising=False)
    assert workflow_enabled() is True


def test_autogen_workflow_flag_false_opts_out(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_AUTOGEN_WORKFLOW", "false")
    assert workflow_enabled() is False


def test_legacy_flag_opts_out_when_workflow_unset(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_AUTOGEN_WORKFLOW", raising=False)
    monkeypatch.setenv("INTERACTIVE_AUTOGEN_LEGACY", "1")
    assert workflow_enabled() is False


def test_workflow_flag_beats_legacy(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_AUTOGEN_WORKFLOW", "1")
    monkeypatch.setenv("INTERACTIVE_AUTOGEN_LEGACY", "1")
    assert workflow_enabled() is True


# ── End-to-end ────────────────────────────────────────────────

_SCRIPT_OK = '{{"title":"{title}","narration":"Some narration text for scene {sid}."}}'


def _feed_spine(scripted):
    scripted.feed("autogen.scene_spine", _SPINE_OK)


def _feed_all_scripts(scripted):
    # Matches the 6 scenes in _SPINE_OK. The workflow loops
    # sequentially so each scene pulls from the same queue once.
    for sid, title in [
        ("intro", "Welcome Aboard"),
        ("pick", "Choose Your Approach"),
        ("a1", "Path A Walkthrough"),
        ("a_end", "Path A Wrap"),
        ("b1", "Path B Walkthrough"),
        ("b_end", "Path B Wrap"),
    ]:
        scripted.feed("autogen.scene_script",
                      _SCRIPT_OK.format(title=title, sid=sid))


def test_workflow_happy_path_produces_full_graph(scripted):
    _feed_spine(scripted)
    _feed_all_scripts(scripted)
    plan = asyncio.run(run_autogen_workflow(_make_experience()))
    assert plan is not None
    assert plan.source == "llm"
    # 6 nodes, 5 edges (intro→pick, pick→a1/b1 [choice], a1→a_end, b1→b_end)
    assert {n.local_id for n in plan.nodes} == {
        "intro", "pick", "a1", "a_end", "b1", "b_end",
    }
    # Entry flag on the start node.
    entries = [n for n in plan.nodes if n.is_entry]
    assert len(entries) == 1 and entries[0].local_id == "intro"
    # Choice edges carry their labels into ActionSpec rows.
    choice_edges = [e for e in plan.edges if e.trigger_kind == "choice"]
    assert {e.label for e in choice_edges} == {"Take path A", "Take path B"}
    assert {a.label for a in plan.actions} == {"Take path A", "Take path B"}


def test_spine_abort_returns_none(scripted):
    # retries=2 → 3 attempts; feed 3 bad responses.
    for _ in range(3):
        scripted.feed("autogen.scene_spine", "garbage not a spine")
    plan = asyncio.run(run_autogen_workflow(_make_experience()))
    assert plan is None


def test_one_failing_script_uses_fallback_title(scripted):
    _feed_spine(scripted)
    # First script (intro) fails every attempt → fallback fires.
    # retries=2 → 3 attempts; we feed exactly 3 garbage replies,
    # then valid scripts for the remaining 5 scenes.
    for _ in range(3):
        scripted.feed("autogen.scene_script", "not-a-json")
    for sid, title in [
        ("pick", "Choose Your Approach"),
        ("a1", "Path A Walkthrough"),
        ("a_end", "Path A Wrap"),
        ("b1", "Path B Walkthrough"),
        ("b_end", "Path B Wrap"),
    ]:
        scripted.feed("autogen.scene_script",
                      _SCRIPT_OK.format(title=title, sid=sid))

    plan = asyncio.run(run_autogen_workflow(_make_experience()))
    assert plan is not None
    intro = next(n for n in plan.nodes if n.local_id == "intro")
    # Fallback title for the opening scene is "Welcome — <topic>".
    assert intro.title.lower().startswith("welcome")
    # Narration is non-empty (the fallback produced something).
    assert intro.narration.strip()
