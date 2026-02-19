"""Entry point for mcp-shell-safe server.

Usage:
    uvicorn agentic.integrations.mcp.shell_safe_server:app --port 9113
"""

from agentic.integrations.mcp.shell_safe.app import app  # noqa: F401
