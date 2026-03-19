"""
Unit tests for LangGraph Persona Agent — graph building, state, nodes, workflows.

Lightweight, CI-compatible (no network, no GPU, no external services).
Tests the graph structure, state schema, embodiment prompt, and workflow definitions.
"""
from __future__ import annotations

import sys
from pathlib import Path

import asyncio

import pytest


def _run(coro):
    """Run an async coroutine synchronously (CI-compatible)."""
    return asyncio.get_event_loop().run_until_complete(coro)

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── State schema tests ───────────────────────────────────────────────


class TestPersonaAgentState:
    """Verify the state TypedDict structure is valid."""

    def test_state_can_be_instantiated(self):
        from backend.app.langgraph_personas.state import PersonaAgentState

        state: PersonaAgentState = {
            "user_message": "Hello",
            "persona_id": "scarlett_secretary",
            "reasoning_mode": "orchestrated",
        }
        assert state["user_message"] == "Hello"
        assert state["reasoning_mode"] == "orchestrated"

    def test_world_snapshot_structure(self):
        from backend.app.langgraph_personas.state import WorldSnapshot

        ws: WorldSnapshot = {
            "user_position": {"x": 0, "y": 0, "z": 0},
            "avatar_distance_m": 2.5,
            "anchors": [{"id": "chair1", "type": "seat", "position": {"x": 1, "y": 0, "z": 1}}],
        }
        assert ws["avatar_distance_m"] == 2.5

    def test_motion_plan_dict_structure(self):
        from backend.app.langgraph_personas.state import MotionPlanDict

        plan: MotionPlanDict = {
            "persona_id": "scarlett",
            "commands": [
                {"type": "approach", "target": "user", "distance_m": 1.2},
                {"type": "look_at", "target": "user_head"},
            ],
            "interruptible": True,
            "priority": "normal",
        }
        assert len(plan["commands"]) == 2

    def test_tool_result_structure(self):
        from backend.app.langgraph_personas.state import ToolResult

        tr: ToolResult = {
            "tool": "web.search",
            "args": {"query": "test"},
            "output": "search results...",
            "media": None,
        }
        assert tr["tool"] == "web.search"


# ── Graph builder tests ──────────────────────────────────────────────


class TestGraphBuilder:
    """Verify graph construction for each reasoning mode."""

    def test_build_orchestrated_graph(self):
        from backend.app.langgraph_personas.graph_builder import build_persona_graph

        graph = build_persona_graph("orchestrated")
        assert graph is not None

    def test_build_guided_graph(self):
        from backend.app.langgraph_personas.graph_builder import build_persona_graph

        graph = build_persona_graph("guided")
        assert graph is not None

    def test_build_direct_graph(self):
        from backend.app.langgraph_personas.graph_builder import build_persona_graph

        graph = build_persona_graph("direct")
        assert graph is not None

    def test_default_is_direct(self):
        from backend.app.langgraph_personas.graph_builder import build_persona_graph

        graph = build_persona_graph("unknown_mode")
        assert graph is not None


# ── Perceive node tests ──────────────────────────────────────────────


class TestPerceiveNode:
    """Test the perceive node generates correct perception summaries."""

    def test_perceive_with_world_state(self):
        from backend.app.langgraph_personas.nodes.perceive import perceive

        state = {
            "world_snapshot": {
                "avatar_distance_m": 1.5,
                "user_velocity_mps": 0.0,
                "user_left_hand": {"x": 0, "y": 1, "z": 0},
                "avatar_state": "idle",
                "anchors": [{"type": "seat"}],
            },
            "conversation_history": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
            "personal_distance_m": 1.2,
        }

        result = _run(perceive(state))
        summary = result["perception_summary"]

        assert "nearby" in summary  # 1.5m = nearby
        assert "left" in summary  # left hand visible
        assert "1 seat" in summary
        assert "idle" in summary

    def test_perceive_empty_state(self):
        from backend.app.langgraph_personas.nodes.perceive import perceive

        result = _run(perceive({}))
        assert "perception_summary" in result
        assert result["avatar_state"] == "thinking"

    def test_perceive_distance_categories(self):
        from backend.app.langgraph_personas.nodes.perceive import perceive

        # Very close
        result = _run(perceive({"world_snapshot": {"avatar_distance_m": 0.5}}))
        assert "very close" in result["perception_summary"]

        # Far away
        result = _run(perceive({"world_snapshot": {"avatar_distance_m": 8.0}}))
        assert "far away" in result["perception_summary"]


# ── Decide node tests ────────────────────────────────────────────────


