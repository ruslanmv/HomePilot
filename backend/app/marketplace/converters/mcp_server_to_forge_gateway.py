"""Convert an MCP server manifest into a Context Forge gateway registration payload."""

from __future__ import annotations

from typing import Any, Dict, Optional


def manifest_to_gateway(manifest: Dict[str, Any], entity_name: str = "") -> Optional[Dict[str, Any]]:
    """Extract gateway registration fields from an MCP server manifest.

    Expected manifest structure (from Matrix Hub):
    {
      "name": "...",
      "description": "...",
      "mcp_registration": {
        "server": {
          "url": "http://...",
          "transport": "SSE"
        }
      }
    }

    Returns a dict suitable for ContextForgeClient.register_gateway(),
    or None if the manifest doesn't contain registration info.
    """
    mcp_reg = manifest.get("mcp_registration", {})
    server_info = mcp_reg.get("server", {})
    url = server_info.get("url", "")

    if not url:
        return None

    name = manifest.get("name", entity_name) or entity_name or "marketplace-server"
    transport = server_info.get("transport", "SSE").upper()

    return {
        "name": name,
        "url": url,
        "transport": transport,
        "description": manifest.get("description", f"Installed from marketplace: {name}"),
        "tags": ["marketplace", "matrixhub"],
        "visibility": "public",
    }
