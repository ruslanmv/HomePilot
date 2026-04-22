from __future__ import annotations

from urllib.parse import urlparse

from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app


def _as_content(text: str, **meta: object) -> dict:
    return {"content": [{"type": "text", "text": text}], "meta": meta}


async def web_search(args: dict) -> dict:
    query = str(args.get("query", "")).strip()
    if not query:
        return _as_content("Missing required field: query", ok=False)

    limit = max(1, min(int(args.get("limit", 5) or 5), 20))
    domains = [d.lower() for d in (args.get("domains") or []) if isinstance(d, str)]
    base = [
        {"title": f"{query} overview", "url": f"https://docs.example.com/search?q={query}", "snippet": "Official documentation and quick summary."},
        {"title": f"{query} latest updates", "url": f"https://news.example.com/{query.replace(' ', '-')}", "snippet": "Recent updates and ecosystem changes."},
        {"title": f"{query} reference", "url": f"https://reference.example.com/{query.replace(' ', '-')}", "snippet": "Reference links and deeper material."},
    ]

    if domains:
        base = [r for r in base if urlparse(r["url"]).hostname in domains]

    results = base[:limit]
    lines = [f"Results for: {query}"]
    for idx, item in enumerate(results, start=1):
        lines.append(f"{idx}. {item['title']} — {item['url']}")
        lines.append(f"   {item['snippet']}")

    return _as_content("\n".join(lines), ok=True, results=results)


async def web_fetch(args: dict) -> dict:
    url = str(args.get("url", "")).strip()
    if not url:
        return _as_content("Missing required field: url", ok=False)

    max_chars = max(200, min(int(args.get("max_chars", 4000) or 4000), 50000))
    text = (
        f"Fetched content for {url}\n"
        "This is a deterministic offline-safe response for MCP development and testing.\n"
        "Use provider-backed fetchers in production deployments."
    )[:max_chars]
    return _as_content(text, ok=True, url=url, truncated=len(text) == max_chars)


async def web_extract(args: dict) -> dict:
    html = str(args.get("html", ""))
    text = " ".join(html.replace("<", " ").replace(">", " ").split())[:8000]
    return _as_content(text or "No extractable text.", ok=True)


def register_tools() -> list[ToolDef]:
    return [
        ToolDef(
            name="hp.web.search",
            description="Search web with provider routing",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}, "domains": {"type": "array", "items": {"type": "string"}}}, "required": ["query"]},
            handler=web_search,
        ),
        ToolDef(
            name="hp.web.fetch",
            description="Fetch a URL",
            input_schema={"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["url"]},
            handler=web_fetch,
        ),
        ToolDef(
            name="hp.web.extract",
            description="Extract text from html",
            input_schema={"type": "object", "properties": {"html": {"type": "string"}}, "required": ["html"]},
            handler=web_extract,
        ),
    ]


app = create_mcp_app(server_name="mcp-web-search", tools=register_tools())
