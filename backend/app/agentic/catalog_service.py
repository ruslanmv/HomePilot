"""High-level catalog builder for the wizard.

Uses ContextForgeClient (tools/agents) + ForgeHttp (servers/gateways)
to produce an AgenticCatalog, cached with TTLCache.

Additive: does not modify any existing module.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .catalog_types import (
    AgenticCatalog,
    CatalogA2AAgent,
    CatalogGateway,
    CatalogServer,
    CatalogTool,
    ForgeStatus,
)
from .client import ContextForgeClient
from .forge_http import ForgeHttp
from .ttl_cache import TTLCache

logger = logging.getLogger("homepilot.agentic.catalog_service")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_list(payload: Any) -> List[Dict[str, Any]]:
    """Normalize varied API response shapes into a flat list of dicts."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for k in ("items", "servers", "gateways", "data"):
            v = payload.get(k)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def capability_sources_from_tools(tools: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Heuristic mapping: capability_id -> tool_ids."""
    patterns = [
        ("web_search", ["search", "web", "google", "bing"]),
        ("analyze_documents", ["document", "pdf", "extract", "summar", "embed", "rag"]),
        ("automate_external", ["notify", "slack", "jira", "ticket", "email", "calendar"]),
        ("code_analysis", ["code", "python_sandbox", "sandbox"]),
        ("data_analysis", ["csv", "pandas", "plotly", "data"]),
        ("generate_images", ["imagine", "image", "sdxl", "flux", "dall", "stable_diffusion"]),
        ("generate_videos", ["video", "animate", "svd", "wan", "seedream"]),
    ]
    out: Dict[str, List[str]] = {}

    for t in tools:
        tid = str(t.get("id") or "")
        name = str(t.get("name") or "").lower()
        if not tid or not name:
            continue
        for cap, keys in patterns:
            if any(k in name for k in keys):
                out.setdefault(cap, [])
                if tid not in out[cap]:
                    out[cap].append(tid)
    return out


class AgenticCatalogService:
    """Build and cache the full wizard catalog from Context Forge."""

    def __init__(
        self,
        forge_base_url: str,
        auth_user: str,
        auth_pass: str,
        bearer_token: Optional[str] = None,
        ttl_seconds: float = 15.0,
    ):
        self.forge_base_url = forge_base_url.rstrip("/")
        self.http = ForgeHttp(
            base_url=self.forge_base_url,
            auth_user=auth_user,
            auth_pass=auth_pass,
            bearer_token=bearer_token,
        )
        self.cache: TTLCache[AgenticCatalog] = TTLCache(ttl_seconds=ttl_seconds)

    async def build(self, client: ContextForgeClient) -> AgenticCatalog:
        ok, err = await self.http.health()

        # Tools from existing client
        try:
            tools_raw = [x for x in await client.list_tools() if isinstance(x, dict)]
        except Exception:
            tools_raw = []

        # Agents from existing client
        try:
            agents_raw = [x for x in await client.list_agents() if isinstance(x, dict)]
        except Exception:
            agents_raw = []

        # Normalize tools
        tools: List[CatalogTool] = []
        for t in tools_raw:
            tid = str(t.get("id") or "")
            name = str(t.get("name") or "")
            if not tid or not name:
                continue
            tools.append(
                CatalogTool(
                    id=tid,
                    name=name,
                    description=str(t.get("description") or ""),
                    enabled=t.get("enabled"),
                    raw=t,
                )
            )

        # Normalize A2A agents
        a2a_agents: List[CatalogA2AAgent] = []
        for a in agents_raw:
            aid = str(a.get("id") or "")
            name = str(a.get("name") or "")
            if not aid or not name:
                continue
            a2a_agents.append(
                CatalogA2AAgent(
                    id=aid,
                    name=name,
                    description=str(a.get("description") or ""),
                    enabled=a.get("enabled"),
                    endpoint_url=a.get("endpoint_url") or a.get("endpoint") or None,
                    raw=a,
                )
            )

        # Servers (virtual servers via best-effort HTTP)
        servers_payload = await self.http.list_servers_best_effort()
        servers: List[CatalogServer] = []
        for s in _as_list(servers_payload):
            sid = str(s.get("id") or "")
            name = str(s.get("name") or "")
            if not sid or not name:
                continue
            tool_ids = s.get("tool_ids") or s.get("associated_tools") or s.get("tools") or []
            if not isinstance(tool_ids, list):
                tool_ids = []
            servers.append(
                CatalogServer(
                    id=sid,
                    name=name,
                    description=str(s.get("description") or ""),
                    enabled=s.get("enabled"),
                    tool_ids=[str(x) for x in tool_ids if x is not None],
                    sse_url=f"{self.forge_base_url}/servers/{sid}/sse",
                    raw=s,
                )
            )

        # Gateways (optional, best-effort)
        gateways_payload = await self.http.list_gateways_best_effort()
        gateways: List[CatalogGateway] = []
        for g in _as_list(gateways_payload):
            gid = str(g.get("id") or "")
            name = str(g.get("name") or "")
            if not gid or not name:
                continue
            gateways.append(
                CatalogGateway(
                    id=gid,
                    name=name,
                    enabled=g.get("enabled"),
                    url=g.get("url") or g.get("endpoint_url") or None,
                    transport=g.get("transport") or None,
                    raw=g,
                )
            )

        catalog = AgenticCatalog(
            source="forge",
            last_updated=_now_iso(),
            forge=ForgeStatus(base_url=self.forge_base_url, healthy=bool(ok), error=err),
            servers=servers,
            tools=tools,
            a2a_agents=a2a_agents,
            gateways=gateways,
            capability_sources=capability_sources_from_tools(tools_raw),
        )
        return catalog

    async def get_cached(self, client: ContextForgeClient) -> AgenticCatalog:
        cached = self.cache.get()
        if cached is not None:
            return cached
        built = await self.build(client)
        return self.cache.set(built)

    def invalidate(self) -> None:
        self.cache.invalidate()
