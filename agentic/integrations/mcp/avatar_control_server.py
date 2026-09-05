"""Entry point for the avatar_control MCP server (spec v1.1 §6.14, batch B17).

Mirrors the other servers in this directory: the module lives in its own package and this
file is what `agentic-start.sh` and Context Forge point at.

    uvicorn agentic.integrations.mcp.avatar_control_server:app --host 0.0.0.0 --port 9121
"""

from __future__ import annotations

from agentic.integrations.mcp.avatar_control.app import app

__all__ = ["app"]
