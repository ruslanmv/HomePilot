"""``GET /v1/meetingsense/status`` answers in every state (batch MS0).

The route's whole job is to be the thing a frontend can trust when nothing else works. So
the tests are mostly about the unhappy paths: the flag is off, the speech providers are
missing, an optional import raises. In every one of those the answer is a 200 with a reason,
never a 404 and never a 500 — because a 404 collapses "disabled", "cannot transcribe" and
"not deployed" into one word, and a 500 fails at the one job a status endpoint has.

MS0 mounts no session route, so nothing here starts a meeting. That arrives in MS3.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Imported inside the fixtures below, never at module scope. `tests/conftest.py` purges
# every `app.*` entry from `sys.modules` in a session fixture, so a module captured at
# collection time is a *different object* from the one `monkeypatch.setattr("app...")`
# reaches afterwards — the patch lands on one and the route runs in the other. That is why
# these tests pass alone and failed the moment another suite ran first.

MS_ENV_VARS = [
    "MEETINGSENSE_ENABLED",
    "MEETINGSENSE_REMOTE",
    "MEETINGSENSE_TOGETHER",
    "MEETINGSENSE_CATALOG",
    "MEETINGSENSE_MCP",
    "MEETINGSENSE_AGENT",
    "MEETINGSENSE_MODES",
    "MEETINGSENSE_RETENTION",
    "MEETINGSENSE_VISION_MODEL",
    "STT_BASE_URL",
    "WHISPER_MODEL",
    "MULTIMODAL_MODEL",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in MS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def routes():
    """The live ``app.meetingsense.routes`` module, imported after conftest's purge.

    Tests patch attributes on *this object* rather than by dotted string, so the patch and
    the running route are guaranteed to be the same module.
    """
    import app.meetingsense.routes as module

    return module


@pytest.fixture()
def client(routes):
    """A bare app carrying only this router — the route must not depend on the rest of
    main.py being importable, which is also what keeps this test fast."""
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


# ── it answers, whichever way the flag is set ───────────────────────────────


def test_disabled_is_a_200_with_a_reason_not_a_404(client, monkeypatch):
    # Stated rather than inherited: since MS30 an unset MEETINGSENSE_ENABLED means *on*.
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "false")
    body = client.get("/v1/meetingsense/status").json()
    assert body["enabled"] is False
    assert body["ready"] is False
    assert "stt" in body and "vision" in body


def test_enabled_still_reports_ready_false_without_speech(client, routes, monkeypatch):
    # The distinction the endpoint exists for: the operator turned it on, and the machine
    # still cannot record. A UI that only reads `enabled` would show a control that fails.
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
    monkeypatch.setattr(
        routes,
        "stt_capability",
        lambda: {"available": False, "provider": None, "segments": False, "remote": False, "hint": "no stt"},
    )
    body = client.get("/v1/meetingsense/status").json()
    assert body["enabled"] is True
    assert body["ready"] is False
    assert body["stt"]["hint"] == "no stt"


def test_ready_needs_both_the_flag_and_a_provider(client, routes, monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
    monkeypatch.setattr(
        routes,
        "stt_capability",
        lambda: {"available": True, "provider": "whisper-local", "segments": True, "remote": False, "hint": None},
    )
    body = client.get("/v1/meetingsense/status").json()
    assert body["ready"] is True


def test_the_flag_alone_is_not_ready(client, routes, monkeypatch):
    # Stated rather than inherited: since MS30 an unset MEETINGSENSE_ENABLED means *on*.
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "false")
    # And the inverse: a provider without the flag is not ready either.
    monkeypatch.setattr(
        routes,
        "stt_capability",
        lambda: {"available": True, "provider": "whisper-local", "segments": True, "remote": False, "hint": None},
    )
    assert client.get("/v1/meetingsense/status").json()["ready"] is False


def test_sub_flags_are_reported_individually(client, monkeypatch):
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
    monkeypatch.setenv("MEETINGSENSE_TOGETHER", "true")
    flags = client.get("/v1/meetingsense/status").json()["flags"]
    assert flags["together"] is True
    assert flags["agent"] is False


def test_limits_are_echoed_so_a_client_needs_one_call(client):
    limits = client.get("/v1/meetingsense/status").json()["limits"]
    assert limits["panel_max_kb"] == 64
    assert limits["max_keyframes_per_hour"] == 60


def test_the_route_never_500s_when_a_probe_explodes(client, routes, monkeypatch):
    # The probes below catch their own errors. This asserts the route survives a probe that
    # does not — because "status always answers" should be a property of the route, not a
    # promise every future probe has to remember to keep.
    def boom():
        raise RuntimeError("providers module is broken")

    monkeypatch.setattr(routes, "stt_capability", boom)
    response = client.get("/v1/meetingsense/status")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert "probe failed" in body["stt"]["hint"]


def test_a_broken_vision_probe_does_not_take_the_route_down(client, routes, monkeypatch):
    monkeypatch.setattr(
        routes,
        "vision_capability",
        lambda _model: (_ for _ in ()).throw(RuntimeError("no vision stack")),
    )
    body = client.get("/v1/meetingsense/status").json()
    assert body["vision"]["available"] is False
    assert "probe failed" in body["vision"]["hint"]


# ── the probes are the thing that must not raise ────────────────────────────


def test_stt_probe_survives_a_missing_provider_module(routes, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if "voice.providers" in name or name.endswith("providers"):
            raise ImportError("no speech stack here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    info = routes.stt_capability()
    assert info["available"] is False
    assert info["hint"]  # says what is missing rather than staying silent


def test_stt_probe_names_the_provider(routes, monkeypatch):
    # Naming it is what lets the consent sheet name it. `get_stt_provider()` prefers the
    # remote endpoint whenever STT_BASE_URL is set, and a user who configured that months
    # ago for voice calls should not discover it by shipping an hour of meeting audio.
    monkeypatch.setenv("STT_BASE_URL", "https://api.example/v1")
    info = routes.stt_capability()
    assert info["remote"] is True
    assert info["provider"] is not None


def test_stt_probe_reports_no_timestamps_before_ms1(routes):
    # Honest today: the design cites t0 per note, and nothing produces timed spans until MS1
    # adds `transcribe_segments`. When that lands this flips with no edit here, because the
    # probe asks for the method rather than for a version.
    assert routes.stt_capability()["segments"] is False


def test_vision_probe_is_a_capability_not_a_blocker(routes):
    info = routes.vision_capability("")
    assert info["available"] is False
    assert info["hint"]


def test_vision_probe_prefers_the_meetingsense_model(routes, monkeypatch):
    monkeypatch.setenv("MULTIMODAL_MODEL", "moondream")
    info = routes.vision_capability("gemma3:4b")
    assert info["model"] == "gemma3:4b"
    assert info["available"] is True


def test_vision_probe_falls_back_to_the_multimodal_default(routes, monkeypatch):
    monkeypatch.setenv("MULTIMODAL_MODEL", "moondream")
    assert routes.vision_capability("")["model"] == "moondream"


# ── it reveals nothing it should not ────────────────────────────────────────


def test_status_carries_no_meeting_content(client, monkeypatch):
    # Unauthenticated by design, like /health. That is only safe while the body says what
    # the install can do and never what anyone said in a meeting.
    monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
    body = client.get("/v1/meetingsense/status").json()
    # `remote_ok` (MS8) is a capability boolean like the rest — whether a meeting may arrive
    # over the avatar session — and says nothing about any meeting.
    assert set(body) == {
        "enabled",
        "ready",
        "retention",
        "flags",
        "stt",
        "vision",
        "limits",
        "remote_ok",
    }


def test_status_does_not_leak_a_remote_stt_url(client, monkeypatch):
    # Reporting *that* a remote provider is configured is the point; reporting the endpoint
    # — which may carry a key in its host or path — is not.
    monkeypatch.setenv("STT_BASE_URL", "https://user:secret@api.example/v1")
    body = client.get("/v1/meetingsense/status").json()
    assert "secret" not in str(body)
    assert "api.example" not in str(body)
