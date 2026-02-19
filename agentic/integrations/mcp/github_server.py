"""Entry point for mcp-github server.

Usage:
    uvicorn agentic.integrations.mcp.github_server:app --port 9118
"""

from agentic.integrations.mcp.github.app import app  # noqa: F401
