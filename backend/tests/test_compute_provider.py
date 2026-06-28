"""Wave A / Batch 6 (HomePilot) — ComputeProvider abstraction + auto mode.

Proves: the default mode is local and wraps the existing runner unchanged; the
cloud provider drives the OllaBridge job API (faked via httpx.MockTransport) and
returns absolute media URLs; and compute_status() speaks plain language.
"""

from __future__ import annotations

import os
import sys

# Ensure the backend root is importable even if no app fixture ran yet.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import pytest


def _job_transport(*states: dict) -> httpx.MockTransport:
    """A fake Cloud: POST creates job_1; successive GETs return `states`."""
    counter = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and ("/generations" in path or "/edits" in path):
            return httpx.Response(200, json={"id": "job_1", "status": "queued"})
        if request.method == "GET" and "/v1/jobs/" in path:
            i = min(counter["n"], len(states) - 1)
            counter["n"] += 1
            return httpx.Response(200, json=states[i])
        if path == "/health":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


_SUCCEEDED = {
    "id": "job_1", "status": "succeeded",
    "output": {"artifacts": [{"url": "/media/cache/abc.png?token=job_1", "content_type": "image/png", "seed": 42}]},
    "selected_device_id": "dev_x", "gpu_seconds": 3.2,
}


async def test_default_mode_is_local(monkeypatch):
    monkeypatch.setattr("app.config.HOMEPILOT_COMPUTE_MODE", "local", raising=False)
    from app.compute import resolve_mode
    assert await resolve_mode() == "local"


async def test_cloud_generate_image_returns_absolute_urls():
    from app.compute.ollabridge_cloud import OllaBridgeCloudComputeProvider

    provider = OllaBridgeCloudComputeProvider(
        "https://cloud.test", "tok", poll_interval=0.0, transport=_job_transport(_SUCCEEDED),
    )
    media = await provider.generate_image(prompt="a red fox", model="flux-schnell")
    assert media.images == ["https://cloud.test/media/cache/abc.png?token=job_1"]
    assert media.meta["device"] == "dev_x"
    assert media.meta["job_id"] == "job_1"


async def test_cloud_polls_running_then_succeeded():
    from app.compute.ollabridge_cloud import OllaBridgeCloudComputeProvider

    states = ({"id": "job_1", "status": "running", "progress": 40}, _SUCCEEDED)
    provider = OllaBridgeCloudComputeProvider(
        "https://cloud.test", "tok", poll_interval=0.0, transport=_job_transport(*states),
    )
    media = await provider.generate_image(prompt="x")
    assert len(media.images) == 1


async def test_cloud_failed_job_raises():
    from app.compute.ollabridge_cloud import OllaBridgeCloudComputeProvider

    failed = {"id": "job_1", "status": "failed", "error": {"code": "no_device_available", "message": "PC offline"}}
    provider = OllaBridgeCloudComputeProvider(
        "https://cloud.test", "tok", poll_interval=0.0, transport=_job_transport(failed),
    )
    with pytest.raises(RuntimeError, match="PC offline"):
        await provider.generate_image(prompt="x")


async def test_get_compute_provider_cloud_mode(monkeypatch):
    monkeypatch.setattr("app.config.HOMEPILOT_COMPUTE_MODE", "ollabridge_cloud", raising=False)
    monkeypatch.setattr("app.config.OLLABRIDGE_CLOUD_URL", "https://cloud.test", raising=False)
    monkeypatch.setattr("app.config.OLLABRIDGE_CLOUD_TOKEN", "tok", raising=False)
    from app.compute import get_compute_provider
    provider = await get_compute_provider()
    assert provider.name == "ollabridge_cloud"


async def test_local_provider_wraps_existing_runner(monkeypatch):
    captured = {}

    def fake_run_workflow(name, variables):
        captured["name"] = name
        captured["variables"] = variables
        return {"images": ["/outputs/fox.png"], "videos": [], "prompt_id": "pid"}

    monkeypatch.setattr("app.comfy.run_workflow", fake_run_workflow, raising=False)
    from app.compute.local import LocalComputeProvider
    media = await LocalComputeProvider().generate_image(prompt="a red fox", model="flux-schnell", width=512)
    assert media.images == ["/outputs/fox.png"]
    assert captured["name"] == "txt2img-flux-schnell"  # model→workflow mapping
    assert captured["variables"]["prompt"] == "a red fox"
    assert captured["variables"]["width"] == 512


async def test_status_local_message(monkeypatch):
    monkeypatch.setattr("app.config.HOMEPILOT_COMPUTE_MODE", "local", raising=False)
    monkeypatch.setattr("app.services.comfyui.client.comfyui_healthy", lambda url: True, raising=False)
    from app.compute import compute_status
    status = await compute_status()
    assert status["mode"] == "local"
    assert status["local_gpu_available"] is True
    assert "Private GPU" in status["message"]


async def test_status_offline_message(monkeypatch):
    monkeypatch.setattr("app.config.HOMEPILOT_COMPUTE_MODE", "auto", raising=False)
    monkeypatch.setattr("app.config.OLLABRIDGE_CLOUD_TOKEN", "", raising=False)
    monkeypatch.setattr("app.services.comfyui.client.comfyui_healthy", lambda url: False, raising=False)
    from app.compute import compute_status
    status = await compute_status()
    assert status["label"] == "Offline"
    assert "offline" in status["message"].lower()
