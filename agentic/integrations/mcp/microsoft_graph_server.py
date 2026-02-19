"""Entry point for mcp-microsoft-graph server.

Usage:
    uvicorn agentic.integrations.mcp.microsoft_graph_server:app --port 9116
"""

from agentic.integrations.mcp.microsoft_graph.app import app  # noqa: F401
