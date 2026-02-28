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
                if r.status_code == 401:
                    # Token may be expired — force refresh and retry once
                    logger.info("forge_http GET %s → 401, refreshing JWT", path)
                    self.bearer_token = None
                    self._jwt_attempted_at = 0.0
                    await self._ensure_token()
                    headers, auth = self._auth_headers_and_auth()
                    r = await c.get(url, headers=headers, auth=auth)
                if r.status_code != 200:
                    logger.warning("forge_http GET %s → %d", path, r.status_code)
                    return None
                try:
                    return r.json()
                except Exception:
                    logger.warning("forge_http GET %s → 200 but non-JSON body", path)
                    return None
        except Exception as exc:
            logger.warning("forge_http GET %s failed: %s", path, exc)
            return None

    async def post_json(self, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        """Best-effort POST with JSON body.

        Does NOT follow redirects — Forge admin endpoints return 303
        redirects to HTML pages on success (e.g., gateway delete).
        We treat 2xx and 3xx as success.
        """
        await self._ensure_token()
        url = f"{self.base_url}{path}"
        headers, auth = self._auth_headers_and_auth()
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(max(self.timeout_seconds, 15.0)),
                follow_redirects=False,
            ) as c:
                r = await c.post(url, headers=headers, auth=auth, json=body or {})
                if r.status_code == 401:
                    # Token may be expired — force refresh and retry once
                    logger.info("forge_http POST %s → 401, refreshing JWT", path)
                    self.bearer_token = None
                    self._jwt_attempted_at = 0.0
                    await self._ensure_token()
                    headers, auth = self._auth_headers_and_auth()
                    r = await c.post(url, headers=headers, auth=auth, json=body or {})
                try:
                    return {"_status": r.status_code, **(r.json())}
                except Exception:
                    return {"_status": r.status_code}
        except Exception as exc:
            logger.warning("forge_http POST %s failed: %s", path, exc)
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
        """List all gateways.

        Forge's GET /admin/gateways returns PaginatedResponse: {data: [...], pagination: {...}}.
        We request a large per_page and include_inactive to get everything.
        """
        data = await self.get_json("/admin/gateways?per_page=500&include_inactive=true")
        if data is None:
            data = await self.get_json("/gateways?per_page=500&include_inactive=true")
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

    async def search_gateways(self, query: str, include_inactive: bool = True) -> Any:
        """Search gateways by name/description via /admin/gateways/search.

        Returns {gateways: [{id, name, url, description}], count: N} on success.
        """
        from urllib.parse import quote
        qs = f"q={quote(query)}&include_inactive={'true' if include_inactive else 'false'}&limit=50"
        return await self.get_json(f"/admin/gateways/search?{qs}")

    async def get_gateway_by_id(self, gateway_id: str) -> Any:
        """Fetch a single gateway by ID via /admin/gateways/{id}."""
        return await self.get_json(f"/admin/gateways/{gateway_id}")

    async def delete_gateway(self, gateway_id: str) -> Any:
        """Delete a gateway via POST /admin/gateways/{id}/delete (standard Forge API).

        The Forge admin delete endpoint returns a 303 redirect to the admin HTML page.
        We treat 2xx and 3xx as success.
        """
        result = await self.post_json(f"/admin/gateways/{gateway_id}/delete", {})
        if result is None:
            return None
        status = result.get("_status", 0)
        # 303 (See Other) is the expected success response from Forge gateway delete
        if status in (200, 201, 204, 303):
            result["_status"] = 200  # Normalize to 200 for callers
        return result
