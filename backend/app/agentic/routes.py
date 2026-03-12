"""FastAPI router — /v1/agentic/*

Phase 1–4 endpoints (additive, non-destructive):
  GET  /v1/agentic/status        → health / feature-flag check
  GET  /v1/agentic/admin         → admin UI redirect URL
  GET  /v1/agentic/capabilities  → dynamic discovery from Context Forge + built-ins
  GET  /v1/agentic/catalog       → wizard-friendly catalog (tools/agents/gateways/servers)
  POST /v1/agentic/invoke        → execute a capability (local orchestrator + Context Forge)

Phase 5–6 additions (additive):
  - /catalog returns real selectable MCP tools, A2A agents, gateways, servers
  - capability_sources map for wiring capabilities to real tool IDs
  - POST /v1/agentic/register/{tool,agent,gateway,server}

Phase 7 additions (additive):
  - /catalog upgraded: returns enriched AgenticCatalog with ForgeStatus,
    last_updated, virtual server tool_ids, and TTL caching via AgenticCatalogService
  - /invoke upgraded: RuntimeToolRouter resolves capability → tool_id
    within virtual-server scope (fallback-safe for legacy projects)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Request

from ..auth import require_api_key
from ..defaults import DEFAULT_NEGATIVE_PROMPT
from ..orchestrator import handle_request
from .capabilities import discover_capabilities, discover_catalog
from .catalog import fetch_catalog
from .catalog_service import AgenticCatalogService
from .client import ContextForgeClient
from .policy import apply_policy, is_allowed, resolve_profile
from .suite_manifest import list_suites, read_suite
from .runtime_tool_router import RuntimeToolRouter
from .server_config import read_server_config, save_server_config, validate_config
from .server_manager import get_server_manager
from .sync_service import sync_homepilot
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


# ── Phase 7: Catalog service (TTL-cached) and runtime tool router ────────────
# Module-level singletons — additive, does not change any existing endpoint
# behavior unless the caller passes tool_source.

_catalog_service = AgenticCatalogService(
    forge_base_url=_FORGE_URL,
    auth_user=_AUTH_USER,
    auth_pass=_AUTH_PASS,
    bearer_token=_TOKEN or None,
    ttl_seconds=15.0,
)


def _tool_router() -> RuntimeToolRouter:
    return RuntimeToolRouter(catalog_service=_catalog_service, client=_client())


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
    Uses JWT auto-login via the client module helper.
    """
    from .client import forge_jwt_login

    base = _FORGE_URL.rstrip("/")
    url = f"{base}{path}"
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    auth = None

    # Prefer pre-configured token, then try JWT login
    token = _TOKEN
    if not token:
        email = _AUTH_USER if "@" in _AUTH_USER else f"{_AUTH_USER}@example.com"
        token = await forge_jwt_login(base, email=email, password=_AUTH_PASS) or ""

    if token:
        headers["Authorization"] = f"Bearer {token}"
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
# Phase 7: upgraded to use AgenticCatalogService (TTL-cached, enriched).
# Response is backward-compatible with the original AgenticCatalogOut contract:
# the UI reads the same fields (tools, a2a_agents, gateways, servers,
# capability_sources, source) plus new enriched fields (last_updated, forge).


@router.get("/catalog")
async def agentic_catalog(_key: str = Depends(require_api_key)):
    if not _ENABLED:
        return {
            "tools": [], "a2a_agents": [], "gateways": [], "servers": [],
            "capability_sources": {}, "source": "built_in",
            "last_updated": "", "forge": {"base_url": _FORGE_URL, "healthy": False, "error": "disabled"},
        }

    try:
        catalog = await _catalog_service.get_cached(_client())
        return catalog.model_dump()
    except Exception as exc:
        logger.warning("catalog_service failed, falling back: %s", exc)
        # Graceful fallback to legacy discover_catalog
        base = await discover_catalog(_client())
        return {
            "tools": [t.model_dump() for t in base.tools],
            "a2a_agents": [a.model_dump() for a in base.a2a_agents],
            "gateways": [],
            "servers": [],
            "capability_sources": base.capability_sources,
            "source": "forge",
            "last_updated": "",
            "forge": {"base_url": _FORGE_URL, "healthy": False, "error": str(exc)},
        }


