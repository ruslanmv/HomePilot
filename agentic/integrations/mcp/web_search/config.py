from __future__ import annotations

import os

LOG_LEVEL = os.getenv('WEB_SEARCH_LOG_LEVEL', 'INFO')
SERVICE_NAME = os.getenv('WEB_SEARCH_SERVICE_NAME', 'mcp-web-search')
PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "searxng").strip().lower()
HTTP_TIMEOUT = float(os.getenv("WEB_SEARCH_HTTP_TIMEOUT", "15"))
USER_AGENT = os.getenv("WEB_SEARCH_USER_AGENT", "HomePilot-WebSearch/1.0")
