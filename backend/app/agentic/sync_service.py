"""Sync HomePilot MCP servers, tools, A2A agents into Context Forge.

Reusable async service that discovers tools from running MCP servers,
registers them in Forge, registers A2A agents, and creates/updates virtual
servers.  Designed to be called from the backend API (POST /v1/agentic/sync)
or from CLI scripts.

Idempotent: creates new items or upserts existing virtual server tool
associations so that tool bundles stay current even after restart.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml

logger = logging.getLogger("homepilot.agentic.sync")

# Host for discovering and registering MCP server tools.
# Override with MCP_TOOL_HOST env var when Forge runs in Docker
# (e.g. "host.docker.internal" so Forge can reach host-side MCP servers).
MCP_TOOL_HOST = os.getenv("MCP_TOOL_HOST", "127.0.0.1")

# Core MCP servers — always running (started by agentic-start.sh).
# Optional servers are managed by ServerManager and added dynamically.
_CORE_SERVERS = [
    ("hp-personal-assistant", 9101, "HomePilot Personal Assistant MCP server"),
    ("hp-knowledge", 9102, "HomePilot Knowledge MCP server"),
    ("hp-decision-copilot", 9103, "HomePilot Decision Copilot MCP server"),
    ("hp-executive-briefing", 9104, "HomePilot Executive Briefing MCP server"),
    ("hp-web-search", 9105, "HomePilot Web Search MCP server"),
    ("hp-inventory", 9120, "HomePilot Inventory MCP server"),
]


def _get_mcp_servers() -> List[tuple]:
    """Return the list of MCP servers to sync: core + installed optional.

    Dynamically includes optional servers that are currently installed via
    the ServerManager so sync only touches servers that are actually running.
    """
    servers = list(_CORE_SERVERS)
    try:
        from .server_manager import get_server_manager
        mgr = get_server_manager()
        for sid in mgr.installed_ids():
            sdef = mgr.get_server(sid)
            if sdef and not sdef.is_core:
                servers.append((sdef.id, sdef.port, sdef.description))
    except Exception:
        pass  # server_manager unavailable — sync core only
    return servers


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


async def _wait_for_forge(client: httpx.AsyncClient, base_url: str, timeout: int = 15) -> bool:
    """Wait up to *timeout* seconds for Forge /health to respond 200."""
    import asyncio
    for i in range(timeout):
        try:
            r = await client.get(f"{base_url}/health")
            if r.status_code == 200:
                return True
        except Exception:
            pass
        if i < timeout - 1:
            await asyncio.sleep(1)
    return False


async def _acquire_jwt(
    client: httpx.AsyncClient,
    base_url: str,
    user: str,
    password: str,
    retries: int = 3,
) -> Optional[str]:
    """Acquire a JWT token from Forge /auth/login.

    Retries up to *retries* times with 2-second backoff to tolerate Forge
    startup delays that cause transient HTTP 500 on the auth endpoint.
    """
    import asyncio
    email = user if "@" in user else f"{user}@example.com"
    for attempt in range(retries):
        try:
            r = await client.post(
                f"{base_url}/auth/login",
                json={"email": email, "password": password},
            )
            if r.status_code == 200:
                return r.json().get("access_token")
            logger.warning(
                "JWT login attempt %d/%d: HTTP %d",
                attempt + 1, retries, r.status_code,
            )
        except Exception as exc:
            logger.warning("JWT login attempt %d/%d: %s", attempt + 1, retries, exc)
        if attempt < retries - 1:
            await asyncio.sleep(2)
    return None


async def _discover_tools(port: int, host: str = "") -> tuple[List[Dict[str, Any]], Optional[str]]:
    """Call a local MCP server's /rpc for tools/list.

    Returns (tools_list, error_message).  error_message is None on success.
    """
    h = host or MCP_TOOL_HOST
    url = f"http://{h}:{port}/rpc"
    body = {"jsonrpc": "2.0", "id": "sync-discover", "method": "tools/list"}
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.post(url, json=body)
            if r.status_code == 200:
                tools = r.json().get("result", {}).get("tools", [])
                return tools, None
            return [], f"HTTP {r.status_code} from {url}"
    except Exception as exc:
        return [], f"Connection failed: {url} ({exc})"


async def _get(client: httpx.AsyncClient, base_url: str, path: str, **params: Any) -> Any:
    r = await client.get(f"{base_url}{path}", params=params or None)
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


async def _put(client: httpx.AsyncClient, base_url: str, path: str, json: Any = None) -> Any:
    """PUT request for updating existing Forge resources."""
    r = await client.put(f"{base_url}{path}", json=json)
    r.raise_for_status()
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return r.text


async def _patch(client: httpx.AsyncClient, base_url: str, path: str, json: Any = None) -> Any:
    """PATCH request for partial updates to existing Forge resources.

    Falls back to PUT if PATCH returns 405 (Method Not Allowed).
    """
    r = await client.patch(f"{base_url}{path}", json=json)
    if r.status_code == 405:
        # Forge version doesn't support PATCH — fall back to PUT
        return await _put(client, base_url, path, json=json)
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


def _tool_needs_update(
    existing: Dict[str, Any],
    discovered: Dict[str, Any],
    port: int,
) -> bool:
    """Check if an existing Forge tool needs updating (schema/description changed).

    Compares the discovered tool definition against what Forge currently has.
    Only checks fields that sync controls: description and inputSchema.
    """
    old_desc = str(existing.get("description") or "")
    new_desc = str(discovered.get("description") or "")
    if old_desc != new_desc:
        return True

    # Compare inputSchema (Forge may store it under different keys)
    old_schema = existing.get("input_schema") or existing.get("inputSchema") or {}
    new_schema = discovered.get("inputSchema") or {"type": "object", "properties": {}}
    if old_schema != new_schema:
        return True

    # Check if the tool URL has changed (e.g. MCP_TOOL_HOST changed)
    old_url = str(existing.get("url") or "")
    expected_url = f"http://{MCP_TOOL_HOST}:{port}/rpc"
    if old_url and old_url != expected_url:
        return True

    return False


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

        # Wait for Forge to be healthy before trying JWT
        forge_healthy = await _wait_for_forge(client, base_url, timeout=10)
        if not forge_healthy:
            errors.append(f"Forge not reachable at {base_url}/health after 10s")
            log.append("Forge health check failed — sync will proceed with basic auth")

        # Acquire JWT (retries to tolerate startup HTTP 500)
        if bearer_token:
            client.headers["Authorization"] = f"Bearer {bearer_token}"
        else:
            token = await _acquire_jwt(client, base_url, auth_user, auth_pass)
            if token:
                client.headers["Authorization"] = f"Bearer {token}"
                log.append("Forge JWT acquired")
            else:
                # Fall back to basic auth
                client.auth = httpx.BasicAuth(auth_user, auth_pass)
                log.append("Forge JWT failed — using basic auth fallback")

        # Pre-fetch existing items.
        # Use limit=0 to bypass Forge default pagination (50 items/page)
        # and retrieve all items in a single request.
        try:
            existing_tools_list = _safe_list(await _get(client, base_url, "/tools", limit=0))
        except Exception:
            existing_tools_list = []

        # Deduplicate: prior sync runs with broken pagination created duplicate
        # tools (same name, different UUIDs).  Keep the first occurrence of each
        # name and delete the rest so Forge stays clean.
        tools_deduped = 0
        seen_names: Dict[str, str] = {}  # name → first-seen ID
        for t in existing_tools_list:
            tname = t.get("name", "")
            tid = t.get("id", "")
            if not tname or not tid:
                continue
            if tname in seen_names:
                # Duplicate — delete it from Forge
                try:
                    await client.delete(f"{base_url}/tools/{tid}")
                    tools_deduped += 1
                except Exception:
                    pass  # best-effort cleanup
            else:
                seen_names[tname] = tid
        if tools_deduped:
            log.append(f"Deduped {tools_deduped} duplicate tools from Forge")
            logger.info("Removed %d duplicate tools from Forge", tools_deduped)

        existing_tools = dict(seen_names)
        # Keep full tool dicts for upsert comparison (description/schema changes)
        existing_tools_full = {t["name"]: t for t in existing_tools_list if t.get("name") and t.get("id") and t["name"] in seen_names and seen_names[t["name"]] == t["id"]}

        try:
            existing_agents_list = _safe_list(await _get(client, base_url, "/a2a", limit=0))
        except Exception:
            existing_agents_list = []
        existing_agents = {a["name"]: a["id"] for a in existing_agents_list if a.get("name") and a.get("id")}

        try:
            existing_servers_list = _safe_list(await _get(client, base_url, "/servers", limit=0))
        except Exception:
            existing_servers_list = []
        existing_servers = {s["name"]: s["id"] for s in existing_servers_list if s.get("name") and s.get("id")}

        # 1. Discover + register tools
        tool_id_map: Dict[str, str] = dict(existing_tools)
        tools_registered = 0
        tools_skipped = 0
        tools_updated = 0
        servers_reachable = 0
        servers_unreachable: List[str] = []
        # Per-server discovery details for diagnostics
        server_details: List[Dict[str, Any]] = []

        mcp_servers = _get_mcp_servers()

        for gw_name, port, desc in mcp_servers:
            tools, discover_err = await _discover_tools(port)
            if not tools:
                msg = f"{gw_name} (port {port}): {discover_err or 'no tools exposed'}"
                log.append(msg)
                servers_unreachable.append(f"{gw_name}:{port}")
                server_details.append({
                    "name": gw_name,
                    "port": port,
                    "reachable": False,
                    "tools_discovered": 0,
                    "error": discover_err or "no tools exposed",
                })
                continue

            servers_reachable += 1
            server_new = 0
            server_updated = 0
            server_skipped = 0

            for tool_def in tools:
                tname = tool_def.get("name", "")
                if tname in existing_tools:
                    tool_id_map[tname] = existing_tools[tname]

                    # Upsert: check if tool metadata has changed
                    full = existing_tools_full.get(tname)
                    if full and _tool_needs_update(full, tool_def, port):
                        tid = existing_tools[tname]
                        update_payload = {
                            "description": tool_def.get("description", ""),
                            "input_schema": tool_def.get("inputSchema", {"type": "object", "properties": {}}),
                            "url": f"http://{MCP_TOOL_HOST}:{port}/rpc",
                        }
                        try:
                            await _put(client, base_url, f"/tools/{tid}", json=update_payload)
                            tools_updated += 1
                            server_updated += 1
                        except Exception as exc:
                            # Non-fatal: tool exists but update failed; log and continue
                            logger.debug("tool '%s' update failed (non-fatal): %s", tname, exc)
                            server_skipped += 1
                    else:
                        server_skipped += 1
                        tools_skipped += 1
                    continue

                payload = {
                    "tool": {
                        "name": tname,
                        "description": tool_def.get("description", ""),
                        "inputSchema": tool_def.get("inputSchema", {"type": "object", "properties": {}}),
                        "integration_type": "REST",
                        "request_type": "POST",
                        "url": f"http://{MCP_TOOL_HOST}:{port}/rpc",
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
                        server_new += 1
                    else:
                        tools_skipped += 1
                        server_skipped += 1
                except Exception as exc:
                    errors.append(f"tool '{tname}': {exc}")

            log.append(f"{gw_name}: {len(tools)} tools discovered ({server_new} new, {server_updated} updated, {server_skipped} unchanged)")
            server_details.append({
                "name": gw_name,
                "port": port,
                "reachable": True,
                "tools_discovered": len(tools),
                "tools_new": server_new,
                "tools_updated": server_updated,
                "tools_unchanged": server_skipped,
            })

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

        # 3. Register gateways
        #
        # DISABLED: HomePilot MCP servers expose plain HTTP POST /rpc
        # endpoints (JSON-RPC 2.0), not SSE.  Forge gateway registration
        # attempts an SSE handshake (GET /rpc) which always fails with
        # 404 or 405, flooding the Forge log with GatewayConnectionError
        # stack traces.  Tool discovery (step 1) already registers tools
        # correctly via direct POST.  Gateway registration is purely
        # decorative (admin UI catalog) and adds no functional value.
        #
        # When HomePilot MCP servers add SSE support, re-enable this
        # section and filter to only reachable servers:
        #   reachable = {port for n, port, _ in mcp_servers
        #                if f"{n}:{port}" not in set(servers_unreachable)}
        gateways_registered = 0
        gateways_skipped = len(templates_gateways.get("gateways", []))

        # 4. Create or update virtual servers (upsert tool associations)
        vservers_created = 0
        vservers_updated = 0
        vservers_unchanged = 0

        # Re-fetch all tools from Forge to ensure tool_id_map has current
        # UUIDs, especially when tools were created by a prior seed run or
        # when 409 conflicts were resolved above.
        try:
            refreshed_tools = _safe_list(await _get(client, base_url, "/tools", limit=0))
            for t in refreshed_tools:
                if t.get("name") and t.get("id"):
                    tool_id_map[t["name"]] = t["id"]
            log.append(f"tool_id_map refreshed: {len(tool_id_map)} tools available for virtual servers")
        except Exception as exc:
            logger.warning("Could not refresh tool list before virtual server upsert: %s", exc)

        logger.info(
            "tool_id_map has %d entries before virtual server upsert",
            len(tool_id_map),
        )

        for spec in templates_servers.get("servers", []):
            name = spec["name"]
            include = spec.get("include_tool_prefixes", [])
            exclude = spec.get("exclude_tool_prefixes", [])
            tool_ids = _tool_ids_by_prefix(tool_id_map, include, exclude)

            logger.info(
                "vserver '%s': include=%s exclude=%s → matched %d tools",
                name, include, exclude, len(tool_ids),
            )

            if name in existing_servers:
                # Upsert: update tool associations for existing server
                server_id = existing_servers[name]
                updated = False
                # Try multiple payload shapes that different Forge versions accept
                payloads_to_try = [
                    {"associated_tools": tool_ids},
                    {"server": {"associated_tools": tool_ids}},
                ]
                for payload in payloads_to_try:
                    try:
                        await _put(client, base_url, f"/servers/{server_id}", json=payload)
                        updated = True
                        break
                    except Exception:
                        continue
                if updated:
                    vservers_updated += 1
                    log.append(f"vserver '{name}': updated ({len(tool_ids)} tools)")
                else:
                    # Last resort: delete + recreate
                    try:
                        await client.delete(f"{base_url}/servers/{server_id}")
                        create_payload = {
                            "server": {
                                "name": name,
                                "description": spec.get("description", ""),
                                "associated_tools": tool_ids,
                                "tags": ["homepilot"],
                            },
                            "visibility": "public",
                        }
                        result = await _post(client, base_url, "/servers", json=create_payload)
                        new_id = result.get("id") if isinstance(result, dict) else None
                        if new_id:
                            existing_servers[name] = new_id
                        vservers_updated += 1
                        log.append(f"vserver '{name}': recreated ({len(tool_ids)} tools)")
                    except Exception as exc:
                        vservers_unchanged += 1
                        logger.warning("vserver '%s': all update methods failed: %s", name, exc)
                continue

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
                log.append(f"vserver '{name}': created ({len(tool_ids)} tools)")
            except Exception as exc:
                errors.append(f"server '{name}': {exc}")

    return {
        "ok": len(errors) == 0,
        "mcp_tool_host": MCP_TOOL_HOST,
        "mcp_servers_reachable": servers_reachable,
        "mcp_servers_total": len(mcp_servers),
        "mcp_servers_unreachable": servers_unreachable,
        "tools_registered": tools_registered,
        "tools_updated": tools_updated,
        "tools_skipped": tools_skipped,
        "tools_deduped": tools_deduped,
        "tools_total_in_forge": len(tool_id_map),
        "agents_registered": agents_registered,
        "agents_skipped": agents_skipped,
        "gateways_registered": gateways_registered,
        "gateways_skipped": gateways_skipped,
        "virtual_servers_created": vservers_created,
        "virtual_servers_updated": vservers_updated,
        "virtual_servers_unchanged": vservers_unchanged,
        "server_details": server_details,
        "log": log,
        "errors": errors,
    }
