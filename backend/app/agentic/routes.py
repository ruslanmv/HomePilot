"""FastAPI router — /v1/agentic/*

Phase 1–4 endpoints (additive, non-destructive):
  GET  /v1/agentic/status        → health / feature-flag check
  GET  /v1/agentic/admin         → admin UI redirect URL
  GET  /v1/agentic/capabilities  → dynamic discovery from Context Forge + built-ins
  GET  /v1/agentic/catalog       → wizard-friendly catalog (tools/agents/gateways/servers)
  POST /v1/agentic/invoke        → execute a capability (local orchestrator + Context Forge)

Phase 4 additions:
  - capabilities returns source="forge"|"built_in"|"mixed" field
  - generate_images uses model-config preset system (not hard-coded dims)
  - generate_videos routed to local animate pipeline

Phase 5 additions (additive):
  - /catalog returns real selectable MCP tools, A2A agents, gateways, servers
  - capability_sources map for wiring capabilities to real tool IDs

Phase 6 additions (additive):
  POST /v1/agentic/register/tool     → register a new tool in Context Forge
  POST /v1/agentic/register/agent    → register a new A2A agent
  POST /v1/agentic/register/gateway  → register a new MCP gateway (+ auto-refresh)
  POST /v1/agentic/register/server   → create a new virtual server
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_api_key
from ..defaults import DEFAULT_NEGATIVE_PROMPT
from ..orchestrator import handle_request
from .capabilities import discover_capabilities, discover_catalog
from .client import ContextForgeClient
from .policy import apply_policy, is_allowed, resolve_profile
from .types import (
    AgenticAdminOut,
    AgenticCatalogOut,
    AgenticStatusOut,
    CapabilitiesOut,
    CatalogGateway,
    CatalogServer,
    CreateServerIn,
    InvokeIn,
    InvokeOut,
    RegisterAgentIn,
    RegisterGatewayIn,
    RegisterOut,
    RegisterToolIn,
)

logger = logging.getLogger("homepilot.agentic.routes")

router = APIRouter(prefix="/v1/agentic", tags=["agentic"])

# ── Configuration (read once at import, overridable via env) ──────────────────

_ENABLED = os.getenv("AGENTIC_ENABLED", "true").lower() in ("1", "true", "yes")
_FORGE_URL = os.getenv("CONTEXT_FORGE_URL", "http://localhost:4444").rstrip("/")
_ADMIN_URL = os.getenv("CONTEXT_FORGE_ADMIN_URL", "http://localhost:4444/admin").rstrip("/")
_TOKEN = os.getenv("CONTEXT_FORGE_TOKEN", "")
_AUTH_USER = os.getenv("CONTEXT_FORGE_AUTH_USER", "admin")
_AUTH_PASS = os.getenv("CONTEXT_FORGE_AUTH_PASS", "changeme")


def _client() -> ContextForgeClient:
    return ContextForgeClient(
        base_url=_FORGE_URL,
        token=_TOKEN,
        auth_user=_AUTH_USER,
        auth_pass=_AUTH_PASS,
    )


# ── GET /v1/agentic/status ───────────────────────────────────────────────────

@router.get("/status", response_model=AgenticStatusOut)
async def agentic_status(_key: str = Depends(require_api_key)):
    configured = bool(_FORGE_URL)
    reachable = False
    if _ENABLED and configured:
        try:
            reachable = await _client().ping()
        except Exception:
            pass
    return AgenticStatusOut(
        enabled=_ENABLED,
        configured=configured,
        reachable=reachable,
        admin_configured=bool(_ADMIN_URL),
    )


# ── GET /v1/agentic/admin ────────────────────────────────────────────────────

@router.get("/admin", response_model=AgenticAdminOut)
async def agentic_admin(_key: str = Depends(require_api_key)):
    if not _ADMIN_URL:
        raise HTTPException(status_code=404, detail="Admin URL not configured")
    return AgenticAdminOut(admin_url=_ADMIN_URL)


# ── GET /v1/agentic/capabilities ─────────────────────────────────────────────

@router.get("/capabilities", response_model=CapabilitiesOut)
async def agentic_capabilities(_key: str = Depends(require_api_key)):
    if not _ENABLED:
        return CapabilitiesOut(capabilities=[], source="built_in")
    try:
        caps, source = await discover_capabilities(_client())
    except Exception as exc:
        logger.warning("capability discovery failed: %s", exc)
        caps, source = [], "built_in"
    return CapabilitiesOut(capabilities=caps, source=source)


# ── Helper: best-effort GET for Forge endpoints not covered by client ────────


async def _forge_get_json(path: str, timeout: float = 5.0) -> Any:
    """Best-effort GET helper for Forge endpoints not covered by ContextForgeClient.

    Additive-only: no behavior changes to existing endpoints.
    """
    base = _FORGE_URL.rstrip("/")
    url = f"{base}{path}"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    auth = None
    if _TOKEN:
        headers["Authorization"] = f"Bearer {_TOKEN}"
    else:
        auth = httpx.BasicAuth(_AUTH_USER, _AUTH_PASS)

    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout), follow_redirects=True) as c:
        r = await c.get(url, headers=headers, auth=auth)
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except Exception:
            return None


# ── GET /v1/agentic/catalog ──────────────────────────────────────────────────
# Additive endpoint for the Agent Creation Wizard:
# returns real selectable tools/agents plus best-effort gateways/servers.


@router.get("/catalog", response_model=AgenticCatalogOut)
async def agentic_catalog(_key: str = Depends(require_api_key)):
    if not _ENABLED:
        # Keep contract stable: return empty lists rather than 503,
        # so the UI can gracefully degrade.
        return AgenticCatalogOut(
            tools=[], a2a_agents=[], gateways=[], servers=[],
            capability_sources={}, source="built_in",
        )

    # tools + a2a agents (+ capability_sources map)
    base = await discover_catalog(_client())

    # Best-effort gateways/servers (Forge deployments vary; try both public and /admin)
    gateways_payload = await _forge_get_json("/gateways")
    if gateways_payload is None:
        gateways_payload = await _forge_get_json("/admin/gateways")

    servers_payload = await _forge_get_json("/servers")
    if servers_payload is None:
        servers_payload = await _forge_get_json("/admin/servers")

    gateways: List[CatalogGateway] = []
    if isinstance(gateways_payload, list):
        items = gateways_payload
    elif isinstance(gateways_payload, dict):
        items = gateways_payload.get("gateways") or gateways_payload.get("items") or []
    else:
        items = []
    for g in items:
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id") or "")
        name = str(g.get("name") or "")
        if not gid or not name:
            continue
        gateways.append(
            CatalogGateway(
                id=gid,
                name=name,
                url=g.get("url") or g.get("endpoint_url") or None,
                transport=g.get("transport") or None,
                enabled=g.get("enabled"),
            )
        )

    servers: List[CatalogServer] = []
    if isinstance(servers_payload, list):
        sitems = servers_payload
    elif isinstance(servers_payload, dict):
        sitems = servers_payload.get("servers") or servers_payload.get("items") or []
    else:
        sitems = []
    for s in sitems:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "")
        name = str(s.get("name") or "")
        if not sid or not name:
            continue
        servers.append(
            CatalogServer(
                id=sid,
                name=name,
                enabled=s.get("enabled"),
                sse_url=f"{_FORGE_URL}/servers/{sid}/sse",
            )
        )

    return AgenticCatalogOut(
        tools=base.tools,
        a2a_agents=base.a2a_agents,
        gateways=gateways,
        servers=servers,
        capability_sources=base.capability_sources,
        source="forge",
    )


# ── POST /v1/agentic/register/* ─────────────────────────────────────────────
# Phase 6: Write endpoints so the wizard can register tools/agents/gateways/servers
# directly into Context Forge without requiring curl or the admin UI.


@router.post("/register/tool", response_model=RegisterOut)
async def agentic_register_tool(body: RegisterToolIn, _key: str = Depends(require_api_key)):
    """Register a new tool in Context Forge from the wizard."""
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    tool_def: Dict[str, Any] = {
        "name": body.name,
        "description": body.description,
        "inputSchema": body.input_schema,
        "integration_type": body.integration_type,
        "request_type": body.request_type,
        "tags": body.tags,
        "visibility": body.visibility,
    }
    if body.url:
        tool_def["url"] = body.url

    result = await _client().register_tool(tool_def)
    if "error" in result:
        return RegisterOut(ok=False, detail=result.get("detail") or result["error"])
    return RegisterOut(
        ok=True,
        id=str(result.get("id", "")),
        name=str(result.get("name", body.name)),
        detail="Tool registered successfully",
    )


@router.post("/register/agent", response_model=RegisterOut)
async def agentic_register_agent(body: RegisterAgentIn, _key: str = Depends(require_api_key)):
    """Register a new A2A agent in Context Forge from the wizard."""
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    agent_def: Dict[str, Any] = {
        "name": body.name,
        "description": body.description,
        "endpoint_url": body.endpoint_url,
        "agent_type": body.agent_type,
        "protocol_version": body.protocol_version,
        "tags": body.tags,
        "visibility": body.visibility,
    }

    result = await _client().register_agent(agent_def)
    if "error" in result:
        return RegisterOut(ok=False, detail=result.get("detail") or result["error"])
    return RegisterOut(
        ok=True,
        id=str(result.get("id", "")),
        name=str(result.get("name", body.name)),
        detail="Agent registered successfully",
    )


@router.post("/register/gateway", response_model=RegisterOut)
async def agentic_register_gateway(body: RegisterGatewayIn, _key: str = Depends(require_api_key)):
    """Register a new MCP gateway in Context Forge from the wizard.

    If auto_refresh is True (default), triggers tool discovery after registration.
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    gateway_def: Dict[str, Any] = {
        "name": body.name,
        "url": body.url,
        "transport": body.transport,
        "description": body.description,
        "tags": body.tags,
        "visibility": body.visibility,
    }

    client = _client()
    result = await client.register_gateway(gateway_def)
    if "error" in result:
        return RegisterOut(ok=False, detail=result.get("detail") or result["error"])

    gw_id = str(result.get("id", ""))
    detail = "Gateway registered successfully"

    # Auto-refresh to discover tools from the new gateway
    if body.auto_refresh and gw_id:
        try:
            refresh = await client.refresh_gateway(gw_id)
            if "error" not in refresh:
                detail += " (tools refreshed)"
            else:
                detail += f" (refresh failed: {refresh.get('error', 'unknown')})"
        except Exception as exc:
            detail += f" (refresh error: {exc})"

    return RegisterOut(
        ok=True,
        id=gw_id,
        name=str(result.get("name", body.name)),
        detail=detail,
    )


