"""Thin HTTP client for MCP Context Forge Gateway.

All network access to Context Forge is centralised here so the rest of
the agentic module only deals with Python objects.
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

    # ── tools / capabilities ──────────────────────────────────────────────

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

    # ── agents ────────────────────────────────────────────────────────────

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
