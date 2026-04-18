"""
End-to-end tests for the additive voice-call backend.

These tests flip the feature flag on by monkey-patching the env var and
re-importing the FastAPI app. With the flag off, not a single endpoint
exists — verified first so we're sure the deployment-default is safe.
"""
from __future__ import annotations

import importlib
import os
import sys

import pytest
from fastapi.testclient import TestClient


# ── Helpers ──────────────────────────────────────────────────────────

def _reload_app():
    """Drop every ``app.*`` module and re-import so env var changes take
    effect. Expensive, so we only do it twice in this file."""
    for k in list(sys.modules):
        if k.startswith("app."):
            sys.modules.pop(k, None)
    return importlib.import_module("app.main")


def _fresh_client(enabled: bool) -> TestClient:
    os.environ["VOICE_CALL_ENABLED"] = "true" if enabled else "false"
    main = _reload_app()
    # Reset per-test in-memory state
    from app.voice_call import store, service
    store.ensure_schema()
    store._reset_for_tests()
    service._reset_for_tests()
    return TestClient(main.app)


def _register(client, username: str) -> tuple[dict, str]:
    r = client.post(
        "/v1/auth/register",
        json={"username": username, "password": "pw", "display_name": username},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["user"], body["token"]


# ── Flag-off invariant ───────────────────────────────────────────────

def test_flag_off_returns_no_endpoints():
    client = _fresh_client(enabled=False)
    # Every voice-call path must 404 when the flag is off.
    for path in (
        "/v1/voice-call/sessions",
        "/v1/voice-call/sessions/vcs_abc",
        "/v1/voice-call/sessions/vcs_abc/end",
        "/v1/voice-call/hints",
    ):
        # POST or GET, doesn't matter — the path shouldn't resolve at all.
        r = client.post(path) if "sessions" in path else client.get(path)
        assert r.status_code == 404, f"{path} should 404 when flag off: {r.status_code}"


# ── Flag-on lifecycle ────────────────────────────────────────────────

@pytest.fixture
def client_on():
    return _fresh_client(enabled=True)


def test_hints_endpoint(client_on):
    r = client_on.get("/v1/voice-call/hints")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hint_enabled"] is True
    assert body["hold_threshold_ms"] == 220
    assert body["auto_hide_ms"] == 1400
    # Entry modes the build accepts — must include the header CTA we ship.
    assert "header_button" in body["accepted_entry_modes"]


def test_create_session_happy_path(client_on):
    _u, token = _register(client_on, "vc_owner_a")
    r = client_on.post(
        "/v1/voice-call/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "entry_mode": "header_button",
            "device_info": {"platform": "web", "app_version": "2.1.0"},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["session_id"].startswith("vcs_")
    assert body["ws_url"].endswith(body["session_id"])
    # Resume token is the only place this value is exposed.
    assert isinstance(body["resume_token"], str) and len(body["resume_token"]) > 20
    # MVP capabilities: no streaming, no true barge-in.
    caps = body["capabilities"]
    assert caps["transcript_live"] is False
    assert caps["barge_in"] is False
    assert body["max_duration_sec"] >= 60


def test_get_session_owner_only(client_on):
    _ua, token_a = _register(client_on, "vc_owner_b")
    _ub, token_b = _register(client_on, "vc_owner_c")

    # Owner A creates a session.
    r = client_on.post(
        "/v1/voice-call/sessions",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"entry_mode": "header_button"},
    )
    sid = r.json()["session_id"]

    # Owner A can read it.
    r = client_on.get(
        f"/v1/voice-call/sessions/{sid}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r.status_code == 200, r.text
    # Resume token MUST NOT appear in the public getter.
    assert "resume_token" not in r.json()

    # Owner B gets 404 — not 403, probe-safe.
    r = client_on.get(
        f"/v1/voice-call/sessions/{sid}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 404, r.text


def test_end_session_is_idempotent(client_on):
    _u, token = _register(client_on, "vc_owner_d")
    sid = client_on.post(
        "/v1/voice-call/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"entry_mode": "header_button"},
    ).json()["session_id"]

    # First end → 200 with duration_sec + ended_reason.
    r1 = client_on.post(
        f"/v1/voice-call/sessions/{sid}/end",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "ended"
    assert r1.json()["ended_reason"] == "user_ended"

    # Second end → also 200, same shape (idempotent).
    r2 = client_on.post(
        f"/v1/voice-call/sessions/{sid}/end",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "ended"

    # Foreign user hitting end → 404.
    _ub, token_b = _register(client_on, "vc_stranger")
    r3 = client_on.post(
        f"/v1/voice-call/sessions/{sid}/end",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r3.status_code == 404, r3.text


# ── Policy tests ─────────────────────────────────────────────────────

def test_concurrent_session_cap(client_on, monkeypatch):
    """Two active sessions per user; third is 409."""
    _u, token = _register(client_on, "vc_many")
    for _ in range(2):
        r = client_on.post(
            "/v1/voice-call/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={"entry_mode": "header_button"},
        )
        assert r.status_code == 201, r.text
    r = client_on.post(
        "/v1/voice-call/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={"entry_mode": "header_button"},
    )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["code"] == "too_many_active_sessions"


# ── Service-level (pure state machine, no HTTP) ──────────────────────

def test_service_state_machine_direct():
    """Drive the service module directly for a pure-python unit test."""
    os.environ["VOICE_CALL_ENABLED"] = "true"
    # Use a fresh import so the in-memory seq cache is clean.
    for k in list(sys.modules):
        if k.startswith("app.voice_call"):
            sys.modules.pop(k, None)
    from app.voice_call import config, service, store
    cfg = config.load()
    store.ensure_schema()
    store._reset_for_tests()
    service._reset_for_tests()

    row = service.create_session(
        user_id="u_test",
        conversation_id=None, persona_id=None,
        entry_mode="header_button",
        client_platform="web", app_version="test",
        cfg=cfg,
    )
    assert row["status"] == "connecting"
    assert row["user_id"] == "u_test"

    service.mark_live(row["id"])
    assert service.get(row["id"], "u_test")["status"] == "live"

    # Foreign owner getter returns None — never leaks.
    assert service.get(row["id"], "u_different") is None

    # End → ended + idempotent.
    ended = service.end_session(sid=row["id"], user_id="u_test")
    assert ended["status"] == "ended"
    again = service.end_session(sid=row["id"], user_id="u_test")
    assert again["status"] == "ended"  # idempotent