@router.post("/register/server", response_model=RegisterOut)
async def agentic_register_server(body: CreateServerIn, _key: str = Depends(require_api_key)):
    """Create a new virtual server in Context Forge from the wizard."""
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    server_def: Dict[str, Any] = {
        "name": body.name,
        "description": body.description,
        "tags": body.tags,
        "visibility": body.visibility,
    }
    if body.tool_ids:
        server_def["associated_tools"] = body.tool_ids

    result = await _client().create_server(server_def)
    if "error" in result:
        return RegisterOut(ok=False, detail=result.get("detail") or result["error"])
    return RegisterOut(
        ok=True,
        id=str(result.get("id", "")),
        name=str(result.get("name", body.name)),
        detail="Virtual server created successfully",
    )


# ── POST /v1/agentic/invoke ──────────────────────────────────────────────────
# Phase 3: built-in intents route to the local HomePilot orchestrator.
# Other intents fall through to Context Forge tool invocation.

async def _invoke_local_imagine(body: InvokeIn, defaults: Dict[str, Any]) -> InvokeOut:
    """Route generate_images through the existing HomePilot imagine pipeline."""
    prompt = (body.args.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing args.prompt")

    # Let the orchestrator's preset system compute width/height/steps/cfg
    # based on model architecture (SDXL bucketed resolutions, Pony-specific
    # steps, Flux CFG, etc.) instead of hard-coding dimensions here.
    payload: Dict[str, Any] = {
        "message": prompt,
        "conversation_id": body.conversation_id,
        "project_id": body.project_id,
        "mode": "imagine",
        "imgPreset": defaults.get("img_preset", "med"),
        "imgSeed": 0,
        "imgModel": body.args.get("model", "pony-xl"),
        "promptRefinement": True,
        "nsfwMode": body.nsfwMode,
        "negative_prompt": DEFAULT_NEGATIVE_PROMPT,
    }

    result = await handle_request("imagine", payload)
    return InvokeOut(
        ok=True,
        conversation_id=result.get("conversation_id", body.conversation_id or ""),
        assistant_text="Here you go.",
        media=result.get("media"),
        meta={"intent": "generate_images", "profile": body.profile},
    )


async def _invoke_local_animate(body: InvokeIn, defaults: Dict[str, Any]) -> InvokeOut:
    """Route generate_videos through the existing HomePilot animate pipeline."""
    prompt = (body.args.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Missing args.prompt")

    payload: Dict[str, Any] = {
        "message": prompt,
        "conversation_id": body.conversation_id,
        "project_id": body.project_id,
        "mode": "animate",
        "vidSteps": defaults.get("vid_steps", 20),
        "vidCfg": defaults.get("vid_cfg", 3.5),
        "vidFrames": defaults.get("vid_frames", 25),
        "nsfwMode": body.nsfwMode,
    }

    result = await handle_request("animate", payload)
    return InvokeOut(
        ok=True,
        conversation_id=result.get("conversation_id", body.conversation_id or ""),
        assistant_text="Here is your video.",
        media=result.get("media"),
        meta={"intent": "generate_videos", "profile": body.profile},
    )


@router.post("/invoke", response_model=InvokeOut)
async def agentic_invoke(body: InvokeIn, _key: str = Depends(require_api_key)):
    """Execute a capability.

    Phase 3 strategy:
    - Built-in intents (generate_images, generate_videos) → local orchestrator
    - Other intents → Context Forge tool invocation (with graceful error)
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    if not is_allowed(body.intent):
        raise HTTPException(status_code=403, detail=f"Capability '{body.intent}' is not allowed")

    defaults = resolve_profile(body.profile)

    # ── Built-in intents (use local HomePilot pipelines) ──────────────────
    try:
        if body.intent == "generate_images":
            return await _invoke_local_imagine(body, defaults)

        if body.intent == "generate_videos":
            return await _invoke_local_animate(body, defaults)
    except HTTPException:
        raise  # re-raise 400s etc.
    except Exception as exc:
        logger.error("Built-in intent '%s' failed: %s", body.intent, exc, exc_info=True)
        return InvokeOut(
            ok=False,
            conversation_id=body.conversation_id or "",
            assistant_text=f"Generation failed: {exc}",
            media=None,
            meta={"intent": body.intent, "error": str(exc)},
        )

    # ── All other intents → Context Forge ─────────────────────────────────
    try:
        merged_args = apply_policy(body.intent, body.args, body.profile)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    client = _client()
    result = await client.invoke_tool(body.intent, merged_args)

    if "error" in result:
        return InvokeOut(
            ok=False,
            conversation_id=body.conversation_id or "",
            assistant_text=result["error"],
            meta=result,
        )

    return InvokeOut(
        ok=True,
        conversation_id=body.conversation_id or "",
        assistant_text=result.get("result", result.get("text", "")),
        media=result.get("media"),
        meta={k: v for k, v in result.items() if k not in ("result", "text", "media")},
    )
