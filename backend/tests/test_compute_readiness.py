"""Production-readiness signal for Compute Sources & Routing."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_unconfigured_reports_not_ready_with_actionable_warnings(monkeypatch):
    from app.compute import readiness
    for k in ("HOMEPILOT_COMPUTE_SECRET_KEY", "HOMEPILOT_CLOUD_TOKEN_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("app.config.API_KEY", "", raising=False)

    r = readiness.production_readiness()
    assert r["production_ready"] is False
    assert r["checks"]["ssrf_guard"] is True
    assert r["multi_tenant_registry"] is False
    joined = " ".join(r["warnings"]).lower()
    assert "homepilot_compute_secret_key" in joined
    assert "api_key" in joined


def test_fully_configured_reports_ready(monkeypatch):
    from app.compute import readiness
    monkeypatch.setattr(readiness, "_crypto_available", lambda: True)
    monkeypatch.setenv("HOMEPILOT_COMPUTE_SECRET_KEY", "k1")
    monkeypatch.setenv("HOMEPILOT_CLOUD_TOKEN_KEY", "k2")
    monkeypatch.setattr("app.config.API_KEY", "secret", raising=False)
    monkeypatch.setattr("app.config.OLLABRIDGE_CLOUD_URL", "https://app.ollabridge.com", raising=False)

    r = readiness.production_readiness()
    assert r["production_ready"] is True
    assert all(r["checks"][k] for k in ("source_secrets_encrypted", "cloud_token_encrypted", "external_api_key_set"))
    assert r["warnings"] == []


def test_non_canonical_cloud_url_is_advisory_only(monkeypatch):
    from app.compute import readiness
    monkeypatch.setattr(readiness, "_crypto_available", lambda: True)
    monkeypatch.setenv("HOMEPILOT_COMPUTE_SECRET_KEY", "k1")
    monkeypatch.setenv("HOMEPILOT_CLOUD_TOKEN_KEY", "k2")
    monkeypatch.setattr("app.config.API_KEY", "secret", raising=False)
    monkeypatch.setattr("app.config.OLLABRIDGE_CLOUD_URL", "https://ruslanmv-ollabridge.hf.space", raising=False)

    r = readiness.production_readiness()
    # Still "ready" (advisory), but a warning nudges toward the canonical URL.
    assert r["production_ready"] is True
    assert any("canonical" in w.lower() for w in r["warnings"])


def test_readiness_endpoint(client):
    body = client.get("/compute/readiness").json()
    assert "production_ready" in body and "checks" in body and "warnings" in body
