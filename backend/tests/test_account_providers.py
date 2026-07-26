"""Tests for the Account Providers BFF endpoint (Step 2).

Drives GET /v1/account/providers with a mocked OllaBridge Cloud upstream so we
can assert: contract status semantics (not_authenticated, not-linked, cloud
unavailable, linked-empty), shared-device grouping into ProviderOption rows,
per-user tenant isolation, device-name/online enrichment, the
owned_by="relay:<id>" compatibility fallback, graceful /v1/devices 404, and
that the server-side cloud token never leaks to the client.
"""
import os
import sys

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from app import account_providers as ap  # noqa: E402
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
    """Scripts responses per upstream path and records the calls made."""
    # path -> {"status": int, "payload": obj}
    routes = {}
    calls = []            # list of (method, url, headers)
    raise_on = None       # {path_substr: Exception} to simulate transport errors

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        _FakeClient.calls.append(("GET", url, headers or {}))
        if _FakeClient.raise_on:
            for frag, exc in _FakeClient.raise_on.items():
                if frag in url:
                    raise exc
        for path, script in _FakeClient.routes.items():
            if url.endswith(path):
                return _FakeResp(script["status"], script["payload"])
        return _FakeResp(404, {"detail": "not found"})


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    # Fixed signed-in user by default (tests override for the 401/isolation cases).
    monkeypatch.setattr(ap, "_require_user", lambda a, c: {"id": "user-1"})
    monkeypatch.setattr(mp._cfg, "OLLABRIDGE_CLOUD_URL", "https://cloud.example", raising=False)
    monkeypatch.setattr(mp._cfg, "OLLABRIDGE_CLOUD_TOKEN", "operator-token", raising=False)
    monkeypatch.setattr(ap.httpx, "AsyncClient", _FakeClient)
    _FakeClient.routes = {}
    _FakeClient.calls = []
    _FakeClient.raise_on = None
    with mp._registry_lock:
        mp._USER_CLOUD_TOKENS.clear()
    yield


def _client():
    app = FastAPI()
    app.include_router(ap.router)
    return TestClient(app)


# ── Flag parsing ─────────────────────────────────────────────────────────────

def test_is_enabled_env(monkeypatch):
    monkeypatch.delenv("HOMEPILOT_ACCOUNT_PROVIDERS_ENABLED", raising=False)
    assert ap.is_enabled() is False
    for v in ("1", "true", "YES", "on"):
        monkeypatch.setenv("HOMEPILOT_ACCOUNT_PROVIDERS_ENABLED", v)
        assert ap.is_enabled() is True
    monkeypatch.setenv("HOMEPILOT_ACCOUNT_PROVIDERS_ENABLED", "off")
    assert ap.is_enabled() is False


# ── Contract: status semantics ───────────────────────────────────────────────

def test_not_authenticated_returns_stable_401(monkeypatch):
    def _raise(a, c):
        raise HTTPException(status_code=401, detail="Authentication required")
    monkeypatch.setattr(ap, "_require_user", _raise)
    r = _client().get("/v1/account/providers")
    assert r.status_code == 401
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "not_authenticated"
    assert body["providers"] == []