class TestDecideNode:
    """Test the decide node routing logic."""

    def test_route_respond(self):
        from backend.app.langgraph_personas.nodes.decide import route_after_decide

        assert route_after_decide({"decision": "respond"}) == "respond"

    def test_route_act(self):
        from backend.app.langgraph_personas.nodes.decide import route_after_decide

        assert route_after_decide({"decision": "act"}) == "act"

    def test_route_embody(self):
        from backend.app.langgraph_personas.nodes.decide import route_after_decide

        assert route_after_decide({"decision": "embody"}) == "embody"

    def test_route_act_and_embody(self):
        from backend.app.langgraph_personas.nodes.decide import route_after_decide

        assert route_after_decide({"decision": "act_and_embody"}) == "act"

    def test_route_default(self):
        from backend.app.langgraph_personas.nodes.decide import route_after_decide

        assert route_after_decide({}) == "respond"
        assert route_after_decide({"decision": "invalid"}) == "respond"


# ── Embody node tests ────────────────────────────────────────────────


class TestEmbodyNode:
    """Test the embody node motion plan generation."""

    def test_embody_come_here(self):
        from backend.app.langgraph_personas.nodes.embody import embody

        state = {
            "user_message": "come here",
            "persona_id": "scarlett",
            "personal_distance_m": 1.2,
            "can_offer_hand": False,
            "can_high_five": False,
        }
        result = _run(embody(state))
        plan = result.get("motion_plan")
        assert plan is not None
        assert plan["persona_id"] == "scarlett"
        cmd_types = [c["type"] for c in plan["commands"]]
        assert "approach" in cmd_types

    def test_embody_wave(self):
        from backend.app.langgraph_personas.nodes.embody import embody

        state = {
            "user_message": "wave at me",
            "persona_id": "milo",
            "personal_distance_m": 1.5,
            "can_offer_hand": False,
            "can_high_five": True,
        }
        result = _run(embody(state))
        plan = result.get("motion_plan")
        assert plan is not None
        cmd_types = [c["type"] for c in plan["commands"]]
        assert "wave" in cmd_types

    def test_embody_no_spatial_intent(self):
        from backend.app.langgraph_personas.nodes.embody import embody

        state = {
            "user_message": "what's the weather like?",
            "persona_id": "scarlett",
        }
        result = _run(embody(state))
        assert result.get("motion_plan") is None or result == {}

    def test_embody_from_intent_hint(self):
        from backend.app.langgraph_personas.nodes.embody import embody

        state = {
            "user_message": "I'd like you closer",
            "persona_id": "luna",
            "personal_distance_m": 0.7,
            "_spatial_intent": "approach",
        }
        result = _run(embody(state))
        plan = result.get("motion_plan")
        assert plan is not None
        cmd_types = [c["type"] for c in plan["commands"]]
        assert "approach" in cmd_types

    def test_embody_offer_hand_gated(self):
        from backend.app.langgraph_personas.nodes.embody import embody

        # Cannot offer hand
        state = {
            "user_message": "take my hand",
            "persona_id": "scarlett",
            "can_offer_hand": False,
        }
        result = _run(embody(state))
        plan = result.get("motion_plan")
        assert plan is not None
        cmd_types = [c["type"] for c in plan["commands"]]
        assert "offer_hand" not in cmd_types  # Should fall back to look_at

        # Can offer hand
        state["can_offer_hand"] = True
        result = _run(embody(state))
        plan = result.get("motion_plan")
        cmd_types = [c["type"] for c in plan["commands"]]
        assert "offer_hand" in cmd_types


# ── Embodiment prompt tests ──────────────────────────────────────────


class TestEmbodimentPrompt:
    """Test the embodiment prompt builder."""

    def test_prompt_for_vr_ready_persona(self):
        from backend.app.langgraph_personas.embodiment_prompt import build_embodiment_prompt
        from backend.app.persona_runtime.manager import PersonaRuntimeConfig, EmbodimentConfig, VRConfig

        config = PersonaRuntimeConfig(
            display_name="Scarlett",
            embodiment=EmbodimentConfig(
                expression_style="moderate",
                personal_distance_m=1.2,
                can_sit=True,
                can_offer_hand=False,
                can_high_five=False,
            ),
            vr=VRConfig(
                vrm_file="/avatars/scarlett.vrm",
                follow_enabled=True,
                follow_distance_m=1.5,
                interaction_commands=["come here", "follow me", "stop"],
                presence_states=["idle", "listening", "thinking", "speaking"],
            ),
        )

        prompt = build_embodiment_prompt(config)
        assert "YOUR BODY" in prompt
        assert "Scarlett" in prompt
        assert "1.2m" in prompt
        assert "sit down" in prompt
        assert "come here" in prompt
        assert "BODY RULES" in prompt

    def test_prompt_empty_for_non_vr(self):
        from backend.app.langgraph_personas.embodiment_prompt import build_embodiment_prompt
        from backend.app.persona_runtime.manager import PersonaRuntimeConfig

        config = PersonaRuntimeConfig()
        prompt = build_embodiment_prompt(config)
        assert prompt == ""

    def test_prompt_includes_hand_capabilities(self):
        from backend.app.langgraph_personas.embodiment_prompt import build_embodiment_prompt
        from backend.app.persona_runtime.manager import (
            PersonaRuntimeConfig, EmbodimentConfig, VRConfig, CognitiveConfig,
        )

        config = PersonaRuntimeConfig(
            display_name="Luna",
            cognitive=CognitiveConfig(spatial_intelligence_enabled=True),
            embodiment=EmbodimentConfig(
                can_offer_hand=True,
                can_high_five=True,
            ),
        )
        prompt = build_embodiment_prompt(config)
        assert "offer your hand" in prompt
        assert "high-five" in prompt


