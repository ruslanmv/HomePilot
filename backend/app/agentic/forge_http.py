"""Best-effort HTTP wrapper for Context Forge endpoints.

This is additive and does NOT replace the existing ContextForgeClient.
It covers endpoints like /servers and /gateways that the thin client
doesn't handle, and tries multiple path patterns for cross-deployment
compatibility.

Phase 8 fix: auto-acquire JWT token when basic auth is rejected.
Phase 9 addition: registry proxy methods for MCP catalog browsing.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import httpx

from .client import forge_jwt_login

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
        self._jwt_attempted_at: float = 0.0

    async def _ensure_token(self) -> None:
        """Auto-acquire JWT if no bearer token is set.

        Retries every 60 seconds so that a slow Forge startup doesn't
        permanently lock out JWT acquisition.
        """
        if self.bearer_token:
            return
        import time
        now = time.monotonic()
        if now - self._jwt_attempted_at < 60.0:
            return
        self._jwt_attempted_at = now
        email = self.auth_user if "@" in self.auth_user else f"{self.auth_user}@example.com"
        jwt = await forge_jwt_login(
            self.base_url,
            email=email,
            password=self.auth_pass,
        )
        if jwt:
            self.bearer_token = jwt
            logger.debug("ForgeHttp: auto-acquired JWT for %s", email)

    def _auth_headers_and_auth(self) -> Tuple[Dict[str, str], Optional[httpx.BasicAuth]]:
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        auth: Optional[httpx.BasicAuth] = None
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        else:
            auth = httpx.BasicAuth(self.auth_user, self.auth_pass)
        return headers, auth

    async def get_json(self, path: str) -> Any:
        await self._ensure_token()
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

    async def post_json(self, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        """Best-effort POST with JSON body."""
        await self._ensure_token()
        url = f"{self.base_url}{path}"
        headers, auth = self._auth_headers_and_auth()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(max(self.timeout_seconds, 15.0)),
                follow_redirects=True,
            ) as c:
                r = await c.post(url, headers=headers, auth=auth, json=body or {})
                try:
                    return {"_status": r.status_code, **(r.json())}
                except Exception:
                    return {"_status": r.status_code}
        except Exception as exc:
            logger.debug("forge_http POST %s failed: %s", path, exc)
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

    async def list_server_tools(self, server_id: str) -> Any:
        """Fetch full tool objects for a virtual server via Forge's
        GET /servers/{id}/tools endpoint (joins through server_tool_association).
        Returns a list of ToolRead dicts or None on failure."""
        data = await self.get_json(f"/servers/{server_id}/tools")
        if data is None:
            data = await self.get_json(f"/admin/servers/{server_id}/tools")
        return data

    # ── Registry proxy methods (Phase 9) ─────────────────────────────────

    async def registry_list_servers(
        self,
        category: Optional[str] = None,
        auth_type: Optional[str] = None,
        provider: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Any:
        """Proxy GET /admin/mcp-registry/servers with optional filters."""
        params = []
        if category:
            params.append(f"category={category}")
        if auth_type:
            params.append(f"auth_type={auth_type}")
        if provider:
            params.append(f"provider={provider}")
        if search:
            params.append(f"search={search}")
        params.append(f"limit={limit}")
        params.append(f"offset={offset}")
        params.append("show_available_only=false")
        qs = "&".join(params)
        return await self.get_json(f"/admin/mcp-registry/servers?{qs}")

    async def registry_register_server(
        self,
        server_id: str,
        api_key: Optional[str] = None,
        name: Optional[str] = None,
    ) -> Any:
        """Proxy POST /admin/mcp-registry/{server_id}/register."""
        body: Dict[str, Any] = {"server_id": server_id}
        if api_key:
            body["api_key"] = api_key
        if name:
            body["name"] = name
        return await self.post_json(f"/admin/mcp-registry/{server_id}/register", body)
