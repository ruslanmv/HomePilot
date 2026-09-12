from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException

from app.voice import routes


class _Request:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


class _STT:
    name = "whisper-local"
    available = True

    def __init__(self, text: str = "hello from the selected microphone"):
        self.text = text
        self.calls: list[tuple[bytes, str]] = []

    async def transcribe(self, audio: bytes, *, fmt: str = "wav") -> str:
        self.calls.append((audio, fmt))
        return self.text


@pytest.mark.asyncio
async def test_voice_stt_status_reports_provider_without_credentials(monkeypatch):
    provider = _STT()
    monkeypatch.setattr(routes, "get_stt_provider", lambda: provider)

    result = await routes.voice_stt_status()

    assert result == {"available": True, "provider": "whisper-local"}


@pytest.mark.asyncio
async def test_voice_transcribe_decodes_browser_audio_and_forwards_format(monkeypatch):
    provider = _STT("the selected microphone works")
    monkeypatch.setattr(routes, "get_stt_provider", lambda: provider)
    audio = b"fake-webm-opus-bytes"

    result = await routes.voice_transcribe(
        _Request({"format": "webm", "data_b64": base64.b64encode(audio).decode("ascii")})
    )

    assert provider.calls == [(audio, "webm")]
    assert result["text"] == "the selected microphone works"
    assert result["provider"] == "whisper-local"
    assert result["audio_bytes"] == len(audio)


@pytest.mark.asyncio
async def test_voice_transcribe_reports_unavailable_provider(monkeypatch):
    provider = _STT()
    provider.available = False
    monkeypatch.setattr(routes, "get_stt_provider", lambda: provider)

    with pytest.raises(HTTPException) as exc:
        await routes.voice_transcribe(_Request({"format": "webm", "data_b64": "AA=="}))

    assert exc.value.status_code == 503
    assert "not configured" in str(exc.value.detail).lower()


@pytest.mark.asyncio
async def test_voice_transcribe_rejects_invalid_base64(monkeypatch):
    monkeypatch.setattr(routes, "get_stt_provider", lambda: _STT())

    with pytest.raises(HTTPException) as exc:
        await routes.voice_transcribe(_Request({"format": "webm", "data_b64": "not base64!"}))

    assert exc.value.status_code == 400
    assert "base64" in str(exc.value.detail).lower()
