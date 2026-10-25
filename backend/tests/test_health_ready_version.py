"""
/health always answers 200, so the Space looked healthy while its chat could not answer.
/health/live, /health/ready and /version tell a deploy what it needs to know: is the process
up, can a visitor get a reply, and which commit is serving.
"""
from __future__ import annotations

import json
import sys


def _resolution(model: str, source: str):
    from app.model_resolver import Resolution

    return Resolution(role="chat", configured=model, model=model, runtime_url="http://127.0.0.1:11434",
                      source=source, reason="test", configured_installed=source == "configured")


def test_live_needs_nothing(client):
    r = client.get("/health/live")
    assert r.status_code == 200 and r.json() == {"live": True}


def test_ready_when_the_chat_has_a_model(client, monkeypatch):
    async def fake(role, configured="", **_):
        return _resolution("qwen2.5:0.5b", "configured")

    monkeypatch.setattr(sys.modules["app.model_resolver"], "resolve", fake)
    r = client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True and body["chat"]["model"] == "qwen2.5:0.5b"


def test_not_ready_without_a_model(client, monkeypatch):
    async def fake(role, configured="", **_):
        return _resolution("", "none")

    monkeypatch.setattr(sys.modules["app.model_resolver"], "resolve", fake)
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["ready"] is False


def test_ready_never_raises(client, monkeypatch):
    async def broken(role, configured="", **_):
        raise KeyError(4)

    monkeypatch.setattr(sys.modules["app.model_resolver"], "resolve", broken)
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["chat"]["reason"] == "KeyError: 4"


def test_version_reads_the_build_info_the_deploy_writes(client, monkeypatch, tmp_path):
    info = tmp_path / "build-info.json"
    info.write_text(json.dumps({"sha": "abc1234", "built_at": "2026-10-24T20:00:00Z"}))
    monkeypatch.setenv("HOMEPILOT_BUILD_INFO", str(info))
    body = client.get("/version").json()
    assert body["sha"] == "abc1234" and body["built_at"] == "2026-10-24T20:00:00Z"
    assert body["edition"] in ("web", "local")


def test_version_without_build_info(client, monkeypatch, tmp_path):
    monkeypatch.setenv("HOMEPILOT_BUILD_INFO", str(tmp_path / "missing.json"))
    monkeypatch.delenv("HOMEPILOT_BUILD_SHA", raising=False)
    assert client.get("/version").json()["sha"] == "unknown"
