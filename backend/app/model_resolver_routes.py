"""
HTTP surface for model discovery and resolution (``/v1/models/*``).

    GET  /v1/models/resolution?configured=<chat>&vision=<vision>&base_url=
    POST /v1/models/refresh          re-probe now (UI "Retry")
    GET  /v1/models/suggested?role=  what the UI may offer to download
    POST /v1/models/pull {name}      start ``ollama pull`` on the active runtime
    GET  /v1/models/pull/{name}      progress for one pull
    GET  /v1/models/pulls            all active pulls

Pulls are restricted to the runtime discovery found (never a client-supplied
URL) and to names that match Ollama's tag syntax.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import model_resolver as mr

router = APIRouter(prefix="/v1/models", tags=["models"])


class PullBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    base_url: Optional[str] = Field(None, description="Settings override for the Chat Base URL, if any")


def _err(status: int, code: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(status_code=status, content={"ok": False, "code": code, "message": message, **extra})


@router.get("/resolution")
async def resolution(
    configured: str = Query("", description="Saved chat model ('' or 'auto' lets the backend pick)"),
    vision: str = Query("", description="Saved multimodal model"),
    base_url: Optional[str] = Query(None, description="Settings override for the Chat Base URL"),
) -> Dict[str, Any]:
    return await mr.snapshot(configured_chat=configured, configured_vision=vision, base_url=base_url or None)


@router.post("/refresh")
async def refresh(
    configured: str = Query(""),
    vision: str = Query(""),
    base_url: Optional[str] = Query(None),
) -> Dict[str, Any]:
    return await mr.snapshot(configured_chat=configured, configured_vision=vision, base_url=base_url or None, force=True)


@router.get("/suggested")
async def suggested(role: str = Query("chat")) -> Dict[str, Any]:
    rt, _ = await mr.active_runtime()
    installed = rt.model_names if rt else []
    return {"ok": True, "role": role, "suggested": mr.suggested_for(role, installed), "runtime_url": rt.url if rt else ""}


@router.post("/pull", status_code=202)
async def pull(body: PullBody):
    name = body.name.strip()
    if not mr.is_valid_model_name(name):
        return _err(400, "invalid_model_name", "Model names look like 'llama3.2:3b' or 'namespace/model:tag'.")
    rt, runtimes = await mr.active_runtime(body.base_url or None)
    if rt is None:
        res = await mr.resolve("chat", "", base_url=body.base_url or None)
        return _err(503, "no_runtime", res.reason, remedy=res.remedy)
    job = mr.pull_manager.start(name, rt.url)
    return {"ok": True, "job": job.to_dict()}


@router.get("/pull/{name:path}")
async def pull_status(name: str):
    job = mr.pull_manager.get(name.strip())
    if job is None:
        return _err(404, "unknown_pull", f"No download has been started for '{name}'.")
    return {"ok": True, "job": job.to_dict()}


@router.get("/pulls")
async def pulls() -> Dict[str, Any]:
    return {"ok": True, "pulls": mr.pull_manager.list_active()}