def test_signed_in_but_not_linked_returns_200_unlinked(monkeypatch):
    # No per-user token and no operator token → seam raises 503 → contract 200.
    monkeypatch.setattr(mp._cfg, "OLLABRIDGE_CLOUD_TOKEN", "", raising=False)
    r = _client().get("/v1/account/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["linked"] is False
    assert body["providers"] == []
    # Nothing was queried upstream.
    assert _FakeClient.calls == []


def test_cloud_unavailable_returns_502():
    _FakeClient.raise_on = {"/ollama/v1/models": httpx.ConnectError("boom")}
    r = _client().get("/v1/account/providers")
    assert r.status_code == 502
    assert r.json()["error"] == "cloud_unavailable"


def test_cloud_timeout_returns_502():
    _FakeClient.raise_on = {"/ollama/v1/models": httpx.TimeoutException("slow")}
    r = _client().get("/v1/account/providers")
    assert r.status_code == 502
    assert r.json()["error"] == "cloud_unavailable"


def test_cloud_html_returns_502():
    _FakeClient.routes = {"/ollama/v1/models": {"status": 200, "payload": ValueError("<!doctype")}}
    r = _client().get("/v1/account/providers")
    assert r.status_code == 502
    assert r.json()["error"] == "cloud_unavailable"


def test_cloud_upstream_500_returns_502():
    _FakeClient.routes = {"/ollama/v1/models": {"status": 500, "payload": {"detail": "boom"}}}
    r = _client().get("/v1/account/providers")
    assert r.status_code == 502
    assert r.json()["error"] == "cloud_unavailable"


def test_expired_token_upstream_401_reads_as_unlinked():
    _FakeClient.routes = {"/ollama/v1/models": {"status": 401, "payload": {"detail": "expired"}}}
    r = _client().get("/v1/account/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["linked"] is False
    assert body["providers"] == []


def test_linked_but_no_shared_backends_returns_empty():
    # Only a route alias + cloud catalog model, nothing shared_device.
    _FakeClient.routes = {
        "/ollama/v1/models": {"status": 200, "payload": {"data": [
            {"id": "ollabridge:auto", "owned_by": "ollabridge-addon", "x_source": "route_alias"},
            {"id": "llama3", "owned_by": "ollama", "x_source": "cloud_catalog"},
        ]}},
        "/v1/devices": {"status": 200, "payload": []},
    }
    r = _client().get("/v1/account/providers")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["linked"] is True
    assert body["providers"] == []


# ── Grouping + enrichment ────────────────────────────────────────────────────

def test_shared_device_models_grouped_into_provider_with_device_metadata():
    _FakeClient.routes = {
        "/ollama/v1/models": {"status": 200, "payload": {"data": [
            {"id": "llama3:8b", "owned_by": "relay:dev-123", "x_source": "shared_device"},
            {"id": "qwen2:7b", "owned_by": "relay:dev-123", "x_source": "shared_device"},
            {"id": "ollabridge:auto", "owned_by": "ollabridge-addon", "x_source": "route_alias"},
        ]}},
        "/v1/devices": {"status": 200, "payload": [
            {"id": "dev-123", "name": "Gaming PC", "online": True},
        ]},
    }
    r = _client().get("/v1/account/providers")
    assert r.status_code == 200
    providers = r.json()["providers"]
    assert len(providers) == 1
    p = providers[0]
    assert p["id"] == "ollabridge:dev-123:ollama"
    assert p["label"] == "Ollama — Gaming PC (OllaBridge)"
    assert p["origin"] == "ollabridge"
    assert p["backend"] == "ollama"
    assert p["capability"] == "chat"
    assert p["online"] is True
    assert p["modelCount"] == 2
    assert p["nodeId"] == "dev-123"


def test_offline_device_flag_is_honored():
    _FakeClient.routes = {
        "/ollama/v1/models": {"status": 200, "payload": {"data": [
            {"id": "llama3:8b", "owned_by": "relay:dev-9", "x_source": "shared_device"},
        ]}},
        "/v1/devices": {"status": 200, "payload": [
            {"id": "dev-9", "name": "Home GPU", "online": False},
        ]},
    }
    providers = _client().get("/v1/account/providers").json()["providers"]
    assert providers[0]["online"] is False
    assert providers[0]["label"] == "Ollama — Home GPU (OllaBridge)"


def test_devices_404_falls_back_to_device_id_and_online_default():
    # /v1/devices 404 (device sharing disabled) → name falls back to the id and
    # an advertising device is treated as online.
    _FakeClient.routes = {
        "/ollama/v1/models": {"status": 200, "payload": {"data": [
            {"id": "llama3:8b", "owned_by": "relay:dev-abc", "x_source": "shared_device"},
        ]}},
        "/v1/devices": {"status": 404, "payload": {"detail": "Device sharing is not enabled"}},
    }
    providers = _client().get("/v1/account/providers").json()["providers"]
    assert len(providers) == 1
    assert providers[0]["nodeId"] == "dev-abc"
    assert providers[0]["label"] == "Ollama — dev-abc (OllaBridge)"
    assert providers[0]["online"] is True


def test_explicit_device_id_field_preferred_over_owned_by():
    _FakeClient.routes = {
        "/ollama/v1/models": {"status": 200, "payload": {"data": [
            {"id": "m1", "device_id": "dev-explicit", "owned_by": "relay:ignored",
             "x_source": "shared_device"},
        ]}},
        "/v1/devices": {"status": 200, "payload": []},
    }
    providers = _client().get("/v1/account/providers").json()["providers"]
    assert providers[0]["nodeId"] == "dev-explicit"


def test_legacy_source_field_also_recognized():
    # Some responses use "source" rather than "x_source".
    _FakeClient.routes = {
        "/ollama/v1/models": {"status": 200, "payload": {"data": [
            {"id": "m1", "owned_by": "relay:dev-1", "source": "shared_device"},
        ]}},
        "/v1/devices": {"status": 200, "payload": []},
    }
    providers = _client().get("/v1/account/providers").json()["providers"]
    assert len(providers) == 1 and providers[0]["nodeId"] == "dev-1"


def test_multiple_devices_produce_multiple_providers():
    _FakeClient.routes = {
        "/ollama/v1/models": {"status": 200, "payload": {"data": [
            {"id": "a", "owned_by": "relay:dev-1", "x_source": "shared_device"},
            {"id": "b", "owned_by": "relay:dev-2", "x_source": "shared_device"},
            {"id": "c", "owned_by": "relay:dev-2", "x_source": "shared_device"},
        ]}},
        "/v1/devices": {"status": 200, "payload": [
            {"id": "dev-1", "name": "One", "online": True},
            {"id": "dev-2", "name": "Two", "online": True},
        ]},
    }
    providers = _client().get("/v1/account/providers").json()["providers"]
    by_node = {p["nodeId"]: p for p in providers}
    assert set(by_node) == {"dev-1", "dev-2"}
    assert by_node["dev-1"]["modelCount"] == 1
    assert by_node["dev-2"]["modelCount"] == 2


def test_bare_list_model_payload_supported():
    # Cloud may return a bare list rather than {"data": [...]}.
    _FakeClient.routes = {
        "/ollama/v1/models": {"status": 200, "payload": [
            {"id": "m1", "owned_by": "relay:dev-1", "x_source": "shared_device"},
        ]},
        "/v1/devices": {"status": 200, "payload": []},
    }
    providers = _client().get("/v1/account/providers").json()["providers"]
    assert len(providers) == 1


# ── Security ─────────────────────────────────────────────────────────────────

def test_token_never_leaks_to_client():
    _FakeClient.routes = {
        "/ollama/v1/models": {"status": 200, "payload": {"data": []}},
        "/v1/devices": {"status": 200, "payload": []},
    }
    r = _client().get("/v1/account/providers")
    assert "operator-token" not in r.text
    assert "authorization" not in {k.lower() for k in r.headers}
    # But the server DID attach the bearer upstream.
    auths = [h.get("Authorization") for _, _, h in _FakeClient.calls]
    assert "Bearer operator-token" in auths


def test_per_user_token_isolates_tenants(monkeypatch):
    # user-2's own registered token must be used, not the operator fallback.
    monkeypatch.setattr(ap, "_require_user", lambda a, c: {"id": "user-2"})
    mp.register_cloud_token("user-2", "user-2-token")
    _FakeClient.routes = {
        "/ollama/v1/models": {"status": 200, "payload": {"data": []}},
        "/v1/devices": {"status": 200, "payload": []},
    }
    _client().get("/v1/account/providers")
    auths = [h.get("Authorization") for _, _, h in _FakeClient.calls]
    assert all(a == "Bearer user-2-token" for a in auths)
    assert "Bearer operator-token" not in auths


def test_response_is_not_cached():
    _FakeClient.routes = {
        "/ollama/v1/models": {"status": 200, "payload": {"data": []}},
        "/v1/devices": {"status": 200, "payload": []},
    }
    r = _client().get("/v1/account/providers")
    assert r.headers["cache-control"] == "no-store"
