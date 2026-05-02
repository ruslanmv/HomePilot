"""Tests for the purpose-built Persona Live Play scene graph.

The autogen's LLM spine path was producing invalid graphs for
persona_live projects ("next=None" validator failures) and the
Standard Interactive heuristic fallback was building an entry →
decision → branches → ending topology with a "Continue / Ask for a
hint" catalog — neither of which fits the intent-driven Live Action
runtime. ``generate_graph`` now short-circuits on
``experience.project_type == "persona_live"`` and returns
``_persona_live_graph`` directly. These tests lock in:

* the graph has an entry scene (so QA's no_entry_scene check passes)
* every edge lands on a node that exists (so the validator's
  "next 'None' not in scenes" regression can't recur)
* the action catalog uses the Level-1 intent ids, not "continue" /
  "request_hint"
* the four choice edges out of the entry match the Level-1 intents in
  ``_INTENT_CATALOG``
* ``_default_actions(experience)`` returns the intent catalog for
  persona_live and the generic pair for everything else
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.interactive.planner.autogen_llm import (
    _PERSONA_LIVE_LEVEL_1_INTENTS,
    _persona_live_graph,
    generate_graph,
)
from app.interactive.routes.generator_auto import _default_actions
from app.interactive.config import InteractiveConfig


def _fake_experience(**kw: Any) -> Any:
    return SimpleNamespace(
        id="exp_test",
        title=kw.get("title", "sexy girl"),
        description=kw.get("description", ""),
        objective="",
        experience_mode=kw.get("experience_mode", "mature_gated"),
        project_type=kw.get("project_type", "persona_live"),
        audience_profile=kw.get("audience_profile", {"persona_label": "Lina"}),
    )


# ── Graph shape ─────────────────────────────────────────────────────────────

def test_graph_has_exactly_one_entry_scene():
    plan = _persona_live_graph(_fake_experience())
    entry_nodes = [n for n in plan.nodes if n.is_entry]
    assert len(entry_nodes) == 1
    assert entry_nodes[0].kind == "scene"


def test_graph_has_four_reaction_scenes_plus_followup_plus_epilogue():
    plan = _persona_live_graph(_fake_experience())
    kinds = [n.kind for n in plan.nodes]
    assert kinds.count("scene") == 6   # entry + 4 reactions + followup
    assert kinds.count("ending") == 1  # epilogue


def test_every_edge_references_an_existing_node():
    """Regression for the 'next None not in scenes' validator failure."""
    plan = _persona_live_graph(_fake_experience())
    node_ids = {n.local_id for n in plan.nodes}
    for edge in plan.edges:
        assert edge.from_local_id in node_ids, f"edge.from missing: {edge.from_local_id}"
        assert edge.to_local_id in node_ids, f"edge.to missing: {edge.to_local_id}"


def test_entry_has_one_choice_edge_per_level_1_intent():
    plan = _persona_live_graph(_fake_experience())
    entry = next(n for n in plan.nodes if n.is_entry)
    choice_edges = [
        e for e in plan.edges
        if e.from_local_id == entry.local_id and e.trigger_kind == "choice"
    ]
    intent_ids = [row[0] for row in _PERSONA_LIVE_LEVEL_1_INTENTS]
    assert sorted(e.label for e in choice_edges) == sorted(intent_ids)


def test_reaction_scenes_all_flow_into_followup():
    plan = _persona_live_graph(_fake_experience())
    reaction_ids = {
        f"lina_reaction_{row[0]}" for row in _PERSONA_LIVE_LEVEL_1_INTENTS
    }
    for rid in reaction_ids:
        outs = [e for e in plan.edges if e.from_local_id == rid]
        assert len(outs) == 1, f"{rid} should have exactly one outbound edge"
        assert outs[0].to_local_id == "lina_followup"
        assert outs[0].trigger_kind == "auto"


def test_followup_flows_into_epilogue():
    plan = _persona_live_graph(_fake_experience())
    outs = [e for e in plan.edges if e.from_local_id == "lina_followup"]
    assert len(outs) == 1
    assert outs[0].to_local_id == "lina_epilogue"


def test_narration_uses_persona_label_from_audience_profile():
    plan = _persona_live_graph(_fake_experience(
        audience_profile={"persona_label": "Mia"},
    ))
    # Entry narration should mention the persona by name
    entry = next(n for n in plan.nodes if n.is_entry)
    assert "Mia" in entry.narration


def test_narration_falls_back_to_default_when_no_persona_label():
    plan = _persona_live_graph(_fake_experience(
        audience_profile={}, title="",
    ))
    entry = next(n for n in plan.nodes if n.is_entry)
    # Default is "Lina"
    assert "Lina" in entry.narration


# ── Action catalog ──────────────────────────────────────────────────────────

def test_action_catalog_uses_intent_ids():
    plan = _persona_live_graph(_fake_experience())
    intent_codes = {a.intent_code for a in plan.actions}
    assert intent_codes == {"say_playful", "compliment", "ask_about_her", "stay_quiet"}
    # And NOT the Standard Interactive default pair
    assert "continue" not in intent_codes
    assert "request_hint" not in intent_codes


def test_action_labels_are_player_facing_not_character_states():
    plan = _persona_live_graph(_fake_experience())
    labels = {a.label for a in plan.actions}
    # The smoking-gun set the user complained about — these are
    # character OUTPUTS and must not appear as action labels.
    assert not ({"Tease", "Smirk", "Blush", "Closer Pose"} & labels)


def test_default_actions_returns_intent_catalog_for_persona_live():
    actions = _default_actions(_fake_experience(project_type="persona_live"))
    intent_codes = {a.intent_code for a in actions}
    assert "say_playful" in intent_codes
    assert "compliment" in intent_codes
    assert "continue" not in intent_codes


def test_default_actions_returns_generic_pair_for_standard():
    actions = _default_actions(_fake_experience(project_type="standard"))
    intent_codes = {a.intent_code for a in actions}
    assert intent_codes == {"continue", "request_hint"}


def test_default_actions_without_experience_argument_stays_generic():
    """Legacy callers that passed no args still get the old behaviour."""
    actions = _default_actions()
    intent_codes = {a.intent_code for a in actions}
    assert intent_codes == {"continue", "request_hint"}


# ── generate_graph routing ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_graph_short_circuits_on_persona_live():
    """project_type='persona_live' must bypass the LLM spine workflow
    entirely and return a plan with source='persona_live'. Without this
    branch the spine LLM's 'next=None' validator failure knocked the
    wizard onto the Standard heuristic which produced generic output."""
    cfg = InteractiveConfig()
    plan = await generate_graph(_fake_experience(), cfg=cfg)
    assert plan.source == "persona_live"
    assert any(n.is_entry and n.kind == "scene" for n in plan.nodes)


@pytest.mark.asyncio
async def test_generate_graph_non_persona_live_skips_the_new_branch():
    """Standard Interactive must NOT pick up the persona_live graph."""
    cfg = InteractiveConfig()
    plan = await generate_graph(_fake_experience(project_type="standard"), cfg=cfg)
    assert plan.source != "persona_live"
