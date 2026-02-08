"""Minimal placeholder MCP tool server.

This is a lightweight FastAPI server that exposes a single "echo" tool
via a REST interface compatible with MCP Context Forge tool registration.

Start:
    uvicorn backend.app.agentic.placeholders.placeholder_tool_server:app --host 0.0.0.0 --port 9101

Then register the tool in Context Forge:
    curl -X POST http://localhost:4444/tools -u admin:changeme \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "placeholder_echo",
        "displayName": "Placeholder Echo Tool",
        "description": "Echoes input text back. Use as a wiring test for the HomePilot wizard.",
        "integration_type": "REST",
        "url": "http://localhost:9101/invoke",
        "request_type": "POST",
        "input_schema": {
          "type": "object",
          "properties": {
            "text": { "type": "string", "description": "Text to echo back" }
          },
          "required": ["text"]
        },
        "tags": ["placeholder", "testing"],
        "visibility": "public"
      }'
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="HomePilot Placeholder Tool Server",
    description="Minimal MCP tool server for development/testing",
    version="0.1.0",
)


class InvokeRequest(BaseModel):
    args: Dict[str, Any] = {}


@app.get("/health")
def health() -> Dict[str, bool]:
    return {"ok": True}


@app.post("/invoke")
def invoke(req: InvokeRequest) -> Dict[str, Any]:
    """Execute the placeholder echo tool.

    Returns the input text wrapped in a response envelope.
    """
    text = req.args.get("text") or req.args.get("input") or ""
    return {
        "ok": True,
        "result": f"[placeholder_echo] {text}",
        "meta": {
            "tool": "placeholder_echo",
            "note": "Replace this placeholder with a real MCP tool.",
        },
    }
