"""Best-effort HTTP wrapper for Context Forge endpoints.

This is additive and does NOT replace the existing ContextForgeClient.
It covers endpoints like /servers and /gateways that the thin client
doesn't handle, and tries multiple path patterns for cross-deployment
compatibility.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger("homepilot.agentic.forge_http")


class ForgeHttp:
    """Low-level HTTP wrapper with best-effort path fallbacks."""

    def __init__(
        self,
        base_url: str,
        auth_user: str,
        auth_pass: str,
        bearer_token: Optional[str] = None,
        timeout_seconds: float = 6.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth_user = auth_user
        self.auth_pass = auth_pass
        self.bearer_token = bearer_token
        self.timeout_seconds = float(timeout_seconds)

    def _auth_headers_and_auth(self) -> Tuple[Dict[str, str], Optional[httpx.BasicAuth]]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        auth: Optional[httpx.BasicAuth] = None
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        else:
            auth = httpx.BasicAuth(self.auth_user, self.auth_pass)
        return headers, auth

    async def get_json(self, path: str) -> Any:
        url = f"{self.base_url}{path}"
        headers, auth = self._auth_headers_and_auth()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=True,
            ) as c:
                r = await c.get(url, headers=headers, auth=auth)
                if r.status_code != 200:
                    return None
                try:
                    return r.json()
                except Exception:
                    return None
        except Exception as exc:
            logger.debug("forge_http GET %s failed: %s", path, exc)
            return None

    async def health(self) -> Tuple[bool, Optional[str]]:
        data = await self.get_json("/health")
        if data is None:
            return False, "Forge /health not reachable"
        return True, None

    async def list_servers_best_effort(self) -> Any:
        data = await self.get_json("/servers")
        if data is None:
            data = await self.get_json("/admin/servers")
        return data

    async def list_gateways_best_effort(self) -> Any:
        data = await self.get_json("/gateways")
        if data is None:
            data = await self.get_json("/admin/gateways")
        return data
