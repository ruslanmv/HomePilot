"""Entry point for mcp-slack server.

Usage:
    uvicorn agentic.integrations.mcp.slack_server:app --port 9117
"""

from agentic.integrations.mcp.slack.app import app  # noqa: F401
