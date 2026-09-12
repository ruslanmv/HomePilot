"""Backend voice endpoints — shared STT plus the optional smart voice session.

The browser uses ``POST /v1/voice/transcribe`` for Chat dictation and Voice mode so both
surfaces transcribe the *same selected microphone stream* instead of handing recognition to
Web Speech's browser-managed/default microphone.  The endpoint deliberately reuses the
existing STT provider abstraction (local Whisper by default, remote only when explicitly
configured) and is independent of ``VOICE_BACKEND_ENABLED``; that feature flag only gates the
full conversational WebSocket.

``GET /v1/voice/stt/status`` is intentionally small and credential-free so the client can
choose the backend path before it starts recording.  It never returns endpoint URLs or keys.

Protocol for the optional ``WS /v1/voice/session`` remains:
  client → server
    {"type":"text","text":"..."}
    {"type":"audio","format":"wav","data_b64":"..."}
    {"type":"config","persona_id":"…"}
    {"type":"interrupt"}
    {"type":"ping"}
  server → client
    {"type":"ready","tts":bool,"stt":bool}
    {"type":"transcript","text":"..."}
    {"type":"configured","persona_id":"…","label":"…"}
    {"type":"reply","text":"...","audio"?:{"format","data_b64"}}
    {"type":"error","error":"..."}
    {"type":"pong"}
"""

from __future__ import annotations

import base64
import binascii
import re

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app import config

from .providers import get_stt_provider, get_tts_provider
from .session import VoiceOrchestrator

router = APIRouter()

# A spoken turn should be tiny compared with normal upload limits.  Keeping a hard cap here
# prevents a broken client from base64-expanding an unbounded recording into backend memory.
_MAX_TRANSCRIBE_BYTES = 12 * 1024 * 1024
_FORMAT_RE = re.compile(r"^[a-z0-9]{2,8}$")


@router.get("/v1/voice/stt/status")
async def voice_stt_status() -> dict:
    """Return whether the configured voice STT provider can transcribe right now."""

    stt = get_stt_provider()
    return {
        "available": bool(stt.available),
        "provider": getattr(stt, "name", "unknown"),
    }


@router.post("/v1/voice/transcribe")
async def voice_transcribe(request: Request) -> dict:
    """Transcribe one browser-recorded utterance with HomePilot's configured STT provider.

    The payload is JSON rather than multipart so the public browser runtime can stay dependency
    free.  Audio is base64 only on the wire; it is never persisted by this route.
    """

    stt = get_stt_provider()
    if not stt.available:
        raise HTTPException(status_code=503, detail="Speech-to-text is not configured")

    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid transcription request") from exc

    fmt = str((payload or {}).get("format") or "webm").strip().lower().lstrip(".")
    if not _FORMAT_RE.fullmatch(fmt):
        raise HTTPException(status_code=400, detail="Unsupported audio format")

    encoded = str((payload or {}).get("data_b64") or "")
    if not encoded:
        raise HTTPException(status_code=400, detail="Audio payload is empty")

    try:
        audio = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Audio payload is not valid base64") from exc

    if not audio:
        raise HTTPException(status_code=400, detail="Audio payload is empty")
    if len(audio) > _MAX_TRANSCRIBE_BYTES:
        raise HTTPException(status_code=413, detail="Audio payload is too large")

    try:
        transcript = (await stt.transcribe(audio, fmt=fmt)).strip()
    except Exception as exc:  # noqa: BLE001 — return an actionable client error
        raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}") from exc

    return {
        "text": transcript,
        "provider": getattr(stt, "name", "unknown"),
        "audio_bytes": len(audio),
    }


@router.websocket("/v1/voice/session")
async def voice_session(websocket: WebSocket) -> None:
    await websocket.accept()

    if not getattr(config, "VOICE_BACKEND_ENABLED", False):
        await websocket.send_json({"type": "error", "error": "voice backend disabled"})
        await websocket.close(code=1008)
        return

    # Premium entitlement seam (MB5): a per-user check replaces this global flag
    # once billing exists. Free → Piper/silent; premium → neural voice.
    premium = getattr(config, "PREMIUM_VOICE_ENABLED", False)
    orchestrator = VoiceOrchestrator(tts=get_tts_provider(premium))
    stt = get_stt_provider()
    await websocket.send_json(
        {"type": "ready", "tts": orchestrator.tts_available, "stt": stt.available}
    )

    try:
        while True:
            msg = await websocket.receive_json()
            kind = (msg or {}).get("type")

            if kind == "text":
                text = (msg.get("text") or "").strip()
                if not text:
                    await websocket.send_json({"type": "error", "error": "empty text"})
                    continue
                try:
                    await websocket.send_json(await orchestrator.respond(text))
                except Exception as exc:  # noqa: BLE001 — surface, don't drop the socket
                    await websocket.send_json({"type": "error", "error": f"llm failed: {exc}"})

            elif kind == "audio":
                if not stt.available:
                    await websocket.send_json(
                        {"type": "error", "error": "speech-to-text not enabled — send {type:'text'}"}
                    )
                    continue
                fmt = msg.get("format") or "wav"
                try:
                    audio = base64.b64decode(msg.get("data_b64") or "")
                    transcript = (await stt.transcribe(audio, fmt=fmt)).strip()
                except Exception as exc:  # noqa: BLE001
                    await websocket.send_json({"type": "error", "error": f"transcription failed: {exc}"})
                    continue
                if not transcript:
                    await websocket.send_json({"type": "error", "error": "no speech detected"})
                    continue
                await websocket.send_json({"type": "transcript", "text": transcript})
                try:
                    await websocket.send_json(await orchestrator.respond(transcript))
                except Exception as exc:  # noqa: BLE001
                    await websocket.send_json({"type": "error", "error": f"llm failed: {exc}"})

            elif kind == "config":
                prompt = (msg.get("system") or "").strip()
                persona_id = (msg.get("persona_id") or "").strip()
                label = None
                if persona_id and not prompt:
                    try:
                        from app.personalities import registry as _registry

                        agent = _registry.get(persona_id)
                        if agent is not None:
                            prompt = (getattr(agent, "system_prompt", "") or "").strip()
                            label = getattr(agent, "label", persona_id)
                    except Exception:  # noqa: BLE001
                        prompt = ""
                if prompt:
                    orchestrator.set_system(prompt)
                    await websocket.send_json(
                        {"type": "configured", "persona_id": persona_id or None, "label": label}
                    )
                else:
                    await websocket.send_json({"type": "error", "error": "unknown persona"})

            elif kind == "interrupt":
                await websocket.send_json({"type": "interrupted"})

            elif kind == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                await websocket.send_json({"type": "error", "error": f"unknown type: {kind}"})
    except WebSocketDisconnect:
        return
