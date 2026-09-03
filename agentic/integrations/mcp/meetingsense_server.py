"""Entry point for mcp-meetingsense server.

Usage:
    uvicorn agentic.integrations.mcp.meetingsense_server:app --port 9107
"""

from agentic.integrations.mcp.meetingsense.app import app  # noqa: F401
