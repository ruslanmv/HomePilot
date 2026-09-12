"""One-shot speech-to-text (POST /v1/voice/transcribe, GET /v1/voice/stt/status).

This endpoint exists so the web client can transcribe the microphone the user
selected. The browser's own recognizer takes no ``deviceId`` and always records
the OS default input, so without a path like this the voice level meter and the
transcript can come from two different devices with no error reported.
"""

from __future__ import annotations

import base64

import importlib

import pytest
from fastapi.testclient import TestClient


class _StubProvider:
    """Stands in for faster-whisper / an OpenAI-compatible endpoint."""

    def __init__(self, *, name="stub", available=True, text="turn the lights on", raises=None):
        self.name = name
        self._available = available
        self._text = text
        self._raises = raises
        self.calls = []

    @property
    def available(self):
        return self._available

    async def transcribe(self, audio, *, fmt="wav"):
        self.calls.append({"bytes": len(audio), "fmt": fmt})
        if self._raises:
            raise self._raises
        return self._text


@pytest.fixture
def client(app):
    return TestClient(app)


def _use(monkeypatch, provider):
    monkeypatch.setattr(
        "app.voice.providers.get_stt_provider", lambda: provider, raising=False
    )
    return provider


class TestStatus:
    def test_reports_availability_without_ever_erroring(self, client):
        # A status route that 404s or 500s collapses "not installed" into
        # "broken", which is what makes a client retry instead of falling back.
        response = client.get("/v1/voice/stt/status")
        assert response.status_code == 200
        body = response.json()
        assert set(["available", "provider", "remote", "hint"]).issubset(body)
        assert isinstance(body["available"], bool)

    def test_names_the_provider_when_one_can_transcribe(self, client, monkeypatch):
        _use(monkeypatch, _StubProvider(name="whisper-local"))
        body = client.get("/v1/voice/stt/status").json()
        assert body["available"] is True
        assert body["provider"] == "whisper-local"
        assert body["hint"] is None

    def test_flags_a_remote_provider_so_the_ui_can_say_so(self, client, monkeypatch):
        # The recording leaves the machine in this case. A user has to be able
        # to learn that before they speak, not after.
        _use(monkeypatch, _StubProvider(name="openai-compat"))
        body = client.get("/v1/voice/stt/status").json()
        assert body["remote"] is True

    def test_keeps_a_hint_when_nothing_can_transcribe(self, client, monkeypatch):
        _use(monkeypatch, _StubProvider(available=False))
        body = client.get("/v1/voice/stt/status").json()
        assert body["available"] is False
        assert body["hint"]

    def test_is_not_gated_behind_the_voice_backend_flag(self, client, monkeypatch):
        # VOICE_BACKEND_ENABLED guards server-side LLM+TTS orchestration. Gating
        # transcription behind it would leave the web client with no alternative
        # to the device split this endpoint exists to remove.
        from app import config

        monkeypatch.setattr(config, "VOICE_BACKEND_ENABLED", False, raising=False)
        assert client.get("/v1/voice/stt/status").status_code == 200