# ── GET /v1/agentic/suite/* ────────────────────────────────────────────────
# Suite manifests drive the wizard UX: tool bundles, A2A agent presets.


@router.get("/suite")
async def agentic_suite_index(_key: str = Depends(require_api_key)):
    """Return all known suite manifests."""
    return list_suites()


@router.get("/suite/{name}")
async def agentic_suite(name: str, _key: str = Depends(require_api_key)):
    """Return a single suite manifest by name (without extension)."""
    return read_suite(name)


# ── POST /v1/agentic/sync ──────────────────────────────────────────────────
# Bulk-sync HomePilot MCP servers, tools, A2A agents, and virtual servers
# into Context Forge.  Discovers tools from running MCP servers (ports 9101-9105),
# registers them, creates virtual servers from templates, then returns the
# refreshed catalog.


@router.post("/sync")
async def agentic_sync(_key: str = Depends(require_api_key)):
    """Sync all HomePilot MCP servers, tools, agents into Context Forge.

    Discovers tools from running MCP servers (ports 9101-9105),
    registers A2A agents and virtual servers from templates.
    Idempotent: skips items that already exist.
    Returns sync summary + refreshed catalog.
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    try:
        result = await sync_homepilot(
            base_url=_FORGE_URL,
            auth_user=_AUTH_USER,
            auth_pass=_AUTH_PASS,
            bearer_token=_TOKEN or None,
        )
    except Exception as exc:
        logger.error("sync_homepilot failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Sync failed: {exc}")

    # Invalidate catalog cache so next fetch shows newly registered items
    _catalog_service.invalidate()

    # Fetch refreshed catalog
    try:
        catalog = await _catalog_service.get_cached(_client())
        catalog_data = catalog.model_dump()
    except Exception:
        catalog_data = None

    return {
        "sync": result,
        "catalog": catalog_data,
    }


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
    _catalog_service.invalidate()  # bust cache so next /catalog reflects new tool
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
    _catalog_service.invalidate()
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

    _catalog_service.invalidate()
    return RegisterOut(
        ok=True,
        id=gw_id,
        name=str(result.get("name", body.name)),
        detail=detail,
    )


@router.get("/servers/{server_id}/tools")
async def agentic_server_tools(server_id: str, _key: str = Depends(require_api_key)):
    """Return the full tool objects associated with a virtual server.

    Proxies Forge's GET /servers/{id}/tools which joins through the
    server_tool_association table and returns ToolRead objects with
    id, name, description, enabled, etc.  This avoids the name-vs-UUID
    confusion in the list endpoint's associated_tools field.
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    data = await _catalog_service.http.list_server_tools(server_id)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    # Forge may wrap in {"tools": [...]} or {"data": [...]}
    for key in ("tools", "data", "items"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


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
    _catalog_service.invalidate()
    return RegisterOut(
        ok=True,
        id=str(result.get("id", "")),
        name=str(result.get("name", body.name)),
        detail="Virtual server created successfully",
    )


# ── GET /v1/agentic/registry/servers ──────────────────────────────────────────
# Phase 9: Proxy to Forge's MCP Registry catalog so the HomePilot frontend
# can browse & install public MCP servers without opening the Forge admin UI.


@router.get("/registry/servers")
async def agentic_registry_servers(
    category: str = "",
    auth_type: str = "",
    provider: str = "",
    search: str = "",
    limit: int = 100,
    offset: int = 0,
    _key: str = Depends(require_api_key),
):
    """Return the Forge MCP Registry catalog (81+ public servers, 38 categories).

    Proxies GET /admin/mcp-registry/servers from Context Forge with filters.
    """
    if not _ENABLED:
        return {
            "servers": [], "total": 0, "categories": [], "auth_types": [],
            "providers": [], "all_tags": [],
        }

    data = await _catalog_service.http.registry_list_servers(
        category=category or None,
        auth_type=auth_type or None,
        provider=provider or None,
        search=search or None,
        limit=limit,
        offset=offset,
    )
    if data is None:
        return {
            "servers": [], "total": 0, "categories": [], "auth_types": [],
            "providers": [], "all_tags": [],
        }
    return data


@router.post("/registry/{server_id}/register")
async def agentic_registry_register(
    server_id: str,
    request: Request,
    _key: str = Depends(require_api_key),
):
    """Register a public MCP server from the Forge catalog into Context Forge.

    Proxies POST /admin/mcp-registry/{server_id}/register.
    After success, the server appears as a gateway in the installed catalog.

    Accepts an optional JSON body with:
      - api_key: credential for API Key / OAuth2.1 & API Key servers
      - name: optional display name override
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    # Parse optional body (may be empty for Open / OAuth servers)
    api_key_for_server = None
    name_override = None
    try:
        body = await request.json()
        api_key_for_server = body.get("api_key")
        name_override = body.get("name")
    except Exception:
        pass  # No body or invalid JSON — fine for Open / OAuth

    result = await _catalog_service.http.registry_register_server(
        server_id,
        api_key=api_key_for_server,
        name=name_override,
    )
    if result is None:
        raise HTTPException(status_code=502, detail="Forge not reachable")

    status_code = result.pop("_status", 200)
    if status_code >= 400:
        detail = result.get("message") or result.get("error") or result.get("detail") or "Registration failed"
        raise HTTPException(status_code=status_code, detail=detail)

    _catalog_service.invalidate()
    return result


@router.post("/registry/{server_id}/unregister")
async def agentic_registry_unregister(
    server_id: str,
    _key: str = Depends(require_api_key),
):
    """Unregister (remove) a catalog MCP server from Context Forge.

    Works with the original Context Forge — no custom endpoints required.
    Uses multiple strategies to find and delete the matching gateway:
      1. Search gateways by name via /admin/gateways/search
      2. List all gateways via /admin/gateways and match by URL/name/hostname
    Then deletes via the standard POST /admin/gateways/{id}/delete.
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    http = _catalog_service.http

    # Step 1: find the catalog server details from registry listing.
    # Note: Forge search matches name/description, not ID. IDs use hyphens
    # (e.g., "cloudflare-docs") while names use spaces ("Cloudflare Docs").
    # We fetch all servers and match by ID locally.
    registry_data = await http.registry_list_servers(limit=200)
    if registry_data is None:
        raise HTTPException(status_code=502, detail="Forge not reachable")

    target_url = None
    target_name = server_id
    for s in registry_data.get("servers", []):
        if s.get("id") == server_id:
            target_url = s.get("url", "")
            target_name = s.get("name", server_id)
            break

    if not target_url:
        # Retry with higher limit in case of pagination
        registry_data2 = await http.registry_list_servers(limit=500)
        if registry_data2:
            for s in registry_data2.get("servers", []):
                if s.get("id") == server_id:
                    target_url = s.get("url", "")
                    target_name = s.get("name", server_id)
                    break

    if not target_url:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found in catalog")

    logger.info(
        "Unregister %s: target_url=%s target_name=%s",
        server_id, target_url, target_name,
    )

    # Step 2: find the matching gateway — try multiple approaches
    gateway_id = None
    from urllib.parse import urlparse

    # ── Approach A: search gateways by name (fast, targeted) ──
    search_result = await http.search_gateways(target_name, include_inactive=True)
    if search_result and isinstance(search_result.get("gateways"), list):
        target_url_stripped = target_url.rstrip("/")
        target_host = urlparse(target_url).hostname or ""
        for gw in search_result["gateways"]:
            gw_url = (gw.get("url") or "").rstrip("/")
            gw_name = (gw.get("name") or "").lower()
            gw_host = urlparse(gw.get("url") or "").hostname or ""
            if (
                gw_url == target_url_stripped
                or gw_name == target_name.lower()
                or (target_host and gw_host == target_host)
            ):
                gateway_id = gw.get("id")
                logger.info("Unregister: found via search: gw_id=%s name=%s url=%s", gateway_id, gw.get("name"), gw.get("url"))
                break

    # ── Approach B: list all gateways (paginated) and match ──
    if not gateway_id:
        gateways_data = await http.list_gateways_best_effort()
        if gateways_data is not None:
            # Extract gateway list from paginated response
            gw_list = []
            if isinstance(gateways_data, list):
                gw_list = gateways_data
            else:
                for key in ("data", "gateways", "items", "results"):
                    if isinstance(gateways_data.get(key), list):
                        gw_list = gateways_data[key]
                        break

            logger.info("Unregister %s: listing found %d gateways", server_id, len(gw_list))

            target_url_stripped = target_url.rstrip("/")
            target_name_lower = target_name.lower()
            target_host = urlparse(target_url).hostname or ""
            sid_lower = server_id.lower()

            for gw in gw_list:
                gw_url = (gw.get("url") or "").rstrip("/")
                gw_name = (gw.get("name") or "").lower()
                gw_host = urlparse(gw.get("url") or "").hostname or ""

                if (
                    gw_url == target_url_stripped                 # exact URL
                    or gw_name == target_name_lower               # exact name
                    or (target_host and gw_host == target_host)   # hostname
                    or sid_lower in gw_name                       # partial server_id
                    or target_name_lower in gw_name               # partial catalog name
                ):
                    gateway_id = gw.get("id")
                    logger.info("Unregister: found via listing: gw_id=%s name=%s url=%s", gateway_id, gw.get("name"), gw.get("url"))
                    break

            if not gateway_id:
                gw_debug = [(gw.get("name", "?"), gw.get("url", "?")) for gw in gw_list[:20]]
                logger.warning("Unregister %s: no match in %d gateways. First 20: %s", server_id, len(gw_list), gw_debug)
        else:
            logger.warning("Unregister %s: gateway listing returned None (auth or network issue)", server_id)

    if not gateway_id:
        raise HTTPException(
            status_code=404,
            detail=f"Server '{target_name}' is not currently registered (no matching gateway found)",
        )

    # Step 3: delete via the standard gateway delete endpoint
    del_result = await http.delete_gateway(gateway_id)
    if del_result is None:
        raise HTTPException(status_code=502, detail="Forge not reachable for gateway deletion")

    del_status = del_result.get("_status", 200)
    if del_status >= 400:
        detail = del_result.get("message") or del_result.get("error") or del_result.get("detail") or "Gateway deletion failed"
        raise HTTPException(status_code=del_status, detail=detail)

    _catalog_service.invalidate()
    return {"success": True, "message": f"Successfully unregistered {target_name}"}


# ── MCP Server Configuration ──────────────────────────────────────────────────
# Get/set credentials for optional MCP servers that require config (OAuth,
# API tokens, etc.).  Config is stored in each server's .env file and
# optionally in the per-user secrets vault.


@router.get("/servers/{server_id}/config")
async def agentic_server_config(server_id: str, _key: str = Depends(require_api_key)):
    """Return the config schema and current (masked) values for a server.

    Only meaningful for servers with `requires_config` set in the catalog.
    Returns schema fields, setup guide, and whether the server is already configured.
    """
    mgr = get_server_manager()
    server = mgr.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_id}")
    if not server.requires_config:
        return {"server_id": server_id, "requires_config": None, "configured": True, "fields": []}
    return read_server_config(server_id, server.requires_config)


