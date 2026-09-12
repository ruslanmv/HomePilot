"""One-shot speech-to-text over HTTP — the selected-microphone transcription path.

Why this exists
---------------
The browser's Web Speech API accepts no ``deviceId``. It always records the
operating system's default input, while HomePilot's VAD opens ``getUserMedia``
on the microphone chosen in Settings → Audio & Video. When those are two
different microphones, the level meter moves while a device nobody is speaking
into gets transcribed — and the browser reports no error, so the failure is
silent.

``WS /v1/voice/session`` could already transcribe, but it is flag-gated off by
default and answers with an LLM reply and synthesized audio in the same socket.
A client that wants *only* "these bytes → this text" had nothing to call.

So: one ungated endpoint that takes recorded audio from whichever device the
client chose and returns the transcript. The client records the selected
microphone with ``MediaRecorder`` and posts the blob, which removes the device
split entirely — the bytes transcribed are, by construction, the bytes captured
from the selected input.

Not gated behind ``VOICE_BACKEND_ENABLED``: that flag guards the server-side
*orchestration* (LLM + TTS in one socket). Transcription of audio the user just
recorded is the same capability MeetingSense already exposes, and gating it
would leave the web client with no alternative to the device split above. The
endpoint still reports ``available: false`` when nothing on the machine can
transcribe, so a client can fall back to Web Speech rather than guess.
"""

from __future__ import annotations

import base64
import os
import time
from typing import Any, Dict

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router = APIRouter(tags=["voice"])

#: Ceiling on one clip. A voice turn is seconds long; anything approaching this
#: is a client bug or an attempt to make the box transcribe a movie.
MAX_AUDIO_BYTES = 25 * 1024 * 1024

#: Container formats a provider can be handed. The value is the suffix the
#: provider writes to a temp file, which is how faster-whisper and the
#: OpenAI-compatible endpoint both infer the decoder.
ALLOWED_FORMATS = ("webm", "ogg", "wav", "mp3", "mp4", "m4a", "flac")


def _normalize_format(raw: str | None, content_type: str | None) -> str:
    """Pick the container suffix to hand the provider.

    An explicit ``format`` field wins. Otherwise it is derived from the upload's
    MIME type, because ``MediaRecorder`` picks its own container per browser
    (``audio/webm;codecs=opus`` on Chromium, ``audio/mp4`` on Safari) and the
    client should not have to hard-code that mapping.
    """
    candidate = (raw or "").strip().lower().lstrip(".")
    if not candidate and content_type:
        # "audio/webm;codecs=opus" → "webm"
        subtype = content_type.split(";")[0].strip().split("/")[-1].lower()
        candidate = {"mpeg": "mp3", "x-m4a": "m4a", "wave": "wav", "x-wav": "wav"}.get(
            subtype, subtype
        )
    if candidate not in ALLOWED_FORMATS:
        # Whisper decodes through ffmpeg, which sniffs the stream; webm is the
        # right guess for a browser recording and a wrong suffix is recoverable.
        return "webm"
    return candidate


def stt_capability() -> Dict[str, Any]:
    """What this machine can do about one-shot transcription.

    Mirrors the shape of MeetingSense's status payload so a client reads the
    same keys either way. ``remote`` is reported rather than merely implied: a
    configured ``STT_BASE_URL`` means the recording leaves the machine, and the
    UI has to be able to say so before the user speaks.
    """
    info: Dict[str, Any] = {
        "available": False,
        "provider": None,
        "remote": False,
        "remote_configured": bool(os.getenv("STT_BASE_URL", "").strip()),
        "device": None,
        "hint": (
            "Install local speech (pip install -r requirements/speech-cpu.txt) or configure "
            "STT_BASE_URL to transcribe on this computer."
        ),
    }
    try:
        from .providers import get_stt_provider

        provider = get_stt_provider()
        info["provider"] = getattr(provider, "name", None)
        info["available"] = bool(getattr(provider, "available", False))
        info["remote"] = getattr(provider, "name", "") == "openai-compat"
        info["device"] = getattr(provider, "device", None)
        if info["available"]:
            info["hint"] = None
    except Exception as exc:  # noqa: BLE001 — a status route must not fail at reporting
        info["hint"] = f"Speech providers unavailable: {exc}"
    return info


@router.get("/v1/voice/stt/status")
async def voice_stt_status() -> Dict[str, Any]:
    """Whether :func:`voice_transcribe` can do anything, and with what.

    A client calls this once at startup to decide between this endpoint and the
    browser's own recognizer. Never a 404 and never a 500: collapsing "not
    installed" into an error is what makes a client retry forever instead of
    falling back.
    """
    return stt_capability()


async def _transcribe_bytes(audio: bytes, fmt: str) -> Dict[str, Any]:
    from .providers import get_stt_provider

    provider = get_stt_provider()
    if not provider.available:
        capability = stt_capability()
        raise HTTPException(
            status_code=503,
            detail={
                "error": "speech-to-text not available on this server",
                "hint": capability.get("hint"),
                "capability": capability,
            },
        )

    started = time.monotonic()
    try:
        text = (await provider.transcribe(audio, fmt=fmt) or "").strip()
    except Exception as exc:  # noqa: BLE001 — surface the reason, do not 500 blindly
        raise HTTPException(
            status_code=502,
            detail={"error": f"transcription failed: {type(exc).__name__}: {exc}"},
        ) from exc

    return {
        # An empty string is a successful transcription of silence, not an
        # error. The caller distinguishes them by `text` being empty, which is
        # exactly what tells a user "your microphone was not picked up".
        "text": text,
        "provider": getattr(provider, "name", None),
        "remote": getattr(provider, "name", "") == "openai-compat",
        "format": fmt,
        "bytes": len(audio),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


@router.post("/v1/voice/transcribe")
async def voice_transcribe(
    audio: UploadFile = File(..., description="Recorded audio from the client's chosen input."),
    format: str | None = Form(default=None, description="Container suffix, e.g. webm or wav."),
) -> Dict[str, Any]:
    """Transcribe one recorded clip.

    Multipart rather than base64 so a ``MediaRecorder`` blob can be posted as-is
    without inflating it by a third in the request body.
    """
    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail={"error": "empty audio upload"})
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error": "audio too large",
                "max_bytes": MAX_AUDIO_BYTES,
                "bytes": len(data),
            },
        )
    return await _transcribe_bytes(data, _normalize_format(format, audio.content_type))


@router.post("/v1/voice/transcribe/base64")
async def voice_transcribe_base64(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Same transcription from a JSON body.

    Kept alongside the multipart route because the existing voice WebSocket
    already speaks ``{"data_b64": ...}``, and a client that has the audio as a
    base64 string should not have to rebuild a multipart request to reuse this.
    """
    raw = payload.get("data_b64") or payload.get("audio_b64") or ""
    if not isinstance(raw, str) or not raw:
        raise HTTPException(status_code=400, detail={"error": "data_b64 is required"})
    try:
        data = base64.b64decode(raw, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"error": f"invalid base64: {exc}"}) from exc
    if not data:
        raise HTTPException(status_code=400, detail={"error": "empty audio payload"})
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"error": "audio too large", "max_bytes": MAX_AUDIO_BYTES, "bytes": len(data)},
        )
    return await _transcribe_bytes(data, _normalize_format(payload.get("format"), None))
