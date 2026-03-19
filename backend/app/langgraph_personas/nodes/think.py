"""
Think Node — internal chain-of-thought reasoning (invisible to user).

AAA pattern: "AI Decision Brain" — the agent's internal deliberation
loop. For orchestrated personas this is multi-step planning; for guided
personas it's lightweight reactive reasoning.

The think node calls the LLM with a special "internal reasoning" system
prompt that asks for a structured decision, NOT a user-facing response.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

from ..state import PersonaAgentState

logger = logging.getLogger(__name__)

# ── Internal reasoning prompt (never shown to user) ──────────────────

_THINK_SYSTEM = """\
You are the internal reasoning engine for a persona named "{name}".
Your job is to THINK about what to do next. The user will NOT see this output.

Given:
- The user's message
- Your perception of the environment
- Your capabilities and personality

Output a JSON object with exactly these fields:
{{
  "reasoning": "Your step-by-step thinking (1-3 sentences)",
  "decision": "respond | act | embody | act_and_embody",
  "emotion": "neutral | happy | thoughtful | concerned | excited | playful | warm",
  "tool_needed": null or "{tool_name}",
  "tool_args": {{}},
  "spatial_intent": null or "come_here | follow | sit | stand | wave | approach | retreat | look_at"
}}

Decision guide:
- "respond": just reply with text (most common)
- "act": need to use a tool first (search, memory, vision, etc.)
- "embody": need to move/gesture in VR (spatial command detected)
- "act_and_embody": need both a tool AND a body motion

Available tools: {tools}
Spatial commands you can trigger: approach, retreat, follow, stop, sit, stand, wave, nod, point, look_at, offer_hand, high_five

Reasoning mode: {reasoning_mode}
{planning_hint}
"""

_ORCHESTRATED_HINT = """\
You are in ORCHESTRATED mode. Think carefully:
1. Break complex requests into steps
2. Consider if you need information before responding
3. Plan tool usage strategically
4. Consider spatial context when relevant"""

_GUIDED_HINT = """\
You are in GUIDED mode. Keep it simple:
1. Respond naturally and conversationally
2. Only use tools if clearly needed
3. React to spatial commands intuitively"""

_DIRECT_HINT = """\
You are in DIRECT mode. Be immediate:
1. Respond directly without deliberation
2. Skip tools unless explicitly asked"""


async def think(state: PersonaAgentState) -> Dict[str, Any]:
    """
    Run internal reasoning and produce a decision.

    This calls the LLM once with a thinking-specific prompt.
    The output is structured JSON that drives the rest of the pipeline.
    """
    from ..state import PersonaAgentState  # noqa: F811 — re-import for type hints

    reasoning_mode = state.get("reasoning_mode", "direct")
    name = state.get("display_name", "Persona")
    tools = ", ".join(state.get("allowed_tool_categories", [])) or "none"

    planning_hint = {
        "orchestrated": _ORCHESTRATED_HINT,
        "guided": _GUIDED_HINT,
        "direct": _DIRECT_HINT,
    }.get(reasoning_mode, _DIRECT_HINT)

    think_prompt = _THINK_SYSTEM.format(
        name=name,
        tools=tools,
        reasoning_mode=reasoning_mode,
        planning_hint=planning_hint,
    )

    # Build the thinking messages
    messages = [
        {"role": "system", "content": think_prompt},
    ]

    # Add perception context
    perception = state.get("perception_summary", "")
    if perception:
        messages.append({
            "role": "system",
            "content": f"[SPATIAL PERCEPTION] {perception}",
        })

    # Add the user message
    messages.append({
        "role": "user",
        "content": state.get("user_message", ""),
    })

    # Call LLM for internal reasoning
    try:
        from ...llm import chat as llm_chat

        raw = await llm_chat(
            messages=messages,
            provider=state.get("llm_provider", "openai_compat"),
            base_url=state.get("llm_base_url", ""),
            model=state.get("llm_model", ""),
            temperature=0.3,  # Lower temp for reasoning
            max_tokens=400,   # Keep reasoning compact
        )
    except Exception as e:
        logger.warning("[think] LLM call failed, falling back to direct response: %s", e)
        return {
            "thinking_trace": f"Reasoning failed: {e}",
            "decision": "respond",
            "avatar_emotion": "neutral",
        }

    # Parse structured JSON from response
    try:
        # Extract JSON from response (may be wrapped in markdown)
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
        else:
            parsed = {}
    except (json.JSONDecodeError, AttributeError):
        parsed = {}

    decision = parsed.get("decision", "respond")
    if decision not in ("respond", "act", "embody", "act_and_embody"):
        decision = "respond"

    emotion = parsed.get("emotion", "neutral")
    reasoning = parsed.get("reasoning", "")

    logger.debug("[think] decision=%s emotion=%s reasoning=%s", decision, emotion, reasoning)

    result: Dict[str, Any] = {
        "thinking_trace": reasoning,
        "decision": decision,
        "avatar_emotion": emotion,
    }

    # If a tool is needed, stash the request for the act node
    if decision in ("act", "act_and_embody") and parsed.get("tool_needed"):
        result["_pending_tool"] = parsed["tool_needed"]
        result["_pending_tool_args"] = parsed.get("tool_args", {})

    # If spatial intent detected, stash for embody node
    if decision in ("embody", "act_and_embody") and parsed.get("spatial_intent"):
        result["_spatial_intent"] = parsed["spatial_intent"]

    return result
