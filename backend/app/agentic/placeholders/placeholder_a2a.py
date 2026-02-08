"""Minimal placeholder A2A agent server.

This is a lightweight FastAPI server that implements the A2A (Agent-to-Agent)
protocol just enough for testing the HomePilot Agent Creation Wizard.

Start:
    uvicorn backend.app.agentic.placeholders.placeholder_a2a:app --host 0.0.0.0 --port 9100

Then register in Context Forge:
    curl -X POST http://localhost:4444/a2a -u admin:changeme \\
      -H "Content-Type: application/json" \\
      -d '{
        "name": "placeholder_agent",
        "description": "Placeholder A2A agent for wiring the HomePilot wizard. Replace with a real agent later.",
        "endpoint_url": "http://localhost:9100/a2a",
        "agent_type": "generic",
        "protocol_version": "1.0",
        "visibility": "public",
        "tags": ["placeholder", "testing"]
      }'
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="HomePilot Placeholder A2A Agent",
    description="Minimal A2A agent for development/testing",
    version="0.1.0",
)


class InvokeRequest(BaseModel):
    interaction_type: str = "query"
    parameters: Dict[str, Any] = {}


@app.get("/health")
def health() -> Dict[str, bool]:
    return {"ok": True}


@app.post("/a2a")
def a2a_invoke(req: InvokeRequest) -> Dict[str, Any]:
    """Handle an A2A invocation.

    Returns a simple echo response so the wizard can verify wiring works.
    """
    text = req.parameters.get("input") or req.parameters.get("text") or req.parameters.get("prompt") or ""
    return {
        "ok": True,
        "result": f"[placeholder_agent] received: {text}",
        "meta": {
            "interaction_type": req.interaction_type,
            "agent": "placeholder_agent",
            "note": "Replace this placeholder with a real A2A agent.",
        },
    }
