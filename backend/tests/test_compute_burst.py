"""MB6 — cloud-GPU burst gating (auto mode, local GPU offline).

Note: the shared `app` fixture purges + re-imports `app.*`, so we resolve the
*live* config/compute modules inside the fixture (not at import time) and patch
those — otherwise patches land on stale module objects.
"""

from __future__ import annotations

import asyncio
import importlib

import pytest


class _FakeCloud:
    async def available(self) -> bool:
        return True


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def env(monkeypatch):
    """auto mode · local GPU offline · a reachable, configured cloud. Returns the
    live (config, compute) modules so tests patch the same objects the code uses."""
    config = importlib.import_module("app.config")
    compute = importlib.import_module("app.compute")

    monkeypatch.setattr(config, "HOMEPILOT_COMPUTE_MODE", "auto", raising=False)
    monkeypatch.setattr(config, "OLLABRIDGE_CLOUD_URL", "https://cloud.example", raising=False)
    monkeypatch.setattr(config, "OLLABRIDGE_CLOUD_TOKEN", "tok", raising=False)

    async def _local_off(self):
        return False

    monkeypatch.setattr(compute.LocalComputeProvider, "available", _local_off, raising=False)
    monkeypatch.setattr(compute, "_build_cloud", lambda: _FakeCloud())
    monkeypatch.setattr(compute, "_cloud_configured", lambda: True)
    return config, compute


def test_burst_free_by_default(env, monkeypatch):
    config, compute = env
    monkeypatch.setattr(config, "COMPUTE_BURST_REQUIRES_PREMIUM", False, raising=False)
    monkeypatch.setattr(config, "PREMIUM_COMPUTE_ENABLED", False, raising=False)
    assert _run(compute.resolve_mode()) == "ollabridge_cloud"  # bursts
    st = _run(compute.compute_status())
    assert st["burst"] is True and st["burst_gated"] is False


def test_burst_gated_for_free_when_required(env, monkeypatch):
    config, compute = env
    monkeypatch.setattr(config, "COMPUTE_BURST_REQUIRES_PREMIUM", True, raising=False)
    monkeypatch.setattr(config, "PREMIUM_COMPUTE_ENABLED", False, raising=False)
    assert _run(compute.resolve_mode()) == "local"  # no burst for free
    st = _run(compute.compute_status())
    assert st["burst"] is False and st["burst_gated"] is True
    assert "premium" in st["message"].lower()


def test_burst_allowed_for_premium(env, monkeypatch):
    config, compute = env
    monkeypatch.setattr(config, "COMPUTE_BURST_REQUIRES_PREMIUM", True, raising=False)
    monkeypatch.setattr(config, "PREMIUM_COMPUTE_ENABLED", True, raising=False)
    assert _run(compute.resolve_mode()) == "ollabridge_cloud"  # premium bursts
    st = _run(compute.compute_status())
    assert st["burst"] is True and st["premium"] is True
