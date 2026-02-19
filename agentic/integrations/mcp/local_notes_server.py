"""Entry point for mcp-local-notes server.

Usage:
    uvicorn agentic.integrations.mcp.local_notes_server:app --port 9110
"""

from agentic.integrations.mcp.local_notes.app import app  # noqa: F401
