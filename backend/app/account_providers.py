"""
Account Providers BFF endpoint (ADDITIVE, FEATURE-FLAGGED) — Step 2.

Gives HomePilot **Web** a single, same-origin, authenticated aggregate that
surfaces the remote providers shared by the signed-in user's OllaBridge account,
so Settings → Providers can list them (e.g. "Ollama — Gaming PC (OllaBridge), 1
model") without the browser ever holding a cloud token or relay URL.

Route
-----
    GET /v1/account/providers

Design / security posture
-------------------------
* **Feature-flagged.** ``HOMEPILOT_ACCOUNT_PROVIDERS_ENABLED`` (default off).
  When off, ``main.py`` does not mount the router — zero behavior change. It is
  mounted independently of the mirror RPC/jobs plane so a linked user can see
  their shared providers without the whole mirror BFF being enabled.
* **Reuses the mirror BFF security seam.** Auth (``_require_user``) and the
  server-side cloud-credential resolution (``_resolve_cloud_credentials``) come
  straight from ``mirror_proxy``: the caller is an authenticated HomePilot user,
  the OllaBridge token is resolved server-side (per-user registry → persistent
  store → operator env), and it is **never** returned to the browser.
* **Compatibility fallback (documented, not the long-term contract).** The cloud
  currently exposes an OpenAI-compatible model list plus a device list, not a
  first-class provider inventory. Until it does, we treat the caller's own
  ``shared_device`` models as the Ollama remote provider, grouped by owning
  device (parsed from ``owned_by = "relay:<device_id>"`` or an explicit
  ``device_id``), and enrich names/online-state from ``GET /v1/devices`` when it
  is available. The preferred contract is a node/provider inventory the cloud
  returns directly.

Response semantics
------------------
    Not signed in                          → 401 {ok:false, error:not_authenticated}
    Signed in but not linked               → 200 {ok:true,  linked:false, providers:[]}
    Cloud unavailable / invalid response   → 502 {ok:false, error:cloud_unavailable}
    Cloud OK with no shared backends       → 200 {ok:true,  linked:true,  providers:[]}
"""
from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Cookie, Header, HTTPException
from fastapi.responses import JSONResponse

from .mirror_proxy import (
    _cloud_base,
    _require_user,
    _resolve_cloud_credentials,
)

logger = logging.getLogger("homepilot.account_providers")

router = APIRouter(prefix="/v1/account", tags=["account-providers"])

# Upstream timeouts (connect, read). Two small GETs, kept snappy so Settings
# never hangs on a slow cloud.
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 15.0

# The caller's own shared-device models are ``owned_by = "relay:<device_id>"``
# in the OpenAI-compatible list. Constrain the id charset so a malformed value
# can never smuggle anything into the provider id we hand back.
_RELAY_OWNER_RE = re.compile(r"^relay:(?P<dev>[A-Za-z0-9._:-]{1,128})$")


