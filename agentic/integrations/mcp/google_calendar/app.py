"""MCP server: google-calendar — read events, plan meetings, optionally create events.

Tools:
  gcal.list_events(time_min, time_max)
  gcal.search(query, time_min?, time_max?)
  gcal.read_event(event_id)
  gcal.create_event(title, start, end, attendees?, location?)  [write-gated]
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


async def gcal_list_events(args: Json) -> Json:
    time_min = str(args.get("time_min", "")).strip()
    time_max = str(args.get("time_max", "")).strip()
    if not time_min or not time_max:
        return _text("Please provide 'time_min' and 'time_max' (ISO 8601).")
    return _text(f"List events from {time_min} to {time_max} — placeholder, OAuth not yet configured.")


async def gcal_search(args: Json) -> Json:
    query = str(args.get("query", "")).strip()
    if not query:
        return _text("Please provide a non-empty 'query'.")
    return _text(f"Calendar search for '{query}' — placeholder, OAuth not yet configured.")


async def gcal_read_event(args: Json) -> Json:
    event_id = str(args.get("event_id", "")).strip()
    if not event_id:
        return _text("Please provide an 'event_id'.")
    return _text(f"Read event '{event_id}' — placeholder, OAuth not yet configured.")


async def gcal_create_event(args: Json) -> Json:
    gate = _write_gate("gcal.create_event")
    if gate:
        return gate
    title = str(args.get("title", "")).strip()
    start = str(args.get("start", "")).strip()
    end = str(args.get("end", "")).strip()
    if not title or not start or not end:
        return _text("Please provide 'title', 'start', and 'end'.")
    attendees = args.get("attendees") or []
    location = str(args.get("location", "")).strip()
    return _text(f"Created event '{title}' from {start} to {end}, attendees={attendees}, location='{location}' — placeholder.")


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.gcal.list_events",
        description="List calendar events in a time range.",
        input_schema={
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "Start time (ISO 8601)"},
                "time_max": {"type": "string", "description": "End time (ISO 8601)"},
            },
            "required": ["time_min", "time_max"],
        },
        handler=gcal_list_events,
    ),
    ToolDef(
        name="hp.gcal.search",
        description="Search calendar events by query.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "time_min": {"type": "string"},
                "time_max": {"type": "string"},
            },
            "required": ["query"],
        },
        handler=gcal_search,
    ),
    ToolDef(
        name="hp.gcal.read_event",
        description="Read details of a calendar event by ID.",
        input_schema={
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
            },
            "required": ["event_id"],
        },
        handler=gcal_read_event,
    ),
    ToolDef(
        name="hp.gcal.create_event",
        description="Create a new calendar event. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "start": {"type": "string", "description": "Start time (ISO 8601)"},
                "end": {"type": "string", "description": "End time (ISO 8601)"},
                "attendees": {"type": "array", "items": {"type": "string"}},
                "location": {"type": "string"},
            },
            "required": ["title", "start", "end"],
        },
        handler=gcal_create_event,
    ),
]

app = create_mcp_app(server_name="homepilot-google-calendar", tools=TOOLS)
