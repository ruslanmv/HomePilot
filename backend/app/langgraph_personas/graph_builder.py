"""
Graph Builder — constructs LangGraph StateGraphs for persona reasoning.

AAA pattern: "Behavior Tree Factory" — builds the right graph topology
based on the persona's reasoning_mode from their cognitive profile.

Three graph topologies:
  - orchestrated: perceive → think → decide → [act|embody|respond] → respond
  - guided:       perceive → think → decide → [embody|respond] → respond
  - direct:       perceive → respond (skip thinking entirely)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from langgraph.graph import END, StateGraph

from .state import PersonaAgentState
from .nodes.perceive import perceive
from .nodes.think import think
from .nodes.decide import decide, route_after_decide
from .nodes.act import act
from .nodes.embody import embody
from .nodes.respond import respond

logger = logging.getLogger(__name__)


def build_persona_graph(reasoning_mode: str = "direct") -> StateGraph:
    """
    Build a LangGraph StateGraph tailored to the persona's reasoning mode.

    Returns a compiled graph ready for invocation.
    """
    graph = StateGraph(PersonaAgentState)

    if reasoning_mode == "orchestrated":
        return _build_orchestrated_graph(graph)
    elif reasoning_mode == "guided":
        return _build_guided_graph(graph)
    else:
        return _build_direct_graph(graph)


def _build_orchestrated_graph(graph: StateGraph) -> StateGraph:
    """
    Full pipeline for orchestrated personas (Secretary, Collaborator).

    perceive → think → decide → {act, embody, respond}
                                    ↓       ↓
                                  embody  respond
                                    ↓
                                  respond
    """
    graph.add_node("perceive", perceive)
    graph.add_node("think", think)
    graph.add_node("decide", decide)
    graph.add_node("act", act)
    graph.add_node("embody", embody)
    graph.add_node("respond", respond)

    graph.set_entry_point("perceive")
    graph.add_edge("perceive", "think")
    graph.add_edge("think", "decide")

    graph.add_conditional_edges(
        "decide",
        route_after_decide,
        {
            "act": "act",
            "embody": "embody",
            "respond": "respond",
        },
    )

    # After act, check if we also need to embody
    graph.add_conditional_edges(
        "act",
        _route_after_act,
        {
            "embody": "embody",
            "respond": "respond",
        },
    )

    graph.add_edge("embody", "respond")
    graph.add_edge("respond", END)

    return graph.compile()


def _build_guided_graph(graph: StateGraph) -> StateGraph:
    """
    Lighter pipeline for guided personas (Friend, Girlfriend, Companion).

    perceive → think → decide → {embody, respond}
                                    ↓
                                  respond
    """
    graph.add_node("perceive", perceive)
    graph.add_node("think", think)
    graph.add_node("decide", decide)
    graph.add_node("embody", embody)
    graph.add_node("respond", respond)

    graph.set_entry_point("perceive")
    graph.add_edge("perceive", "think")
    graph.add_edge("think", "decide")

    graph.add_conditional_edges(
        "decide",
        _route_guided,
        {
            "embody": "embody",
            "respond": "respond",
        },
    )

    graph.add_edge("embody", "respond")
    graph.add_edge("respond", END)

    return graph.compile()


def _build_direct_graph(graph: StateGraph) -> StateGraph:
    """
    Minimal pipeline for direct personas — skip thinking.

    perceive → respond
    """
    graph.add_node("perceive", perceive)
    graph.add_node("respond", respond)

    graph.set_entry_point("perceive")
    graph.add_edge("perceive", "respond")
    graph.add_edge("respond", END)

    return graph.compile()


# ── Conditional edge helpers ─────────────────────────────────────────


def _route_after_act(state: PersonaAgentState) -> str:
    """After act node, check if we also need embodiment."""
    decision = state.get("decision", "respond")
    if decision == "act_and_embody":
        return "embody"
    return "respond"


def _route_guided(state: PersonaAgentState) -> str:
    """Guided personas can embody but cannot use tools via the graph."""
    decision = state.get("decision", "respond")
    if decision in ("embody", "act_and_embody"):
        return "embody"
    return "respond"


# ── High-level runner ────────────────────────────────────────────────


async def run_persona_graph(
    *,
    reasoning_mode: str,
    initial_state: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build and run the appropriate graph for a persona.

    Returns the final state dict containing response_text, motion_plan,
    avatar_emotion, etc.
    """
    graph = build_persona_graph(reasoning_mode)

    logger.info(
        "[graph] Running %s graph for persona=%s",
        reasoning_mode,
        initial_state.get("persona_id", "?"),
    )

    result = await graph.ainvoke(initial_state)
    return dict(result)
