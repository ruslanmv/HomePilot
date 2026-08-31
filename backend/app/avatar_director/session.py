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

from .protocol import HEARTBEAT_SECONDS, ProtocolHandler

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
        handler = ProtocolHandler(authenticate=authenticate)
        key = f"{id(websocket):x}"
        _SESSIONS[key] = handler

        heartbeat = asyncio.create_task(_heartbeat(websocket, handler))
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
        except WebSocketDisconnect:
            log.info("avatar session closed (%s)", handler.state.client or "unidentified")
        finally:
            heartbeat.cancel()
            _SESSIONS.pop(key, None)

    return router


async def _heartbeat(websocket: WebSocket, handler: ProtocolHandler) -> None:  # pragma: no cover
    """§6.9: a ping every 15 s. A silent socket is indistinguishable from a dead one."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await _send(websocket, handler.ping())
    except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
        return


async def _send(websocket: WebSocket, message: dict) -> None:  # pragma: no cover - transport
    await websocket.send_text(json.dumps(message, separators=(",", ":")))
