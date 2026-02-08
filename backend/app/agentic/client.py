"""Thin HTTP client for MCP Context Forge Gateway.

All network access to Context Forge is centralised here so the rest of
the agentic module only deals with Python objects.

Phase 6 additions (additive):
  - register_tool(), register_agent(), register_gateway(), create_server()
  - set_tool_state(), refresh_gateway()
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("homepilot.agentic.client")


class ContextForgeClient:
    """Async client that wraps the MCP Context Forge REST API."""

    def __init__(self, base_url: str, token: str = "", auth_user: str = "admin", auth_pass: str = "changeme"):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.auth_user = auth_user
        self.auth_pass = auth_pass

    # ── helpers ───────────────────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _auth(self) -> Optional[httpx.BasicAuth]:
        if not self.token and self.auth_user:
            return httpx.BasicAuth(self.auth_user, self.auth_pass)
        return None

    # ── health ────────────────────────────────────────────────────────────

    async def ping(self, timeout: float = 1.5) -> bool:
        """Return True if the gateway responds to any health-like endpoint."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=True) as c:
            for path in ("/health", "/docs"):
                try:
                    r = await c.get(f"{self.base_url}{path}", headers=self._headers(), auth=self._auth())
                    if 200 <= r.status_code < 500:
                        return True
                except Exception:
                    continue
        return False

    # ── tools / capabilities (read) ────────────────────────────────────────

    async def list_tools(self, timeout: float = 5.0) -> List[Dict[str, Any]]:
        """Fetch all registered tools from the gateway."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as c:
            try:
                r = await c.get(f"{self.base_url}/tools", headers=self._headers(), auth=self._auth())
                if r.status_code == 200:
                    data = r.json()
                    return data if isinstance(data, list) else data.get("tools", [])
            except Exception as exc:
                logger.warning("list_tools failed: %s", exc)
        return []

    # ── agents (read) ──────────────────────────────────────────────────────

    async def list_agents(self, timeout: float = 5.0) -> List[Dict[str, Any]]:
        """Fetch all registered A2A agents."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as c:
            try:
                r = await c.get(f"{self.base_url}/a2a", headers=self._headers(), auth=self._auth())
                if r.status_code == 200:
                    data = r.json()
                    return data if isinstance(data, list) else data.get("agents", [])
            except Exception as exc:
                logger.warning("list_agents failed: %s", exc)
        return []

    # ── invoke ────────────────────────────────────────────────────────────

    async def invoke_tool(self, tool_id: str, args: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        """Execute a tool by ID via JSON-RPC, then REST fallback."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as c:
            # Try JSON-RPC first
            try:
                body = {"jsonrpc": "2.0", "id": "1", "method": tool_id, "params": args}
                r = await c.post(f"{self.base_url}/rpc", json=body, headers=self._headers(), auth=self._auth())
                if r.status_code == 200:
                    data = r.json()
                    if "error" not in data:
                        return data
            except Exception:
                pass

            # Fallback: REST invoke
            for path in (f"/tools/{tool_id}/invoke", f"/admin/tools/{tool_id}/invoke"):
                try:
                    r = await c.post(
                        f"{self.base_url}{path}",
                        json={"args": args},
                        headers=self._headers(),
                        auth=self._auth(),
                    )
                    if r.status_code == 200:
                        return r.json()
                except Exception:
                    continue

        return {"error": f"Could not invoke tool {tool_id}"}

    # ── registration: tools (write) ──────────────────────────────────────
    # Additive: these methods mirror the Forge REST API for creating resources.
    # Payload shapes match the demo script / Forge OpenAPI schema.

    async def register_tool(self, tool_def: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
        """Register a new tool in Context Forge.

        Args:
            tool_def: Tool definition dict with keys: name, description, inputSchema, etc.
                      Wrapped in {"tool": ...} to match Forge API contract.
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as c:
            try:
                payload = {"tool": tool_def} if "tool" not in tool_def else tool_def
                r = await c.post(
                    f"{self.base_url}/tools",
                    json=payload,
                    headers=self._headers(),
                    auth=self._auth(),
                )
                if r.status_code in (200, 201):
                    return r.json()
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:500]}
            except Exception as exc:
                logger.warning("register_tool failed: %s", exc)
                return {"error": str(exc)}

    async def set_tool_state(self, tool_id: str, activate: bool, timeout: float = 5.0) -> Dict[str, Any]:
        """Enable or disable a tool in Context Forge."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as c:
            try:
                r = await c.post(
                    f"{self.base_url}/tools/{tool_id}/state",
                    params={"activate": str(activate).lower()},
                    headers=self._headers(),
                    auth=self._auth(),
                )
                if r.status_code == 200:
                    return r.json()
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:500]}
            except Exception as exc:
                logger.warning("set_tool_state failed: %s", exc)
                return {"error": str(exc)}

    # ── registration: A2A agents (write) ─────────────────────────────────

    async def register_agent(self, agent_def: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
        """Register a new A2A agent in Context Forge.

        Args:
            agent_def: Agent definition dict with keys: name, description,
                       endpoint_url, agent_type, protocol_version, etc.
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as c:
            try:
                r = await c.post(
                    f"{self.base_url}/a2a",
                    json=agent_def,
                    headers=self._headers(),
                    auth=self._auth(),
                )
                if r.status_code in (200, 201):
                    return r.json()
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:500]}
            except Exception as exc:
                logger.warning("register_agent failed: %s", exc)
                return {"error": str(exc)}

    # ── registration: gateways (write) ───────────────────────────────────

    async def register_gateway(self, gateway_def: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
        """Register a new MCP gateway in Context Forge.

        Args:
            gateway_def: Gateway definition dict with keys: name, url, transport,
                         description, etc. Wrapped in {"gateway": ...} if needed.
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as c:
            try:
                payload = {"gateway": gateway_def} if "gateway" not in gateway_def else gateway_def
                r = await c.post(
                    f"{self.base_url}/gateways",
                    json=payload,
                    headers=self._headers(),
                    auth=self._auth(),
                )
                if r.status_code in (200, 201):
                    return r.json()
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:500]}
            except Exception as exc:
                logger.warning("register_gateway failed: %s", exc)
                return {"error": str(exc)}

    async def refresh_gateway(self, gateway_id: str, timeout: float = 15.0) -> Dict[str, Any]:
        """Trigger tool discovery refresh for a gateway."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as c:
            try:
                r = await c.post(
                    f"{self.base_url}/gateways/{gateway_id}/tools/refresh",
                    headers=self._headers(),
                    auth=self._auth(),
                )
                if r.status_code == 200:
                    return r.json()
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:500]}
            except Exception as exc:
                logger.warning("refresh_gateway failed: %s", exc)
                return {"error": str(exc)}

    # ── registration: virtual servers (write) ─────────────────────────────

    async def create_server(self, server_def: Dict[str, Any], timeout: float = 10.0) -> Dict[str, Any]:
        """Create a new virtual server in Context Forge.

        Args:
            server_def: Server definition dict with keys: name, description,
                        tool_ids (optional), etc.
                        Wrapped in {"server": ...} if needed.
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as c:
            try:
                payload = {"server": server_def} if "server" not in server_def else server_def
                r = await c.post(
                    f"{self.base_url}/servers",
                    json=payload,
                    headers=self._headers(),
                    auth=self._auth(),
                )
                if r.status_code in (200, 201):
                    return r.json()
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:500]}
            except Exception as exc:
                logger.warning("create_server failed: %s", exc)
                return {"error": str(exc)}
