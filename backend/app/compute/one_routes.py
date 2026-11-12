"""HomePilot One — per-user routing settings and the startup handshake.

    GET  /v1/routing            my strategy, spending rules, effective priority, usage
    PUT  /v1/routing            change my own preferences
    GET  /v1/ecosystem/status   one lightweight snapshot of everything I can use
    GET  /v1/ecosystem/catalog  the unified capability catalog (from OllaBridge)

Everything here is scoped to the signed-in user. No secret is ever returned:
linked accounts are reported as booleans and display names only.

The handshake never blocks the app: each external check has a short timeout,
runs concurrently, and a slow or unreachable service is reported as such
rather than awaited.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import registry, routing

router = APIRouter(tags=["homepilot-one"])

_PROBE_TIMEOUT_S = 4.0


def _user() -> str:
    from ..connectors.context import current_user_id
    uid = current_user_id()
    if not uid:
        raise HTTPException(status_code=401, detail="Sign in first")
    return uid


class PrefsIn(BaseModel):
    strategy: Optional[str] = None
    allow_paid: Optional[bool] = None
    max_request_cost_usd: Optional[float] = None
    daily_budget_usd: Optional[float] = None
    monthly_budget_usd: Optional[float] = None
    use_my_devices: Optional[bool] = None


@router.get("/v1/routing")
def get_routing(user_id: str = Depends(_user)) -> dict[str, Any]:
    return {"ok": True, **routing.describe(user_id), "usage": routing.usage_summary(user_id)}


@router.put("/v1/routing")
def put_routing(body: PrefsIn, user_id: str = Depends(_user)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    try:
        routing.save_prefs(user_id, changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **routing.describe(user_id), "usage": routing.usage_summary(user_id)}


async def _gateway_get(path: str, token: str, *, timeout: float = _PROBE_TIMEOUT_S,
                       transport: httpx.BaseTransport | None = None) -> tuple[int, Any]:
    base = (registry.load_settings().cloud_url or "").rstrip("/")
    if not base:
        return 0, None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(base_url=base, timeout=timeout, transport=transport) as client:
            r = await client.get(path, headers=headers)
            try:
                return r.status_code, r.json()
            except Exception:
                return r.status_code, None
    except Exception:
        return 0, None


def _hf_section(user_id: str) -> dict[str, Any]:
    from ..connectors import huggingface as hf, store
    linked = next((c for c in store.linked(user_id) if c.get("id") == hf.ID), None)
    operator = bool(hf.shared_token())
    return {
        "linked": bool(linked),
        "account": (linked or {}).get("account") or (linked or {}).get("name"),
        "operator_token": operator,
        "usable": bool(linked) or operator,
        "billed_to": "your account" if linked else ("the operator" if operator else None),
        # Hugging Face exposes no balance API; what HomePilot knows is what it
        # has recorded itself, and only when the operator set the allowance.
        "quota_status": "tracked" if routing._env_float("HOMEPILOT_HF_INCLUDED_USD") is not None
        else "unknown",
        "modalities": ["chat", "vision", "image", "video"] if (linked or operator) else [],
    }


@router.get("/v1/ecosystem/status")
async def ecosystem_status(user_id: str = Depends(_user)) -> dict[str, Any]:
    settings = registry.load_settings()
    own_cloud = routing._user_cloud_token(user_id)
    call = routing.build_gateway_call(user_id)

    health, catalog, nodes = await asyncio.gather(
        _gateway_get("/health", ""),
        _gateway_get("/v1/catalog", call.token) if call.token else asyncio.sleep(0, (0, None)),
        _gateway_get("/v1/account/compute-nodes", own_cloud) if own_cloud
        else asyncio.sleep(0, (0, None)),
    )

    providers: list[dict[str, Any]] = []
    models = 0
    if catalog[0] == 200 and isinstance(catalog[1], dict):
        providers = catalog[1].get("providers") or []
        models = len(catalog[1].get("models") or [])

    devices: list[dict[str, Any]] = []
    if nodes[0] == 200 and isinstance(nodes[1], dict):
        for node in nodes[1].get("nodes") or nodes[1].get("devices") or []:
            devices.append({
                "id": node.get("id") or node.get("device_id"),
                "name": node.get("name") or node.get("label"),
                "online": bool(node.get("online")),
                "gpu": node.get("gpu_name") or node.get("gpu"),
                "models": len(node.get("models") or []),
            })

    info = routing.describe(user_id)
    return {
        "ok": True,
        "edition": "web" if routing.is_web() else "local",
        "huggingface": _hf_section(user_id),
        "ollabridge": {
            "url": settings.cloud_url,
            "reachable": health[0] == 200,
            "account_linked": bool(own_cloud),
            "catalog": "ready" if catalog[0] == 200 else
                       ("unavailable" if call.token else "not_linked"),
            "models": models,
        },
        "providers": providers,
        "devices": {
            "linked": bool(own_cloud),
            "items": devices,
            "online": sum(1 for d in devices if d["online"]),
            "sharing": info["effective"]["use_my_devices"],
        },
        "routing": {
            "strategy": info["effective"]["strategy"],
            "priority": info["priority"],
            "allow_paid": info["effective"]["allow_paid"],
            "paid_allowed_by_operator": info["operator"]["paid_allowed"],
        },
        "usage": routing.usage_summary(user_id),
        "storage": _storage_section(),
    }


def _storage_section() -> dict[str, Any]:
    try:
        from .. import durable_storage
        info = durable_storage.describe()
        return {"durable": info["durable"], "warning": info["warning"],
                "last_backup_at": info["last_backup_at"]}
    except Exception:
        return {"durable": None, "warning": None, "last_backup_at": None}


@router.get("/v1/ecosystem/catalog")
async def ecosystem_catalog(user_id: str = Depends(_user)) -> dict[str, Any]:
    """The unified capability catalog, as OllaBridge sees it for this user."""
    call = routing.build_gateway_call(user_id)
    if not call.token:
        raise HTTPException(status_code=503, detail={
            "error": "missing_credentials", "message": "OllaBridge Cloud is not linked."})
    status, body = await _gateway_get("/v1/catalog", call.token, timeout=10.0)
    if status != 200 or not isinstance(body, dict):
        raise HTTPException(status_code=502, detail={
            "error": "provider_unavailable", "message": "The model catalog is not available."})
    return body
