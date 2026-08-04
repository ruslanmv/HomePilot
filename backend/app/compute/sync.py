"""
Cloud → registry sync (P0-1).

The registry only becomes *real* when it is fed by OllaBridge Cloud: a paired
Colab/RunPod/home node advertises itself and its models to Cloud over the
outbound relay, and HomePilot must pull that inventory into its own
``ComputeDevice`` / ``ModelManifest`` tables so the Resources panel and the
per-model selector show live nodes and route to them.

This module maps Cloud's ``GET /v1/devices`` (paired devices + heartbeat/GPU)
and ``GET /ollama/v1/models`` (advertised models, tagged to a device) into the
registry. Capabilities come from what the node/device advertises — never from
guessing model names.

The HTTP fetch is injected (``fetch(path) -> (status, json)``) so the mapping
and reconcile logic are unit-testable without a live Cloud; the route supplies a
real httpx-backed fetcher with the server-side cloud token.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from . import registry
from .schemas import ComputeDevice, ComputeSource, ModelManifest

# The single logical source that represents "devices reached via OllaBridge
# Cloud". Its devices are the user's paired nodes.
CLOUD_SOURCE_ID = "ollabridge-cloud"

Fetch = Callable[[str], Awaitable[tuple[int, Any]]]

_RELAY_OWNER_RE = re.compile(r"^relay:(?P<dev>[^:]+)")
# Which model-capabilities imply which routing modality-capabilities.
_CHAT_CAPS = {"chat", "text", "completion"}
_VISION_CAPS = {"vision", "multimodal", "image-input"}


def ensure_cloud_source(base_url: Optional[str] = None) -> ComputeSource:
    """Ensure the ollabridge Cloud source row exists (idempotent)."""
    existing = registry.get_source(CLOUD_SOURCE_ID)
    source = ComputeSource(
        id=CLOUD_SOURCE_ID,
        name="OllaBridge Cloud",
        kind="ollabridge",
        base_url=base_url or (existing.base_url if existing else None),
        enabled=existing.enabled if existing else True,
        execution_type="relay",
        meta={"managed": True},
    )
    return registry.upsert_source(source)


def _parse_last_seen(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def map_device(cloud_dev: dict, *, now: Optional[float] = None) -> ComputeDevice:
    """Cloud device record → registry ComputeDevice (defensive about shape)."""
    now = now or time.time()
    gpu = cloud_dev.get("gpu") if isinstance(cloud_dev.get("gpu"), dict) else {}
    gpu_name = gpu.get("name") or cloud_dev.get("gpu_name")
    vram_mb = gpu.get("vram_mb") if gpu else cloud_dev.get("vram_mb")
    online = bool(cloud_dev.get("online", False))
    last_seen = _parse_last_seen(cloud_dev.get("last_seen") or cloud_dev.get("last_heartbeat"))
    return ComputeDevice(
        id=str(cloud_dev.get("id")),
        source_id=CLOUD_SOURCE_ID,
        name=cloud_dev.get("name") or str(cloud_dev.get("id")),
        online=online,
        ephemeral=bool(cloud_dev.get("ephemeral", False)),
        gpu_name=gpu_name,
        vram_mb=int(vram_mb) if vram_mb is not None else None,
        capacity=int(cloud_dev.get("capacity", 1)),
        active_jobs=int(cloud_dev.get("active_jobs", 0)),
        # A device advertising over the relay is alive now; prefer the reported
        # last_seen, else stamp now when online so heartbeat-age reads correctly.
        last_heartbeat=last_seen if last_seen is not None else (now if online else None),
    )


def _device_id_of(model: dict) -> str:
    for key in ("device_id", "deviceId"):
        val = model.get(key)
        if val:
            return str(val)
    m = _RELAY_OWNER_RE.match(str(model.get("owned_by") or ""))
    return m.group("dev") if m else ""


def _caps_for(device_caps: list[str], model: dict) -> list[str]:
    """Manifest-driven capabilities: prefer the model's own advertised caps,
    then the device's; fall back to chat. No name-guessing."""
    raw = model.get("capabilities") or device_caps or []
    caps: list[str] = []
    lowered = {str(c).lower() for c in raw}
    if lowered & _VISION_CAPS:
        caps.append("multimodal")
    if not caps or (lowered & _CHAT_CAPS):
        if "chat" not in caps:
            caps.insert(0, "chat")
    return caps or ["chat"]


def map_manifests(
    models_payload: Any, device_caps: dict[str, list[str]]
) -> list[ModelManifest]:
    """Advertised models → manifests, grouped by owning device."""
    data = models_payload.get("data") if isinstance(models_payload, dict) else models_payload
    if not isinstance(data, list):
        return []
    by_id: dict[str, ModelManifest] = {}
    for m in data:
        if not isinstance(m, dict):
            continue
        source = m.get("x_source") or m.get("source")
        if source not in (None, "shared_device"):
            # Only the user's own shared-device models are node inventory.
            continue
        dev_id = _device_id_of(m)
        mid = m.get("id")
        if not (dev_id and mid):
            continue
        caps = _caps_for(device_caps.get(dev_id, []), m)
        man = by_id.get(mid)
        if man is None:
            man = ModelManifest(
                id=mid,
                runtime=str(m.get("runtime") or "ollama"),
                capabilities=caps,
                device_ids=[dev_id],
                digest=m.get("digest"),
            )
            by_id[mid] = man
        else:
            if dev_id not in man.device_ids:
                man.device_ids.append(dev_id)
            for c in caps:
                if c not in man.capabilities:
                    man.capabilities.append(c)
    return list(by_id.values())


async def sync_from_cloud(base_url: str, *, fetch: Fetch) -> dict:
    """Pull devices + advertised models from Cloud into the registry.

    Returns a summary the UI shows: how many devices/models synced, and whether
    the account is linked/reachable. Never raises for an unreachable Cloud — it
    reports ``linked=False`` so the UI can prompt a re-link.
    """
    ensure_cloud_source(base_url)

    try:
        dev_status, dev_payload = await fetch("/v1/devices")
        mdl_status, mdl_payload = await fetch("/ollama/v1/models")
    except Exception as exc:
        return {"ok": False, "linked": False, "reason": f"Cloud unreachable: {exc}",
                "devices": 0, "models": 0}

    if dev_status == 401 or mdl_status == 401:
        return {"ok": False, "linked": False, "reason": "Cloud rejected the token — re-link your account.",
                "devices": 0, "models": 0}

    cloud_devices = dev_payload if isinstance(dev_payload, list) else []
    device_caps: dict[str, list[str]] = {}
    reported_ids: set[str] = set()

    for cd in cloud_devices:
        if not isinstance(cd, dict) or not cd.get("id"):
            continue
        dev = map_device(cd)
        registry.upsert_device(dev)
        reported_ids.add(dev.id)
        caps = cd.get("capabilities")
        if isinstance(caps, list):
            device_caps[dev.id] = [str(c) for c in caps]

    # Reconcile: devices we previously synced from Cloud that are no longer
    # reported are marked offline (never deleted — an offline device keeps its
    # routes and can come back).
    for existing in registry.list_devices(CLOUD_SOURCE_ID):
        if existing.id not in reported_ids and existing.online:
            existing.online = False
            registry.upsert_device(existing)

    manifests = map_manifests(mdl_payload, device_caps)
    for man in manifests:
        registry.upsert_manifest(man)

    return {
        "ok": True,
        "linked": True,
        "devices": len(reported_ids),
        "models": len(manifests),
        "source_id": CLOUD_SOURCE_ID,
    }
