"""Entry point for mcp-web server.

Usage:
    uvicorn agentic.integrations.mcp.web_mcp_server:app --port 9112
"""

from agentic.integrations.mcp.web.app import app  # noqa: F401
