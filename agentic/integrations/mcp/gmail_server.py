"""Entry point for mcp-gmail server.

Usage:
    uvicorn agentic.integrations.mcp.gmail_server:app --port 9114
"""

from agentic.integrations.mcp.gmail.app import app  # noqa: F401
