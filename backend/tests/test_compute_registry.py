"""PR 2 — registry, secrets, health cache, policies, provider factory.

Covers the persisted registry (sources/devices/manifests/routes/settings), the
credential store, the circuit-breaking health cache, route resolution order and
static filtering, and the target→provider factory.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ---- schemas round-trip -------------------------------------------------

def test_schema_round_trip():
    from app.compute.schemas import ComputeSource, ModelRoute, ModelManifest

    src = ComputeSource(id="s", name="S", kind="openai_compatible", base_url="http://x")
    assert ComputeSource.from_dict(src.to_dict()) == src

    route = ModelRoute(modality="chat", model_id="m", primary_target="device:d",
                       fallback_targets=["local"], strategy="prefer_local")
    assert ModelRoute.from_dict(route.to_dict()) == route

    man = ModelManifest(id="m", runtime="ollama", capabilities=["chat", "vision"],
                        device_ids=["d"], minimum_vram_mb=8000)
    assert ModelManifest.from_dict(man.to_dict()).supports("vision")


# ---- registry + settings ------------------------------------------------

def test_registry_crud_and_settings_overlay(compute_db):
    from app.compute import registry
    from app.compute.schemas import ComputeSource, ModelRoute, ComputeSettings

    assert registry.is_empty() is True

    registry.upsert_source(ComputeSource(id="oa", name="OpenAI", kind="openai_compatible"))
    assert registry.get_source("oa").kind == "openai_compatible"
    assert registry.is_empty() is False

    registry.upsert_route(ModelRoute(modality="chat", model_id="m", primary_target="local"))
    assert registry.get_route("m", "chat").primary_target == "local"
    registry.delete_route("m", "chat")
    assert registry.get_route("m", "chat") is None

    # Settings overlay: env default first, persisted override wins.
    base = registry.load_settings()
    assert base.compute_mode in ("local", "ollabridge_cloud", "auto")
    base.compute_mode = "auto"
    registry.save_settings(base)
    assert registry.load_settings().compute_mode == "auto"


def test_secrets_store_never_returns_missing(compute_db):
    from app.compute import secrets
    ref = secrets.put_secret("sk-123")
    assert secrets.get_secret(ref) == "sk-123"
    secrets.delete_secret(ref)
    assert secrets.get_secret(ref) is None
    assert secrets.get_secret(None) is None


# ---- health cache / circuit breaker -------------------------------------

async def test_health_cache_caches_within_ttl():
    from app.compute.health import HealthCache
    t = {"n": 100.0}
    cache = HealthCache(ttl_s=10, clock=lambda: t["n"])
    calls = {"n": 0}

    async def probe():
        calls["n"] += 1
        return True

    assert await cache.healthy("k", probe) is True
    assert await cache.healthy("k", probe) is True  # cached — no second probe
    assert calls["n"] == 1
    t["n"] += 20  # TTL expired
    assert await cache.healthy("k", probe) is True
    assert calls["n"] == 2


async def test_circuit_breaker_opens_after_failures():
    from app.compute.health import HealthCache
    t = {"n": 0.0}
    cache = HealthCache(ttl_s=1, fail_threshold=3, cooldown_s=30, clock=lambda: t["n"])

    async def bad():
        return False

    for _ in range(3):
        t["n"] += 2  # step past ttl each time so the probe actually runs
        await cache.healthy("k", bad)
    # 3 consecutive failures → breaker open → allows() is False without probing.
    assert cache.allows("k") is False
    t["n"] += 40  # past cooldown
    assert cache.allows("k") is True


# ---- policies (resolution order + filters) ------------------------------

def test_policy_resolution_order(compute_db):
    from app.compute import registry, policies
    from app.compute.schemas import ModelRoute, ComputeSettings, ModalityDefault

    # Global default (no route, no modality default) → compute_mode targets.
    s = registry.load_settings(); s.compute_mode = "local"; registry.save_settings(s)
    assert policies.resolve_targets("chat", "x") == ["local"]

    # Modality default beats global.
    s = registry.load_settings()
    s.modality_defaults["chat"] = ModalityDefault(
        modality="chat", strategy="pinned", target="ollabridge_cloud", fallback_targets=["local"])
    registry.save_settings(s)
    assert policies.resolve_targets("chat", "x")[0] == "ollabridge_cloud"

    # Explicit per-model route beats the modality default.
    registry.upsert_route(ModelRoute(
        modality="chat", model_id="deepseek", primary_target="device:colab",
        fallback_targets=["local"], strategy="pinned"))
    assert policies.resolve_targets("chat", "deepseek")[0] == "device:colab"


def test_policy_prefer_local_reorders(compute_db):
    from app.compute import registry, policies
    from app.compute.schemas import ModelRoute
    registry.upsert_route(ModelRoute(
        modality="image", model_id="m", primary_target="device:remote",
        fallback_targets=["local"], strategy="prefer_local"))
    # prefer_local pulls local to the front regardless of author order.
    assert policies.resolve_targets("image", "m")[0] == "local"


def test_policy_privacy_local_only_drops_remote(compute_db):
    from app.compute import registry, policies
    from app.compute.schemas import ModelRoute
    registry.upsert_route(ModelRoute(
        modality="chat", model_id="m", primary_target="ollabridge_cloud",
        fallback_targets=["local"], strategy="pinned", privacy="local_only"))
    assert policies.resolve_targets("chat", "m") == ["local"]


def test_policy_capability_filter_drops_unqualified_device(compute_db):
    from app.compute import registry, policies
    from app.compute.schemas import ModelRoute, ModelManifest, ComputeDevice
    # Device advertises only 8GB; model needs 20GB → device dropped, local tail kept.
    registry.upsert_device(ComputeDevice(id="colab", source_id="ob", vram_mb=8000, online=True))
    registry.upsert_manifest(ModelManifest(
        id="big", runtime="comfyui", capabilities=["image"],
        device_ids=["colab"], minimum_vram_mb=20000))
    registry.upsert_route(ModelRoute(
        modality="image", model_id="big", primary_target="device:colab",
        fallback_targets=["local"], strategy="pinned"))
    assert "device:colab" not in policies.resolve_targets("image", "big")


# ---- provider factory ---------------------------------------------------

def test_build_target_local_and_openai(compute_db):
    from app.compute import registry, secrets, providers
    from app.compute.schemas import ComputeSource

    built = providers.build_target("local")
    assert built and built.provider.name == "local" and built.remote is False

    ref = secrets.put_secret("sk-xyz")
    registry.upsert_source(ComputeSource(
        id="oa", name="OpenAI compat", kind="openai_compatible",
        base_url="http://endpoint", credential_ref=ref))
    b2 = providers.build_target("source:oa")
    assert b2 and b2.provider.name == "openai_compatible" and b2.remote is True
    assert b2.provider.api_key == "sk-xyz"

    # Device target carries routing metadata for the Cloud relay.
    s = registry.load_settings(); s.cloud_url = "https://cloud.test"; registry.save_settings(s)
    b3 = providers.build_target("device:colab")
    assert b3 and b3.extra["routing"]["device_id"] == "colab"

    # Unknown / disabled → None (router skips it).
    assert providers.build_target("provider:free-best") is None
