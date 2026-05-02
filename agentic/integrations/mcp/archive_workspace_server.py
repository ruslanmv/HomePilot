from __future__ import annotations

from agentic.integrations.mcp.archive_workspace.app import register_tools

if __name__ == "__main__":
    print({"server": __file__, "tools": register_tools()})
