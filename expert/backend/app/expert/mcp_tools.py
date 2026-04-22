from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx


@dataclass
class ToolResult:
    tool: str
    ok: bool
    content: str
    meta: Dict[str, Any]


@dataclass
class ToolCall:
    tool: str
    input: str


class MCPToolClient:
    """Production-oriented MCP tool runner with explicit call budget."""

    def __init__(self, endpoints: Dict[str, str], timeout_s: float = 15.0) -> None:
        self.endpoints = endpoints
        self.timeout_s = timeout_s

    async def run_many(self, calls: List[ToolCall], budget: int = 3) -> List[ToolResult]:
        out: List[ToolResult] = []
        remaining = budget
        for call in calls:
            if remaining <= 0:
                out.append(ToolResult(call.tool, False, "Skipped (budget exhausted)", {"budget": budget}))
                continue

            endpoint = self.endpoints.get(call.tool)
            if not endpoint:
                out.append(ToolResult(call.tool, False, "No MCP endpoint configured", {}))
                continue

            remaining -= 1
            out.append(await self._invoke(call.tool, endpoint, call.input))
        return out

    async def _invoke(self, tool: str, endpoint: str, payload: str) -> ToolResult:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(endpoint, json={"input": payload})
                resp.raise_for_status()
                data = resp.json() if resp.text else {}
            content = str(data.get("content", data))
            return ToolResult(tool, True, content, {"endpoint": endpoint})
        except Exception as exc:
            return ToolResult(tool, False, f"{type(exc).__name__}: {exc}", {"endpoint": endpoint})
