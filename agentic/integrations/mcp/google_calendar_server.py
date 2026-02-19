"""Entry point for mcp-google-calendar server.

Usage:
    uvicorn agentic.integrations.mcp.google_calendar_server:app --port 9115
"""

from agentic.integrations.mcp.google_calendar.app import app  # noqa: F401
