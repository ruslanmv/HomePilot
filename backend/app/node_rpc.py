"""
HomePilot Node RPC — Phase 2 (read-only mirror) of the OllaBridge Cloud Mirror.

The control-plane half of the execution mirror: OllaBridge Local invokes
NAMED, read-only operations here to answer the cloud UI's "show me this PC's
resources" requests. This is deliberately NOT a localhost proxy - the relay
can only call operations that appear in this whitelist, never an arbitrary
URL, port, path, or shell command (design §6, §20.5).

Design: docs/design/ollabridge-cloud-mirror/README.md (Phase 2)

Guardrails, all enforced + tested:
  - localhost only (shares node_manifest's guard) + feature-flagged
    (HOMEPILOT_MIRROR_RPC_ENABLED, default off)
  - read-only in this phase: every registered op is a getter; there is no
    write path here at all
  - no secrets: settings.get_safe returns a curated allowlist; personas and
    projects go through projections that strip credentials
  - every op declares a scope, so Phase 4's authorization has a hook already
  - responses carry a {source, data} envelope so the cloud can label which
    node answered (design §13)

Strictly ADDITIVE - only reads existing modules; changes none.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .node_manifest import _is_localhost, _node_id, _node_name

router = APIRouter(tags=["node-rpc"])


def _flag_enabled() -> bool:
    return os.getenv("HOMEPILOT_MIRROR_RPC_ENABLED", "false").strip().lower() in (
        "1", "true", "yes")


# ── Operation registry ───────────────────────────────────────────────────────

# op_name -> (scope, handler). Handlers take a params dict and return JSON-safe
# data. Read-only by construction in Phase 2.
_OPS: Dict[str, "RpcOp"] = {}


class RpcOp(BaseModel):
    scope: str
    handler: Callable[[Dict[str, Any]], Any]

    model_config = {"arbitrary_types_allowed": True}


def op(name: str, scope: str) -> Callable[[Callable], Callable]:
    def deco(fn: Callable[[Dict[str, Any]], Any]) -> Callable:
        _OPS[name] = RpcOp(scope=scope, handler=fn)
        return fn
    return deco


class RpcRequest(BaseModel):
    operation: str
    params: Dict[str, Any] = Field(default_factory=dict)


# ── Read-only operations ─────────────────────────────────────────────────────

@op("services.health", scope="node:read")
def _services_health(_: Dict[str, Any]) -> Any:
    from .node_manifest import _services
    return _services()


@op("node.manifest", scope="catalog:read")
def _node_manifest(_: Dict[str, Any]) -> Any:
    from .node_manifest import build_manifest
    return build_manifest()


@op("models.list", scope="catalog:read")
def _models_list(_: Dict[str, Any]) -> Any:
    from .node_manifest import _chat_models, _image_models, _video_models
    return {"chat_models": _chat_models(),
            "image_models": _image_models(),
            "video_models": _video_models()}


@op("personas.list", scope="persona:read")
def _personas_list(_: Dict[str, Any]) -> Any:
    # The owner mirror catalog: ALL personas with both permission flags -
    # distinct from /v1/models, which lists only shared_api-published ones.
    from .node_manifest import _personas
    return _personas()


@op("projects.list", scope="project:read")
def _projects_list(_: Dict[str, Any]) -> Any:
    return [_project_projection(p) for p in _all_projects()]


@op("projects.get", scope="project:read")
def _projects_get(params: Dict[str, Any]) -> Any:
    pid = str(params.get("id", ""))
    for p in _all_projects():
        if p.get("id") == pid:
            return _project_projection(p, detailed=True)
    return None


@op("workflows.list", scope="catalog:read")
def _workflows_list(_: Dict[str, Any]) -> Any:
    from .node_manifest import _workflows
    return _workflows()


# Settings that are SAFE to expose to remote control. Anything not on this
# allowlist (API keys, MCP OAuth tokens, DB creds, device keys) is never
# returned - design §13.
_SAFE_SETTING_KEYS = (
    "HOMEPILOT_EDITION", "HOMEPILOT_VERSION", "OLLAMA_BASE_URL",
    "COMFY_BASE_URL", "NSFW_MODE",
)


@op("settings.get_safe", scope="node:read")
def _settings_get_safe(_: Dict[str, Any]) -> Any:
    out: Dict[str, Any] = {}
    for key in _SAFE_SETTING_KEYS:
        val = os.getenv(key)
        if val is not None:
            out[key] = val
    # Report MCP connection *status* without ever returning credentials.
    out["mcp_connections"] = _mcp_connection_status()
    return out


# ── Projections (credential-stripping) ───────────────────────────────────────

# Keys that must never leave the node in any projection.
_FORBIDDEN_KEYS = {
    "api_key", "apikey", "secret", "token", "password", "credential",
    "credentials", "private_key", "oauth", "refresh_token", "access_token",
    "shared_api",  # contains publish config; the flag is surfaced separately
    "files",       # raw file blobs stay local
}


def _all_projects() -> List[Dict[str, Any]]:
    try:
        from . import projects as projects_mod
        return projects_mod.list_all_projects()
    except Exception:
        return []


def _scrub(value: Any) -> Any:
    """Recursively drop any key whose name looks credential-bearing. Recursion
    matters: a nested structure (e.g. mcp_servers[].oauth) would otherwise
    leak a secret the top-level key name didn't reveal."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()
                if not any(bad in k.lower() for bad in _FORBIDDEN_KEYS)}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def _project_projection(proj: Dict[str, Any], detailed: bool = False) -> Dict[str, Any]:
    base = {
        "id": proj.get("id"),
        "name": proj.get("name"),
        "project_type": proj.get("project_type"),
        "description": proj.get("description", ""),
        "updated_at": proj.get("updated_at"),
        "published_to_provider_api": bool((proj.get("shared_api") or {}).get("enabled")),
    }
    if detailed:
        # a scrubbed view of the rest, never the raw dict
        extra = _scrub({k: v for k, v in proj.items() if k not in base})
        base["detail"] = extra
    return base


