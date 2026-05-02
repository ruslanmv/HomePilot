from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx
try:
    from app.agentic.client import ContextForgeClient  # type: ignore
except Exception:  # pragma: no cover - optional dependency in isolated expert test env
    ContextForgeClient = None  # type: ignore

from .mcp_catalog import ESSENTIAL_MCP_SERVERS, FORGE_TOOL_MAPPING, mcp_key_to_env, mcp_key_to_forge_tool_env


@dataclass
class MCPServerStatus:
    key: str
    priority: str
    configured: bool
    endpoint: str
    forge_tool_id: str


class MCPGateway:
    """Thin HTTP gateway for Expert MCP servers.

    The gateway is intentionally generic and additive so servers can be swapped
    without changing Expert routes/orchestration contracts.
    """

    def __init__(self, timeout_s: float = 15.0, env: Optional[Dict[str, str]] = None) -> None:
        self.timeout_s = timeout_s
        self.env = env or dict(os.environ)
        self.orchestrator = (self.env.get("EXPERT_MCP_ORCHESTRATOR", "context_forge") or "context_forge").strip().lower()
        self.forge_base_url = (self.env.get("CONTEXT_FORGE_URL", "http://localhost:4444") or "").strip().rstrip("/")
        self.forge_auth_user = (self.env.get("CONTEXT_FORGE_AUTH_USER", "admin") or "admin").strip()
        self.forge_auth_pass = (self.env.get("CONTEXT_FORGE_AUTH_PASS", "changeme") or "changeme").strip()
        self.forge_token = (self.env.get("CONTEXT_FORGE_TOKEN", "") or "").strip()
        self._endpoint_map = self._build_endpoint_map()
        self._forge_tool_map = self._build_forge_tool_map()

    def _build_endpoint_map(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for spec in ESSENTIAL_MCP_SERVERS:
            endpoint = (self.env.get(mcp_key_to_env(spec.key), "") or "").strip()
            if endpoint:
                mapping[spec.key] = endpoint.rstrip("/")
        return mapping

    def endpoint_for(self, key: str) -> str:
        return self._endpoint_map.get(key, "")

    def forge_tool_for(self, key: str) -> str:
        return self._forge_tool_map.get(key, "")

    def _build_forge_tool_map(self) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for spec in ESSENTIAL_MCP_SERVERS:
            env_key = mcp_key_to_forge_tool_env(spec.key)
            tool_id = (self.env.get(env_key, "") or "").strip() or FORGE_TOOL_MAPPING.get(spec.key, "")
            if tool_id:
                mapping[spec.key] = tool_id
        return mapping

    def status(self) -> list[MCPServerStatus]:
        status: list[MCPServerStatus] = []
        for spec in ESSENTIAL_MCP_SERVERS:
            endpoint = self.endpoint_for(spec.key)
            status.append(
                MCPServerStatus(
                    key=spec.key,
                    priority=spec.priority,
                    configured=bool(endpoint or self.forge_tool_for(spec.key)),
                    endpoint=endpoint,
                    forge_tool_id=self.forge_tool_for(spec.key),
                )
            )
        return status

    def _forge_client(self) -> ContextForgeClient:
        if ContextForgeClient is None:
            raise RuntimeError("ContextForgeClient is unavailable; ensure backend/app is on PYTHONPATH")
        return ContextForgeClient(
            base_url=self.forge_base_url,
            token=self.forge_token,
            auth_user=self.forge_auth_user,
            auth_pass=self.forge_auth_pass,
        )

    async def _invoke_via_forge(self, server_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.forge_base_url:
            return {
                "ok": False,
                "error": "context_forge_not_configured",
                "server": server_key,
            }
        tool_id = self.forge_tool_for(server_key)
        if not tool_id:
            return {
                "ok": False,
                "error": f"forge_tool_not_configured:{server_key}",
                "server": server_key,
            }
        try:
            client = self._forge_client()
        except Exception as exc:
            return {
                "ok": False,
                "error": str(exc),
                "server": server_key,
                "tool_id": tool_id,
                "orchestrator": "context_forge",
            }

        result = await client.invoke_tool(tool_id=tool_id, args=payload, timeout=self.timeout_s)
        if isinstance(result, dict) and result.get("error"):
            return {
                "ok": False,
                "error": str(result["error"]),
                "server": server_key,
                "tool_id": tool_id,
                "orchestrator": "context_forge",
            }
        return {
            "ok": True,
            "server": server_key,
            "tool_id": tool_id,
            "orchestrator": "context_forge",
            "data": result,
        }

    async def invoke(self, server_key: str, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.orchestrator == "context_forge":
            return await self._invoke_via_forge(server_key=server_key, payload={"method": method, "payload": payload})

        endpoint = self.endpoint_for(server_key)
        if not endpoint:
            return {
                "ok": False,
                "error": f"server_not_configured:{server_key}",
                "server": server_key,
                "method": method,
            }

        url = f"{endpoint.rstrip('/')}/{method.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json() if resp.text else {}
            return {"ok": True, "server": server_key, "method": method, "data": data, "orchestrator": "direct"}
        except Exception as exc:
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "server": server_key,
                "method": method,
                "url": url,
                "orchestrator": "direct",
            }

    # P0 typed wrappers (preprod essentials)
    async def web_search_search(self, query: str, top_k: int = 5, recency_days: int = 7) -> Dict[str, Any]:
        return await self.invoke(
            "mcp-web-search",
            "search",
            {"query": query, "top_k": top_k, "recency_days": recency_days},
        )

    async def doc_retrieval_query(self, text: str, top_k: int = 5, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return await self.invoke(
            "mcp-doc-retrieval",
            "query",
            {"text": text, "top_k": top_k, "filters": filters or {}},
        )

    async def code_sandbox_run(self, language: str, code: str, timeout_s: int = 15, memory_mb: int = 256) -> Dict[str, Any]:
        return await self.invoke(
            "mcp-code-sandbox",
            "run",
            {"language": language, "code": code, "timeout_s": timeout_s, "memory_mb": memory_mb},
        )

    async def citation_verify(self, response_text: str) -> Dict[str, Any]:
        return await self.invoke(
            "mcp-citation-provenance",
            "verify_citations",
            {"response_text": response_text},
        )

    async def memory_append(self, session_id: str, role: str, content: str) -> Dict[str, Any]:
        return await self.invoke(
            "mcp-memory-store",
            "append",
            {"session_id": session_id, "role": role, "content": content},
        )
