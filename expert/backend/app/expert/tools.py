"""Per-turn tools for the Expert pipelines — the other half of a ChatGPT-style turn.

HomePilot's own MCP servers (web search, knowledge, personal notes) speak JSON-RPC
``tools/list`` / ``tools/call`` on ``/rpc``. The registry discovers a curated set of their
tools, offers them to the model in OpenAI's function-calling shape, runs the calls the model
makes, and turns each result into text the model can read plus sources the UI can show.
Context Forge's ``/rpc`` speaks the same protocol, so federated tools work by adding its URL
to ``EXPERT_TOOL_SERVERS`` (its REST-registered copies of HomePilot's servers do not forward
``tools/call``, which is why the servers are called directly by default).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import urlparse

import httpx

from .config import (
    EXPERT_TOOLS_ENABLED,
    EXPERT_TOOL_ALLOWLIST,
    EXPERT_TOOL_SERVERS,
    EXPERT_TOOL_TIMEOUT_S,
)

logger = logging.getLogger("expert.tools")

_DISCOVERY_TTL_S = 60.0

# Appended to the system prompt whenever tools are offered.
TOOLS_NOTE = (
    "You can call tools. Use them when the answer depends on current events, specific facts, "
    "URLs, or the user's own documents and notes; answer directly when you already know. "
    "After a web search, cite the results you used as [n], with the numbers given in the results."
)


@dataclass(frozen=True)
class ToolSpec:
    name: str                 # what the model sees (OpenAI-safe: letters, digits, _ and -)
    native: str               # what the server knows
    description: str
    parameters: Dict[str, Any]
    server: str               # the /rpc URL

    def as_openai(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": (self.description or self.native)[:1024],
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }


@dataclass
class ToolOutcome:
    name: str
    ok: bool
    text: str = ""
    data: Any = None
    sources: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    elapsed_ms: int = 0


def sanitize_name(native: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", native)[:64] or "tool"


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:  # noqa: BLE001
        return ""


def label_for(native: str, arguments: Dict[str, Any]) -> str:
    """What the chip says while a tool runs."""
    q = str(arguments.get("query") or arguments.get("question") or "").strip()
    quoted = f" for “{q[:80]}”" if q else ""
    n = native.lower()
    if "web" in n and "search" in n:
        return f"Searching the web{quoted}"
    if "fetch" in n:
        return f"Reading {_domain(str(arguments.get('url') or '')) or 'a page'}"
    if "project" in n:
        return f"Searching the project's documents{quoted}"
    if "document" in n and not q:
        return f"Opening document {arguments.get('doc_id', '')}".strip()
    if "workspace" in n or "document" in n or "sources" in n:
        return f"Searching your workspace{quoted}"
    if "personal" in n or "memory" in n or "notes" in n:
        return f"Searching your notes{quoted}"
    return f"Running {native}"


async def rpc(url: str, method: str, params: Optional[Dict[str, Any]], timeout_s: float) -> Any:
    """One JSON-RPC 2.0 call; the result, or RuntimeError with the server's message."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_s, connect=5.0)) as client:
        r = await client.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
        r.raise_for_status()
        body = r.json()
    if isinstance(body, dict) and body.get("error"):
        err = body["error"]
        raise RuntimeError(str(err.get("message") if isinstance(err, dict) else err))
    return body.get("result") if isinstance(body, dict) else body