@router.post("/servers/{server_id}/config")
async def agentic_server_config_save(
    server_id: str,
    request: Request,
    _key: str = Depends(require_api_key),
):
    """Save config for a server, then restart it.

    Expects JSON body: { "fields": { "KEY": "value", ... } }
    Saves to the server's .env file, then stops + starts the server process.
    Returns the restart result including health check.
    """
    mgr = get_server_manager()
    server = mgr.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_id}")
    if not server.requires_config:
        raise HTTPException(status_code=400, detail=f"Server '{server_id}' does not require configuration")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    values = body.get("fields", {})
    if not isinstance(values, dict):
        raise HTTPException(status_code=400, detail="'fields' must be a JSON object")

    # Validate
    validation = validate_config(server.requires_config, values)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail="; ".join(validation["errors"]))

    # Save
    save_result = save_server_config(server_id, server.requires_config, values)
    if not save_result.get("ok"):
        raise HTTPException(status_code=500, detail=save_result.get("error", "Save failed"))

    # Restart the server if it was installed
    restarted = False
    healthy = False
    if mgr.is_installed(server_id):
        mgr._stop_process(server_id)
        result = await mgr.install(
            server_id,
            forge_url=_FORGE_URL,
            auth_user=_AUTH_USER,
            auth_pass=_AUTH_PASS,
            bearer_token=_TOKEN or None,
        )
        restarted = True
        healthy = result.get("healthy", False)
        _catalog_service.invalidate()

    return {
        "ok": True,
        "saved": True,
        "restarted": restarted,
        "healthy": healthy,
    }


