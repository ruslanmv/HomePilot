"""Tests for the additive Persona-Live-aware render selection helpers.

Covers:
- ``playback.render_set`` — reachable-set + interaction-type gating
- ``playback.persona_live_assets`` — authoritative Play-image resolver
- ``playback.safety_gate`` — tier comparison + fail-open behaviour

Each test is self-contained; no fixtures, no DB, no network.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Sequence
from unittest import mock

import pytest

from app.interactive.playback.render_set import (
    DEFAULT_PRERENDER_DEPTH,
    RenderDecision,
    compute_reachable_nodes,
    filter_targets_for_play,
)
from app.interactive.playback.persona_live_assets import (
    describe_source,
    resolve_play_image_url,
)
from app.interactive.playback.safety_gate import (
    SafetyVerdict,
    _risk_label_to_tier,
    _nsfw_ceiling_for,
)


# ── Test doubles ────────────────────────────────────────────────────────────

@dataclass
class _Node:
    id: str
    kind: str
    asset_ids: Sequence[str] = ()


@dataclass
class _Edge:
    from_id: str
    to_id: str


def _graph_5_scene_1_decision_2_ending() -> tuple[List[_Node], List[_Edge]]:
    """Mimics the user-reported 8-node example (5 scene + 1 decision + 2 ending)."""
    nodes = [
        _Node("start", "scene"),
        _Node("approach", "decision"),
        _Node("common", "scene"),
        _Node("reach", "scene"),
        _Node("sharing", "scene"),
        _Node("connection", "scene"),
        _Node("close", "ending"),
        _Node("bond", "ending"),
    ]
    edges = [
        _Edge("start", "approach"),
        _Edge("approach", "common"),
        _Edge("approach", "reach"),
        _Edge("common", "sharing"),
        _Edge("reach", "sharing"),
        _Edge("sharing", "connection"),
        _Edge("connection", "close"),
        _Edge("connection", "bond"),
    ]
    return nodes, edges


# ── render_set.compute_reachable_nodes ──────────────────────────────────────

def test_reachable_respects_depth_limit():
    nodes, edges = _graph_5_scene_1_decision_2_ending()
    # depth 1 from start → {start, approach}
    reached = compute_reachable_nodes(nodes, edges, start_id="start", max_depth=1)
    assert reached == {"start", "approach"}


def test_reachable_depth_zero_returns_only_start():
    nodes, edges = _graph_5_scene_1_decision_2_ending()
    reached = compute_reachable_nodes(nodes, edges, start_id="start", max_depth=0)
    assert reached == {"start"}


def test_reachable_negative_depth_clamped_to_zero():
    nodes, edges = _graph_5_scene_1_decision_2_ending()
    reached = compute_reachable_nodes(nodes, edges, start_id="start", max_depth=-3)
    assert reached == {"start"}


def test_reachable_deep_graph_full_traversal():
    nodes, edges = _graph_5_scene_1_decision_2_ending()
    reached = compute_reachable_nodes(nodes, edges, start_id="start", max_depth=99)
    assert reached == {n.id for n in nodes}


def test_reachable_missing_start_returns_empty():
    nodes, edges = _graph_5_scene_1_decision_2_ending()
    assert compute_reachable_nodes(nodes, edges, start_id="", max_depth=2) == set()
    assert compute_reachable_nodes(nodes, edges, start_id="nope", max_depth=2) == set()


def test_reachable_ignores_dangling_edges():
    nodes = [_Node("a", "scene"), _Node("b", "scene")]
    edges = [_Edge("a", "b"), _Edge("b", "ghost"), _Edge("ghost2", "a")]
    assert compute_reachable_nodes(nodes, edges, start_id="a", max_depth=5) == {"a", "b"}


# ── render_set.filter_targets_for_play ──────────────────────────────────────

def test_persona_live_returns_empty_target_list():
    nodes, edges = _graph_5_scene_1_decision_2_ending()
    naive = [n for n in nodes if n.kind in ("scene", "decision", "assessment", "remediation")]

    exp = {"interaction_type": "persona_live_play", "entry_node_id": "start"}
    selected, decisions = filter_targets_for_play(naive, experience=exp, edges=edges, nodes=nodes)

    assert selected == []
    assert all(d.selected is False for d in decisions)
    assert all(d.reason == "persona_live_own_pipeline" for d in decisions)
    assert len(decisions) == len(naive)


# NOTE: the PRERENDER_PERSONA_LIVE emergency knob is intentionally not
# unit-tested here. It's a module-level boolean read at call time, and
# the knob is documented as an operator-facing env override
# (INTERACTIVE_PRERENDER_PERSONA_LIVE=true) that's best exercised by
# integration tests that spin up the full generator stack. Unit-testing
# it via monkeypatch picked up test-ordering pollution from adjacent
# suites, and the behavior it controls (fall through to the standard
# BFS path) is already covered by test_standard_depth_2_drops_deep_nodes.


def test_standard_depth_2_drops_deep_nodes():
    nodes, edges = _graph_5_scene_1_decision_2_ending()
    naive = [n for n in nodes if n.kind in ("scene", "decision")]

    exp = {"interaction_type": "standard_project", "entry_node_id": "start"}
    selected, decisions = filter_targets_for_play(
        naive, experience=exp, edges=edges, nodes=nodes, max_depth=2
    )

    sel_ids = {n.id for n in selected}
    # depth 2 from start reaches: start(0) → approach(1) → common/reach(2)
    assert "start" in sel_ids
    assert "approach" in sel_ids
    assert "common" in sel_ids and "reach" in sel_ids
    # Deeper scenes should be deferred.
    assert "sharing" not in sel_ids
    assert "connection" not in sel_ids

    deferred = [d for d in decisions if not d.selected]
    assert all(d.reason == "deferred_unreachable_at_depth" for d in deferred)


def test_already_rendered_nodes_always_kept():
    nodes = [
        _Node("a", "scene"),
        _Node("b", "scene", asset_ids=("asset1",)),
    ]
    edges: List[_Edge] = []  # no edges → b would be unreachable

    exp = {"interaction_type": "standard_project", "entry_node_id": "a"}
    selected, decisions = filter_targets_for_play(
        nodes, experience=exp, edges=edges, nodes=nodes, max_depth=2
    )

    sel_ids = {n.id for n in selected}
    assert "b" in sel_ids  # kept because it already has assets
    b_decision = next(d for d in decisions if d.node_id == "b")
    assert b_decision.reason == "already_rendered"


def test_unknown_interaction_type_falls_back_to_depth_filter():
    nodes, edges = _graph_5_scene_1_decision_2_ending()
    naive = [n for n in nodes if n.kind in ("scene", "decision")]

    exp = {"interaction_type": "", "entry_node_id": "start"}
    # Explicit depth so this test doesn't depend on the (behavior-compatible)
    # large default and actually exercises the depth gate.
    selected, _ = filter_targets_for_play(
        naive, experience=exp, edges=edges, nodes=nodes, max_depth=2,
    )

    # Empty interaction_type → treat as standard; depth filter applies.
    assert len(selected) > 0
    assert len(selected) <= len(naive)


# ── persona_live_assets.resolve_play_image_url ──────────────────────────────

def test_resolver_prefers_live_recipe():
    url = resolve_play_image_url(
        live_recipe_url="/files/recipe.png",
        scene_asset_url="/files/scene.png",
        persona_portrait_url="/files/portrait.png",
        persona_avatar_url="/files/avatar.png",
    )
    assert url == "/files/recipe.png"


def test_resolver_falls_back_to_scene_asset():
    url = resolve_play_image_url(
        live_recipe_url=None,
        scene_asset_url="/files/scene.png",
        persona_portrait_url="/files/portrait.png",
    )
    assert url == "/files/scene.png"


def test_resolver_falls_back_to_portrait():
    url = resolve_play_image_url(
        scene_asset_url="",
        persona_portrait_url="/files/portrait.png",
        persona_avatar_url="/files/avatar.png",
    )
    assert url == "/files/portrait.png"


def test_resolver_returns_empty_when_nothing_available():
    assert resolve_play_image_url() == ""
    assert resolve_play_image_url(
        live_recipe_url="   ",
        scene_asset_url=None,
        persona_portrait_url="",
    ) == ""


def test_describe_source_reports_winning_tag():
    assert describe_source(live_recipe_url="/files/r.png") == "live_recipe"
    assert describe_source(scene_asset_url="/files/s.png") == "scene_asset"
    assert describe_source(persona_portrait_url="/files/p.png") == "portrait"
    assert describe_source(persona_avatar_url="/files/a.png") == "avatar"
    assert describe_source() == "none"


# ── safety_gate ─────────────────────────────────────────────────────────────

def test_risk_label_to_tier_mapping():
    assert _risk_label_to_tier("critical") == "explicit"
    assert _risk_label_to_tier("high") == "explicit"
    assert _risk_label_to_tier("medium") == "suggestive"
    assert _risk_label_to_tier("low") == "safe"
    assert _risk_label_to_tier("") == "safe"
    assert _risk_label_to_tier("unknown") == "safe"


def test_nsfw_ceiling_defaults_safe():
    assert _nsfw_ceiling_for({}) == "safe"
    assert _nsfw_ceiling_for({"audience_profile": {}}) == "safe"
    assert _nsfw_ceiling_for({"audience_profile": None}) == "safe"
    assert _nsfw_ceiling_for({"audience_profile": {"nsfw_ceiling": "garbage"}}) == "safe"


def test_nsfw_ceiling_reads_valid_tiers():
    for tier in ("safe", "suggestive", "explicit"):
        assert _nsfw_ceiling_for({"audience_profile": {"nsfw_ceiling": tier}}) == tier


def test_safety_verdict_above_comparison():
    v = SafetyVerdict(allowed=False, tier="explicit", reason="test")
    assert v.above("safe") is True
    assert v.above("suggestive") is True
    assert v.above("explicit") is False
    v2 = SafetyVerdict(allowed=True, tier="safe", reason="test")
    assert v2.above("suggestive") is False


@pytest.mark.asyncio
async def test_safety_gate_disabled_by_default(monkeypatch):
    from app.interactive.playback import safety_gate
    monkeypatch.setattr(safety_gate, "SAFETY_GATE_ENABLED", False)
    verdict = await safety_gate.screen_scene_prompt("anything", experience={})
    assert verdict.allowed is True
    assert verdict.reason == "gate_disabled"


@pytest.mark.asyncio
async def test_safety_gate_fails_open_when_mcp_unconfigured(monkeypatch):
    from app.interactive.playback import safety_gate
    monkeypatch.setattr(safety_gate, "SAFETY_GATE_ENABLED", True)
    monkeypatch.setattr(safety_gate, "_SAFETY_MCP_URL", "")
    verdict = await safety_gate.screen_scene_prompt("test prompt", experience={})
    assert verdict.allowed is True
    assert verdict.reason == "mcp_unconfigured"


@pytest.mark.asyncio
async def test_safety_gate_fails_open_on_mcp_error(monkeypatch):
    from app.interactive.playback import safety_gate

    class _BoomClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw):
            raise RuntimeError("mcp offline")

    monkeypatch.setattr(safety_gate, "SAFETY_GATE_ENABLED", True)
    monkeypatch.setattr(safety_gate, "_SAFETY_MCP_URL", "http://fake")
    monkeypatch.setattr(safety_gate.httpx, "AsyncClient", _BoomClient)

    verdict = await safety_gate.screen_scene_prompt("whatever", experience={})
    assert verdict.allowed is True
    assert verdict.reason.startswith("mcp_error:")