def _sources(data: Any) -> List[Dict[str, Any]]:
    """Web-like results in a tool's structured content → source entries (url, title, snippet)."""
    items = None
    if isinstance(data, dict):
        for key in ("results", "sources", "items", "hits"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
    out: List[Dict[str, Any]] = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or it.get("link") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        entry: Dict[str, Any] = {
            "title": str(it.get("title") or url)[:200],
            "url": url,
            "domain": _domain(url),
            "snippet": str(it.get("snippet") or it.get("content") or "")[:300],
        }
        if it.get("published"):
            entry["published"] = str(it["published"])
        out.append(entry)
    return out


def outcome_from(name: str, result: Any, elapsed_ms: int = 0) -> ToolOutcome:
    """An MCP ``tools/call`` result → text for the model, data and sources for the UI."""
    result = result if isinstance(result, dict) else {"content": [{"type": "text", "text": str(result)}]}
    content = result.get("content") or []
    text = "\n".join(
        str(c.get("text") or "") for c in content if isinstance(c, dict) and c.get("type", "text") == "text"
    ).strip()
    data = result.get("structuredContent")
    if not text and data is not None:
        text = json.dumps(data, ensure_ascii=False)
    is_error = bool(result.get("isError"))
    return ToolOutcome(
        name=name, ok=not is_error, text=text, data=data, sources=_sources(data),
        error=text if is_error else "", elapsed_ms=elapsed_ms,
    )


class ToolRegistry:
    """The curated tools: discovered from the servers, cached briefly, called by name."""

    def __init__(
        self,
        servers: Optional[List[str]] = None,
        allow: Optional[str] = None,
        timeout_s: Optional[float] = None,
    ) -> None:
        raw_servers = servers if servers is not None else EXPERT_TOOL_SERVERS.split(",")
        self.servers = [s.strip().rstrip("/") for s in raw_servers if s and s.strip()]
        allow_raw = EXPERT_TOOL_ALLOWLIST if allow is None else allow
        self.allow = {a.strip() for a in allow_raw.split(",") if a.strip()}
        self.timeout_s = float(timeout_s or EXPERT_TOOL_TIMEOUT_S)
        self._specs: Dict[str, ToolSpec] = {}
        self._discovered_at = 0.0
        self._lock = asyncio.Lock()

    def _allowed(self, native: str) -> bool:
        return "*" in self.allow or native in self.allow

    def _fresh(self) -> bool:
        return bool(self._specs) and (time.monotonic() - self._discovered_at) < _DISCOVERY_TTL_S

    async def _list(self, url: str) -> List[Dict[str, Any]]:
        result = await rpc(url, "tools/list", {}, min(self.timeout_s, 8.0))
        return list((result or {}).get("tools") or []) if isinstance(result, dict) else []

    async def discover(self, force: bool = False) -> List[ToolSpec]:
        if not force and self._fresh():
            return list(self._specs.values())
        async with self._lock:
            if not force and self._fresh():
                return list(self._specs.values())
            specs: Dict[str, ToolSpec] = {}
            listed = await asyncio.gather(*(self._list(url) for url in self.servers), return_exceptions=True)
            for url, tools in zip(self.servers, listed):
                if isinstance(tools, BaseException):
                    logger.debug("tools: %s not listed (%s)", url, tools)
                    continue
                for t in tools:
                    native = str(t.get("name") or "")
                    if not native or not self._allowed(native):
                        continue
                    name = sanitize_name(native)
                    if name in specs:
                        continue
                    specs[name] = ToolSpec(
                        name=name, native=native,
                        description=str(t.get("description") or native),
                        parameters=t.get("inputSchema") or {"type": "object", "properties": {}},
                        server=url,
                    )
            # A server that is down keeps its last known tools for the TTL rather than vanishing.
            if specs or not self._specs:
                self._specs = specs
            self._discovered_at = time.monotonic()
            return list(self._specs.values())

    async def openai_tools(self) -> List[Dict[str, Any]]:
        return [s.as_openai() for s in await self.discover()]

    def spec(self, name: str) -> Optional[ToolSpec]:
        return self._specs.get(name)

    async def call(self, name: str, arguments: Optional[Dict[str, Any]]) -> ToolOutcome:
        spec = self._specs.get(name)
        if spec is None:
            await self.discover(force=True)
            spec = self._specs.get(name)
        if spec is None:
            return ToolOutcome(name=name, ok=False, error=f"Unknown tool {name}")
        started = time.monotonic()
        try:
            result = await rpc(spec.server, "tools/call", {"name": spec.native, "arguments": arguments or {}}, self.timeout_s)
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.monotonic() - started) * 1000)
            logger.warning("tool %s failed: %s", spec.native, exc)
            return ToolOutcome(name=name, ok=False, error=f"{type(exc).__name__}: {exc}", elapsed_ms=elapsed)
        return outcome_from(name, result, int((time.monotonic() - started) * 1000))


@dataclass
class LocalTool:
    """A tool that exists for one request and runs in-process — a project's documents."""
    spec: ToolSpec
    handler: Callable[[Dict[str, Any]], Awaitable[ToolOutcome]]


class RequestTools:
    """The shared registry plus a request's own tools, behind the same four calls the loop
    makes (discover, openai_tools, spec, call)."""

    def __init__(self, base: ToolRegistry, local: Optional[List[LocalTool]] = None) -> None:
        self.base = base
        self.local: Dict[str, LocalTool] = {t.spec.name: t for t in (local or [])}

    async def discover(self, force: bool = False) -> List[ToolSpec]:
        shared = await self.base.discover(force)
        return [*[s for s in shared if s.name not in self.local], *(t.spec for t in self.local.values())]

    async def openai_tools(self) -> List[Dict[str, Any]]:
        return [s.as_openai() for s in await self.discover()]

    def spec(self, name: str) -> Optional[ToolSpec]:
        if name in self.local:
            return self.local[name].spec
        return self.base.spec(name)

    async def call(self, name: str, arguments: Optional[Dict[str, Any]]) -> ToolOutcome:
        tool = self.local.get(name)
        if tool is None:
            return await self.base.call(name, arguments)
        started = time.monotonic()
        try:
            out = await tool.handler(arguments or {})
        except Exception as exc:  # noqa: BLE001
            logger.warning("local tool %s failed: %s", name, exc)
            return ToolOutcome(name=name, ok=False, error=f"{type(exc).__name__}: {exc}",
                               elapsed_ms=int((time.monotonic() - started) * 1000))
        if not out.elapsed_ms:
            out.elapsed_ms = int((time.monotonic() - started) * 1000)
        return out


_REGISTRY: Optional[ToolRegistry] = None


def registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ToolRegistry()
    return _REGISTRY


def enabled() -> bool:
    return EXPERT_TOOLS_ENABLED
