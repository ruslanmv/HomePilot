from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


Json = Dict[str, Any]


@dataclass
class AgentDef:
    name: str
    description: str


def create_a2a_app(agent: AgentDef, handle_message: Callable[[str, Json], Awaitable[Json]]) -> FastAPI:
    """Create a small JSON-RPC endpoint suitable for Context Forge A2A federation.

    Context Forge can proxy an external agent and expose it in `/a2a`.
    This starter implementation supports a minimal method:

    * `a2a.message` – send a message and get a structured response
    """

    app = FastAPI(title=f"A2A Agent: {agent.name}", version="0.1.0")

    @app.get("/health")
    async def health() -> Json:
        return {"ok": True, "agent": agent.name}

    @app.post("/rpc")
    async def rpc(request: Request) -> JSONResponse:
        body = await request.json()
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}

        if method in ("initialize", "a2a.initialize"):
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "name": agent.name,
                    "description": agent.description,
                    "methods": ["a2a.message"],
                },
            })

        if method != "a2a.message":
            return JSONResponse({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })

        text = str(params.get("text") or "")
        meta = params.get("meta") or {}
        result = await handle_message(text, meta)
        return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})

    return app
