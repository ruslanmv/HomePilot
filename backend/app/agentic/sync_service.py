"""Sync HomePilot MCP servers, tools, A2A agents into Context Forge.

Reusable async service that discovers tools from running MCP servers,
registers them in Forge, registers A2A agents, and creates virtual
servers.  Designed to be called from the backend API (POST /v1/agentic/sync)
or from CLI scripts.

Idempotent: skips items that already exist (matched by name).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml

logger = logging.getLogger("homepilot.agentic.sync")

# HomePilot MCP server definitions: (name, port, description)
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


def _templates_dir() -> Path:
    """Return the path to agentic/forge/templates/ from any working directory."""
    # Try relative to project root
    candidates = [
        Path(__file__).resolve().parents[3] / "agentic" / "forge" / "templates",
        Path("agentic/forge/templates"),
        Path(os.environ.get("HOMEPILOT_ROOT", ".")) / "agentic" / "forge" / "templates",
    ]
    for p in candidates:
        if p.is_dir():
            return p
    return candidates[0]  # best guess


def _load_yaml(filename: str) -> Dict[str, Any]:
    path = _templates_dir() / filename
    if not path.exists():
        logger.warning("template file not found: %s", path)
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


async def _acquire_jwt(
    client: httpx.AsyncClient,
    base_url: str,
    user: str,
    password: str,
) -> Optional[str]:
    """Acquire a JWT token from Forge /auth/login."""
    email = user if "@" in user else f"{user}@example.com"
    try:
        r = await client.post(
            f"{base_url}/auth/login",
            json={"email": email, "password": password},
        )
        if r.status_code == 200:
            return r.json().get("access_token")
    except Exception as exc:
        logger.warning("JWT login failed: %s", exc)
    return None


async def _discover_tools(port: int) -> List[Dict[str, Any]]:
    """Call a local MCP server's /rpc for tools/list."""
    url = f"http://127.0.0.1:{port}/rpc"
    body = {"jsonrpc": "2.0", "id": "sync-discover", "method": "tools/list"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(url, json=body)
            if r.status_code == 200:
                return r.json().get("result", {}).get("tools", [])
    except Exception:
        pass
    return []


async def _get(client: httpx.AsyncClient, base_url: str, path: str) -> Any:
    r = await client.get(f"{base_url}{path}")
    r.raise_for_status()
    return r.json()


async def _post(client: httpx.AsyncClient, base_url: str, path: str, json: Any = None) -> Any:
    r = await client.post(f"{base_url}{path}", json=json)
    if r.status_code == 409:
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    r.raise_for_status()
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return r.text


def _safe_list(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "data", "tools", "agents", "servers", "gateways"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def _tool_ids_by_prefix(
    tool_id_map: Dict[str, str],
    include_prefixes: List[str],
    exclude_prefixes: Optional[List[str]] = None,
) -> List[str]:
    exclude = exclude_prefixes or []
    out = []
    for name, tid in tool_id_map.items():
        if any(name.startswith(p) for p in include_prefixes):
            if not any(name.startswith(ep) for ep in exclude):
                out.append(tid)
    return out


async def sync_homepilot(
    base_url: str,
    auth_user: str = "admin",
    auth_pass: str = "changeme",
    bearer_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Discover HomePilot MCP tools and register everything in Context Forge.

    Returns a summary dict with counts and any errors.
    """
    log: List[str] = []
    errors: List[str] = []

    templates_agents = _load_yaml("a2a_agents.yaml")
    templates_gateways = _load_yaml("gateways.yaml")
    templates_servers = _load_yaml("virtual_servers.yaml")

    async with httpx.AsyncClient(
        headers={"Content-Type": "application/json"},
        timeout=30.0,
    ) as client:

        # Acquire JWT
        if bearer_token:
            client.headers["Authorization"] = f"Bearer {bearer_token}"
        else:
            token = await _acquire_jwt(client, base_url, auth_user, auth_pass)
            if token:
                client.headers["Authorization"] = f"Bearer {token}"
            else:
                # Fall back to basic auth
                client.auth = httpx.BasicAuth(auth_user, auth_pass)

        # Pre-fetch existing items
        try:
            existing_tools_list = _safe_list(await _get(client, base_url, "/tools"))
        except Exception:
            existing_tools_list = []
        existing_tools = {t["name"]: t["id"] for t in existing_tools_list if t.get("name") and t.get("id")}

        try:
            existing_agents_list = _safe_list(await _get(client, base_url, "/a2a"))
        except Exception:
            existing_agents_list = []
        existing_agents = {a["name"]: a["id"] for a in existing_agents_list if a.get("name") and a.get("id")}

        try:
            existing_servers_list = _safe_list(await _get(client, base_url, "/servers"))
        except Exception:
            existing_servers_list = []
        existing_servers = {s["name"]: s["id"] for s in existing_servers_list if s.get("name") and s.get("id")}

        # 1. Discover + register tools
        tool_id_map: Dict[str, str] = dict(existing_tools)
        tools_registered = 0
        tools_skipped = 0
        servers_reachable = 0

        for gw_name, port, desc in MCP_SERVERS:
            tools = await _discover_tools(port)
            if not tools:
                log.append(f"{gw_name} (port {port}): not reachable or no tools")
                continue

            servers_reachable += 1
            for tool_def in tools:
                tname = tool_def.get("name", "")
                if tname in existing_tools:
                    tool_id_map[tname] = existing_tools[tname]
                    tools_skipped += 1
                    continue

                payload = {
                    "tool": {
                        "name": tname,
                        "description": tool_def.get("description", ""),
                        "inputSchema": tool_def.get("inputSchema", {"type": "object", "properties": {}}),
                        "integration_type": "REST",
                        "request_type": "POST",
                        "url": f"http://127.0.0.1:{port}/rpc",
                        "tags": ["homepilot"],
                    },
                    "team_id": None,
                }
                try:
                    result = await _post(client, base_url, "/tools", json=payload)
                    tid = result.get("id") or result.get("tool_id") if isinstance(result, dict) else None
                    if tid:
                        tool_id_map[tname] = tid
                        existing_tools[tname] = tid
                        tools_registered += 1
                    else:
                        tools_skipped += 1
                except Exception as exc:
                    errors.append(f"tool '{tname}': {exc}")

            log.append(f"{gw_name}: {len(tools)} tools discovered")

        # 2. Register A2A agents
        agents_registered = 0
        agents_skipped = 0

        for agent_def in templates_agents.get("agents", []):
            name = agent_def["name"]
            if name in existing_agents:
                agents_skipped += 1
                continue

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
                result = await _post(client, base_url, "/a2a", json=payload)
                aid = result.get("id") or result.get("agent_id") if isinstance(result, dict) else None
                if aid:
                    existing_agents[name] = aid
                    agents_registered += 1
                else:
                    agents_skipped += 1
            except Exception as exc:
                errors.append(f"agent '{name}': {exc}")

        # 3. Register gateways (best-effort, may 503 on Community Edition)
        gateways_registered = 0
        for gw in templates_gateways.get("gateways", []):
            name = gw["name"]
            payload = {
                "name": name,
                "url": gw.get("url", ""),
                "description": gw.get("description", ""),
                "transport": "SSE",
                "tags": ["homepilot"],
                "visibility": "public",
            }
            try:
                await _post(client, base_url, "/gateways", json=payload)
                gateways_registered += 1
            except Exception:
                pass  # gateways are optional

        # 4. Create virtual servers
        vservers_created = 0
        vservers_skipped = 0

        for spec in templates_servers.get("servers", []):
            name = spec["name"]
            if name in existing_servers:
                vservers_skipped += 1
                continue

            include = spec.get("include_tool_prefixes", [])
            exclude = spec.get("exclude_tool_prefixes", [])
            tool_ids = _tool_ids_by_prefix(tool_id_map, include, exclude)

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
                await _post(client, base_url, "/servers", json=payload)
                vservers_created += 1
            except Exception as exc:
                errors.append(f"server '{name}': {exc}")

    return {
        "ok": len(errors) == 0,
        "mcp_servers_reachable": servers_reachable,
        "mcp_servers_total": len(MCP_SERVERS),
        "tools_registered": tools_registered,
        "tools_skipped": tools_skipped,
        "agents_registered": agents_registered,
        "agents_skipped": agents_skipped,
        "gateways_registered": gateways_registered,
        "virtual_servers_created": vservers_created,
        "virtual_servers_skipped": vservers_skipped,
        "log": log,
        "errors": errors,
    }
