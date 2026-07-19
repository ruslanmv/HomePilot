"""
Node RPC tests — Phase 2 (read-only mirror) of the OllaBridge Cloud Mirror.

The load-bearing guarantee: the relay can invoke ONLY whitelisted, read-only
operations - never an arbitrary URL/port/path/shell, and never a write. Plus
the shared guardrails: localhost-only, feature-flagged, no secrets, and the
{source, data} envelope.

Self-contained: no network, no live LLM.
"""
from __future__ import annotations

import importlib
import os
import sys

import pytest

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


@pytest.fixture()
def rpc(tmp_path, monkeypatch):
    monkeypatch.setenv("HOMEPILOT_MIRROR_RPC_ENABLED", "true")
    monkeypatch.setenv("OLLABRIDGE_NODE_MANIFEST_ENABLED", "true")
    monkeypatch.setenv("NODE_MANIFEST_STATE_PATH", str(tmp_path / "rev.json"))
    import app.node_rpc as r
    importlib.reload(r)
    return r


class _FakeReq:
    def __init__(self, host="127.0.0.1"):
        class _C:
            def __init__(s): s.host = host
        self.client = _C()


PROJECTS = [
    {"id": "proj1", "project_type": "persona", "name": "Public Assistant",
     "description": "d", "updated_at": 5, "shared_api": {"enabled": True},
     "api_key": "SECRET-KEY", "mcp_oauth_token": "SECRET-TOKEN",
     "mcp_servers": [{"name": "GitHub", "connected": True, "oauth": "SECRET"}]},
    {"id": "proj2", "project_type": "persona", "name": "Private Assistant",
     "description": "d", "updated_at": 3, "shared_api": {"enabled": False}},
]


# ── No arbitrary proxy: the core security property ───────────────────────────

class TestWhitelist:
    def test_unknown_operation_rejected(self, rpc):
        with pytest.raises(KeyError):
            rpc.dispatch("shell.exec", {"cmd": "rm -rf /"})
        with pytest.raises(KeyError):
            rpc.dispatch("http.get", {"url": "http://localhost:11434/api/tags"})

    def test_only_read_ops_registered(self, rpc):
        # Phase 2 is read-only: the verb (last dotted segment) must be a getter
        read_verbs = ("list", "get", "get_safe", "health", "manifest")
        for name in rpc._OPS:
            verb = name.split(".")[-1]
            assert verb in read_verbs, f"{name} has non-read verb {verb!r}"

    def test_every_op_declares_scope(self, rpc):
        for name, o in rpc._OPS.items():
            assert o.scope and ":" in o.scope

    def test_endpoint_unknown_op_400(self, rpc):
        resp = rpc.node_rpc(rpc.RpcRequest(operation="danger.op"), _FakeReq())
        assert resp.status_code == 400


# ── Envelope + operations ────────────────────────────────────────────────────

class TestOperations:
    def test_source_envelope(self, rpc):
        out = rpc.dispatch("services.health", {})
        assert out["source"]["type"] == "homepilot_node"
        assert out["source"]["node_id"].startswith("node_")
        assert out["operation"] == "services.health"
        assert "data" in out

    def test_projects_list_projection(self, rpc, monkeypatch):
        import app.projects as pj
        monkeypatch.setattr(pj, "list_all_projects", lambda: PROJECTS)
        out = rpc.dispatch("projects.list", {})["data"]
        assert {p["id"] for p in out} == {"proj1", "proj2"}
        pub = next(p for p in out if p["id"] == "proj1")
        assert pub["published_to_provider_api"] is True

    def test_personas_list_has_both_flags(self, rpc, monkeypatch):
        import app.projects as pj
        monkeypatch.setattr(pj, "list_all_projects", lambda: PROJECTS)
        out = rpc.dispatch("personas.list", {})["data"]
        by = {p["id"]: p for p in out}
        assert by["proj1"]["mirror_to_owner"] and by["proj1"]["publish_provider_api"]
        assert by["proj2"]["mirror_to_owner"] and not by["proj2"]["publish_provider_api"]

    def test_operations_listing(self, rpc):
        ops = {o["operation"] for o in rpc.available_operations()}
        assert {"services.health", "models.list", "personas.list",
                "projects.list", "workflows.list", "settings.get_safe"} <= ops


# ── No secrets ───────────────────────────────────────────────────────────────

class TestNoSecrets:
    def test_projects_detail_scrubs_credentials(self, rpc, monkeypatch):
        import json
        import app.projects as pj
        monkeypatch.setattr(pj, "list_all_projects", lambda: PROJECTS)
        detail = rpc.dispatch("projects.get", {"id": "proj1"})
        blob = json.dumps(detail)
        assert "SECRET-KEY" not in blob and "SECRET-TOKEN" not in blob
        for banned in ("api_key", "oauth", "shared_api"):
            assert banned not in blob.lower()

    def test_settings_get_safe_is_allowlisted(self, rpc, monkeypatch):
        import json
        monkeypatch.setenv("OPENAI_API_KEY", "sk-leak-me")
        monkeypatch.setenv("CIVITAI_API_KEY", "civ-leak-me")
        out = rpc.dispatch("settings.get_safe", {})["data"]
        blob = json.dumps(out)
        assert "leak-me" not in blob
        # only allowlisted keys + the connection-status summary
        assert set(out).issubset(set(rpc._SAFE_SETTING_KEYS) | {"mcp_connections"})

    def test_mcp_status_without_credentials(self, rpc, monkeypatch):
        import json
        import app.projects as pj
        monkeypatch.setattr(pj, "list_all_projects", lambda: PROJECTS)
        out = rpc.dispatch("settings.get_safe", {})["data"]["mcp_connections"]
        assert any(c["name"] == "GitHub" and c["status"] == "connected" for c in out)
        assert "SECRET" not in json.dumps(out)


# ── Guards ───────────────────────────────────────────────────────────────────

class TestGuards:
    def test_remote_forbidden(self, rpc):
        resp = rpc.node_rpc(rpc.RpcRequest(operation="services.health"),
                            _FakeReq(host="203.0.113.7"))
        assert resp.status_code == 403

    def test_disabled_404(self, rpc, monkeypatch):
        monkeypatch.setenv("HOMEPILOT_MIRROR_RPC_ENABLED", "false")
        resp = rpc.node_rpc(rpc.RpcRequest(operation="services.health"), _FakeReq())
        assert resp.status_code == 404

    def test_localhost_ok(self, rpc):
        out = rpc.node_rpc(rpc.RpcRequest(operation="services.health"), _FakeReq())
        assert out["operation"] == "services.health"
