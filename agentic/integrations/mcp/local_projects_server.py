"""Entry point for mcp-local-projects server.

Usage:
    uvicorn agentic.integrations.mcp.local_projects_server:app --port 9111
"""

from agentic.integrations.mcp.local_projects.app import app  # noqa: F401
