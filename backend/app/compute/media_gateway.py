"""
Generation jobs through OllaBridge (HomePilot One).

Sends an image, edit or video job to the gateway's async job API under the
user's signed routing policy, waits for it, and then **copies the result into
HomePilot's own storage**. The gateway's media cache is temporary; HomePilot is
the durable owner of generated content, so the conversation only ever
references a HomePilot asset.

Used by the Hugging Face connector's image and video turns. It is opt-in
(``HOMEPILOT_MEDIA_VIA_GATEWAY=true``) because it needs a gateway with the job
API enabled; when it is off, or the gateway cannot serve the job, the existing
direct path runs — except under ``private_local``, where there is no hosted
fallback at all.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Optional

import httpx

from . import registry, routing
from .providers.hosted import GatewayError, _error_from, answered_by

_PATHS = {
    "image": "/v1/images/generations",
    "edit": "/v1/images/edits",
    "video": "/v1/videos/generations",
}
_MAX_ARTIFACT_BYTES = 512 * 1024 * 1024
#: Test seam.
default_transport: httpx.BaseTransport | None = None


def enabled() -> bool:
    return routing._env_bool("HOMEPILOT_MEDIA_VIA_GATEWAY", False)


def strategy(user_id: str) -> str:
    return routing.effective_prefs(user_id).strategy


def should_use_gateway(user_id: str) -> bool:
    """Private mode always goes through the gateway (own devices only);
    otherwise only when the operator switched gateway media on."""
    s = strategy(user_id)
    if s == "private_local":
        return routing.is_web()
    return enabled() and s in routing.GATEWAY_STRATEGIES


def hosted_direct_allowed(user_id: str) -> bool:
    """May HomePilot call a hosted provider itself for this user?"""
    return strategy(user_id) != "private_local"


async def run(
    user_id: str,
    task: str,
    body: dict[str, Any],
    *,
    conversation_id: str = "",
    project_id: str = "",
    timeout: Optional[float] = None,
    poll_interval: float = 1.5,
) -> dict[str, Any]:
    """Run one job and persist its artifact.

    Returns ``{"asset": {...}, "mime": str, "provenance": dict, "job_id": str}``.
    Raises :class:`GatewayError` with a structured code when it cannot.
    """
    from ..config import OLLABRIDGE_CLOUD_TIMEOUT
    from ..files import save_generated_media_as_asset

    base = (registry.load_settings().cloud_url or "").rstrip("/")
    if not base or task not in _PATHS:
        raise GatewayError("provider_unavailable", "The generation gateway is not configured.")
    call = routing.build_gateway_call(user_id, modality=task)
    if not call.token:
        raise GatewayError("missing_credentials", "OllaBridge Cloud is not linked for this account.")
    headers = {
        "Authorization": f"Bearer {call.token}", **call.headers,
        # A retried request must not generate (or bill) twice.
        "Idempotency-Key": uuid.uuid4().hex,
    }
    deadline = time.monotonic() + float(timeout or OLLABRIDGE_CLOUD_TIMEOUT)
    async with httpx.AsyncClient(base_url=base, timeout=60.0, transport=default_transport) as client:
        r = await client.post(_PATHS[task], json=body, headers=headers)
        if r.status_code >= 400:
            raise _error_from(r.status_code, _json(r))
        job = r.json()
        job_id = job["id"]
        auth = {"Authorization": f"Bearer {call.token}"}
        while job.get("status") not in ("succeeded", "failed", "canceled"):
            if time.monotonic() > deadline:
                # Do not leave a job running that nobody is waiting for.
                try:
                    await client.post(f"/v1/jobs/{job_id}/cancel", headers=auth)
                except Exception:
                    pass
                raise GatewayError("provider_timeout", f"Generation job {job_id} timed out.")
            await asyncio.sleep(poll_interval)
            r = await client.get(f"/v1/jobs/{job_id}", headers=auth)
            if r.status_code >= 400:
                raise _error_from(r.status_code, _json(r))
            job = r.json()
        if job["status"] != "succeeded":
            err = job.get("error") or {}
            raise GatewayError(str(err.get("code") or "provider_unavailable"),
                               str(err.get("message") or f"job {job['status']}"))
        output = job.get("output") or {}
        artifacts = output.get("artifacts") or []
        if not artifacts:
            raise GatewayError("provider_unavailable", "The job finished without a result.")
        artifact = artifacts[0]
        url = str(artifact.get("url") or "")
        mime = str(artifact.get("content_type") or ("video/mp4" if task == "video" else "image/png"))
        # Only ever fetch from the gateway we just called — never a URL a
        # response body points elsewhere (SSRF).
        if url.startswith(("http://", "https://")) and not url.startswith(base + "/"):
            raise GatewayError("provider_unavailable", "The job result points outside the gateway.")
        fetched = await client.get(url, headers=auth)
        if fetched.status_code != 200:
            raise GatewayError("provider_unavailable", "The job result could not be downloaded.")
        data = fetched.content
        if not data or len(data) > _MAX_ARTIFACT_BYTES:
            raise GatewayError("provider_unavailable", "The job result is empty or too large.")

    provenance = output.get("provenance") or {
        "provider": f"device:{job.get('selected_device_id')}", "provider_kind": "device",
        "model": job.get("model"), "tier": "device", "billing": "free", "execution": "device",
        "cost": {"estimated_usd": 0.0, "actual_usd": 0.0, "known": True},
    }
    asset = save_generated_media_as_asset(
        user_id or "", data, mime, "video" if task == "video" else "image",
        project_id=project_id, conversation_id=conversation_id,
    )
    routing.record_usage(user_id, provenance, modality=task)
    return {"asset": asset, "mime": mime, "provenance": provenance, "job_id": job_id,
            "artifact": {k: artifact.get(k) for k in ("width", "height", "seed") if artifact.get(k)}}


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {}


def media_provenance(provenance: dict) -> dict[str, Any]:
    """The provenance fields stored with a generated asset's message."""
    served = answered_by(provenance)
    return {
        "provider": served["provider"],
        "served_by": served,
        "execution": provenance.get("execution"),
        "generated_at": time.time(),
    }
