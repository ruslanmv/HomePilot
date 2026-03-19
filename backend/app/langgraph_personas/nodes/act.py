"""
Act Node — executes tool calls using the existing agent_chat tool dispatch.

AAA pattern: "Action System" — wraps the existing HomePilot tool registry
so that LangGraph can invoke tools without duplicating dispatch logic.
All 11+ existing tools are available without modification.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..state import PersonaAgentState, ToolResult

logger = logging.getLogger(__name__)


async def act(state: PersonaAgentState) -> Dict[str, Any]:
    """
    Execute the tool requested by the think node.

    Delegates to the existing agent_chat._dispatch_tool() infrastructure.
    Returns the tool result so subsequent nodes can use it.
    """
    tool_name = state.get("_pending_tool", "")
    tool_args = state.get("_pending_tool_args", {})
    tool_calls_used = state.get("tool_calls_used", 0)
    max_tool_calls = state.get("max_tool_calls", 4)

    if not tool_name:
        logger.debug("[act] no tool requested, skipping")
        return {}

    if tool_calls_used >= max_tool_calls:
        logger.warning("[act] max tool calls (%d) reached, skipping", max_tool_calls)
        return {
            "tool_results": state.get("tool_results", []) + [
                ToolResult(
                    tool=tool_name,
                    args=tool_args,
                    output=f"[Skipped: max tool calls ({max_tool_calls}) reached]",
                    media=None,
                )
            ],
        }

    logger.debug("[act] dispatching tool=%s args=%s", tool_name, tool_args)

    try:
        from ...agent_chat import _dispatch_tool

        output_text, meta, media = await _dispatch_tool(
            tool=tool_name,
            args=tool_args,
            conversation_id=state.get("conversation_id", ""),
            project_id=state.get("project_id", ""),
            messages=[],  # Tools don't need full history
            vision_provider="",
            vision_base_url="",
            vision_model="",
            nsfw_mode=False,
            user_id=None,
            image_url=None,
        )

        result = ToolResult(
            tool=tool_name,
            args=tool_args,
            output=output_text or "",
            media=media,
        )

    except Exception as e:
        logger.error("[act] tool dispatch failed: %s", e)
        result = ToolResult(
            tool=tool_name,
            args=tool_args,
            output=f"[Error: {e}]",
            media=None,
        )

    existing_results = list(state.get("tool_results", []))
    existing_results.append(result)

    updates: Dict[str, Any] = {
        "tool_results": existing_results,
        "tool_calls_used": tool_calls_used + 1,
    }

    # If media was returned (e.g. image.generate), stash it
    if result.get("media"):
        updates["response_media"] = result["media"]

    return updates
