"""P0-1 — Cloud → registry sync: mapping, manifest-driven caps, reconcile."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


def test_map_device_defensive_shapes():
    from app.compute.sync import map_device, CLOUD_SOURCE_ID
    d = map_device(
        {"id": "colab", "name": "Colab T4", "online": True, "ephemeral": True,
         "gpu": {"name": "NVIDIA T4", "vram_mb": 15360}, "capacity": 1, "active_jobs": 0,
         "last_seen": "2026-08-03T09:35:00Z"},
        now=1_800_000_000.0,
    )
    assert d.source_id == CLOUD_SOURCE_ID
    assert d.gpu_name == "NVIDIA T4" and d.vram_mb == 15360
    assert d.online and d.ephemeral and d.last_heartbeat is not None

    # Flat gpu fields + offline (no heartbeat stamped when offline).
    d2 = map_device({"id": "rig", "gpu_name": "RTX 4090", "vram_mb": 24576, "online": False})
    assert d2.gpu_name == "RTX 4090" and d2.vram_mb == 24576
    assert d2.online is False and d2.last_heartbeat is None


def test_map_manifests_are_capability_driven_not_name_guessed():
    from app.compute.sync import map_manifests
    payload = {"data": [
        {"id": "llama3.2:3b", "x_source": "shared_device", "owned_by": "relay:colab"},
        {"id": "moondream", "x_source": "shared_device", "device_id": "colab",
         "capabilities": ["chat", "vision"]},
        {"id": "route-alias", "x_source": "route"},  # not node inventory → skipped
    ]}
    device_caps = {"colab": ["chat"]}
    mans = {m.id: m for m in map_manifests(payload, device_caps)}
    assert set(mans) == {"llama3.2:3b", "moondream"}
    assert mans["llama3.2:3b"].capabilities == ["chat"]
    # moondream advertises vision → multimodal, from the manifest, not its name.
    assert "multimodal" in mans["moondream"].capabilities
    assert mans["moondream"].device_ids == ["colab"]


async def _run_sync(compute_devices, models_payload):
    from app.compute import sync

    async def fetch(path):
        if path == "/v1/devices":
            return 200, compute_devices
        if path == "/ollama/v1/models":
            return 200, models_payload
        return 404, None

    return await sync.sync_from_cloud("https://app.ollabridge.com", fetch=fetch)


async def test_sync_populates_registry(compute_db):
    from app.compute import registry, sync
    res = await _run_sync(
        [{"id": "colab", "name": "Colab T4", "online": True, "ephemeral": True,
          "gpu": {"name": "NVIDIA T4", "vram_mb": 15360}, "capabilities": ["chat"]}],
        {"data": [{"id": "llama3.2:3b", "x_source": "shared_device", "device_id": "colab"}]},
    )
    assert res == {"ok": True, "linked": True, "devices": 1, "models": 1,
                   "source_id": sync.CLOUD_SOURCE_ID}
    # The managed Cloud source + device + manifest are now in the registry.
    assert registry.get_source(sync.CLOUD_SOURCE_ID).kind == "ollabridge"
    dev = registry.get_device("colab")
    assert dev and dev.is_online() and dev.name == "Colab T4"
    man = registry.get_manifest("llama3.2:3b")
    assert man and "colab" in man.device_ids


async def test_sync_marks_missing_devices_offline(compute_db):
    from app.compute import registry
    # First sync: two online devices.
    await _run_sync(
        [{"id": "a", "online": True}, {"id": "b", "online": True}],
        {"data": []},
    )
    assert registry.get_device("a").online and registry.get_device("b").online
    # Second sync only reports "a" → "b" is reconciled offline, not deleted.
    await _run_sync([{"id": "a", "online": True}], {"data": []})
    assert registry.get_device("a").online is True
    b = registry.get_device("b")
    assert b is not None and b.online is False


async def test_sync_unlinked_when_cloud_401(compute_db):
    from app.compute import sync

    async def fetch(path):
        return 401, {"error": "unauthorized"}

    res = await sync.sync_from_cloud("https://app.ollabridge.com", fetch=fetch)
    assert res["ok"] is False and res["linked"] is False and res["devices"] == 0
