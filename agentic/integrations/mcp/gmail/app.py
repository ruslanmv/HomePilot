"""MCP server: gmail — read, search, draft, and send email via Gmail API.

Tools:
  gmail.search(query, limit=20)
  gmail.read(message_id)
  gmail.draft(to, subject, body, thread_id?)  [write-gated]
  gmail.send(draft_id)                        [write-gated]
"""

from __future__ import annotations

import os
from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

WRITE_ENABLED = os.getenv("WRITE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
CONFIRM_SEND = os.getenv("CONFIRM_SEND", "true").lower() == "true"


def _text(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


def _write_gate(action: str) -> Json | None:
    if not WRITE_ENABLED:
        msg = f"Write disabled: '{action}' requires WRITE_ENABLED=true."
        if DRY_RUN:
            msg += " (DRY_RUN mode — no changes made)"
        return _text(msg)
    return None


async def gmail_search(args: Json) -> Json:
    query = str(args.get("query", "")).strip()
    limit = max(1, min(int(args.get("limit", 20) or 20), 100))
    if not query:
        return _text("Please provide a non-empty 'query'.")
    # Placeholder
    return _text(f"Gmail search for '{query}' (limit={limit}) — placeholder, OAuth not yet configured.")


async def gmail_read(args: Json) -> Json:
    message_id = str(args.get("message_id", "")).strip()
    if not message_id:
        return _text("Please provide a 'message_id'.")
    return _text(f"Gmail read message '{message_id}' — placeholder, OAuth not yet configured.")


async def gmail_draft(args: Json) -> Json:
    gate = _write_gate("gmail.draft")
    if gate:
        return gate
    to = str(args.get("to", "")).strip()
    subject = str(args.get("subject", "")).strip()
    body = str(args.get("body", "")).strip()
    if not to or not subject:
        return _text("Please provide 'to' and 'subject'.")
    return _text(f"Draft created: to={to}, subject='{subject}', body={len(body)} chars — placeholder.")


async def gmail_send(args: Json) -> Json:
    gate = _write_gate("gmail.send")
    if gate:
        return gate
    draft_id = str(args.get("draft_id", "")).strip()
    if not draft_id:
        return _text("Please provide a 'draft_id'.")
    if CONFIRM_SEND:
        return _text(f"Send requires confirmation (CONFIRM_SEND=true). Draft '{draft_id}' ready to send.")
    return _text(f"Sent draft '{draft_id}' — placeholder.")


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.gmail.search",
        description="Search Gmail messages.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Gmail search query"},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
        handler=gmail_search,
    ),
    ToolDef(
        name="hp.gmail.read",
        description="Read a Gmail message by ID.",
        input_schema={
            "type": "object",
            "properties": {
                "message_id": {"type": "string"},
            },
            "required": ["message_id"],
        },
        handler=gmail_read,
    ),
    ToolDef(
        name="hp.gmail.draft",
        description="Create a Gmail draft. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "thread_id": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
        handler=gmail_draft,
    ),
    ToolDef(
        name="hp.gmail.send",
        description="Send a Gmail draft. Write-gated; may require CONFIRM_SEND.",
        input_schema={
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
            },
            "required": ["draft_id"],
        },
        handler=gmail_send,
    ),
]

app = create_mcp_app(server_name="homepilot-gmail", tools=TOOLS)
