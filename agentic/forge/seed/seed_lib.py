from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml


Json = Dict[str, Any]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip() or default


class ForgeSeeder:
    def __init__(self) -> None:
        self.base_url = _env("MCPGATEWAY_URL", "http://localhost:4444").rstrip("/")
        self.auth_user = _env("BASIC_AUTH_USER", "admin")
        self.auth_pass = _env("BASIC_AUTH_PASSWORD", "changeme")

    async def _request(self, method: str, path: str, json: Optional[Json] = None) -> Json:
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers={"Content-Type": "application/json"},
                auth=(self.auth_user, self.auth_pass),
            )
            if r.headers.get("content-type", "").startswith("application/json"):
                return r.json()
            return {"status_code": r.status_code, "text": r.text}

    async def list_tools(self) -> List[Json]:
        data = await self._request("GET", "/tools")
        return data if isinstance(data, list) else (data.get("tools") or [])

    async def list_gateways(self) -> List[Json]:
        data = await self._request("GET", "/gateways")
        return data if isinstance(data, list) else (data.get("gateways") or [])

    async def list_servers(self) -> List[Json]:
        data = await self._request("GET", "/servers")
        return data if isinstance(data, list) else (data.get("servers") or [])

    async def list_a2a(self) -> List[Json]:
        data = await self._request("GET", "/a2a")
        return data if isinstance(data, list) else (data.get("agents") or [])

    async def ensure_gateway(self, name: str, url: str, transport: str, description: str = "") -> Json:
        existing = await self.list_gateways()
        for g in existing:
            if g.get("name") == name:
                return g
        return await self._request(
            "POST",
            "/gateways",
            json={"gateway": {"name": name, "url": url, "transport": transport, "description": description}},
        )

    async def refresh_gateway(self, gateway_id: str) -> Json:
        return await self._request("POST", f"/gateways/{gateway_id}/refresh")

    async def ensure_a2a_agent(self, name: str, agent_type: str, endpoint_url: str, description: str = "") -> Json:
        existing = await self.list_a2a()
        for a in existing:
            if a.get("name") == name:
                return a
        return await self._request(
            "POST",
            "/a2a",
            json={"agent": {"name": name, "agent_type": agent_type, "endpoint_url": endpoint_url, "description": description}},
        )

    async def ensure_server(self, name: str, description: str, tool_ids: List[str]) -> Json:
        existing = await self.list_servers()
        for s in existing:
            if s.get("name") == name:
                return s
        return await self._request(
            "POST",
            "/servers",
            json={"server": {"name": name, "description": description, "tool_ids": tool_ids}},
        )


def read_yaml(path: Path) -> Json:
    return yaml.safe_load(path.read_text(encoding="utf-8"))
