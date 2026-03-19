"""
Respond Node — generates the final user-facing text response.

AAA pattern: "Dialog System" — takes all accumulated context (perception,
thinking trace, tool results, motion plan) and produces the final
natural-language response the user sees + hears.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..state import PersonaAgentState

logger = logging.getLogger(__name__)


async def respond(state: PersonaAgentState) -> Dict[str, Any]:
    """
    Generate the final user-facing response using the persona's system prompt.

    This is the ONLY node whose output the user sees. All previous nodes
    (perceive, think, act, embody) are internal.
    """
    system_prompt = state.get("system_prompt", "")
    user_message = state.get("user_message", "")
    history = list(state.get("conversation_history", []))

    # Build messages for the response LLM call
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Inject perception as invisible context
    perception = state.get("perception_summary", "")
    if perception:
        messages.append({
            "role": "system",
            "content": f"[CURRENT SPATIAL CONTEXT — do not mention this explicitly] {perception}",
        })

    # Inject tool results as context
    tool_results = state.get("tool_results", [])
    for tr in tool_results:
        tool_ctx = f"[Tool result from {tr.get('tool', 'unknown')}]: {tr.get('output', '')}"
        messages.append({"role": "system", "content": tool_ctx})

    # Inject motion plan awareness
    motion = state.get("motion_plan")
    if motion and motion.get("commands"):
        cmd_names = [c.get("type", "?") for c in motion["commands"]]
        messages.append({
            "role": "system",
            "content": (
                f"[You are currently performing these body actions: {', '.join(cmd_names)}. "
                f"Acknowledge your movement naturally in your response if relevant.]"
            ),
        })

    # Add conversation history
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        from ...llm import chat as llm_chat

        response_text = await llm_chat(
            messages=messages,
            provider=state.get("llm_provider", "openai_compat"),
            base_url=state.get("llm_base_url", ""),
            model=state.get("llm_model", ""),
            temperature=state.get("temperature", 0.7),
            max_tokens=state.get("max_tokens", 900),
        )
    except Exception as e:
        logger.error("[respond] LLM call failed: %s", e)
        response_text = "I'm having trouble thinking right now. Could you try again?"

    logger.debug("[respond] generated %d chars", len(response_text or ""))

    return {
        "response_text": response_text or "",
        "avatar_state": "speaking",
        "is_complete": True,
    }
