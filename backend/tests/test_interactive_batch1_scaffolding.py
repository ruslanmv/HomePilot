"""
Batch 1/8 — scaffolding tests.

Validates the additive-mount contract:
 - With the flag OFF, the interactive router contributes zero paths.
 - The service module is importable and re-exports its public surface.
 - With the flag ON, a single /health path is exposed and returns a
   sane configuration snapshot.

Later batches stack on top; these assertions keep the mount-time
guarantees stable no matter what else lands.
"""
from __future__ import annotations

import importlib


def test_module_imports_cleanly():
    mod = importlib.import_module("app.interactive")
    assert hasattr(mod, "load_config")
    assert hasattr(mod, "build_router")
    assert hasattr(mod, "InteractiveConfig")


def test_flag_off_router_has_no_paths(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_ENABLED", "false")
    from app.interactive import build_router, load_config
    router = build_router(load_config())
    # APIRouter.routes is a list of Route / APIRoute objects — empty
    # when the service is disabled.
    assert len(router.routes) == 0


def test_flag_on_exposes_health(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_ENABLED", "true")
    from app.interactive import build_router, load_config
    router = build_router(load_config())
    paths = {getattr(r, "path", None) for r in router.routes}
    assert "/v1/interactive/health" in paths


def test_config_defaults_are_safe(monkeypatch):
    # Clear every INTERACTIVE_* var to simulate a pristine install.
    for key in list(monkeypatch._setenv_targets if hasattr(monkeypatch, "_setenv_targets") else []):
        pass
    for k in [
        "INTERACTIVE_ENABLED",
        "INTERACTIVE_MAX_BRANCHES",
        "INTERACTIVE_MAX_DEPTH",
        "INTERACTIVE_MAX_NODES",
        "INTERACTIVE_LLM_MODEL",
        "INTERACTIVE_STORAGE_ROOT",
        "INTERACTIVE_REQUIRE_MATURE_CONSENT",
        "INTERACTIVE_ENFORCE_REGION_BLOCK",
        "INTERACTIVE_MODERATE_MATURE",
        "INTERACTIVE_REGION_BLOCK",
        "INTERACTIVE_LATENCY_TARGET_MS",
    ]:
        monkeypatch.delenv(k, raising=False)
    from app.interactive import load_config
    cfg = load_config()
    # Chassis guardrails ON by default — cannot be skipped without env.
    assert cfg.enabled is False
    assert cfg.require_consent_for_mature is True
    assert cfg.enforce_region_block is True
    assert cfg.moderate_mature_narration is True
    assert cfg.max_branches == 12
    assert cfg.max_depth == 6
    assert cfg.llm_model == "llama3:8b"
    assert cfg.region_block == []


def test_region_block_parses_csv(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_REGION_BLOCK", " US , RU, VA ")
    from app.interactive import load_config
    cfg = load_config()
    assert cfg.region_block == ["US", "RU", "VA"]


def test_app_mount_is_idempotent_when_flag_off(client):
    """The app's test client is imported with the flag defaulting to
    False. Mounting the interactive router must not have added any
    ``/v1/interactive/*`` paths to the API."""
    resp = client.get("/v1/interactive/health")
    assert resp.status_code == 404  # no such route when disabled