@router.post("/servers/{server_id}/config/test")
async def agentic_server_config_test(
    server_id: str,
    request: Request,
    _key: str = Depends(require_api_key),
):
    """Validate server config without saving (dry-run).

    Checks that required fields are present and basic format validation passes.
    Does NOT write to .env or restart the server.
    """
    mgr = get_server_manager()
    server = mgr.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail=f"Unknown server: {server_id}")
    if not server.requires_config:
        return {"valid": True, "errors": []}

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    values = body.get("fields", {})
    return validate_config(server.requires_config, values)


# ── MCP Server Management ────────────────────────────────────────────────────
# Install/uninstall optional MCP servers on-the-fly.


@router.get("/servers/available")
async def agentic_servers_available(_key: str = Depends(require_api_key)):
    """List all MCP servers (core + optional) with install/health status."""
    mgr = get_server_manager()
    return await mgr.get_available()


@router.post("/servers/{server_id}/install")
async def agentic_server_install(server_id: str, _key: str = Depends(require_api_key)):
    """Install an optional MCP server: start process, register tools in Forge.

    After install, triggers a full sync to update virtual server tool associations.
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    mgr = get_server_manager()
    result = await mgr.install(
        server_id,
        forge_url=_FORGE_URL,
        auth_user=_AUTH_USER,
        auth_pass=_AUTH_PASS,
        bearer_token=_TOKEN or None,
    )

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Install failed"))

    # Trigger full sync to update virtual server tool associations
    if result.get("status") == "installed":
        try:
            sync_result = await sync_homepilot(
                base_url=_FORGE_URL,
                auth_user=_AUTH_USER,
                auth_pass=_AUTH_PASS,
                bearer_token=_TOKEN or None,
            )
            result["sync"] = {
                "tools_total": sync_result.get("tools_total_in_forge", 0),
                "virtual_servers_updated": sync_result.get("virtual_servers_updated", 0),
            }
        except Exception as exc:
            result["sync_error"] = str(exc)
        _catalog_service.invalidate()

    return result


@router.post("/servers/{server_id}/uninstall")
async def agentic_server_uninstall(server_id: str, _key: str = Depends(require_api_key)):
    """Uninstall an optional MCP server: deactivate tools, stop process.

    After uninstall, triggers a sync to update virtual server associations.
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    mgr = get_server_manager()
    result = await mgr.uninstall(
        server_id,
        forge_url=_FORGE_URL,
        auth_user=_AUTH_USER,
        auth_pass=_AUTH_PASS,
        bearer_token=_TOKEN or None,
    )

    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Uninstall failed"))

    # Trigger sync to refresh virtual server associations
    try:
        sync_result = await sync_homepilot(
            base_url=_FORGE_URL,
            auth_user=_AUTH_USER,
            auth_pass=_AUTH_PASS,
            bearer_token=_TOKEN or None,
        )
        result["sync"] = {
            "tools_total": sync_result.get("tools_total_in_forge", 0),
            "virtual_servers_updated": sync_result.get("virtual_servers_updated", 0),
        }
    except Exception as exc:
        result["sync_error"] = str(exc)
    _catalog_service.invalidate()

    return result


