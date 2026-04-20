"""
Tests for planner.autogen_llm — Stage-2 scene graph generator.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.interactive.config import InteractiveConfig
from app.interactive.models import Experience
from app.interactive.planner.autogen_llm import (
    ActionSpec, EdgeSpec, GraphPlan, NodeSpec, generate_graph,
)
from app.interactive.playback.playback_config import PlaybackConfig


@pytest.fixture(autouse=True)
def _force_legacy_autogen(monkeypatch):
    """Pin legacy for this file — REV-7 flipped the default to
    workflow-on. ``test_interactive_autogen_workflow.py`` covers
    the new path."""
    monkeypatch.setenv("INTERACTIVE_AUTOGEN_LEGACY", "true")
    monkeypatch.delenv("INTERACTIVE_AUTOGEN_WORKFLOW", raising=False)
    yield


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
        llm_enabled=llm_enabled, llm_timeout_s=30.0,
        llm_max_tokens=1500, llm_temperature=0.55,
        render_enabled=False, render_workflow="animate", image_workflow="avatar_txt2img",
        render_timeout_s=60.0,
    )


def _exp() -> Experience:
    return Experience(
        id="ixe_test", user_id="u1",
        title="Sales rep pricing training",
        description="Walk a new hire through our 3 pricing tiers.",
        experience_mode="enterprise_training",
        policy_profile_id="enterprise_training",
        status="draft",
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


# A valid LLM payload: 1 intro → 1 decision → 2 endings. No cycles.
_VALID_PAYLOAD = (
    '{'
    '"scenes": ['
    '  {"id": "intro", "type": "scene", "title": "Welcome",'
    '   "script": "Welcome aboard. Let\'s pick your path.",'
    '   "visual_direction": "warm studio light, direct gaze",'
    '   "next": ["pick"]},'
    '  {"id": "pick", "type": "decision", "title": "Choose a tier",'
    '   "script": "Which tier matches your customer?",'
    '   "visual_direction": "three paths visualized behind host",'
    '   "interaction": {"type": "choice", "options": ['
    '      {"label": "Starter", "next": "end_starter"},'
    '      {"label": "Pro", "next": "end_pro"}'
    '   ]}},'
    '  {"id": "end_starter", "type": "ending", "title": "Starter plan",'
    '   "script": "Nice. The Starter plan is our most popular entry.",'
    '   "visual_direction": "smile, nodding"},'
    '  {"id": "end_pro", "type": "ending", "title": "Pro plan",'
    '   "script": "Great choice for power users.",'
    '   "visual_direction": "confident smile"}'
    '],'
    '"logic": {"start_scene": "intro"}'
    '}'
)


# ── Heuristic path ────────────────────────────────────────────

def test_heuristic_returns_a_plan_with_entry_and_ending():
    plan = _run(generate_graph(_exp(), cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False)))
    assert plan.source == "heuristic"
    assert plan.nodes
    # Exactly one entry node.
    entries = [n for n in plan.nodes if n.is_entry]
    assert len(entries) == 1
    # At least one ending.
    assert any(n.kind == "ending" for n in plan.nodes)


def test_heuristic_last_resort_when_parse_fails(monkeypatch):
    # Force parse_prompt to explode so the heuristic hits the
    # 'last resort' single-scene graph path.
    import app.interactive.planner.autogen_llm as mod

    def _boom(*a, **k):
        raise RuntimeError("broken")

    monkeypatch.setattr(mod, "parse_prompt", _boom)
    plan = _run(generate_graph(_exp(), cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False)))
    assert plan.source == "heuristic"
    # Minimal graph: one entry scene + one ending + one edge.
    assert len(plan.nodes) == 2
    assert plan.nodes[0].is_entry
    assert plan.nodes[-1].kind == "ending"


# ── LLM path ──────────────────────────────────────────────────

def test_llm_payload_maps_to_graph_plan(monkeypatch):
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": _VALID_PAYLOAD}}]},
    )
    plan = _run(generate_graph(_exp(), cfg=_cfg(), playback_cfg=_pcfg()))
    assert plan.source == "llm"
    assert len(plan.nodes) == 4
    # Slug-matched ids + normalized kinds
    kinds = {n.local_id: n.kind for n in plan.nodes}
    assert kinds["intro"] == "scene"
    assert kinds["pick"] == "decision"
    assert kinds["end_starter"] == "ending"
    assert kinds["end_pro"] == "ending"
    # Entry flag = start_scene
    assert any(n.local_id == "intro" and n.is_entry for n in plan.nodes)
    # Choice options produced both edges and actions
    labels = sorted(a.label for a in plan.actions)
    assert labels == ["Pro", "Starter"]
    # 4 edges: intro→pick (auto) + pick→end_starter (choice) +
    # pick→end_pro (choice). The dedup step prevents counting
    # duplicates from the options and next arrays.
    assert len(plan.edges) == 3
    triggers = [e.trigger_kind for e in plan.edges]
    assert "auto" in triggers and triggers.count("choice") == 2


def test_llm_code_fence_tolerated(monkeypatch):
    fenced = "```json\n" + _VALID_PAYLOAD + "\n```"
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": fenced}}]},
    )
    plan = _run(generate_graph(_exp(), cfg=_cfg(), playback_cfg=_pcfg()))
    assert plan.source == "llm"


def test_llm_missing_ending_gets_promoted(monkeypatch):
    # Payload with NO explicit ending — the normalizer should
    # promote the last node to kind='ending' so validate_graph
    # doesn't reject on V3 (every non-ending needs an outbound edge).
    no_ending = (
        '{'
        '"scenes": ['
        '  {"id": "a", "type": "scene", "title": "A",'
        '   "script": "Aaa", "visual_direction": "v",'
        '   "next": ["b"]},'
        '  {"id": "b", "type": "scene", "title": "B",'
        '   "script": "Bbb", "visual_direction": "v"}'
        '],'
        '"logic": {"start_scene": "a"}'
        '}'
    )
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": no_ending}}]},
    )
    plan = _run(generate_graph(_exp(), cfg=_cfg(), playback_cfg=_pcfg()))
    assert plan.source == "llm"
    assert plan.nodes[-1].kind == "ending"


def test_llm_rejects_cyclic_graph_and_falls_back(monkeypatch):
    cyclic = (
        '{'
        '"scenes": ['
        '  {"id": "a", "type": "scene", "title": "A",'
        '   "script": "Aa", "visual_direction": "v", "next": ["b"]},'
        '  {"id": "b", "type": "scene", "title": "B",'
        '   "script": "Bb", "visual_direction": "v", "next": ["a"]}'
        '],'
        '"logic": {"start_scene": "a"}'
        '}'
    )
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": cyclic}}]},
    )
    plan = _run(generate_graph(_exp(), cfg=_cfg(), playback_cfg=_pcfg()))
    # Cycle fails validate_graph → heuristic fallback used.
    assert plan.source == "heuristic"


# ── LLM fallback paths ────────────────────────────────────────

def test_llm_disabled_uses_heuristic(monkeypatch):
    async def _boom(*a, **k):
        raise AssertionError("LLM should not be called")
    import app.llm as llm_mod
    monkeypatch.setattr(llm_mod, "chat_ollama", _boom)
    plan = _run(generate_graph(_exp(), cfg=_cfg(), playback_cfg=_pcfg(llm_enabled=False)))
    assert plan.source == "heuristic"


def test_llm_exception_falls_back(monkeypatch):
    _install_chat(monkeypatch, RuntimeError("network down"))
    plan = _run(generate_graph(_exp(), cfg=_cfg(), playback_cfg=_pcfg()))
    assert plan.source == "heuristic"


def test_llm_malformed_json_falls_back(monkeypatch):
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": "definitely not json"}}]},
    )
    plan = _run(generate_graph(_exp(), cfg=_cfg(), playback_cfg=_pcfg()))
    assert plan.source == "heuristic"


def test_llm_empty_scenes_array_falls_back(monkeypatch):
    empty = '{"scenes": [], "logic": {"start_scene": "x"}}'
    _install_chat(
        monkeypatch,
        {"choices": [{"message": {"content": empty}}]},
    )
    plan = _run(generate_graph(_exp(), cfg=_cfg(), playback_cfg=_pcfg()))
    assert plan.source == "heuristic"
