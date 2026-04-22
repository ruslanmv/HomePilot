import importlib

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.expert.readiness import build_readiness_report


def test_readiness_report_production_when_all_checks_enabled():
    report = build_readiness_report(
        {
            "EXPERT_TOOLS_ENABLED": "true",
            "EXPERT_MEMORY_ENABLED": "true",
            "EXPERT_EVALS_ENABLED": "true",
            "EXPERT_V2_ROUTER_ENABLED": "true",
            "EXPERT_MEMORY_BACKEND": "sqlite:///expert.db",
            "EXPERT_TELEMETRY_ENDPOINT": "http://otel:4318",
            "EXPERT_SAFETY_POLICY": "strict-research",
        }
    )

    assert report.ready is True
    assert report.stage == "production"
    assert all(c.passed for c in report.checks)


def test_readiness_route_returns_expected_shape(monkeypatch):
    routes_mod = importlib.import_module("app.expert.routes")

    app = FastAPI()
    app.include_router(routes_mod.router)
    client = TestClient(app)

    monkeypatch.setenv("EXPERT_TOOLS_ENABLED", "true")
    monkeypatch.setenv("EXPERT_MEMORY_ENABLED", "true")
    monkeypatch.setenv("EXPERT_EVALS_ENABLED", "true")
    monkeypatch.setenv("EXPERT_V2_ROUTER_ENABLED", "true")
    monkeypatch.setenv("EXPERT_MEMORY_BACKEND", "sqlite:///expert.db")
    monkeypatch.setenv("EXPERT_TELEMETRY_ENDPOINT", "http://otel:4318")
    monkeypatch.setenv("EXPERT_SAFETY_POLICY", "strict-research")

    res = client.get("/v1/expert/readiness")
    assert res.status_code == 200
    body = res.json()
    assert body["ready"] is True
    assert body["stage"] == "production"
    assert isinstance(body["checks"], list)
    assert len(body["checks"]) >= 5


def test_readiness_preprod_mode_requires_p0_mcp_servers():
    report = build_readiness_report(
        {
            "EXPERT_TOOLS_ENABLED": "true",
            "EXPERT_MEMORY_ENABLED": "true",
            "EXPERT_EVALS_ENABLED": "true",
            "EXPERT_V2_ROUTER_ENABLED": "true",
            "EXPERT_MEMORY_BACKEND": "sqlite:///expert.db",
            "EXPERT_TELEMETRY_ENDPOINT": "http://otel:4318",
            "EXPERT_SAFETY_POLICY": "strict-research",
            "EXPERT_PREPROD_MODE": "true",
        }
    )
    mcp_checks = [c for c in report.checks if c.name.startswith("mcp:")]
    assert not mcp_checks
    assert any(c.name == "context_forge_url" and c.passed is False for c in report.checks)


def test_readiness_preprod_direct_mode_requires_p0_mcp_servers():
    report = build_readiness_report(
        {
            "EXPERT_TOOLS_ENABLED": "true",
            "EXPERT_MEMORY_ENABLED": "true",
            "EXPERT_EVALS_ENABLED": "true",
            "EXPERT_V2_ROUTER_ENABLED": "true",
            "EXPERT_MEMORY_BACKEND": "sqlite:///expert.db",
            "EXPERT_TELEMETRY_ENDPOINT": "http://otel:4318",
            "EXPERT_SAFETY_POLICY": "strict-research",
            "EXPERT_PREPROD_MODE": "true",
            "EXPERT_MCP_ORCHESTRATOR": "direct",
        }
    )
    mcp_checks = [c for c in report.checks if c.name.startswith("mcp:")]
    assert mcp_checks
    assert all(c.passed is False for c in mcp_checks)