@router.get("/servers/external/{server_name}/uninstall-preview")
async def agentic_external_uninstall_preview(server_name: str, _key: str = Depends(require_api_key)):
    """Preview what will happen if an external MCP server is uninstalled.

    Returns affected personas, tools that will be deactivated, and warnings.
    Safe to call — does not make any changes.
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    from .mcp_uninstaller import preview_uninstall
    from .mcp_installer import _find_in_external_registry

    entry = _find_in_external_registry(server_name)
    port = entry.get("port") if entry else None

    preview = await preview_uninstall(
        server_name,
        server_port=port,
        forge_url=_FORGE_URL,
        auth_user=_AUTH_USER,
        auth_pass=_AUTH_PASS,
        bearer_token=_TOKEN or None,
    )
    return preview.to_dict()


@router.post("/servers/external/{server_name}/uninstall")
async def agentic_external_server_uninstall(server_name: str, _key: str = Depends(require_api_key)):
    """Uninstall an external/community MCP server.

    Full lifecycle:
      1. Scan affected personas and warn
      2. Deactivate tools in Context Forge
      3. Stop server process
      4. Record disabled tools (so reinstall can re-enable them)
      5. Mark as uninstalled in registry
      6. Sync with Forge to update virtual servers

    Personas that depended on this server will have their tools disabled
    automatically. Reinstalling the server or re-importing the persona
    will re-enable them.
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    from .mcp_uninstaller import uninstall_external_server

    result = await uninstall_external_server(
        server_name,
        forge_url=_FORGE_URL,
        auth_user=_AUTH_USER,
        auth_pass=_AUTH_PASS,
        bearer_token=_TOKEN or None,
    )

    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error or "Uninstall failed")

    _catalog_service.invalidate()
    return result.to_dict()


