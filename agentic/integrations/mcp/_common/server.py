from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


Json = Dict[str, Any]


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: Json
    handler: Callable[[Json], Awaitable[Json]]

    # Convenience alias to match common MCP vocabulary
    @property
    def inputSchema(self) -> Json:  # noqa: N802
        return self.input_schema


def mcp_app(
    *,
    server_name: str,
    tools: List[ToolDef],
    version: str = "2025-03-26",
) -> FastAPI:
    """Create a minimal MCP-ish JSON-RPC server.

    This is intentionally lightweight:
    * Context Forge can federate it via JSON-RPC/HTTP
    * Tools are discoverable via `tools/list`
    * Tools are invokable via `tools/call`
    """

    tool_map: Dict[str, ToolDef] = {t.name: t for t in tools}

    app = FastAPI(title=server_name)

    @app.get("/health")
    async def health() -> Json:
        return {"ok": True, "name": server_name, "ts": int(time.time())}

    @app.post("/rpc")
    async def rpc(request: Request) -> JSONResponse:
        body = await request.json()
        jsonrpc = body.get("jsonrpc")
        method = body.get("method")
        params = body.get("params") or {}
        req_id = body.get("id")

        def err(code: int, message: str, data: Optional[Json] = None) -> JSONResponse:
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": code, "message": message, "data": data or {}},
                }
            )

        if jsonrpc != "2.0":
            return err(-32600, "Invalid JSON-RPC")

        # Minimal MCP lifecycle
        if method in ("initialize", "mcp/initialize"):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": version,
                        "serverInfo": {"name": server_name, "version": "0.1.0"},
                        "capabilities": {"tools": True, "resources": False, "prompts": False},
                    },
                }
            )

        if method in ("tools/list", "mcp/tools/list"):
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": [
                            {
                                "name": t.name,
                                "description": t.description,
                                "inputSchema": t.inputSchema,
                            }
                            for t in tools
                        ]
                    },
                }
            )

        if method in ("tools/call", "mcp/tools/call"):
            name = (params or {}).get("name")
            args = (params or {}).get("arguments") or {}
            if not name:
                return err(-32602, "Missing params.name")
            tool = tool_map.get(name)
            if not tool:
                return err(-32601, f"Unknown tool: {name}")
            try:
                result = await tool.handler(args)
                # MCP tool call results commonly return a content[] array.
                return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})
            except Exception as exc:
                return err(-32000, "Tool execution failed", {"tool": name, "error": str(exc)})

        return err(-32601, f"Method not found: {method}")

    return app


# Backwards-friendly alias used by the sample servers.
create_mcp_app = mcp_app
