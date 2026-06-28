"""Backend voice session endpoint (MB2) — the 'smart backend' keystone.

`WS /v1/voice/session` lets a thin client (mobile or web) hold a spoken
conversation while the server does the work: it receives an utterance, calls the
LLM, and returns reply text + synthesized audio. STT/TTS sit behind providers so
free→premium is a server swap. Barge-in is a client signal the server honors.

Protocol (JSON frames):
  client → server
    {"type":"text","text":"..."}        # an utterance (typed, or client STT)
    {"type":"audio","format":"wav",     # raw audio → transcribed by the STT
     "data_b64":"..."}                  #   provider, then answered
    {"type":"config","persona_id":"…"}  # pick a persona (or {"system":"…"})
    {"type":"interrupt"}                # barge-in: stop speaking
    {"type":"ping"}
  server → client
    {"type":"ready","tts":bool,"stt":bool}
    {"type":"transcript","text":"..."}   # what STT heard (after an audio frame)
    {"type":"configured","persona_id":"…","label":"…"}
    {"type":"reply","text":"...","audio"?:{"format","data_b64"}}
    {"type":"error","error":"..."}
    {"type":"pong"}

Additive + flag-gated (`VOICE_BACKEND_ENABLED`, default off): the route exists but
rejects connections until enabled, so including it is a prod no-op until switched
on. The web's existing client-side voice mode is untouched.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import config

from .providers import get_stt_provider, get_tts_provider
from .session import VoiceOrchestrator

router = APIRouter()


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
                # Echo what we heard, then answer it — same path as a text turn.
                await websocket.send_json({"type": "transcript", "text": transcript})
                try:
                    await websocket.send_json(await orchestrator.respond(transcript))
                except Exception as exc:  # noqa: BLE001
                    await websocket.send_json({"type": "error", "error": f"llm failed: {exc}"})

            elif kind == "config":
                # MB4 — pick a persona/voice companion. Resolve a persona_id to
                # its system prompt (reusing the personality registry), or accept
                # a raw system prompt. Switching resets the conversation.
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
                # Barge-in hook: streaming TTS would be cancelled here.
                await websocket.send_json({"type": "interrupted"})

            elif kind == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                await websocket.send_json({"type": "error", "error": f"unknown type: {kind}"})
    except WebSocketDisconnect:
        return
