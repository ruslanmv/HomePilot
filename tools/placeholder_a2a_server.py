"""Standalone placeholder A2A agent for development/testing.

Run: uvicorn tools.placeholder_a2a_server:app --host 0.0.0.0 --port 9100
"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict

app = FastAPI(title="HomePilot Placeholder A2A Agent", version="0.1.0")


class InvokeReq(BaseModel):
    interaction_type: str = "query"
    parameters: Dict[str, Any] = {}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/a2a")
def a2a(req: InvokeReq):
    text = req.parameters.get("input") or req.parameters.get("text") or ""
    return {
        "ok": True,
        "result": f"[placeholder_agent] received: {text}",
        "meta": {"interaction_type": req.interaction_type},
    }
