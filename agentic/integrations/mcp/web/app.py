"""MCP server: web — fetch and extract clean text from web pages.

Tools:
  web.fetch(url)
  web.extract_main(url_or_html)
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

from agentic.integrations.mcp._common.server import Json, ToolDef, create_mcp_app

WRITE_ENABLED = os.getenv("WRITE_ENABLED", "false").lower() == "true"
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
MAX_DOWNLOAD_BYTES = int(os.getenv("MAX_DOWNLOAD_BYTES", "5242880"))
DENY_INTERNAL_IPS = os.getenv("DENY_INTERNAL_IPS", "true").lower() == "true"


def _text(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


def _is_internal_url(url: str) -> bool:
    """Basic SSRF protection: block requests to localhost / private IPs."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname or ""
    blocked = ["localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254."]
    return any(host.startswith(b) or host == b for b in blocked)


async def web_fetch(args: Json) -> Json:
    url = str(args.get("url", "")).strip()
    if not url:
        return _text("Please provide a non-empty 'url'.")
    if DENY_INTERNAL_IPS and _is_internal_url(url):
        return _text("Blocked: internal/private URL (SSRF protection).")
    # Placeholder — production would use httpx
    return _text(f"Fetched '{url}' (placeholder — {MAX_DOWNLOAD_BYTES} byte limit, {REQUEST_TIMEOUT}s timeout).")


async def web_extract_main(args: Json) -> Json:
    url_or_html = str(args.get("url_or_html", "")).strip()
    if not url_or_html:
        return _text("Please provide 'url_or_html'.")
    if url_or_html.startswith("http"):
        if DENY_INTERNAL_IPS and _is_internal_url(url_or_html):
            return _text("Blocked: internal/private URL (SSRF protection).")
        return _text(f"Extracted main content from '{url_or_html}' (placeholder).")
    # Treat as raw HTML — strip tags
    plain = re.sub(r"<[^>]+>", "", url_or_html)[:5000]
    return _text(f"Extracted text ({len(plain)} chars): {plain[:500]}...")


TOOLS: List[ToolDef] = [
    ToolDef(
        name="hp.web.fetch",
        description="Fetch raw HTML and headers from a URL.",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
            },
            "required": ["url"],
        },
        handler=web_fetch,
    ),
    ToolDef(
        name="hp.web.extract_main",
        description="Extract main article text from a URL or raw HTML.",
        input_schema={
            "type": "object",
            "properties": {
                "url_or_html": {"type": "string", "description": "URL or raw HTML string"},
            },
            "required": ["url_or_html"],
        },
        handler=web_extract_main,
    ),
]

app = create_mcp_app(server_name="homepilot-web", tools=TOOLS)
