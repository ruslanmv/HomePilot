"""MCP server: microsoft-graph — Outlook mail & calendar via MS Graph API.

Tools (Mail):
  graph.mail.search(query, limit=20)
  graph.mail.read(message_id)
  graph.mail.draft(to, subject, body, thread_id?)  [write-gated]
  graph.mail.send(draft_id)                        [write-gated]

Tools (Calendar):
  graph.calendar.list_events(time_min, time_max)
  graph.calendar.read_event(event_id)
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


# ── Mail tools ──

async def graph_mail_search(args: Json) -> Json:
    query = str(args.get("query", "")).strip()
    limit = max(1, min(int(args.get("limit", 20) or 20), 100))
    if not query:
        return _text("Please provide a non-empty 'query'.")
    return _text(f"MS Graph mail search for '{query}' (limit={limit}) — placeholder, OAuth not yet configured.")


async def graph_mail_read(args: Json) -> Json:
    message_id = str(args.get("message_id", "")).strip()
    if not message_id:
        return _text("Please provide a 'message_id'.")
    return _text(f"MS Graph read mail '{message_id}' — placeholder, OAuth not yet configured.")


async def graph_mail_draft(args: Json) -> Json:
    gate = _write_gate("graph.mail.draft")
    if gate:
        return gate
    to = str(args.get("to", "")).strip()
    subject = str(args.get("subject", "")).strip()
    if not to or not subject:
        return _text("Please provide 'to' and 'subject'.")
    return _text(f"MS Graph draft: to={to}, subject='{subject}' — placeholder.")


async def graph_mail_send(args: Json) -> Json:
    gate = _write_gate("graph.mail.send")
    if gate:
        return gate
    draft_id = str(args.get("draft_id", "")).strip()
    if not draft_id:
        return _text("Please provide a 'draft_id'.")
    return _text(f"MS Graph send draft '{draft_id}' — placeholder.")


# ── Calendar tools ──

async def graph_calendar_list_events(args: Json) -> Json:
    time_min = str(args.get("time_min", "")).strip()
    time_max = str(args.get("time_max", "")).strip()
    if not time_min or not time_max:
        return _text("Please provide 'time_min' and 'time_max' (ISO 8601).")
    return _text(f"MS Graph calendar events from {time_min} to {time_max} — placeholder.")


async def graph_calendar_read_event(args: Json) -> Json:
    event_id = str(args.get("event_id", "")).strip()
    if not event_id:
        return _text("Please provide an 'event_id'.")
    return _text(f"MS Graph read event '{event_id}' — placeholder.")


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.graph.mail.search",
        description="Search Outlook mail via Microsoft Graph.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
        handler=graph_mail_search,
    ),
    ToolDef(
        name="hp.graph.mail.read",
        description="Read an Outlook message by ID.",
        input_schema={
            "type": "object",
            "properties": {
                "message_id": {"type": "string"},
            },
            "required": ["message_id"],
        },
        handler=graph_mail_read,
    ),
    ToolDef(
        name="hp.graph.mail.draft",
        description="Create an Outlook mail draft. Write-gated.",
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
        handler=graph_mail_draft,
    ),
    ToolDef(
        name="hp.graph.mail.send",
        description="Send an Outlook draft. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "draft_id": {"type": "string"},
            },
            "required": ["draft_id"],
        },
        handler=graph_mail_send,
    ),
    ToolDef(
        name="hp.graph.calendar.list_events",
        description="List Outlook calendar events in a time range.",
        input_schema={
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "Start time (ISO 8601)"},
                "time_max": {"type": "string", "description": "End time (ISO 8601)"},
            },
            "required": ["time_min", "time_max"],
        },
        handler=graph_calendar_list_events,
    ),
    ToolDef(
        name="hp.graph.calendar.read_event",
        description="Read an Outlook calendar event by ID.",
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
            },
            "required": ["event_id"],
        },
        handler=graph_calendar_read_event,
    ),
]

app = create_mcp_app(server_name="homepilot-microsoft-graph", tools=TOOLS)
