#!/usr/bin/env python3
"""
List MCP Context Forge inventory:
- Gateways (registered remote MCP servers)
- Virtual Servers (/servers, "ready-to-use" MCP endpoints)
- Tools (/tools)
- A2A Agents (/a2a)

Supports Basic Auth, Bearer token, and auto-login via /auth/login (JWT).

Usage as standalone script:
  export MCPF_BASE_URL="http://localhost:4444"
  export MCPF_BASIC_USER="admin"
  export MCPF_BASIC_PASS="changeme"
  python -m app.agentic.list_forge_inventory

  # OR with bearer token directly
  export MCPF_BEARER_TOKEN="YOUR_TOKEN"
  python -m app.agentic.list_forge_inventory

Usage as importable helper (for future HomePilot integration):
  from app.agentic.list_forge_inventory import ForgeInventory
  inv = ForgeInventory()
  result = inv.fetch_all()
  print(result)  # dict with gateways, servers, tools, agents
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.auth import HTTPBasicAuth


# ---------------------------------------------------------------------------
#  Configuration helpers
# ---------------------------------------------------------------------------

def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    return v if v not in (None, "") else default


# ---------------------------------------------------------------------------
#  ForgeInventory — the reusable helper class
# ---------------------------------------------------------------------------

class ForgeInventory:
    """Query MCP Context Forge and return structured inventory data.

    This class is designed to be imported into the HomePilot agentic backend
    so that any route or service can display the current Forge state.

    Auth modes (tried in order):
      1. MCPF_BEARER_TOKEN — use directly as Bearer header
      2. MCPF_BASIC_USER + MCPF_BASIC_PASS — first attempts JWT login
         via POST /auth/login, then falls back to HTTP Basic Auth
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        basic_user: Optional[str] = None,
        basic_pass: Optional[str] = None,
        bearer_token: Optional[str] = None,
        timeout: float = 10.0,
        verify_ssl: bool = True,
    ):
        self.base_url = (base_url or _env("MCPF_BASE_URL") or "http://localhost:4444").rstrip("/")
        self.bearer_token = bearer_token or _env("MCPF_BEARER_TOKEN")
        self.basic_user = basic_user or _env("MCPF_BASIC_USER")
        self.basic_pass = basic_pass or _env("MCPF_BASIC_PASS")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self._jwt_attempted = False

        # Build session
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._session.verify = self.verify_ssl

        if self.bearer_token:
            self._session.headers["Authorization"] = f"Bearer {self.bearer_token}"
            self.auth_mode = "bearer"
        elif self.basic_user and self.basic_pass:
            # Start with basic auth as fallback; JWT login attempted lazily
            self._session.auth = HTTPBasicAuth(self.basic_user, self.basic_pass)
            self.auth_mode = "basic"
        else:
            self.auth_mode = "none"

    # -- JWT auto-login -----------------------------------------------------

    def _login_and_set_bearer(self) -> None:
        """Attempt to acquire a JWT token via POST /auth/login.

        HomePilot's Context Forge requires Bearer JWT for API endpoints.
        This method derives an email from BASIC_AUTH_USER (appending
        @example.com if needed) and calls /auth/login to obtain a token.
        Once acquired, all subsequent requests use the Bearer token.
        """
        if self._jwt_attempted:
            return
        self._jwt_attempted = True

        if "Authorization" in self._session.headers:
            return  # already have a bearer token

        user = self.basic_user
        pwd = self.basic_pass
        if not (user and pwd):
            return

        email = user if "@" in user else f"{user}@example.com"
        url = f"{self.base_url}/auth/login"
        try:
            r = self._session.post(
                url,
                json={"email": email, "password": pwd},
                timeout=self.timeout,
            )
            if r.status_code == 200:
                token = r.json().get("access_token")
                if token:
                    self._session.headers["Authorization"] = f"Bearer {token}"
                    self._session.auth = None  # drop basic auth
                    self.auth_mode = "jwt"
                    return
        except Exception:
            pass
        # JWT login failed — keep basic auth as fallback

    # -- low-level helpers --------------------------------------------------

    def _get_json(self, path: str, params: Optional[Dict[str, str]] = None) -> Any:
        self._login_and_set_bearer()
        url = f"{self.base_url}{path}"
        r = self._session.get(url, timeout=self.timeout, params=params)
        r.raise_for_status()
        if not r.content:
            return None
        return r.json()

    @staticmethod
    def _safe_list(payload: Any) -> List[Dict[str, Any]]:
        """Normalize varied API response shapes into a flat list of dicts."""
        if payload is None:
            return []
        if isinstance(payload, list):
            return [x for x in payload if isinstance(x, dict)]
        if isinstance(payload, dict):
            for k in ("items", "data", "servers", "tools", "gateways",
                       "agents", "a2a_agents", "results"):
                v = payload.get(k)
                if isinstance(v, list):
                    return [x for x in v if isinstance(x, dict)]
            return [payload]
        return []

    @staticmethod
    def _pick(item: Dict[str, Any], *keys: str, default: Any = None) -> Any:
        for k in keys:
            if k in item:
                return item[k]
        return default

    # -- health check -------------------------------------------------------

    def health(self) -> Tuple[bool, Optional[str]]:
        """Return (healthy, error_message)."""
        try:
            self._get_json("/health")
            return True, None
        except Exception as exc:
            return False, str(exc)

    # -- fetchers -----------------------------------------------------------

    def fetch_gateways(self, include_inactive: bool = True) -> List[Dict[str, Any]]:
        params = {"include_inactive": "true"} if include_inactive else {}
        try:
            return self._safe_list(self._get_json("/gateways", params=params))
        except Exception:
            return []

    def fetch_servers(self, include_inactive: bool = True) -> List[Dict[str, Any]]:
        params = {"include_inactive": "true"} if include_inactive else {}
        try:
            return self._safe_list(self._get_json("/servers", params=params))
        except Exception:
            return []

    def fetch_tools(self, include_inactive: bool = True) -> List[Dict[str, Any]]:
        params = {"include_inactive": "true"} if include_inactive else {}
        try:
            return self._safe_list(self._get_json("/tools", params=params))
        except Exception:
            return []

    def fetch_agents(self, include_inactive: bool = True) -> List[Dict[str, Any]]:
        params = {"include_inactive": "true"} if include_inactive else {}
        try:
            return self._safe_list(self._get_json("/a2a", params=params))
        except Exception:
            return []

    def fetch_all(self, include_inactive: bool = True) -> Dict[str, Any]:
        """Fetch all four inventories in one call. Returns a dict."""
        ok, err = self.health()
        return {
            "base_url": self.base_url,
            "auth_mode": self.auth_mode,
            "healthy": ok,
            "error": err,
            "gateways": self.fetch_gateways(include_inactive),
            "servers": self.fetch_servers(include_inactive),
            "tools": self.fetch_tools(include_inactive),
            "agents": self.fetch_agents(include_inactive),
        }

    # -- formatted printing -------------------------------------------------

    def print_gateways(self, gateways: List[Dict[str, Any]]) -> None:
        _print_section(f"Gateways (registered remote MCP servers): {len(gateways)}")
        if not gateways:
            print("  (none registered)")
            return
        for g in gateways:
            gid = self._pick(g, "id", "gateway_id", "uuid", default="(no id)")
            name = self._pick(g, "name", default="(no name)")
            url = self._pick(g, "url", "endpoint", "endpoint_url", default="(no url)")
            active = self._pick(g, "is_active", "active", "enabled", default=None)
            status = self._pick(g, "status", "health", default=None)
            print(f"  - {name}  [id={gid}]")
            print(f"    url: {url}")
            if active is not None:
                print(f"    active/enabled: {active}")
            if status is not None:
                print(f"    status/health: {status}")

    def print_servers(self, servers: List[Dict[str, Any]]) -> None:
        _print_section(f"Virtual Servers (/servers): {len(servers)}")
        if not servers:
            print("  (none registered)")
            return
        for sv in servers:
            sid = self._pick(sv, "id", "server_id", "uuid", default="(no id)")
            name = self._pick(sv, "name", default="(no name)")
            desc = self._pick(sv, "description", default="")
            active = self._pick(sv, "is_active", "active", "enabled", default=None)
            sse_endpoint = f"{self.base_url}/servers/{sid}/sse" if sid != "(no id)" else None
            print(f"  - {name}  [id={sid}]")
            if desc:
                print(f"    desc: {desc}")
            if active is not None:
                print(f"    active/enabled: {active}")
            if sse_endpoint:
                print(f"    connect (SSE): {sse_endpoint}")
            tool_ids = self._pick(sv, "tool_ids", "associated_tools", "tools", default=None)
            if isinstance(tool_ids, list) and tool_ids:
                print(f"    tools linked: {len(tool_ids)}")

    def print_tools(self, tools: List[Dict[str, Any]]) -> None:
        _print_section(f"Tools (/tools): {len(tools)}")
        if not tools:
            print("  (none registered)")
            return
        for t in tools:
            tid = self._pick(t, "id", "tool_id", "uuid", default="(no id)")
            name = self._pick(t, "name", default="(no name)")
            desc = self._pick(t, "description", default="")
            active = self._pick(t, "is_active", "active", "enabled", default=None)
            print(f"  - {name}  [id={tid}]")
            if desc:
                print(f"    desc: {desc}")
            if active is not None:
                print(f"    active/enabled: {active}")

    def print_agents(self, agents: List[Dict[str, Any]]) -> None:
        _print_section(f"A2A Agents (/a2a): {len(agents)}")
        if not agents:
            print("  (none registered)")
            return
        for a in agents:
            aid = self._pick(a, "id", "agent_id", "uuid", default="(no id)")
            name = self._pick(a, "name", default="(no name)")
            endpoint = self._pick(a, "endpoint_url", "url", "endpoint", default="(no endpoint)")
            agent_type = self._pick(a, "agent_type", "type", default=None)
            active = self._pick(a, "is_active", "active", "enabled", default=None)
            print(f"  - {name}  [id={aid}]")
            print(f"    endpoint: {endpoint}")
            if agent_type is not None:
                print(f"    type: {agent_type}")
            if active is not None:
                print(f"    active/enabled: {active}")

    def print_all(self) -> int:
        """Fetch everything and print a formatted report. Returns 0 on success."""
        print(f"Base URL:  {self.base_url}")

        data = self.fetch_all()
        print(f"Auth mode: {data['auth_mode']}")

        if not data["healthy"]:
            print(f"\n[ERROR] Forge not healthy: {data['error']}")
            print("  Is MCP Context Forge running? Start with: make start-mcp")
            return 1

        self.print_gateways(data["gateways"])
        self.print_servers(data["servers"])
        self.print_tools(data["tools"])
        self.print_agents(data["agents"])

        total = (
            len(data["gateways"])
            + len(data["servers"])
            + len(data["tools"])
            + len(data["agents"])
        )
        print(f"\nTotal items: {total}")
        print("Done.")
        return 0


# ---------------------------------------------------------------------------
#  Standalone formatting helpers
# ---------------------------------------------------------------------------

def _print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    inv = ForgeInventory()
    return inv.print_all()


if __name__ == "__main__":
    raise SystemExit(main())