def is_enabled() -> bool:
    return os.getenv("HOMEPILOT_ACCOUNT_PROVIDERS_ENABLED", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _json(status: int, body: Dict[str, Any], rid: str) -> JSONResponse:
    body.setdefault("request_id", rid)
    return JSONResponse(status_code=status, content=body, headers={"Cache-Control": "no-store"})


def _device_id_of(model: Dict[str, Any]) -> str:
    """Owning device id for a shared-device model.

    Prefers explicit fields (a future cloud contract), then falls back to
    parsing ``owned_by = "relay:<device_id>"`` — today's shape.
    """
    for key in ("device_id", "deviceId"):
        val = model.get(key)
        if val:
            return str(val)
    match = _RELAY_OWNER_RE.match(str(model.get("owned_by") or ""))
    return match.group("dev") if match else ""


def _parse_device_meta(payload: Any) -> Dict[str, Dict[str, Any]]:
    """Map ``device_id -> {name, online}`` from the cloud ``/v1/devices`` list.

    Absent / 404 / non-list is tolerated: names simply fall back to the id and
    online defaults are decided by the caller.
    """
    meta: Dict[str, Dict[str, Any]] = {}
    if not isinstance(payload, list):
        return meta
    for d in payload:
        if not isinstance(d, dict):
            continue
        did = d.get("id")
        if not did:
            continue
        meta[str(did)] = {
            "name": d.get("name") or str(did),
            "online": bool(d.get("online", False)),
            "has_online": "online" in d,
        }
    return meta


def _build_providers(models_payload: Any, device_meta: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group the caller's shared-device models into one Ollama provider per device."""
    data = models_payload.get("data") if isinstance(models_payload, dict) else models_payload
    if not isinstance(data, list):
        return []

    grouped: Dict[str, List[str]] = {}
    for m in data:
        if not isinstance(m, dict):
            continue
        # Own-node models are tagged shared_device (``x_source`` today, legacy
        # ``source``). Anything else — route aliases, cloud catalog, personas —
        # is not a shared remote backend and is skipped.
        source = m.get("x_source") or m.get("source")
        if source != "shared_device":
            continue
        dev_id = _device_id_of(m)
        mid = m.get("id")
        if not dev_id or not mid:
            continue
        bucket = grouped.setdefault(dev_id, [])
        if mid not in bucket:
            bucket.append(mid)

    providers: List[Dict[str, Any]] = []
    for dev_id, model_ids in sorted(grouped.items()):
        meta = device_meta.get(dev_id, {})
        name = meta.get("name") or dev_id
        # A device advertising relay models is connected (offline devices don't
        # surface relay models). Honor an explicit offline flag from
        # /v1/devices when present; otherwise treat as online.
        online = bool(meta["online"]) if meta.get("has_online") else True
        providers.append({
            "id": f"ollabridge:{dev_id}:ollama",
            "label": f"Ollama — {name} (OllaBridge)",
            "origin": "ollabridge",
            "capability": "chat",
            "online": online,
            "modelCount": len(model_ids),
            "nodeId": dev_id,
            "backend": "ollama",
        })
    return providers


async def _cloud_get(client: httpx.AsyncClient, base: str, path: str, token: str, rid: str) -> httpx.Response:
    return await client.get(
        f"{base}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "X-Request-Id": rid,
        },
    )


@router.get("/providers")
async def account_providers(
    authorization: Optional[str] = Header(default=None),
    homepilot_session: Optional[str] = Cookie(default=None),
) -> JSONResponse:
    """Aggregate the signed-in user's shared OllaBridge providers (server-side)."""
    rid = "apr_" + uuid.uuid4().hex[:16]

    # 1. Authenticate — stable ``not_authenticated`` code on 401.
    try:
        user = _require_user(authorization, homepilot_session)
    except HTTPException as exc:
        if exc.status_code == 401:
            return _json(401, {
                "ok": False,
                "error": "not_authenticated",
                "message": "Sign in to view your account providers.",
                "providers": [],
            }, rid)
        raise
    user_id = str(user.get("id", ""))

    # 2. Resolve the server-side cloud credentials. The seam raises 503 when no
    #    token is available — that means "signed in but not linked", which the
    #    contract reports as a successful, empty, unlinked result (not an error
    #    the Settings panel would surface as a failure).
    try:
        base, token = _resolve_cloud_credentials(user)
    except HTTPException as exc:
        if exc.status_code == 503:
            return _json(200, {
                "ok": True,
                "linked": False,
                "providers": [],
                "cloud": _cloud_base(),
            }, rid)
        raise

    # 3. Query the canonical cloud inventory (models + devices), server-side.
    timeout = httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            models_resp = await _cloud_get(client, base, "/ollama/v1/models", token, rid)
            # Devices give friendly names + online state; /v1/devices is 404
            # when device sharing is disabled on the cloud, and may fail
            # independently — tolerated as "no metadata", never fatal.
            try:
                dev_resp: Optional[httpx.Response] = await _cloud_get(
                    client, base, "/v1/devices", token, rid)
            except httpx.RequestError:
                dev_resp = None
    except httpx.TimeoutException:
        logger.warning("[account-providers %s] cloud timeout user=%s", rid, user_id)
        return _json(502, {
            "ok": False,
            "error": "cloud_unavailable",
            "message": "The OllaBridge cloud did not respond in time.",
            "providers": [],
        }, rid)
    except httpx.RequestError as exc:
        logger.warning("[account-providers %s] cloud error user=%s: %s", rid, user_id, type(exc).__name__)
        return _json(502, {
            "ok": False,
            "error": "cloud_unavailable",
            "message": "Could not reach the OllaBridge cloud.",
            "providers": [],
        }, rid)

    # A 401 from upstream means the server-side token expired/was revoked.
    # Present it as "not linked" so the UI prompts a re-link instead of showing
    # a hard error the user can't act on.
    if models_resp.status_code == 401:
        return _json(200, {
            "ok": True,
            "linked": False,
            "providers": [],
            "cloud": _cloud_base(),
        }, rid)
    if models_resp.status_code >= 400:
        return _json(502, {
            "ok": False,
            "error": "cloud_unavailable",
            "message": f"The OllaBridge cloud returned HTTP {models_resp.status_code}.",
            "providers": [],
        }, rid)

    try:
        models_payload = models_resp.json()
    except ValueError:
        # HTML or other non-JSON where the model list was expected.
        return _json(502, {
            "ok": False,
            "error": "cloud_unavailable",
            "message": "The OllaBridge cloud returned a non-JSON model list.",
            "providers": [],
        }, rid)

    device_meta: Dict[str, Dict[str, Any]] = {}
    if dev_resp is not None and dev_resp.status_code < 400:
        try:
            device_meta = _parse_device_meta(dev_resp.json())
        except ValueError:
            device_meta = {}

    providers = _build_providers(models_payload, device_meta)
    logger.info("[account-providers %s] user=%s providers=%d", rid, user_id, len(providers))
    return _json(200, {
        "ok": True,
        "linked": True,
        "providers": providers,
        "cloud": _cloud_base(),
    }, rid)