def _mcp_connection_status() -> List[Dict[str, str]]:
    """Names + connected/disconnected only - never the credentials."""
    try:
        from . import projects as projects_mod  # MCP config lives per-project
        seen: Dict[str, bool] = {}
        for p in projects_mod.list_all_projects():
            for srv in (p.get("mcp_servers") or []):
                if isinstance(srv, dict) and srv.get("name"):
                    seen[srv["name"]] = bool(srv.get("connected") or srv.get("enabled"))
        return [{"name": n, "status": "connected" if c else "disconnected"}
                for n, c in seen.items()]
    except Exception:
        return []


# ── Dispatch ─────────────────────────────────────────────────────────────────

def dispatch(operation: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run a whitelisted read-only op and wrap it in the source envelope.
    Raises KeyError for unknown operations (no arbitrary proxy)."""
    if operation not in _OPS:
        raise KeyError(operation)
    data = _OPS[operation].handler(params or {})
    return {
        "source": {"type": "homepilot_node",
                   "node_id": _node_id(), "node_name": _node_name()},
        "operation": operation,
        "data": data,
    }


def available_operations() -> List[Dict[str, str]]:
    return [{"operation": name, "scope": o.scope} for name, o in sorted(_OPS.items())]


# ── Endpoints (localhost only, feature-flagged) ──────────────────────────────

def _guard(request: Request) -> Optional[JSONResponse]:
    if not _flag_enabled():
        return JSONResponse(status_code=404, content={"error": "node_rpc_disabled"})
    if not _is_localhost(request):
        return JSONResponse(status_code=403,
                            content={"error": "node_rpc_local_only",
                                     "message": "Node RPC is served to localhost / "
                                                "the local sidecar only."})
    return None


@router.get("/v1/node/rpc/operations")
def list_operations(request: Request):
    """The whitelist of callable read-only operations and their scopes."""
    blocked = _guard(request)
    if blocked is not None:
        return blocked
    return {"operations": available_operations()}


@router.post("/v1/node/rpc")
def node_rpc(req: RpcRequest, request: Request):
    """Invoke one named read-only operation. Unknown operations 400 (the
    relay can never reach anything not on the whitelist)."""
    blocked = _guard(request)
    if blocked is not None:
        return blocked
    try:
        return dispatch(req.operation, req.params)
    except KeyError:
        return JSONResponse(status_code=400,
                            content={"error": "unknown_operation",
                                     "operation": req.operation,
                                     "message": "Operation is not in the read-only "
                                                "mirror whitelist."})
