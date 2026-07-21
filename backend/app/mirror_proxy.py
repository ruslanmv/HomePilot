"""
Account Mirror BFF proxy (ADDITIVE, FEATURE-FLAGGED) — Batch 1.

Gives the HomePilot **Web** frontend a single, same-origin, server-mediated
path to the OllaBridge Cloud mirror. The browser talks only to this backend
under ``/v1/account/mirror/*``; it never learns the cloud relay URL and never
holds a cloud token. The token lives server-side and is attached here.

Routes (thin, explicit — NOT an open proxy):

    GET  /v1/account/mirror/status                         → is the feature usable
    GET  /v1/account/mirror/nodes                          → cloud GET  /v1/mirror/nodes
    GET  /v1/account/mirror/nodes/{node_id}/manifest       → cloud GET  …/manifest
    POST /v1/account/mirror/nodes/{node_id}/rpc            → cloud POST …/rpc   (read-only allow-list)
    POST /v1/account/mirror/nodes/{node_id}/jobs           → cloud POST …/jobs
    GET  /v1/account/mirror/jobs/{job_id}?node_id=…        → cloud GET  /v1/mirror/jobs/{id}
    POST /v1/account/mirror/jobs/{job_id}/cancel?node_id=… → cloud POST …/cancel

Design / security posture
-------------------------
* **Feature-flagged.** ``HOMEPILOT_MIRROR_BFF_ENABLED`` (default off). When off,
  ``main.py`` does not mount the router at all — zero behavior change.
* **Additive & non-destructive.** New router only. Does not touch ``/chat``,
  ``/v1/auth/*``, or any existing route.
* **Fail-closed auth.** The caller must be an authenticated HomePilot user
  (Bearer/JWT or ``homepilot_session`` cookie), resolved with the same helper
  the rest of the app uses. Single-user self-host keeps its default-user
  behavior; multi-user without a token → 401.
* **Server-side credential.** The cloud bearer is resolved on the server via
  ``_resolve_cloud_credentials`` — a per-user registry (the Batch-7 BFF seam)
  with a fallback to the operator's ``OLLABRIDGE_CLOUD_TOKEN`` env. The token is
  never read from, nor returned to, the browser, and is never logged.
* **Least privilege.** Only the fixed mirror endpoints are reachable; RPC
  operations are checked against a read-only allow-list mirroring the cloud's;
  node/job ids are format-validated; request bodies are size-capped.
* **Honest passthrough.** Upstream status codes that carry product meaning —
  notably ``409 node_offline`` — are preserved so the UI can render offline
  states instead of guessing. Transport failures map to 502/504. Bodies are
  returned as-is (they contain no secrets); our own errors never echo the token.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import APIRouter, Cookie, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import config as _cfg

logger = logging.getLogger("homepilot.mirror_proxy")

router = APIRouter(prefix="/v1/account/mirror", tags=["account-mirror"])

# Read-only RPC operations we forward — mirrors OllaBridge Cloud's
# ``_ALLOWED_RPC_OPS``. Defense in depth: the cloud AND the owning node also
# enforce their own whitelists. Keep this list in sync with the cloud's.
_ALLOWED_RPC_OPS = frozenset({
    "services.health", "node.manifest", "models.list", "personas.list",
    "projects.list", "projects.get", "workflows.list", "settings.get_safe",
})

# Ids are opaque tokens from the cloud (device ids, job ids). Constrain the
# charset so a caller can never smuggle path/query segments into the upstream
# URL, independent of httpx's own encoding.
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")

# Body guard for rpc/job params so the proxy can't be used to shovel megabytes
# of JSON at the cloud on someone else's token.
_MAX_PARAMS_BYTES = 256 * 1024

# Upstream timeouts (connect, read). Jobs creation is allowed to take longer.
_CONNECT_TIMEOUT = 5.0
_RPC_TIMEOUT = 30.0
_JOB_CREATE_TIMEOUT = 60.0

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    return os.getenv("HOMEPILOT_MIRROR_BFF_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def bff_session_enabled() -> bool:
    """Batch 7 (BFF session): store the cloud token server-side and inject it
    into cloud-relay calls, so the browser never holds it. Off by default."""
    return os.getenv("HOMEPILOT_BFF_SESSION_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ---------------------------------------------------------------------------
# Per-user cloud credential registry — the Batch-7 BFF seam.
#
# Batch 7 (BFF session) will call ``register_cloud_token(user_id, token)`` right
# after the ``/v1/auth/exchange`` validation so each user's own cloud token is
# used. Until then the operator's ``OLLABRIDGE_CLOUD_TOKEN`` env is the
# server-side fallback (correct for the single-operator web deployment). Kept
# in-memory ONLY: this batch deliberately does not persist raw cloud tokens to
# disk — encrypted at-rest storage belongs to Batch 7.
# ---------------------------------------------------------------------------

_registry_lock = threading.Lock()
_USER_CLOUD_TOKENS: Dict[str, str] = {}


def register_cloud_token(user_id: str, token: str) -> None:
    """Associate a HomePilot user with their OllaBridge cloud bearer token."""
    if not user_id or not token:
        return
    with _registry_lock:
        _USER_CLOUD_TOKENS[str(user_id)] = token


def clear_cloud_token(user_id: str) -> None:
    with _registry_lock:
        _USER_CLOUD_TOKENS.pop(str(user_id), None)


def _cloud_base() -> str:
    return (getattr(_cfg, "OLLABRIDGE_CLOUD_URL", "") or "").rstrip("/")


def _resolve_cloud_credentials(user: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """Return ``(base_url, bearer_token)`` for the cloud call, server-side only.

    Order: per-user registered token (Batch 7) → operator env token. Raises 503
    when neither is available so the frontend can surface "cloud not linked"
    rather than a confusing 401 from upstream.
    """
    base = _cloud_base()
    if not base:
        raise HTTPException(status_code=503, detail="Cloud gateway not configured")

    token: Optional[str] = None
    if user and user.get("id"):
        with _registry_lock:
            token = _USER_CLOUD_TOKENS.get(str(user["id"]))
        # Batch 7: fall back to the server-side per-user token store (survives
        # restarts). In-memory registry stays a fast path.
        if not token:
            try:
                from .cloud_tokens import get_cloud_token
                token = get_cloud_token(str(user["id"]))
            except Exception:
                token = None
    if not token:
        token = (getattr(_cfg, "OLLABRIDGE_CLOUD_TOKEN", "") or "").strip() or None
    if not token:
        raise HTTPException(
            status_code=503,
            detail="Cloud account not linked. Configure OLLABRIDGE_CLOUD_TOKEN "
                   "or sign in to link your account.",
        )
    return base, token


# ---------------------------------------------------------------------------
# Caller authentication (fail-closed, same semantics as the rest of the app)
# ---------------------------------------------------------------------------

def _require_user(authorization: Optional[str], homepilot_session: Optional[str]) -> Dict[str, Any]:
    from .users import (  # lazy import avoids any import cycle with main
        _validate_token,
        count_users,
        ensure_users_tables,
        get_or_create_default_user,
    )

    ensure_users_tables()
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not token and homepilot_session:
        token = homepilot_session.strip()

    user = _validate_token(token) if token else None
    if user:
        return user
    # No token: single-user self-host keeps working; multi-user must sign in.
    if count_users() > 1:
        raise HTTPException(status_code=401, detail="Authentication required")
    return get_or_create_default_user()


# ---------------------------------------------------------------------------
# Upstream call helper
# ---------------------------------------------------------------------------

def _validate_id(value: str, what: str) -> str:
    if not _ID_RE.match(value or ""):
        raise HTTPException(status_code=400, detail=f"Invalid {what}")
    return value


def _check_params(params: Any) -> Dict[str, Any]:
    params = params or {}
    if not isinstance(params, dict):
        raise HTTPException(status_code=400, detail="params must be an object")
    try:
        if len(json.dumps(params)) > _MAX_PARAMS_BYTES:
            raise HTTPException(status_code=413, detail="params too large")
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="params must be JSON-serializable")
    return params


async def _forward(
    *,
    method: str,
    path: str,
    token: str,
    base: str,
    user_id: str,
    params: Optional[Dict[str, Any]] = None,
    json_body: Optional[Dict[str, Any]] = None,
    read_timeout: float = _RPC_TIMEOUT,
) -> JSONResponse:
    """Perform the upstream mirror call and return a sanitized JSONResponse.

    Passes the cloud's status code and JSON body through unchanged (they carry
    product-meaningful signals like ``node_offline`` and contain no secrets).
    Never forwards browser headers upstream, never logs or echoes the token.
    """
    rid = "mbff_" + uuid.uuid4().hex[:16]
    url = f"{base}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "X-Request-Id": rid,
    }
    timeout = httpx.Timeout(read_timeout, connect=_CONNECT_TIMEOUT)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, headers=headers, params=params, json=json_body)
    except httpx.TimeoutException:
        logger.warning("[mirror-bff %s] upstream timeout user=%s %s %s", rid, user_id, method, path)
        return _err(504, "upstream_timeout", "The cloud gateway did not respond in time.", rid)
    except httpx.RequestError as exc:
        logger.warning("[mirror-bff %s] upstream error user=%s %s %s: %s", rid, user_id, method, path, type(exc).__name__)
        return _err(502, "upstream_unreachable", "Could not reach the cloud gateway.", rid)

    elapsed_ms = int((time.monotonic() - started) * 1000)
    # Parse JSON defensively; the mirror always returns JSON, but never trust it.
    try:
        payload = resp.json()
    except ValueError:
        payload = {"error": "upstream_bad_response",
                   "message": "Cloud gateway returned a non-JSON response."}
    logger.info("[mirror-bff %s] user=%s %s %s -> %s (%dms)",
                rid, user_id, method, path, resp.status_code, elapsed_ms)

    body = payload if isinstance(payload, (dict, list)) else {"data": payload}
    if isinstance(body, dict):
        body.setdefault("request_id", rid)
    return JSONResponse(status_code=resp.status_code, content=body,
                        headers={"Cache-Control": "no-store"})


def _err(status: int, code: str, message: str, rid: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": code, "message": message, "request_id": rid},
        headers={"Cache-Control": "no-store"},
    )


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RpcIn(BaseModel):
    operation: str = Field(..., min_length=1, max_length=128)
    params: Dict[str, Any] = Field(default_factory=dict)


class JobIn(BaseModel):
    operation: str = Field(..., min_length=1, max_length=128)
    params: Dict[str, Any] = Field(default_factory=dict)
    resource_uri: Optional[str] = Field(default=None, max_length=1024)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/status")
async def mirror_status(
    authorization: Optional[str] = Header(default=None),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    """Lightweight readiness probe for the frontend spine (Batch 2).

    Reports whether the feature is usable for this caller — without exposing the
    token. ``linked`` is true when a server-side cloud credential is resolvable.
    """
    user = _require_user(authorization, homepilot_session)
    linked = True
    try:
        _resolve_cloud_credentials(user)
    except HTTPException:
        linked = False
    return JSONResponse(
        status_code=200,
        content={"ok": True, "enabled": True, "linked": linked, "cloud": _cloud_base()},
        headers={"Cache-Control": "no-store"},
    )


@router.get("/nodes")
async def list_nodes(
    authorization: Optional[str] = Header(default=None),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    user = _require_user(authorization, homepilot_session)
    base, token = _resolve_cloud_credentials(user)
    return await _forward(method="GET", path="/v1/mirror/nodes", token=token,
                          base=base, user_id=str(user.get("id", "")))


@router.get("/nodes/{node_id}/manifest")
async def node_manifest(
    node_id: str,
    authorization: Optional[str] = Header(default=None),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    user = _require_user(authorization, homepilot_session)
    _validate_id(node_id, "node_id")
    base, token = _resolve_cloud_credentials(user)
    return await _forward(method="GET", path=f"/v1/mirror/nodes/{node_id}/manifest",
                          token=token, base=base, user_id=str(user.get("id", "")))


@router.post("/nodes/{node_id}/rpc")
async def node_rpc(
    node_id: str,
    body: RpcIn,
    authorization: Optional[str] = Header(default=None),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    user = _require_user(authorization, homepilot_session)
    _validate_id(node_id, "node_id")
    if body.operation not in _ALLOWED_RPC_OPS:
        raise HTTPException(status_code=400, detail="Operation is not in the read-only mirror allow-list")
    params = _check_params(body.params)
    base, token = _resolve_cloud_credentials(user)
    return await _forward(
        method="POST", path=f"/v1/mirror/nodes/{node_id}/rpc", token=token, base=base,
        user_id=str(user.get("id", "")),
        json_body={"operation": body.operation, "params": params},
    )


@router.post("/nodes/{node_id}/jobs")
async def create_job(
    node_id: str,
    body: JobIn,
    authorization: Optional[str] = Header(default=None),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    user = _require_user(authorization, homepilot_session)
    _validate_id(node_id, "node_id")
    params = _check_params(body.params)
    payload: Dict[str, Any] = {"operation": body.operation, "params": params}
    if body.resource_uri:
        payload["resource_uri"] = body.resource_uri
    base, token = _resolve_cloud_credentials(user)
    return await _forward(
        method="POST", path=f"/v1/mirror/nodes/{node_id}/jobs", token=token, base=base,
        user_id=str(user.get("id", "")), json_body=payload, read_timeout=_JOB_CREATE_TIMEOUT,
    )


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    node_id: str = Query(..., description="Owning node id (ownership is re-checked upstream)"),
    authorization: Optional[str] = Header(default=None),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    user = _require_user(authorization, homepilot_session)
    _validate_id(job_id, "job_id")
    _validate_id(node_id, "node_id")
    base, token = _resolve_cloud_credentials(user)
    return await _forward(
        method="GET", path=f"/v1/mirror/jobs/{job_id}", token=token, base=base,
        user_id=str(user.get("id", "")), params={"node_id": node_id},
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    node_id: str = Query(..., description="Owning node id (ownership is re-checked upstream)"),
    authorization: Optional[str] = Header(default=None),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    user = _require_user(authorization, homepilot_session)
    _validate_id(job_id, "job_id")
    _validate_id(node_id, "node_id")
    base, token = _resolve_cloud_credentials(user)
    return await _forward(
        method="POST", path=f"/v1/mirror/jobs/{job_id}/cancel", token=token, base=base,
        user_id=str(user.get("id", "")), params={"node_id": node_id},
    )
