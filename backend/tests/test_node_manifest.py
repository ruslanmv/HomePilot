"""
Node Manifest tests — Phase 1 of the OllaBridge Cloud Mirror.

Locks the invariants the design guarantees:
  - localhost only (remote callers get 403; the manifest can expose more
    than the public catalog)
  - feature-flagged (404 when off; mounting is always safe)
  - no secrets ever appear in the manifest
  - the two permission flags stay distinct: every persona is
    mirror_to_owner=True, but publish_provider_api follows shared_api.enabled
    (the unchanged legacy-catalog gate)
  - revision only advances when content changes (cheap delta sync)

Self-contained: no network dependency (ollama/comfyui probes fail closed).
"""
from __future__ import annotations

import os
import sys

import pytest

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


@pytest.fixture()
def nm(tmp_path, monkeypatch):
    monkeypatch.setenv("OLLABRIDGE_NODE_MANIFEST_ENABLED", "true")
    monkeypatch.setenv("NODE_MANIFEST_STATE_PATH", str(tmp_path / "rev.json"))
    monkeypatch.setenv("HOMEPILOT_NODE_NAME", "Test Workstation")
    import app.node_manifest as m
    import importlib
    importlib.reload(m)
    m._REVISION_STATE.update({"hash": "", "revision": 0})
    return m


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, host="127.0.0.1"):
        self.client = _FakeClient(host)


# ── Build ────────────────────────────────────────────────────────────────────

class TestBuild:
    def test_manifest_shape(self, nm):
        man = nm.build_manifest()
        assert man["schema"] == "homepilot.node.manifest/v1"
        assert man["node_id"].startswith("node_")
        assert man["node_name"] == "Test Workstation"
        for key in ("hardware", "services", "capabilities", "resources"):
            assert key in man
        for key in ("chat_models", "personas", "image_models",
                    "video_models", "workflows"):
            assert key in man["resources"]

    def test_video_models_match_pipeline(self, nm):
        man = nm.build_manifest()
        ids = {m["id"] for m in man["resources"]["video_models"]}
        # from the essay-video bundle work
        assert "ltx-video" in ids and "seedream" not in ids

    def test_revision_advances_only_on_change(self, nm):
        r1 = nm.build_manifest()["manifest_revision"]
        r2 = nm.build_manifest()["manifest_revision"]
        assert r1 == r2 and r1 >= 1  # idle node: stable revision
        # a changed resource set bumps it
        nm._REVISION_STATE["hash"] = "forced-different"
        r3 = nm.build_manifest()["manifest_revision"]
        assert r3 == r2 + 1

    def test_services_fail_closed_without_backends(self, nm):
        man = nm.build_manifest()
        # no ollama/comfyui reachable in the test env -> offline, never crash
        assert man["services"]["ollama"]["status"] in ("ready", "offline")
        assert man["services"]["comfyui"]["status"] in ("ready", "offline")


# ── Permission flags ─────────────────────────────────────────────────────────

class TestPermissionFlags:
    def test_persona_flags_distinct(self, nm, monkeypatch):
        published = {"id": "p1", "project_type": "persona",
                     "name": "Public Assistant",
                     "shared_api": {"enabled": True, "alias": "pub"}}
        private = {"id": "p2", "project_type": "persona",
                   "name": "Private Financial Assistant",
                   "shared_api": {"enabled": False}}

        import app.projects as projects_mod
        monkeypatch.setattr(projects_mod, "list_all_projects",
                            lambda: [published, private])
        personas = nm._personas()
        by_id = {p["id"]: p for p in personas}

        # both mirror to the owner...
        assert by_id["p1"]["mirror_to_owner"] is True
        assert by_id["p2"]["mirror_to_owner"] is True
        # ...but only the shared_api-enabled one is publishable to the legacy API
        assert by_id["p1"]["publish_provider_api"] is True
        assert by_id["p2"]["publish_provider_api"] is False
        # unpublished persona exposes no provider_id (absent from /v1/models)
        assert by_id["p2"]["provider_id"] is None
        assert by_id["p1"]["provider_id"] and by_id["p1"]["provider_id"].startswith("persona:")


# ── No secrets ───────────────────────────────────────────────────────────────

class TestNoSecrets:
    def test_manifest_has_no_secret_material(self, nm, monkeypatch):
        secret = "sk-super-secret-token-DEADBEEF"
        monkeypatch.setenv("OPENAI_API_KEY", secret)
        monkeypatch.setenv("CIVITAI_API_KEY", secret)
        proj = {"id": "p1", "project_type": "persona", "name": "A",
                "shared_api": {"enabled": True},
                "mcp_oauth_token": secret, "api_key": secret}

        import app.projects as projects_mod
        monkeypatch.setattr(projects_mod, "list_all_projects", lambda: [proj])
        import json
        blob = json.dumps(nm.build_manifest())
        assert secret not in blob
        for banned in ("api_key", "oauth", "password", "secret", "private_key"):
            assert banned not in blob.lower()


# ── Endpoint guards ──────────────────────────────────────────────────────────

class TestEndpointGuards:
    def test_remote_caller_forbidden(self, nm):
        resp = nm.get_node_manifest(_FakeRequest(host="203.0.113.9"))
        assert resp.status_code == 403

    def test_localhost_allowed(self, nm):
        out = nm.get_node_manifest(_FakeRequest(host="127.0.0.1"))
        assert isinstance(out, dict) and out["schema"] == "homepilot.node.manifest/v1"

    def test_disabled_flag_404(self, nm, monkeypatch):
        monkeypatch.setenv("OLLABRIDGE_NODE_MANIFEST_ENABLED", "false")
        resp = nm.get_node_manifest(_FakeRequest(host="127.0.0.1"))
        assert resp.status_code == 404

    def test_allowlist_host(self, nm, monkeypatch):
        monkeypatch.setenv("NODE_MANIFEST_ALLOW_HOSTS", "172.18.0.5")
        out = nm.get_node_manifest(_FakeRequest(host="172.18.0.5"))
        assert isinstance(out, dict)

    def test_revision_endpoint_is_cheap(self, nm):
        out = nm.get_node_manifest_revision(_FakeRequest(host="127.0.0.1"))
        assert set(out) == {"node_id", "manifest_revision", "manifest_hash",
                            "generated_at"}