class TestTranscribeMultipart:
    def test_returns_the_transcript_for_a_recorded_clip(self, client, monkeypatch):
        provider = _use(monkeypatch, _StubProvider(text="  turn the lights on  "))

        response = client.post(
            "/v1/voice/transcribe",
            files={"audio": ("turn.webm", b"fake-opus-bytes", "audio/webm;codecs=opus")},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["text"] == "turn the lights on"
        assert body["bytes"] == len(b"fake-opus-bytes")
        assert provider.calls == [{"bytes": 15, "fmt": "webm"}]

    def test_derives_the_container_from_the_upload_mime_type(self, client, monkeypatch):
        # MediaRecorder picks its own container per browser (webm on Chromium,
        # mp4 on Safari); the client should not have to hard-code that mapping.
        provider = _use(monkeypatch, _StubProvider())
        client.post(
            "/v1/voice/transcribe",
            files={"audio": ("clip.m4a", b"bytes", "audio/mp4")},
        )
        assert provider.calls[0]["fmt"] == "mp4"

    def test_an_explicit_format_field_wins(self, client, monkeypatch):
        provider = _use(monkeypatch, _StubProvider())
        client.post(
            "/v1/voice/transcribe",
            files={"audio": ("clip.bin", b"bytes", "application/octet-stream")},
            data={"format": "wav"},
        )
        assert provider.calls[0]["fmt"] == "wav"

    def test_falls_back_to_webm_for_an_unknown_container(self, client, monkeypatch):
        provider = _use(monkeypatch, _StubProvider())
        client.post(
            "/v1/voice/transcribe",
            files={"audio": ("clip.bin", b"bytes", "application/octet-stream")},
        )
        assert provider.calls[0]["fmt"] == "webm"

    def test_silence_transcribes_to_empty_text_not_an_error(self, client, monkeypatch):
        # "Your microphone was not picked up" is a successful transcription of
        # silence. Turning it into an error would hide which of the two it was.
        _use(monkeypatch, _StubProvider(text="   "))
        response = client.post(
            "/v1/voice/transcribe",
            files={"audio": ("quiet.webm", b"bytes", "audio/webm")},
        )
        assert response.status_code == 200
        assert response.json()["text"] == ""

    def test_rejects_an_empty_upload(self, client, monkeypatch):
        _use(monkeypatch, _StubProvider())
        response = client.post(
            "/v1/voice/transcribe",
            files={"audio": ("empty.webm", b"", "audio/webm")},
        )
        assert response.status_code == 400

    def test_rejects_a_clip_over_the_ceiling(self, client, monkeypatch):
        _use(monkeypatch, _StubProvider())
        # Imported here, not at module scope: the `app` fixture purges and
        # re-imports every `app.*` module, so a module object captured at
        # collection time is not the one the mounted route uses.
        transcribe_module = importlib.import_module("app.voice.transcribe")
        monkeypatch.setattr(transcribe_module, "MAX_AUDIO_BYTES", 8)
        response = client.post(
            "/v1/voice/transcribe",
            files={"audio": ("long.webm", b"x" * 9, "audio/webm")},
        )
        assert response.status_code == 413

    def test_says_so_when_the_server_cannot_transcribe(self, client, monkeypatch):
        # 503 plus the capability payload, so the client can fall back to the
        # browser recognizer and tell the user why.
        _use(monkeypatch, _StubProvider(available=False))
        response = client.post(
            "/v1/voice/transcribe",
            files={"audio": ("clip.webm", b"bytes", "audio/webm")},
        )
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["capability"]["available"] is False
        assert detail["hint"]

    def test_surfaces_a_provider_failure_as_a_bad_gateway(self, client, monkeypatch):
        _use(monkeypatch, _StubProvider(raises=RuntimeError("ffmpeg missing")))
        response = client.post(
            "/v1/voice/transcribe",
            files={"audio": ("clip.webm", b"bytes", "audio/webm")},
        )
        assert response.status_code == 502
        assert "ffmpeg missing" in response.json()["detail"]["error"]


class TestTranscribeBase64:
    def test_accepts_the_same_audio_as_json(self, client, monkeypatch):
        # The existing voice WebSocket already speaks {"data_b64": ...}; a client
        # holding a base64 string should not have to rebuild a multipart request.
        provider = _use(monkeypatch, _StubProvider(text="hello there"))
        response = client.post(
            "/v1/voice/transcribe/base64",
            json={"data_b64": base64.b64encode(b"fake-wav").decode(), "format": "wav"},
        )
        assert response.status_code == 200
        assert response.json()["text"] == "hello there"
        assert provider.calls[0]["fmt"] == "wav"

    def test_rejects_a_missing_payload(self, client, monkeypatch):
        _use(monkeypatch, _StubProvider())
        assert client.post("/v1/voice/transcribe/base64", json={}).status_code == 400

    def test_rejects_undecodable_base64(self, client, monkeypatch):
        _use(monkeypatch, _StubProvider())
        response = client.post("/v1/voice/transcribe/base64", json={"data_b64": "!!!!"})
        assert response.status_code == 400
