"""Seed MCP Context Forge with the HomePilot agentic suite.

Strategy:
  1. Acquire JWT token from Forge via POST /auth/login
  2. Query each local MCP server's /rpc endpoint for tools/list
  3. Register every tool DIRECTLY with Forge via POST /tools (integration_type=REST)
  4. Register A2A agents via POST /a2a
  5. Register gateways for admin UI visibility (optional, no auto-discovery)
  6. Create virtual servers referencing the collected tool IDs

This avoids relying on Forge gateway auto-discovery (SSE), since our
MCP servers speak plain HTTP JSON-RPC at /rpc.

Forge requires JWT Bearer tokens — basic auth is NOT accepted by the API.
The script acquires a token from POST /auth/login using the platform admin
email convention: {BASIC_AUTH_USER}@example.com / {BASIC_AUTH_PASSWORD}.

Idempotent: skips items that already exist (matched by name).

Usage:
  python agentic/forge/seed/seed_all.py

Environment variables:
  MCPGATEWAY_URL        (default: http://localhost:4444)
  BASIC_AUTH_USER       (default: admin)
  BASIC_AUTH_PASSWORD   (default: changeme)
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml


BASE_URL = os.environ.get("MCPGATEWAY_URL", "http://localhost:4444").rstrip("/")
AUTH_USER = os.environ.get("BASIC_AUTH_USER", "admin")
AUTH_PASS = os.environ.get("BASIC_AUTH_PASSWORD", "changeme")

# Local MCP servers and their ports (must be running)
MCP_SERVERS = [
    # Core (9101–9105)
    ("hp-personal-assistant", 9101, "HomePilot Personal Assistant MCP server"),
    ("hp-knowledge", 9102, "HomePilot Knowledge MCP server"),
    ("hp-decision-copilot", 9103, "HomePilot Decision Copilot MCP server"),
    ("hp-executive-briefing", 9104, "HomePilot Executive Briefing MCP server"),
    ("hp-web-search", 9105, "HomePilot Web Search MCP server"),
    # Local (9110–9113)
    ("hp-local-notes", 9110, "HomePilot Local Notes MCP server"),
    ("hp-local-projects", 9111, "HomePilot Local Projects MCP server"),
    ("hp-web-fetch", 9112, "HomePilot Web Fetch MCP server"),
    ("hp-shell-safe", 9113, "HomePilot Shell Safe MCP server"),
    # Communication (9114–9117)
    ("hp-gmail", 9114, "HomePilot Gmail MCP server"),
    ("hp-google-calendar", 9115, "HomePilot Google Calendar MCP server"),
    ("hp-microsoft-graph", 9116, "HomePilot Microsoft Graph MCP server"),
    ("hp-slack", 9117, "HomePilot Slack MCP server"),
    # Dev & Knowledge (9118–9119)
    ("hp-github", 9118, "HomePilot GitHub MCP server"),
    ("hp-notion", 9119, "HomePilot Notion MCP server"),
]


def _load_yaml(rel: str) -> Dict[str, Any]:
    # seed_all.py is at agentic/forge/seed/ — templates are at agentic/forge/templates/
    root = Path(__file__).resolve().parents[1]
    path = root / "templates" / rel
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ── JWT authentication ──────────────────────────────────────────────────────


async def _acquire_jwt(client: httpx.AsyncClient) -> str:
    """Get a JWT token from Forge /auth/login."""
    email = AUTH_USER if "@" in AUTH_USER else f"{AUTH_USER}@example.com"
    payload = {"email": email, "password": AUTH_PASS}
    r = await client.post(
        f"{BASE_URL}/auth/login",
        json=payload,
        headers={"Content-Type": "application/json"},
    )
    if r.status_code != 200:
        raise RuntimeError(f"Forge login failed: HTTP {r.status_code} - {r.text[:200]}")
    data = r.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"Forge login response missing access_token: {data}")
    return token


# ── Forge API helpers ──────────────────────────────────────────────────────


async def _get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    r = await client.get(f"{BASE_URL}{path}", params=params or None)
    r.raise_for_status()
    return r.json()


async def _post(client: httpx.AsyncClient, path: str, json: Any = None) -> Any:
    r = await client.post(f"{BASE_URL}{path}", json=json)
    if r.status_code == 409:
        # Already exists — not an error
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    r.raise_for_status()
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return r.text


# ── Step 1: Discover tools from local MCP servers ─────────────────────────


async def discover_tools_from_server(port: int) -> List[Dict[str, Any]]:
    """Call a local MCP server's /rpc with tools/list and return tool defs."""
    url = f"http://127.0.0.1:{port}/rpc"
    body = {"jsonrpc": "2.0", "id": "seed-discover", "method": "tools/list"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(url, json=body)
            if r.status_code == 200:
                data = r.json()
                return data.get("result", {}).get("tools", [])
    except Exception as exc:
        print(f"  ⚠ Could not reach server on port {port}: {exc}")
    return []


# ── Step 2: Register tools directly with Forge ────────────────────────────


async def ensure_tool(
    client: httpx.AsyncClient,
    name: str,
    description: str,
    input_schema: Dict[str, Any],
    existing_tools: Dict[str, str],
    server_port: int,
) -> Optional[str]:
    """Register a tool with Forge; return its ID. Skip if already exists.

    Uses integration_type="REST" because Forge blocks manual MCP tool
    creation (MCP tools must come from gateway auto-discovery).
    """
    if name in existing_tools:
        return existing_tools[name]

    payload = {
        "tool": {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "integration_type": "REST",
            "request_type": "POST",
            "url": f"http://127.0.0.1:{server_port}/rpc",
            "tags": ["homepilot"],
        },
        "team_id": None,
    }
    try:
        result = await _post(client, "/tools", json=payload)
        tool_id = None
        if isinstance(result, dict):
            tool_id = result.get("id") or result.get("tool_id")
        if tool_id:
            return tool_id
        # On 409 conflict, try to find existing by listing again
        refreshed = await _get(client, "/tools", limit=0)
        if not isinstance(refreshed, list):
            refreshed = refreshed.get("tools", []) if isinstance(refreshed, dict) else []
        for t in refreshed:
            if t.get("name") == name:
                return t.get("id")
    except Exception as exc:
        print(f"  ⚠ Failed to register tool '{name}': {exc}")
    return None


# ── Step 3: Register A2A agents ────────────────────────────────────────────


async def ensure_a2a_agent(
    client: httpx.AsyncClient,
    agent_def: Dict[str, Any],
    existing_agents: Dict[str, str],
) -> Optional[str]:
    """Register an A2A agent with Forge; return its ID."""
    name = agent_def["name"]
    if name in existing_agents:
        return existing_agents[name]

    payload = {
        "agent": {
            "name": name,
            "description": agent_def.get("description", ""),
            "endpoint_url": agent_def.get("endpoint_url", ""),
            "agent_type": "custom",
            "protocol_version": "1.0",
            "capabilities": {"tools": []},
            "config": {},
            "tags": ["homepilot"],
        },
        "visibility": "public",
    }
    try:
        result = await _post(client, "/a2a", json=payload)
        agent_id = None
        if isinstance(result, dict):
            agent_id = result.get("id") or result.get("agent_id")
        if agent_id:
            return agent_id
        # Try to find existing
        refreshed = await _get(client, "/a2a")
        for a in refreshed:
            if a.get("name") == name:
                return a.get("id")
    except Exception as exc:
        print(f"  ⚠ Failed to register A2A agent '{name}': {exc}")
    return None


# ── Step 4: Register gateways (admin visibility only) ─────────────────────


async def ensure_gateway(
    client: httpx.AsyncClient,
    gw_def: Dict[str, Any],
    existing_gateways: Dict[str, str],
) -> Optional[str]:
    """Register a gateway for admin UI visibility. No auto-discovery."""
    name = gw_def["name"]
    if name in existing_gateways:
        return existing_gateways[name]

    # Use SSE transport (required by Forge) even though our servers are HTTP JSON-RPC.
    # This is for admin catalog visibility only — tool discovery is done directly above.
    payload = {
        "name": name,
        "url": gw_def.get("url", ""),
        "description": gw_def.get("description", ""),
        "transport": "SSE",
        "tags": ["homepilot"],
        "visibility": "public",
    }
    try:
        result = await _post(client, "/gateways", json=payload)
        gw_id = None
        if isinstance(result, dict):
            gw_id = result.get("id") or result.get("gateway_id")
        if gw_id:
            return gw_id
        refreshed = await _get(client, "/gateways")
        for g in (refreshed if isinstance(refreshed, list) else []):
            if g.get("name") == name:
                return g.get("id")
    except Exception as exc:
        print(f"  ⚠ Failed to register gateway '{name}': {exc}")
    return None


# ── Step 5: Create virtual servers ─────────────────────────────────────────


def _tool_ids_by_prefix(
    tool_id_map: Dict[str, str],
    include_prefixes: List[str],
    exclude_prefixes: Optional[List[str]] = None,
) -> List[str]:
    """Match tool names by prefix and return their Forge IDs."""
    exclude = exclude_prefixes or []
    out: List[str] = []
    for name, tid in tool_id_map.items():
        if any(name.startswith(p) for p in include_prefixes):
            if not any(name.startswith(ep) for ep in exclude):
                out.append(tid)
    return out


async def ensure_virtual_server(
    client: httpx.AsyncClient,
    spec: Dict[str, Any],
    tool_id_map: Dict[str, str],
    existing_servers: Dict[str, str],
) -> None:
    """Create or update a virtual server's tool associations."""
    name = spec["name"]
    include = spec.get("include_tool_prefixes", [])
    exclude = spec.get("exclude_tool_prefixes", [])
    tool_ids = _tool_ids_by_prefix(tool_id_map, include, exclude)

    if name in existing_servers:
        # Upsert: update tool associations for existing server.
        # Try multiple payload shapes for cross-version Forge compatibility.
        server_id = existing_servers[name]
        updated = False
        for payload in [
            {"associated_tools": tool_ids},
            {"server": {"associated_tools": tool_ids}},
        ]:
            try:
                r = await client.put(
                    f"{BASE_URL}/servers/{server_id}",
                    json=payload,
                )
                r.raise_for_status()
                updated = True
                break
            except Exception:
                continue
        if updated:
            print(f"  virtual server: {name} (updated, {len(tool_ids)} tools)")
        else:
            # Last resort: delete + recreate
            try:
                await client.delete(f"{BASE_URL}/servers/{server_id}")
                create_payload = {
                    "server": {
                        "name": name,
                        "description": spec.get("description", ""),
                        "associated_tools": tool_ids,
                        "tags": ["homepilot"],
                    },
                    "visibility": "public",
                }
                await _post(client, "/servers", json=create_payload)
                print(f"  virtual server: {name} (recreated, {len(tool_ids)} tools)")
            except Exception as exc:
                print(f"  virtual server: {name} (exists, all update methods failed: {exc})")
        return

    payload = {
        "server": {
            "name": name,
            "description": spec.get("description", ""),
            "associated_tools": tool_ids,
            "tags": ["homepilot"],
        },
        "visibility": "public",
    }
    try:
        await _post(client, "/servers", json=payload)
        print(f"  virtual server: {name} ({len(tool_ids)} tools)")
    except Exception as exc:
        print(f"  ⚠ Failed to create virtual server '{name}': {exc}")


# ── Main ───────────────────────────────────────────────────────────────────


async def main() -> int:
    templates_gateways = _load_yaml("gateways.yaml")
    templates_servers = _load_yaml("virtual_servers.yaml")
    templates_agents = _load_yaml("a2a_agents.yaml")

    async with httpx.AsyncClient(
        headers={"Content-Type": "application/json"},
        timeout=30.0,
    ) as client:
        print(f"Seeding Context Forge at {BASE_URL} ...")

        # ── 0. Acquire JWT token ──────────────────────────────────────
        try:
            token = await _acquire_jwt(client)
            client.headers["Authorization"] = f"Bearer {token}"
            print("  JWT token acquired")
        except Exception as exc:
            print(f"  ✗ JWT login failed: {exc}")
            print("  Hint: ensure Forge is running and BASIC_AUTH_USER/PASSWORD are correct")
            return 1

        # ── Pre-fetch existing items to make idempotent ────────────────
        # Use limit=0 to bypass Forge default pagination (50 items/page)
        # and retrieve all items in a single request.
        try:
            existing_tools_list = await _get(client, "/tools", limit=0)
            if not isinstance(existing_tools_list, list):
                existing_tools_list = existing_tools_list.get("tools", []) if isinstance(existing_tools_list, dict) else []
        except Exception:
            existing_tools_list = []

        # Deduplicate: prior seed runs may have created duplicate tools
        # (same name, different UUIDs) due to broken pagination.
        seen_tool_names: Dict[str, str] = {}
        dedup_count = 0
        for t in (existing_tools_list or []):
            tname = t.get("name", "")
            tid = t.get("id", "")
            if not tname or not tid:
                continue
            if tname in seen_tool_names:
                try:
                    await client.delete(f"{BASE_URL}/tools/{tid}")
                    dedup_count += 1
                except Exception:
                    pass
            else:
                seen_tool_names[tname] = tid
        if dedup_count:
            print(f"  Removed {dedup_count} duplicate tools from Forge")

        existing_tools: Dict[str, str] = dict(seen_tool_names)

        try:
            existing_agents_list = await _get(client, "/a2a", limit=0)
            if not isinstance(existing_agents_list, list):
                existing_agents_list = existing_agents_list.get("agents", []) if isinstance(existing_agents_list, dict) else []
        except Exception:
            existing_agents_list = []
        existing_agents: Dict[str, str] = {
            a["name"]: a["id"]
            for a in (existing_agents_list or [])
            if a.get("name") and a.get("id")
        }

        try:
            existing_gateways_list = await _get(client, "/gateways", limit=0)
            if not isinstance(existing_gateways_list, list):
                existing_gateways_list = existing_gateways_list.get("gateways", []) if isinstance(existing_gateways_list, dict) else []
        except Exception:
            existing_gateways_list = []
        existing_gateways: Dict[str, str] = {
            g["name"]: g["id"]
            for g in existing_gateways_list
            if g.get("name") and g.get("id")
        }

        try:
            existing_servers_list = await _get(client, "/servers", limit=0)
            if not isinstance(existing_servers_list, list):
                existing_servers_list = existing_servers_list.get("servers", []) if isinstance(existing_servers_list, dict) else []
        except Exception:
            existing_servers_list = []
        existing_servers: Dict[str, str] = {
            s["name"]: s["id"]
            for s in existing_servers_list
            if s.get("name") and s.get("id")
        }

        # ── 1. Discover + register tools from each local MCP server ───
        tool_id_map: Dict[str, str] = dict(existing_tools)
        total_tools = 0

        for gw_name, port, desc in MCP_SERVERS:
            tools = await discover_tools_from_server(port)
            if not tools:
                print(f"  {gw_name}: no tools discovered (server may not be ready)")
                continue

            for tool_def in tools:
                tname = tool_def.get("name", "")
                tdesc = tool_def.get("description", "")
                tschema = tool_def.get("inputSchema", {"type": "object", "properties": {}})
                tid = await ensure_tool(client, tname, tdesc, tschema, existing_tools, port)
                if tid:
                    tool_id_map[tname] = tid
                    existing_tools[tname] = tid
                    total_tools += 1

            print(f"  {gw_name}: {len(tools)} tools registered")

        print(f"  Total tools: {total_tools}")

        # ── 2. Register A2A agents ─────────────────────────────────────
        for agent_def in templates_agents.get("agents", []):
            aid = await ensure_a2a_agent(client, agent_def, existing_agents)
            if aid:
                existing_agents[agent_def["name"]] = aid
            print(f"  a2a: {agent_def['name']}")

        # ── 3. Register gateways (admin visibility) ────────────────────
        for gw in templates_gateways.get("gateways", []):
            await ensure_gateway(client, gw, existing_gateways)
            print(f"  gateway: {gw['name']}")

        # ── 4. Create virtual servers ──────────────────────────────────
        # Re-fetch all tools from Forge to ensure tool_id_map has current
        # UUIDs, especially if tools were created by a previous run or
        # if 409 conflicts were resolved above.
        try:
            refreshed_tools = await _get(client, "/tools", limit=0)
            if not isinstance(refreshed_tools, list):
                refreshed_tools = refreshed_tools.get("tools", []) if isinstance(refreshed_tools, dict) else []
            for t in refreshed_tools:
                if t.get("name") and t.get("id"):
                    tool_id_map[t["name"]] = t["id"]
            print(f"  tool_id_map refreshed: {len(tool_id_map)} tools available for virtual servers")
        except Exception as exc:
            print(f"  ⚠ Could not refresh tool list: {exc}")

        for server_spec in templates_servers.get("servers", []):
            await ensure_virtual_server(client, server_spec, tool_id_map, existing_servers)

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
