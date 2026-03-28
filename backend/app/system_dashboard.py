"""System Status dashboard endpoint — additive, non-destructive.

Provides GET /v1/system/overview which aggregates health from all
HomePilot subsystems into a single response for the frontend
SystemStatusDialog.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .config import (
    OLLAMA_BASE_URL,
    COMFY_BASE_URL,
)

router = APIRouter(prefix="/v1/system", tags=["system-dashboard"])

_STARTED_AT: float = time.time()


async def _probe(url: str, path: str, timeout: float = 2.5) -> Dict[str, Any]:
    """Probe a service endpoint and return health + latency."""
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(f"{url.rstrip('/')}{path}")
        ms = round((time.perf_counter() - started) * 1000)
        return {"ok": r.status_code == 200, "status_code": r.status_code, "latency_ms": ms, "url": url}
    except Exception as e:
        ms = round((time.perf_counter() - started) * 1000)
        return {"ok": False, "status_code": None, "latency_ms": ms, "url": url, "error": str(e)}


@router.get("/overview")
async def system_overview() -> JSONResponse:
    """Aggregate health overview for the System Status dashboard."""

    uptime_seconds = int(time.time() - _STARTED_AT)

    # Probe external services
    backend_status: Dict[str, Any] = {"ok": True, "service": "homepilot-backend", "latency_ms": 0}
    ollama = await _probe(OLLAMA_BASE_URL, "/api/tags")
    comfy = await _probe(COMFY_BASE_URL, "/system_stats")

    # Probe Context Forge gateway
    forge_url = os.getenv("CONTEXT_FORGE_URL", "http://127.0.0.1:4444")
    forge = await _probe(forge_url, "/health")

    # Probe Avatar Service (Quick Face / StyleGAN2)
    avatar_svc_url = os.getenv("AVATAR_SERVICE_URL", "http://localhost:8020")
    avatar_svc = await _probe(avatar_svc_url, "/v1/avatars/capabilities")

    # SQLite is always in-process
    sqlite_status: Dict[str, Any] = {"ok": True, "status": "connected", "latency_ms": 0}

    # Agentic catalog counts (best-effort)
    tools_count = 0
    agents_count = 0
    servers_count = 0
    gateways_count = 0
    try:
        from .agentic.server_manager import get_server_manager
        mgr = get_server_manager()
        # Count MCP servers that are healthy
        all_servers = mgr.list_all()
        for s in all_servers:
            servers_count += 1
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            # Get tool count from Forge
            r = await client.get(f"{forge_url}/tools?limit=0")
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    tools_count = len(data)
                elif isinstance(data, dict) and "tools" in data:
                    tools_count = len(data["tools"])
                elif isinstance(data, dict) and "total" in data:
                    tools_count = data["total"]

            # Get agent count
            r2 = await client.get(f"{forge_url}/a2a?limit=0")
            if r2.status_code == 200:
                data2 = r2.json()
                if isinstance(data2, list):
                    agents_count = len(data2)
                elif isinstance(data2, dict) and "agents" in data2:
                    agents_count = len(data2["agents"])

            # Get gateway count
            r3 = await client.get(f"{forge_url}/gateways?limit=0")
            if r3.status_code == 200:
                data3 = r3.json()
                if isinstance(data3, list):
                    gateways_count = len(data3)
                elif isinstance(data3, dict) and "gateways" in data3:
                    gateways_count = len(data3["gateways"])
    except Exception:
        pass

    services: Dict[str, Dict[str, Any]] = {
        "backend": backend_status,
        "ollama": ollama,
        "avatar_svc": avatar_svc,
        "comfyui": comfy,
        "forge": forge,
        "sqlite": sqlite_status,
    }

    total_services = len(services)
    healthy_services = sum(1 for s in services.values() if s.get("ok") is True)
    avg_latency = round(
        sum(s.get("latency_ms", 0) or 0 for s in services.values()) / max(total_services, 1)
    )
    active_entities = tools_count + agents_count + servers_count + gateways_count

    return JSONResponse({
        "ok": healthy_services > 0,
        "overview": {
            "uptime_seconds": uptime_seconds,
            "version": "3.0.0",
            "healthy_services": healthy_services,
            "total_services": total_services,
            "degraded_services": total_services - healthy_services,
            "avg_latency_ms": avg_latency,
            "active_entities": active_entities,
        },
        "architecture": {
            "inputs": {
                "virtual_servers_total": gateways_count,
                "virtual_servers_active": gateways_count,
            },
            "gateway": {
                "contextforge_ok": forge.get("ok", False),
            },
            "infrastructure": {
                "sqlite": True,
                "database": "SQLite",
                "memory_mode": "In-Memory",
            },
            "outputs": {
                "mcp_servers_total": servers_count,
                "mcp_servers_active": servers_count if forge.get("ok") else 0,
                "a2a_agents_total": agents_count,
                "a2a_agents_active": agents_count if forge.get("ok") else 0,
                "tools_total": tools_count,
                "tools_active": tools_count if forge.get("ok") else 0,
                "prompts_total": 0,
                "prompts_active": 0,
                "resources_total": 0,
                "resources_active": 0,
            },
        },
        "services": services,
    })
