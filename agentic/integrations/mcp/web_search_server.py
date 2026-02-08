"""HomePilot Web Search MCP server.

Provides two tools:
  - hp.web.search  — search the web (SearXNG home / Tavily enterprise)
  - hp.web.fetch   — fetch raw content of a URL (best-effort)

Provider is configured via WEB_SEARCH_PROVIDER env var (default: searxng).
"""

from __future__ import annotations

from typing import Any, Dict, List

import httpx

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app
from agentic.integrations.mcp.web_search.config import HTTP_TIMEOUT, PROVIDER, USER_AGENT
from agentic.integrations.mcp.web_search.providers import get_provider


def _text(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


async def tool_web_search(args: Json) -> Json:
    """Search the web using the configured provider."""
    query = str(args.get("query", "")).strip()
    if not query:
        return _text("Please provide a non-empty 'query'.")

    limit = int(args.get("limit", 5) or 5)
    limit = max(1, min(limit, 20))
    recency_days = int(args.get("recency_days", 30) or 30)
    domains = args.get("domains") or None

    provider = get_provider()
    try:
        results = await provider.search(
            query=query,
            limit=limit,
            recency_days=recency_days,
            domains=domains,
        )
    except Exception as e:
        return _text(f"Web search failed ({PROVIDER}): {e}")

    if not results:
        return _text(f"No results found for: {query}")

    lines = [f"### Web Search Results (provider: {PROVIDER})", ""]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r.title}**")
        lines.append(f"   - URL: {r.url}")
        if r.snippet:
            lines.append(f"   - {r.snippet}")
        lines.append("")

    return _text("\n".join(lines).strip())


async def tool_web_fetch(args: Json) -> Json:
    """Fetch the text content of a URL (best-effort)."""
    url = str(args.get("url", "")).strip()
    if not url:
        return _text("Please provide a non-empty 'url'.")

    max_chars = int(args.get("max_chars", 8000) or 8000)
    max_chars = max(500, min(max_chars, 50000))

    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            text = resp.text or ""
    except Exception as e:
        return _text(f"Fetch failed: {e}")

    text = text.replace("\r", "")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...(truncated)"

    return _text(text)


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.web.search",
        description="Search the web. Home mode: SearXNG (no API key). Enterprise: Tavily.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                "recency_days": {"type": "integer", "default": 30, "minimum": 1, "maximum": 365,
                                 "description": "Recency filter in days (best-effort)"},
                "domains": {"type": "array", "items": {"type": "string"},
                            "description": "Optional domain allow-list"},
            },
            "required": ["query"],
        },
        handler=tool_web_search,
    ),
    ToolDef(
        name="hp.web.fetch",
        description="Fetch raw text content of a URL (best-effort, for summarization after search).",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_chars": {"type": "integer", "default": 8000, "minimum": 500, "maximum": 50000},
            },
            "required": ["url"],
        },
        handler=tool_web_fetch,
    ),
]

app = create_mcp_app(server_name="homepilot-web-search", tools=TOOLS)
