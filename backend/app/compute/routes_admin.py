"""
Compute admin routes (PR 2).

CRUD for the persisted registry — sources, per-model routes, model manifests —
plus the settings that replaced the env-only global flags, and a
``/resolve`` endpoint that explains how a given request would be routed. These
back the settings UI (PR 3); they are additive and do not touch existing
generation routes.

Credentials are write-only: a source stores only a ``credential_ref``; the
secret is posted separately and kept server-side (``secrets``), never returned.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
from fastapi import APIRouter, Body, Cookie, Depends, Header, HTTPException

from ..auth import require_api_key
from . import registry, secrets
from .netguard import UnsafeEndpointError, validate_outbound_url
from .schemas import (
    ComputeSettings,
    ComputeSource,
    ModelManifest,
    ModelRoute,
)

# Auth follows the app convention (Depends(require_api_key)); the substantive
# hardening for these routes is the SSRF guard on custom endpoint URLs below.
router = APIRouter(
    prefix="/compute/admin", tags=["compute-admin"],
    dependencies=[Depends(require_api_key)],
)


# ---- Cloud sync -------------------------------------------------------------

@router.post("/sync")
async def sync_cloud(
    authorization: Optional[str] = Header(default=None),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> dict:
    """Pull the signed-in user's paired devices + advertised models from
    OllaBridge Cloud into the registry, so Resources and the per-model selector
    show live nodes. Credentials are resolved server-side; the browser never
    holds a cloud token. Reports ``linked=False`` (not an error) when unlinked or
    the cloud is unreachable."""
    from . import sync as cloud_sync
    from ..mirror_proxy import _require_user, _resolve_cloud_credentials

    try:
        user = _require_user(authorization, homepilot_session)
    except HTTPException as exc:
        if exc.status_code == 401:
            return {"ok": False, "linked": False, "reason": "Sign in to sync your devices.", "devices": 0, "models": 0}
        raise
    try:
        base, token = _resolve_cloud_credentials(user)
    except HTTPException as exc:
        if exc.status_code == 503:
            return {"ok": False, "linked": False, "reason": "Link your OllaBridge account first.", "devices": 0, "models": 0}
        raise

    async def fetch(path: str) -> tuple[int, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            r = await client.get(
                f"{base}{path}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            try:
                body = r.json()
            except Exception:
                body = None
            return r.status_code, body

    return await cloud_sync.sync_from_cloud(base, fetch=fetch)


# ---- sources ----------------------------------------------------------------

@router.get("/sources")
async def list_sources() -> dict:
    return {"sources": [s.to_dict() for s in registry.list_sources()]}


@router.post("/sources")
async def upsert_source(body: dict = Body(...)) -> dict:
    if not body.get("id"):
        raise HTTPException(400, "source.id is required")
    # SSRF guard: refuse to persist a source pointing at a blocked endpoint.
    try:
        validate_outbound_url(body.get("base_url"))
    except UnsafeEndpointError as exc:
        raise HTTPException(400, str(exc))
    # A secret may be supplied inline; it is stored out-of-band and replaced by a ref.
    secret = body.pop("credential", None)
    source = ComputeSource.from_dict(body)
    if secret:
        source.credential_ref = secrets.put_secret(secret, ref=source.credential_ref)
    registry.upsert_source(source)
    return {"source": source.to_dict()}


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str) -> dict:
    existing = registry.get_source(source_id)
    if existing and existing.credential_ref:
        secrets.delete_secret(existing.credential_ref)
    registry.delete_source(source_id)
    return {"deleted": source_id}


@router.post("/sources/{source_id}/test")
async def test_source(source_id: str) -> dict:
    """Probe a source's reachability by building its provider and calling
    ``available()``. Returns a plain-language result for the Sources UI."""
    from . import providers
    source = registry.get_source(source_id)
    if source is None:
        raise HTTPException(404, "source not found")
    # Re-check before dialing (a stored source, or DNS, may have changed).
    try:
        validate_outbound_url(source.base_url)
    except UnsafeEndpointError as exc:
        return {"ok": False, "reason": str(exc)}
    built = providers.build_target(f"source:{source_id}")
    if built is None:
        return {"ok": False, "reason": "This source can't be built (missing URL/credential or unsupported kind)."}
    try:
        ok = await built.provider.available()
        return {
            "ok": bool(ok),
            "reason": "Reachable." if ok else "Unreachable — check the URL, credential, or that the endpoint is up.",
        }
    except Exception as exc:  # never 500 a connectivity probe
        return {"ok": False, "reason": f"Probe failed: {exc}"}


@router.post("/sources/{source_id}/credential")
async def set_source_credential(source_id: str, body: dict = Body(...)) -> dict:
    source = registry.get_source(source_id)
    if source is None:
        raise HTTPException(404, "source not found")
    secret = (body or {}).get("credential") or ""
    if not secret:
        raise HTTPException(400, "credential is required")
    source.credential_ref = secrets.put_secret(secret, ref=source.credential_ref)
    registry.upsert_source(source)
    return {"credential_ref": source.credential_ref}


# ---- devices ----------------------------------------------------------------

@router.get("/devices")
async def list_devices(source_id: Optional[str] = None) -> dict:
    settings = registry.load_settings()
    ttl = settings.device_heartbeat_ttl_s
    devices = []
    for d in registry.list_devices(source_id):
        row = d.to_dict()
        row["online_effective"] = d.is_online(ttl_s=ttl)
        row["heartbeat_age_s"] = d.heartbeat_age_s()
        devices.append(row)
    return {"devices": devices}


# ---- manifests --------------------------------------------------------------

@router.get("/models")
async def list_models() -> dict:
    return {"models": [m.to_dict() for m in registry.list_manifests()]}


@router.post("/models")
async def upsert_model(body: dict = Body(...)) -> dict:
    if not body.get("id"):
        raise HTTPException(400, "model.id is required")
    manifest = ModelManifest.from_dict(body)
    registry.upsert_manifest(manifest)
    return {"model": manifest.to_dict()}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str) -> dict:
    registry.delete_manifest(model_id)
    return {"deleted": model_id}


# ---- routes -----------------------------------------------------------------

@router.get("/routes")
async def list_routes() -> dict:
    return {"routes": [r.to_dict() for r in registry.list_routes()]}


@router.post("/routes")
async def upsert_route(body: dict = Body(...)) -> dict:
    for required in ("modality", "model_id", "primary_target"):
        if not body.get(required):
            raise HTTPException(400, f"route.{required} is required")
    route = ModelRoute.from_dict(body)
    registry.upsert_route(route)
    return {"route": route.to_dict()}


@router.delete("/routes/{modality}/{model_id}")
async def delete_route(modality: str, model_id: str) -> dict:
    registry.delete_route(model_id, modality)
    return {"deleted": {"modality": modality, "model_id": model_id}}


# ---- settings ---------------------------------------------------------------

@router.get("/settings")
async def get_settings() -> dict:
    return {"settings": registry.load_settings().to_dict()}


@router.put("/settings")
async def put_settings(body: dict = Body(...)) -> dict:
    # Overlay onto current (env-seeded) settings so partial updates are allowed.
    current = registry.load_settings().to_dict()
    current.update({k: v for k, v in (body or {}).items() if v is not None})
    if body.get("modality_defaults") is not None:
        current["modality_defaults"] = body["modality_defaults"]
    settings = ComputeSettings.from_dict(current)
    registry.save_settings(settings)
    return {"settings": settings.to_dict()}


# ---- routing explain --------------------------------------------------------

@router.get("/resolve")
async def resolve(modality: str, model_id: Optional[str] = None) -> dict:
    from . import policies
    return policies.explain(modality, model_id)
