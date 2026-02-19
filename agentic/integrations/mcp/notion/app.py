"""MCP server: notion — search, read, and update Notion pages.

Tools:
  notion.search(query, limit=20)
  notion.page.read(page_id)
  notion.page.append(page_id, content)  [write-gated]
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


async def notion_search(args: Json) -> Json:
    query = str(args.get("query", "")).strip()
    limit = max(1, min(int(args.get("limit", 20) or 20), 100))
    if not query:
        return _text("Please provide a non-empty 'query'.")
    return _text(f"Notion search for '{query}' (limit={limit}) — placeholder, token not yet configured.")


async def notion_page_read(args: Json) -> Json:
    page_id = str(args.get("page_id", "")).strip()
    if not page_id:
        return _text("Please provide a 'page_id'.")
    return _text(f"Notion page '{page_id}' — placeholder, token not yet configured.")


async def notion_page_append(args: Json) -> Json:
    gate = _write_gate("notion.page.append")
    if gate:
        return gate
    page_id = str(args.get("page_id", "")).strip()
    content = str(args.get("content", "")).strip()
    if not page_id or not content:
        return _text("Please provide 'page_id' and 'content'.")
    return _text(f"Appended to Notion page '{page_id}': {len(content)} chars — placeholder.")


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.notion.search",
        description="Search Notion pages and databases.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 20, "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
        },
        handler=notion_search,
    ),
    ToolDef(
        name="hp.notion.page.read",
        description="Read a Notion page by ID.",
        input_schema={
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
            },
            "required": ["page_id"],
        },
        handler=notion_page_read,
    ),
    ToolDef(
        name="hp.notion.page.append",
        description="Append content to a Notion page. Write-gated.",
        input_schema={
            "type": "object",
            "properties": {
                "page_id": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["page_id", "content"],
        },
        handler=notion_page_append,
    ),
]

app = create_mcp_app(server_name="homepilot-notion", tools=TOOLS)
