"""Entry point for mcp-notion server.

Usage:
    uvicorn agentic.integrations.mcp.notion_server:app --port 9119
"""

from agentic.integrations.mcp.notion.app import app  # noqa: F401
