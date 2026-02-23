"""Entry point for mcp-inventory server.

Usage:
    uvicorn agentic.integrations.mcp.inventory_server:app --port 9120
"""

from agentic.integrations.mcp.inventory.app import app  # noqa: F401
