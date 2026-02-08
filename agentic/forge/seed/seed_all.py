"""Seed MCP Context Forge with the HomePilot agentic suite.

Idempotent best-effort:
* registers gateways
* refreshes them
* registers A2A agents
* creates virtual servers (tool bundles)

Usage:

  python agentic/forge/seed/seed_all.py

Environment variables:

  MCPGATEWAY_URL        (default: http://localhost:4444)
  BASIC_AUTH_USER        (default: admin)
  BASIC_AUTH_PASSWORD    (default: changeme)

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
AUTH = (
    os.environ.get("BASIC_AUTH_USER", "admin"),
    os.environ.get("BASIC_AUTH_PASSWORD", "changeme"),
)


def _load_yaml(rel: str) -> Dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    path = root / "templates" / rel
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


async def _get(client: httpx.AsyncClient, path: str) -> Any:
    r = await client.get(f"{BASE_URL}{path}")
    r.raise_for_status()
    return r.json()


async def _post(client: httpx.AsyncClient, path: str, json: Optional[Dict[str, Any]] = None) -> Any:
    r = await client.post(f"{BASE_URL}{path}", json=json)
    r.raise_for_status()
    if r.headers.get("content-type", "").startswith("application/json"):
        return r.json()
    return r.text


async def _delete(client: httpx.AsyncClient, path: str) -> None:
    r = await client.delete(f"{BASE_URL}{path}")
    if r.status_code not in (200, 204, 404):
        r.raise_for_status()


async def ensure_gateway(client: httpx.AsyncClient, gw: Dict[str, Any]) -> Dict[str, Any]:
    existing = await _get(client, "/gateways")
    hit = next((g for g in (existing or []) if g.get("name") == gw["name"]), None)
    if hit:
        return hit

    payload = {"gateway": gw}
    return await _post(client, "/gateways", json=payload)


async def refresh_gateway(client: httpx.AsyncClient, gateway_id: str) -> None:
    # Some Forge versions use POST /gateways/{id}/refresh
    try:
        await _post(client, f"/gateways/{gateway_id}/refresh")
    except Exception:
        return


async def ensure_a2a_agent(client: httpx.AsyncClient, agent: Dict[str, Any]) -> Dict[str, Any]:
    existing = await _get(client, "/a2a")
    hit = next((a for a in (existing or []) if a.get("name") == agent["name"]), None)
    if hit:
        return hit

    payload = {"agent": agent}
    return await _post(client, "/a2a", json=payload)


def _tool_ids_by_prefix(tools: List[Dict[str, Any]], prefixes: List[str]) -> List[str]:
    out: List[str] = []
    for t in tools:
        name = t.get("name") or ""
        if any(name.startswith(p) for p in prefixes):
            tid = t.get("id") or t.get("tool_id")
            if tid:
                out.append(tid)
    return out


async def ensure_virtual_server(client: httpx.AsyncClient, spec: Dict[str, Any], tools: List[Dict[str, Any]]) -> Dict[str, Any]:
    existing = await _get(client, "/servers")
    hit = next((s for s in (existing or []) if s.get("name") == spec["name"]), None)
    if hit:
        return hit

    prefixes = spec.get("include_tool_prefixes") or []
    tool_ids = _tool_ids_by_prefix(tools, prefixes)
    payload = {
        "server": {
            "name": spec["name"],
            "description": spec.get("description", ""),
            "tool_ids": tool_ids,
        }
    }
    return await _post(client, "/servers", json=payload)


async def main() -> int:
    templates_gateways = _load_yaml("gateways.yaml")
    templates_servers = _load_yaml("virtual_servers.yaml")
    templates_agents = _load_yaml("a2a_agents.yaml")

    async with httpx.AsyncClient(auth=AUTH, headers={"Content-Type": "application/json"}, timeout=30.0) as client:
        print(f"Seeding Context Forge at {BASE_URL} ...")

        # Gateways
        gateway_ids: List[str] = []
        for gw in templates_gateways.get("gateways", []):
            created = await ensure_gateway(client, gw)
            gid = created.get("id")
            if gid:
                gateway_ids.append(gid)
            print(f"  gateway: {gw['name']}")

        for gid in gateway_ids:
            await refresh_gateway(client, gid)

        # A2A agents
        for agent in templates_agents.get("agents", []):
            await ensure_a2a_agent(client, agent)
            print(f"  a2a: {agent['name']}")

        # Virtual servers (tool bundles)
        tools = await _get(client, "/tools")
        for server in templates_servers.get("servers", []):
            await ensure_virtual_server(client, server, tools)
            print(f"  virtual server: {server['name']}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
