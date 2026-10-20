from __future__ import annotations

import os

LOG_LEVEL = os.getenv('WEB_SEARCH_LOG_LEVEL', 'INFO')
SERVICE_NAME = os.getenv('WEB_SEARCH_SERVICE_NAME', 'mcp-web-search')
PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "searxng").strip().lower()
HTTP_TIMEOUT = float(os.getenv("WEB_SEARCH_HTTP_TIMEOUT", "15"))
USER_AGENT = os.getenv("WEB_SEARCH_USER_AGENT", "HomePilot-WebSearch/1.0")
# The providers read these two; they were never defined, so every search failed with an
# AttributeError before it reached SearXNG or Tavily.
# 127.0.0.1, not localhost: the container listens on IPv4 only, and localhost can resolve to ::1
# first. 8899 is `make start-searxng`'s default port (SEARXNG_PORT).
SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "http://127.0.0.1:8899").strip() or "http://127.0.0.1:8899"
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()