@router.post("/servers/external/{server_name}/restart")
async def agentic_external_restart(server_name: str, _key: str = Depends(require_api_key)):
    """Restart a stopped external server without reinstalling.

    Finds the server in the external registry and uses the same startup
    logic as auto_start_external() to relaunch the process.
    """
    from .server_manager import get_server_manager
    mgr = get_server_manager()

    # Run auto-start which skips already-healthy servers
    started = await mgr.auto_start_external()

    if server_name in started:
        return {"status": "started", "server_name": server_name}

    # Check if it's now healthy (may have already been running)
    from .mcp_installer import _read_external_registry
    reg = _read_external_registry()
    entry = next((s for s in reg.get("servers", []) if s.get("name") == server_name), None)
    if entry and entry.get("port"):
        healthy = await mgr._check_health(entry["port"], timeout=3)
        if healthy:
            return {"status": "already_running", "server_name": server_name}

    return {"status": "failed", "server_name": server_name, "error": "Server did not start"}


@router.post("/servers/external/{server_name}/reinstall")
async def agentic_external_reinstall(server_name: str, _key: str = Depends(require_api_key)):
    """Reinstall a previously uninstalled external server.

    Re-starts the server from its existing install_path, re-discovers
    tools, and sets status back to "installed" in the registry.
    """
    if not _ENABLED:
        raise HTTPException(status_code=503, detail="Agentic features are disabled")

    from .mcp_installer import _read_external_registry, _write_external_registry

    reg = _read_external_registry()
    entry = next((s for s in reg.get("servers", []) if s.get("name") == server_name), None)
    if not entry:
        raise HTTPException(status_code=404, detail=f"External server '{server_name}' not in registry")

    # Mark as installed so auto_start_external can pick it up
    entry["status"] = "installed"
    _write_external_registry(reg)

    # Use auto_start_external to start the server
    mgr = get_server_manager()
    started = await mgr.auto_start_external()

    if server_name in started:
        # Re-discover and register tools in Forge
        port = entry.get("port")
        if port:
            try:
                tools = await mgr._discover_tools(port)
                tool_ids = await mgr._register_tools_in_forge(
                    tools, port, _FORGE_URL, _AUTH_USER, _AUTH_PASS, _TOKEN or None,
                )
                # Sync
                await sync_homepilot(
                    base_url=_FORGE_URL, auth_user=_AUTH_USER,
                    auth_pass=_AUTH_PASS, bearer_token=_TOKEN or None,
                )
                _catalog_service.invalidate()
                return {
                    "ok": True, "status": "installed", "server_name": server_name,
                    "tools_discovered": len(tools), "tools_registered": len(tool_ids),
                }
            except Exception as exc:
                return {"ok": True, "status": "installed", "server_name": server_name, "sync_error": str(exc)}
        return {"ok": True, "status": "installed", "server_name": server_name}

    # Failed to start — revert status
    entry["status"] = "uninstalled"
    _write_external_registry(reg)
    raise HTTPException(status_code=500, detail=f"Failed to restart server '{server_name}'")