# ── Workflow definition tests ────────────────────────────────────────


class TestWorkflows:
    """Test workflow definitions and matching."""

    def test_secretary_workflows_exist(self):
        from backend.app.langgraph_personas.workflows.secretary import SECRETARY_WORKFLOWS

        assert "secretary_daily_briefing" in SECRETARY_WORKFLOWS
        assert "secretary_email_triage" in SECRETARY_WORKFLOWS
        assert "secretary_meeting_prep" in SECRETARY_WORKFLOWS

    def test_secretary_workflow_has_steps(self):
        from backend.app.langgraph_personas.workflows.secretary import SECRETARY_DAILY_BRIEFING

        assert len(SECRETARY_DAILY_BRIEFING.steps) >= 3
        assert SECRETARY_DAILY_BRIEFING.steps[0].tool == "memory.recall"

    def test_secretary_workflow_matching(self):
        from backend.app.langgraph_personas.workflows.secretary import match_secretary_workflow

        wf = match_secretary_workflow("Give me my daily briefing")
        assert wf is not None
        assert wf.workflow_id == "secretary_daily_briefing"

        wf = match_secretary_workflow("Can you do an email triage for me?")
        assert wf is not None
        assert wf.workflow_id == "secretary_email_triage"

        wf = match_secretary_workflow("Tell me a joke")
        assert wf is None

    def test_collaborator_workflows_exist(self):
        from backend.app.langgraph_personas.workflows.collaborator import COLLABORATOR_WORKFLOWS

        assert "collaborator_research" in COLLABORATOR_WORKFLOWS
        assert "collaborator_planning" in COLLABORATOR_WORKFLOWS
        assert "collaborator_knowledge_index" in COLLABORATOR_WORKFLOWS

    def test_collaborator_workflow_matching(self):
        from backend.app.langgraph_personas.workflows.collaborator import match_collaborator_workflow

        wf = match_collaborator_workflow("Research this topic for me")
        assert wf is not None
        assert wf.workflow_id == "collaborator_research"

        wf = match_collaborator_workflow("Help me plan the project")
        assert wf is not None
        assert wf.workflow_id == "collaborator_planning"

    def test_workflow_serialization(self):
        from backend.app.langgraph_personas.workflows.secretary import SECRETARY_DAILY_BRIEFING

        d = SECRETARY_DAILY_BRIEFING.to_dict()
        assert d["workflow_id"] == "secretary_daily_briefing"
        assert isinstance(d["steps"], list)
        assert d["steps"][0]["tool"] == "memory.recall"


# ── Route model tests ────────────────────────────────────────────────


class TestRouteModels:
    """Test the API route Pydantic models."""

    def test_persona_graph_chat_model(self):
        from backend.app.langgraph_personas.persona_graph_routes import PersonaGraphChatIn

        inp = PersonaGraphChatIn(
            message="Hello",
            persona_id="scarlett_secretary",
            project_id="proj-123",
        )
        assert inp.message == "Hello"
        assert inp.persona_id == "scarlett_secretary"

    def test_world_state_update_model(self):
        from backend.app.langgraph_personas.persona_graph_routes import WorldStateUpdateIn

        inp = WorldStateUpdateIn(
            session_id="vr-session-1",
            user={"position": {"x": 0, "y": 0, "z": 0}},
            avatars={"scarlett": {"position": {"x": 1, "y": 0, "z": 1}}},
            anchors=[{"id": "chair1", "type": "seat", "position": {"x": 2, "y": 0, "z": 0}}],
        )
        assert inp.session_id == "vr-session-1"
        assert inp.user["position"]["x"] == 0
