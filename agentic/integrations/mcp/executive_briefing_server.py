from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app


def _text(content: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": content}]}


async def hp_brief_daily(audience: str = "team", project_ids: Optional[List[str]] = None, max_items: int = 7) -> Dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    return _text(
        "Daily Brief (" + audience + ")\n"
        f"Generated at {ts}\n\n"
        "• Priority: Review top tasks\n"
        "• Risk: Check blockers\n"
        "• Next: Confirm tomorrow's goals"
    )


async def hp_brief_weekly(audience: str = "team", project_ids: Optional[List[str]] = None, max_items: int = 10) -> Dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()
    return _text(
        "Weekly Brief (" + audience + ")\n"
        f"Generated at {ts}\n\n"
        "1) Wins\n2) Risks\n3) Focus for next week"
    )


async def hp_brief_what_changed_since(since: str, project_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    return _text(
        f"Change Summary since {since}\n\n"
        "• Example: New files uploaded\n"
        "• Example: Project description updated\n"
        "• Example: Agent configuration changed"
    )


async def hp_brief_digest(items: List[str], audience: str = "team") -> Dict[str, Any]:
    bullets = "\n".join([f"• {i}" for i in items][:20])
    return _text(f"Digest ({audience})\n\n{bullets}")


tools = [
    ToolDef(
        name="hp.brief.daily",
        description="Daily digest for a team (read-only).",
        input_schema={
            "type": "object",
            "properties": {
                "audience": {"type": "string", "enum": ["executive", "team", "personal"], "default": "team"},
                "project_ids": {"type": "array", "items": {"type": "string"}},
                "max_items": {"type": "integer", "default": 7, "minimum": 3, "maximum": 15},
            },
        },
        handler=lambda args: hp_brief_daily(**args),
    ),
    ToolDef(
        name="hp.brief.weekly",
        description="Weekly digest (read-only).",
        input_schema={
            "type": "object",
            "properties": {
                "audience": {"type": "string", "enum": ["executive", "team", "personal"], "default": "team"},
                "project_ids": {"type": "array", "items": {"type": "string"}},
                "max_items": {"type": "integer", "default": 10, "minimum": 3, "maximum": 20},
            },
        },
        handler=lambda args: hp_brief_weekly(**args),
    ),
    ToolDef(
        name="hp.brief.what_changed_since",
        description="What changed since a timestamp (read-only).",
        input_schema={
            "type": "object",
            "properties": {
                "since": {"type": "string", "description": "ISO timestamp"},
                "project_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["since"],
        },
        handler=lambda args: hp_brief_what_changed_since(**args),
    ),
    ToolDef(
        name="hp.brief.digest",
        description="Create a digest from items (read-only).",
        input_schema={
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": {"type": "string"}},
                "audience": {"type": "string", "enum": ["executive", "team"], "default": "team"},
            },
            "required": ["items"],
        },
        handler=lambda args: hp_brief_digest(**args),
    ),
]

app = create_mcp_app(
    server_name="homepilot-executive-briefing",
    tools=tools,
)