@router.get("/servers/external/{server_name}/disabled-tools")
async def agentic_external_disabled_tools(server_name: str, _key: str = Depends(require_api_key)):
    """Check if a server was previously uninstalled and has disabled tools.

    Returns the disabled tools record if it exists, or null if the server
    was never uninstalled (or tools were already re-enabled).
    Useful for the frontend to show a "re-enable tools" prompt on reinstall.
    """
    from .mcp_uninstaller import get_disabled_tools
    record = get_disabled_tools(server_name)
    return {"server_name": server_name, "disabled": record}


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

    # Phase 7: resolve capability → tool_id via RuntimeToolRouter
    # when the project has a tool_source configured.  Falls back to
    # legacy behavior (invoke by intent name) if tool_source is not set.
    tool_source = body.args.pop("tool_source", None)
    router_instance = _tool_router()
    decision = await router_instance.resolve(body.intent, tool_source)

    if decision.mode != "fallback":
        if decision.mode == "none":
            return InvokeOut(
                ok=False,
                conversation_id=body.conversation_id or "",
                assistant_text="This agent is configured with no tools.",
                meta={"intent": body.intent, "mode": decision.mode, "reason": decision.reason},
            )
        if decision.resolved_tool_id is None:
            return InvokeOut(
                ok=False,
                conversation_id=body.conversation_id or "",
                assistant_text=decision.reason,
                meta={"intent": body.intent, "mode": decision.mode, "reason": decision.reason},
            )
        # Use resolved tool_id instead of intent name
        result = await client.invoke_tool(decision.resolved_tool_id, merged_args)
    else:
        # Legacy fallback: invoke by intent name (unchanged behavior)
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


# ── GET /v1/agentic/servers/install-logs ─────────────────────────────────
# Provides detailed installation logs for tracking external MCP server
# installation progress (clone, deps, start, health, discover, register).


@router.get("/servers/install-logs")
async def agentic_install_logs(
    server: str = "",
    since: int = 0,
    _key: str = Depends(require_api_key),
):
    """Return installation logs for MCP servers.

    Query params:
      - server: filter to a specific server name (optional)
      - since:  return entries starting from this index (for polling)

    Returns all servers' logs if no server name given.
    """
    from .mcp_installer import install_logger

    if server:
        return {
            "server": server,
            "logs": install_logger.get_logs(server, since_idx=since),
            "log_file": install_logger.get_log_file(server),
        }

    # Return logs for all servers
    servers = install_logger.get_all_servers()
    return {
        "servers": servers,
        "logs": {
            s: install_logger.get_logs(s, since_idx=since) for s in servers
        },
    }
