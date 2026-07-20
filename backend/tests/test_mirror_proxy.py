"""Tests for the Account Mirror BFF proxy (Batch 1).

Drives the router with a mocked OllaBridge Cloud upstream so we can assert
forwarding, server-side token attachment (and non-leakage), status passthrough
(incl. 409 node_offline), input validation, credential resolution, and
transport error mapping — without a real cloud or the full app.
"""
import os
import sys

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app import mirror_proxy as mp  # noqa: E402


# ── Fake upstream ────────────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, ValueError):
            raise self._payload
        return self._payload


class _FakeClient:
    """Records the last upstream request and returns a scripted response."""
    last = {}
    script = {"status": 200, "payload": []}
    raise_exc = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def request(self, method, url, headers=None, params=None, json=None):
        _FakeClient.last = {"method": method, "url": url, "headers": headers or {},
                            "params": params, "json": json}
        if _FakeClient.raise_exc is not None:
            raise _FakeClient.raise_exc
        return _FakeResp(_FakeClient.script["status"], _FakeClient.script["payload"])


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    # Bypass DB-backed auth: every request is a fixed signed-in user.
    monkeypatch.setattr(mp, "_require_user", lambda a, c: {"id": "user-1"})
    # Deterministic cloud config.
    monkeypatch.setattr(mp._cfg, "OLLABRIDGE_CLOUD_URL", "https://cloud.example", raising=False)
    monkeypatch.setattr(mp._cfg, "OLLABRIDGE_CLOUD_TOKEN", "operator-token", raising=False)
    # Mock the upstream HTTP client.
    monkeypatch.setattr(mp.httpx, "AsyncClient", _FakeClient)
    _FakeClient.last = {}
    _FakeClient.raise_exc = None
    _FakeClient.script = {"status": 200, "payload": []}
    with mp._registry_lock:
        mp._USER_CLOUD_TOKENS.clear()
    yield


def _client():
    app = FastAPI()
    app.include_router(mp.router)
    return TestClient(app)


# ── Flag parsing ─────────────────────────────────────────────────────────────

def test_is_enabled_env(monkeypatch):
    monkeypatch.delenv("HOMEPILOT_MIRROR_BFF_ENABLED", raising=False)
    assert mp.is_enabled() is False
    for v in ("1", "true", "YES", "on"):
        monkeypatch.setenv("HOMEPILOT_MIRROR_BFF_ENABLED", v)
        assert mp.is_enabled() is True
    monkeypatch.setenv("HOMEPILOT_MIRROR_BFF_ENABLED", "off")
    assert mp.is_enabled() is False


# ── Forwarding + token attachment ────────────────────────────────────────────

def test_list_nodes_forwards_and_attaches_token():
    _FakeClient.script = {"status": 200, "payload": [{"id": "node-a", "online": True}]}
    r = _client().get("/v1/account/mirror/nodes")
    assert r.status_code == 200
    assert r.json()[0]["id"] == "node-a"
    # Went to the right upstream path with the server-side bearer.
    assert _FakeClient.last["url"] == "https://cloud.example/v1/mirror/nodes"
    assert _FakeClient.last["headers"]["Authorization"] == "Bearer operator-token"
    # No-store so mirror data isn't cached by the browser.
    assert r.headers["cache-control"] == "no-store"


def test_token_never_leaks_to_client():
    _FakeClient.script = {"status": 200, "payload": [{"id": "n"}]}
    r = _client().get("/v1/account/mirror/nodes")
    assert "operator-token" not in r.text
    assert "authorization" not in {k.lower() for k in r.headers}


def test_per_user_token_preferred_over_operator():
    mp.register_cloud_token("user-1", "per-user-token")
    _client().get("/v1/account/mirror/nodes")
    assert _FakeClient.last["headers"]["Authorization"] == "Bearer per-user-token"


def test_node_offline_409_preserved():
    _FakeClient.script = {"status": 409, "payload": {"error": "node_offline", "node_id": "n1"}}
    r = _client().get("/v1/account/mirror/nodes/n1/manifest")
    assert r.status_code == 409
    assert r.json()["error"] == "node_offline"


# ── RPC allow-list + validation ──────────────────────────────────────────────

def test_rpc_allowed_op_forwards():
    _FakeClient.script = {"status": 200, "payload": {"ok": True}}
    r = _client().post("/v1/account/mirror/nodes/n1/rpc",
                       json={"operation": "projects.list", "params": {}})
    assert r.status_code == 200
    assert _FakeClient.last["json"] == {"operation": "projects.list", "params": {}}


def test_rpc_disallowed_op_rejected_without_upstream_call():
    _FakeClient.last = {}
    r = _client().post("/v1/account/mirror/nodes/n1/rpc",
                       json={"operation": "shell.exec", "params": {}})
    assert r.status_code == 400
    assert _FakeClient.last == {}  # never forwarded


def test_invalid_node_id_rejected():
    r = _client().get("/v1/account/mirror/nodes/bad%2Fid/manifest")
    assert r.status_code in (400, 404)  # our 400, or path-not-matched


def test_oversized_params_rejected():
    big = {"x": "a" * (300 * 1024)}
    r = _client().post("/v1/account/mirror/nodes/n1/rpc",
                       json={"operation": "projects.list", "params": big})
    assert r.status_code == 413


# ── Jobs ─────────────────────────────────────────────────────────────────────

def test_create_job_forwards_resource_uri():
    _FakeClient.script = {"status": 202, "payload": {"job_id": "job-1"}}
    r = _client().post("/v1/account/mirror/nodes/n1/jobs",
                       json={"operation": "chat", "params": {"m": "hi"},
                             "resource_uri": "hpnode://n1/model/x"})
    assert r.status_code == 202
    assert _FakeClient.last["json"]["resource_uri"] == "hpnode://n1/model/x"


def test_get_job_requires_node_id():
    r = _client().get("/v1/account/mirror/jobs/job-1")   # missing node_id
    assert r.status_code == 422


def test_get_job_passes_node_id_query():
    _FakeClient.script = {"status": 200, "payload": {"status": "running"}}
    r = _client().get("/v1/account/mirror/jobs/job-1", params={"node_id": "n1"})
    assert r.status_code == 200
    assert _FakeClient.last["params"] == {"node_id": "n1"}
    assert _FakeClient.last["url"] == "https://cloud.example/v1/mirror/jobs/job-1"


# ── Credential resolution ────────────────────────────────────────────────────

def test_missing_credentials_returns_503(monkeypatch):
    monkeypatch.setattr(mp._cfg, "OLLABRIDGE_CLOUD_TOKEN", "", raising=False)
    r = _client().get("/v1/account/mirror/nodes")
    assert r.status_code == 503


def test_status_reports_linked_without_exposing_token():
    r = _client().get("/v1/account/mirror/status")
    assert r.status_code == 200
    body = r.json()
    assert body["linked"] is True and body["enabled"] is True
    assert "operator-token" not in r.text


# ── Transport error mapping ──────────────────────────────────────────────────

def test_upstream_timeout_maps_504():
    _FakeClient.raise_exc = httpx.TimeoutException("slow")
    r = _client().get("/v1/account/mirror/nodes")
    assert r.status_code == 504
    assert r.json()["error"] == "upstream_timeout"


def test_upstream_error_maps_502():
    _FakeClient.raise_exc = httpx.ConnectError("boom")
    r = _client().get("/v1/account/mirror/nodes")
    assert r.status_code == 502
    assert r.json()["error"] == "upstream_unreachable"
