"""MCP server: slack — read channels, search messages, optionally post.

Tools:
  slack.channels.list()
  slack.channel.history(channel_id, since?, until?, limit=100)
  slack.messages.search(query, limit=20)
  slack.message.post(channel_id, text)  [write-gated]
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

WRITE_ENABLED = os.getenv("WRITE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"


def _text(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


def _write_gate(action: str) -> Json | None:
    if not WRITE_ENABLED:
        msg = f"Write disabled: '{action}' requires WRITE_ENABLED=true."
        if DRY_RUN:
            msg += " (DRY_RUN mode — no changes made)"
        return _text(msg)
    return None


async def slack_channels_list(args: Json) -> Json:
    return _text("Slack channels list — placeholder, token not yet configured.")


async def slack_channel_history(args: Json) -> Json:
    channel_id = str(args.get("channel_id", "")).strip()
    limit = max(1, min(int(args.get("limit", 100) or 100), 1000))
    if not channel_id:
        return _text("Please provide a 'channel_id'.")
    return _text(f"Slack channel history for '{channel_id}' (limit={limit}) — placeholder.")


async def slack_messages_search(args: Json) -> Json:
    query = str(args.get("query", "")).strip()
    limit = max(1, min(int(args.get("limit", 20) or 20), 100))
    if not query:
        return _text("Please provide a non-empty 'query'.")
    return _text(f"Slack search for '{query}' (limit={limit}) — placeholder.")


async def slack_message_post(args: Json) -> Json:
    gate = _write_gate("slack.message.post")
    if gate:
        return gate
    channel_id = str(args.get("channel_id", "")).strip()
    text = str(args.get("text", "")).strip()
    if not channel_id or not text:
        return _text("Please provide 'channel_id' and 'text'.")
    return _text(f"Posted to Slack channel '{channel_id}': '{text[:80]}...' — placeholder.")


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.slack.channels.list",
        description="List Slack channels.",
        input_schema={
            "type": "object",
            "properties": {},
        },
        handler=slack_channels_list,
    ),
    ToolDef(
        name="hp.slack.channel.history",
        description="Get message history for a Slack channel.",
        input_schema={
            "type": "object",
            "properties": {
                "channel_id": {"type": "string"},
                "since": {"type": "string", "description": "Start time (ISO 8601)"},
                "until": {"type": "string", "description": "End time (ISO 8601)"},
                "limit": {"type": "integer", "default": 100, "minimum": 1, "maximum": 1000},
            },
            "required": ["channel_id"],
        },
        handler=slack_channel_history,
    ),
    ToolDef(
        name="hp.slack.messages.search",
        description="Search Slack messages.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
        handler=slack_messages_search,
    ),
    ToolDef(
        name="hp.slack.message.post",
        description="Post a message to a Slack channel. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "channel_id": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["channel_id", "text"],
        },
        handler=slack_message_post,
    ),
]

app = create_mcp_app(server_name="homepilot-slack", tools=TOOLS)
