"""
Decide Node — routes the pipeline based on the think node's decision.

AAA pattern: "Behavior Tree Selector" — a pure routing node that reads
the decision and returns control-flow hints for LangGraph conditional edges.
This node does NO LLM calls — it's a deterministic router.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..state import PersonaAgentState

logger = logging.getLogger(__name__)


def decide(state: PersonaAgentState) -> Dict[str, Any]:
    """
    Read the decision from the think node and return it unchanged.

    The actual routing happens in the graph's conditional edges
    (see graph_builder.py). This node exists so the decision is
    a named, inspectable step in the graph.
    """
    decision = state.get("decision", "respond")
    logger.debug("[decide] routing to: %s", decision)
    return {"decision": decision}


def route_after_decide(state: PersonaAgentState) -> str:
    """
    Conditional edge function: returns the next node name.

    Used by graph_builder as:
        graph.add_conditional_edges("decide", route_after_decide, {...})
    """
    decision = state.get("decision", "respond")

    if decision == "act":
        return "act"
    elif decision == "embody":
        return "embody"
    elif decision == "act_and_embody":
        return "act"  # act first, then embody
    else:
        return "respond"
