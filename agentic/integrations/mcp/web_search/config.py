"""Web Search MCP — configuration via environment variables.

Defaults to SearXNG (home mode, no API key needed).
Set WEB_SEARCH_PROVIDER=tavily + TAVILY_API_KEY for enterprise mode.
"""

from __future__ import annotations

import os


def _env(name: str, default: str) -> str:
    return (os.environ.get(name) or default).strip()


# Provider: "searxng" (default, home) or "tavily" (enterprise)
PROVIDER: str = _env("WEB_SEARCH_PROVIDER", "searxng")

# SearXNG (home mode)
SEARXNG_BASE_URL: str = _env("SEARXNG_BASE_URL", "http://localhost:8080")

# Tavily (enterprise mode)
TAVILY_API_KEY: str = _env("TAVILY_API_KEY", "")

# Common
HTTP_TIMEOUT: float = float(_env("WEB_SEARCH_TIMEOUT", "12.0"))
USER_AGENT: str = "HomePilotWebSearchMCP/1.0"
