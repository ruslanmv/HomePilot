"""WebSocket ``/avatar/session`` — the realtime channel (spec v1.1 §6.9).

This module moves bytes. Everything that decides *what* to say lives in ``protocol.py``,
which has no FastAPI dependency and is where the contract tests point.

Importing this file costs FastAPI, so ``register()`` in ``__init__.py`` imports it lazily —
with ``avatar.enabled`` false nothing here is loaded at all, which is the claim B8 is
accepted on.

Auth reuses whatever pairing HomePilot already has: the token arrives in the ``hello``
message (headers do not round-trip cleanly from browsers, and the voice-call router solved
the same problem the same way). The verifier is injected, so the transport never grows an
opinion about identity.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .protocol import EMOTE_WHITELIST, HEARTBEAT_SECONDS, ProtocolHandler
from .rtc import VoiceUplink, webrtc_terminus
from .vision import VisionService

log = logging.getLogger("avatar_director.session")

#: Live handlers, so curiosity (B16) and the MCP tool server (B17) can reach a session.
_SESSIONS: dict[str, ProtocolHandler] = {}


def sessions() -> dict[str, ProtocolHandler]:
    """The live sessions. B17 errors when this is empty rather than acting blind."""
    return _SESSIONS


def build_router(config, *, authenticate: Optional[Callable[[Any], bool]] = None) -> APIRouter:
    """The router mounted when ``avatar.enabled`` is true, and only then."""
    router = APIRouter(tags=["avatar-director"])

    @router.websocket("/avatar/session")
    async def avatar_session(websocket: WebSocket) -> None:  # pragma: no cover - transport
        await websocket.accept()
        handler = ProtocolHandler(
            authenticate=authenticate, voice=_uplink_for(config), vision=vision_service(config)
        )
        key = f"{id(websocket):x}"
        _SESSIONS[key] = handler

        heartbeat = asyncio.create_task(_heartbeat(websocket, handler))
        # B17. A tool call queues on the handler and this sends it — four wakeups a second,
        # because a gesture that waits for the next heartbeat is a gesture that arrives
        # fifteen seconds after the thing it was reacting to.
        pump = asyncio.create_task(_outbox_pump(websocket, handler))
        turns: set = set()
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError:
                    await _send(websocket, handler.error("bad_json", "not JSON"))
                    continue

                for reply in handler.handle(message):
                    await _send(websocket, reply)

                # Anything a tool call (B17) or curiosity (B16) queued while we were
                # waiting. Drained here rather than pushed from those modules, so the
                # socket has exactly one writer.
                await _drain(websocket, handler)

                # B10. A spoken turn is the one thing here that waits on the chat endpoint,
                # so it runs as its own task: the socket stays readable, which is what lets
                # the next utterance barge in on the reply to the last one.
                pending = handler.voice.take_pending() if handler.voice else None
                if pending is not None:
                    task = asyncio.create_task(_run_turn(websocket, handler, pending))
                    turns.add(task)
                    task.add_done_callback(turns.discard)

        except WebSocketDisconnect:
            log.info("avatar session closed (%s)", handler.state.client or "unidentified")
        finally:
            heartbeat.cancel()
            pump.cancel()
            for task in list(turns):
                task.cancel()
            _SESSIONS.pop(key, None)

    return router


def _uplink_for(config):
    """One uplink per session, or None while ``avatar.voice.enabled`` is false.

    Building it costs nothing but a dataclass — the chat path and the barge-in registry are
    imported lazily, inside the turn — so a session that never speaks pays nothing for the
    uplink existing.
    """
    voice = getattr(config, "voice", None)
    if voice is None or not voice.enabled:
        return None
    terminus = webrtc_terminus(voice) if voice.media == "webrtc" else None
    return VoiceUplink(voice, whitelist=EMOTE_WHITELIST, media_terminus=terminus)


async def _run_turn(websocket: WebSocket, handler: ProtocolHandler, pending) -> None:  # pragma: no cover
    """Await one spoken turn and send what it produced."""
    try:
        for reply in await handler.voice.run_pending(pending):
            await _send(websocket, reply)
    except asyncio.CancelledError:
        raise
    except (WebSocketDisconnect, RuntimeError):
        return  # the socket went while we were thinking; nothing to say to it


def vision_service(config):
    """One service per session, or None while vision has no model configured.

    §6.13's model is a deployment choice; with none named the endpoint is not mounted and
    ``vision_ask`` is refused by name, which is B8's rule for a stub that cannot answer.
    """
    vision = getattr(config, "vision", None)
    if vision is None or not (vision.model or "").strip():
        return None
    return VisionService(config)


async def _drain(websocket: WebSocket, handler: ProtocolHandler) -> int:  # pragma: no cover
    """Send whatever was queued out of band. Returns how many went."""
    sent = 0
    while handler.outbox:
        await _send(websocket, handler.outbox.pop(0))
        sent += 1
    return sent


#: How often the outbox is checked. Fast enough that a queued gesture feels immediate,
#: slow enough that an idle session costs four no-op wakeups a second.
OUTBOX_POLL_SECONDS = 0.25


async def _outbox_pump(websocket: WebSocket, handler: ProtocolHandler) -> None:  # pragma: no cover
    try:
        while True:
            await asyncio.sleep(OUTBOX_POLL_SECONDS)
            await _drain(websocket, handler)
    except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
        return


async def _heartbeat(websocket: WebSocket, handler: ProtocolHandler) -> None:  # pragma: no cover
    """§6.9: a ping every 15 s, and a chance to flush the outbox.

    The heartbeat is why a tool call does not wait for the user to say something: a queued
    intent goes out on the next tick at the latest, which for an animation is close enough
    to now and is one timer rather than two.
    """
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await _drain(websocket, handler)
            await _send(websocket, handler.ping())
    except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
        return


async def _send(websocket: WebSocket, message: dict) -> None:  # pragma: no cover - transport
    await websocket.send_text(json.dumps(message, separators=(",", ":")))
