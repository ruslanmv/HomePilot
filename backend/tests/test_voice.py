"""MB2 — backend voice session (WS /v1/voice/session)."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


def test_voice_session_disabled_rejects(app, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "VOICE_BACKEND_ENABLED", False, raising=False)
    client = TestClient(app)
    with client.websocket_connect("/v1/voice/session") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error" and "disabled" in msg["error"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_voice_session_enabled_replies(app, monkeypatch):
    from app import config, llm

    monkeypatch.setattr(config, "VOICE_BACKEND_ENABLED", True, raising=False)

    async def fake_chat(messages, **kw):
        user = [m for m in messages if m["role"] == "user"][-1]["content"]
        return {"choices": [{"message": {"content": f"You said: {user}"}}]}

    monkeypatch.setattr(llm, "chat", fake_chat)

    client = TestClient(app)
    with client.websocket_connect("/v1/voice/session") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"
        assert "tts" in ready and "stt" in ready

        ws.send_json({"type": "text", "text": "hello world"})
        reply = ws.receive_json()
        assert reply["type"] == "reply"
        assert reply["text"] == "You said: hello world"

        # ping/pong
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"

        # audio with no STT provider → graceful error, socket stays open
        ws.send_json(
            {"type": "audio", "format": "wav", "data_b64": base64.b64encode(b"x").decode()}
        )
        assert ws.receive_json()["type"] == "error"

        # barge-in signal acknowledged
        ws.send_json({"type": "interrupt"})
        assert ws.receive_json()["type"] == "interrupted"


def test_voice_session_audio_transcribes_then_replies(app, monkeypatch):
    """MB2.5 — an audio frame is transcribed (STT) then answered (LLM)."""
    from app import config, llm
    from app.voice import routes

    monkeypatch.setattr(config, "VOICE_BACKEND_ENABLED", True, raising=False)

    class FakeSTT:
        name = "fake"
        available = True

        async def transcribe(self, audio, *, fmt="wav"):
            return "what time is it"

    monkeypatch.setattr(routes, "get_stt_provider", lambda: FakeSTT())

    async def fake_chat(messages, **kw):
        user = [m for m in messages if m["role"] == "user"][-1]["content"]
        return {"choices": [{"message": {"content": f"heard: {user}"}}]}

    monkeypatch.setattr(llm, "chat", fake_chat)

    client = TestClient(app)
    with client.websocket_connect("/v1/voice/session") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json(
            {"type": "audio", "format": "wav", "data_b64": base64.b64encode(b"RIFF....").decode()}
        )
        tr = ws.receive_json()
        assert tr["type"] == "transcript" and tr["text"] == "what time is it"
        reply = ws.receive_json()
        assert reply["type"] == "reply" and reply["text"] == "heard: what time is it"


def test_voice_session_persona_config(app, monkeypatch):
    """MB4 — a config frame switches the persona/system prompt for the LLM call."""
    from app import config, llm

    monkeypatch.setattr(config, "VOICE_BACKEND_ENABLED", True, raising=False)
    seen: dict = {}

    async def fake_chat(messages, **kw):
        seen["system"] = messages[0]["content"]
        return {"choices": [{"message": {"content": "arr"}}]}

    monkeypatch.setattr(llm, "chat", fake_chat)

    client = TestClient(app)
    with client.websocket_connect("/v1/voice/session") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "config", "system": "You are a pirate."})
        assert ws.receive_json()["type"] == "configured"
        ws.send_json({"type": "text", "text": "hi"})
        assert ws.receive_json()["type"] == "reply"
        assert seen["system"] == "You are a pirate."  # persona applied to the LLM


def test_tts_premium_gating(monkeypatch):
    """MB5 — neural voice only for entitled sessions, only when configured."""
    from app.voice import providers as P

    monkeypatch.delenv("TTS_BASE_URL", raising=False)
    assert P.get_tts_provider(premium=True).name in ("piper", "null")  # nothing to upgrade to

    monkeypatch.setenv("TTS_BASE_URL", "https://tts.example/v1")
    assert P.get_tts_provider(premium=True).name == "cloud-neural"
    assert P.get_tts_provider(premium=False).name in ("piper", "null")  # free stays free


def test_cloud_neural_synth_mocked(monkeypatch):
    """MB5 — neural provider POSTs /audio/speech and returns audio bytes."""
    import asyncio

    import httpx

    from app.voice.providers import CloudNeuralTTSProvider

    monkeypatch.setenv("TTS_BASE_URL", "https://tts.example/v1")

    class _Resp:
        content = b"MP3DATA"

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    audio = asyncio.run(CloudNeuralTTSProvider().synth("hello"))
    assert audio == b"MP3DATA"


def test_orchestrator_unit(monkeypatch):
    """Orchestrator reuses the injected LLM fn and keeps conversation state."""
    import asyncio

    from app.voice.session import VoiceOrchestrator

    async def llm_fn(messages):
        # second turn should see the first turn in history
        return f"turns={sum(1 for m in messages if m['role'] == 'user')}"

    orch = VoiceOrchestrator(llm_fn=llm_fn)
    r1 = asyncio.run(orch.respond("a"))
    r2 = asyncio.run(orch.respond("b"))
    assert r1["text"] == "turns=1"
    assert r2["text"] == "turns=2"  # history carried across turns
    assert "audio" not in r1  # Null TTS in tests → text only
