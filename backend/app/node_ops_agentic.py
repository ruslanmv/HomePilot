"""
agentic.invoke — an allow-listed MCP tool call as a node job.

Lets an external application reach one of the owner's tools through the
Cloud Mirror job plane (OllaBridge Cloud -> OllaBridge Local -> /v1/node/jobs),
e.g. SmartMirror asking its own MCP server for outfit suggestions. The call
goes through the same Context Forge path as /v1/agentic/invoke.

Guardrails (additive, dark by default):
  - HOMEPILOT_MIRROR_MCP_ENABLED (default false): when off the operation is
    not registered at all, so the job whitelist, /v1/node/jobs/operations and
    the manifest are byte-for-byte unchanged.
  - HOMEPILOT_MIRROR_ALLOWED_TOOLS (default empty = deny everything):
    comma-separated fnmatch globs, e.g. "hp.smartmirror.*".
  - Tool arguments and results are never logged (they may carry prompts or
    photos); only tool name, duration and outcome are.
  - Honest failure: errors carry a stable code prefix (TOOL_NOT_ALLOWED,
    CAPABILITY_UNAVAILABLE, TOOL_FAILED) and never fabricate output.
"""
from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List

logger = logging.getLogger("homepilot.node_ops_agentic")

OPERATION = "agentic.invoke"
SCOPE = "mcp:invoke"
_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DEFAULT_TIMEOUT = 30.0
_MAX_TIMEOUT = 120.0


class ToolNotAllowed(PermissionError):
    pass


def mcp_enabled() -> bool:
    return os.getenv("HOMEPILOT_MIRROR_MCP_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def allowed_patterns() -> List[str]:
    raw = os.getenv("HOMEPILOT_MIRROR_ALLOWED_TOOLS", "")
    return [p.strip() for p in raw.split(",") if p.strip()]


def tool_allowed(tool: str) -> bool:
    """Deny by default; a tool must match one configured glob."""
    return any(fnmatch.fnmatchcase(tool, pattern) for pattern in allowed_patterns())


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def resolve_tool_name(requested: str, tools: List[Dict[str, Any]]) -> str:
    """Map the requested (allow-listed) name to the id Context Forge knows.

    Forge may expose a gateway's tools under a prefixed name
    ("smartmirror-hp-smartmirror-style-suggest"). Match, in order: exact
    name, original/custom name, then a gateway-prefixed slug. Falls back to
    the requested name.
    """
    slug = _slug(requested)
    for key in ("name", "originalName", "original_name", "customName", "custom_name"):
        for tool in tools:
            if isinstance(tool, dict) and tool.get(key) == requested:
                return str(tool.get("name") or requested)
    for tool in tools:
        name = str((tool or {}).get("name") or "") if isinstance(tool, dict) else ""
        if name and (_slug(name) == slug or _slug(name).endswith("-" + slug)):
            return name
    return requested


def normalize_result(raw: Any) -> Any:
    """Unwrap JSON-RPC / MCP tool results to the tool's own payload."""
    data = raw.get("result", raw) if isinstance(raw, dict) else raw
    if isinstance(data, dict):
        if data.get("structuredContent") is not None:
            return data["structuredContent"]
        content = data.get("content")
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            if len(texts) == 1:
                try:
                    return json.loads(texts[0])
                except (TypeError, ValueError):
                    return {"text": texts[0]}
            if texts:
                return {"text": "\n".join(texts)}
    return data


def _forge_client():
    # Same configuration as /v1/agentic/* (agentic/routes.py).
    from .agentic.client import ContextForgeClient

    return ContextForgeClient(
        base_url=os.getenv("CONTEXT_FORGE_URL", "http://localhost:4444").rstrip("/"),
        token=os.getenv("CONTEXT_FORGE_TOKEN", ""),
        auth_user=os.getenv("CONTEXT_FORGE_AUTH_USER", "admin"),
        auth_pass=os.getenv("CONTEXT_FORGE_AUTH_PASS", "changeme"),
    )


async def _invoke(tool: str, arguments: Dict[str, Any], timeout: float) -> Any:
    client = _forge_client()
    try:
        tools = await client.list_tools(timeout=5.0)
    except Exception:  # noqa: BLE001 — resolution is best-effort
        tools = []
    return await client.invoke_tool(resolve_tool_name(tool, tools or []), arguments, timeout=timeout)


def op_agentic_invoke(job: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    if not mcp_enabled():
        raise RuntimeError("CAPABILITY_UNAVAILABLE: agentic.invoke is disabled on this node")
    tool = params.get("tool")
    if not isinstance(tool, str) or not _TOOL_NAME.match(tool):
        raise ValueError("TOOL_NOT_ALLOWED: invalid tool name")
    if not tool_allowed(tool):
        raise ToolNotAllowed(f"TOOL_NOT_ALLOWED: {tool}")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ValueError("TOOL_FAILED: arguments must be an object")
    try:
        timeout = min(_MAX_TIMEOUT, max(1.0, float(params.get("timeout_s") or _DEFAULT_TIMEOUT)))
    except (TypeError, ValueError):
        timeout = _DEFAULT_TIMEOUT

    job.set_progress(10, "invoke", tool)
    started = time.monotonic()
    raw = asyncio.run(_invoke(tool, arguments, timeout))
    elapsed_ms = int((time.monotonic() - started) * 1000)

    if isinstance(raw, dict) and raw.get("error") and "result" not in raw:
        logger.info("agentic.invoke tool=%s status=failed ms=%d", tool, elapsed_ms)
        raise RuntimeError("TOOL_FAILED: the tool did not return a result")
    logger.info("agentic.invoke tool=%s status=ok ms=%d", tool, elapsed_ms)
    job.set_progress(100, "done", "")
    return {"tool": tool, "result": normalize_result(raw)}


def register_if_enabled(register: Callable[[str, str, Callable[..., Dict[str, Any]]], None]) -> bool:
    """Register the operation only when the feature flag is on."""
    if not mcp_enabled():
        return False
    register(OPERATION, SCOPE, op_agentic_invoke)
    return True


def manifest_capabilities() -> List[str]:
    return [OPERATION] if mcp_enabled() else []

