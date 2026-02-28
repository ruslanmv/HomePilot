# services/teams-relay/app.py
"""
HomePilot Teams Relay — lightweight WebSocket router.

Allows two (or more) HomePilot instances to join the same ``room_code``
and exchange meeting events (transcript deltas, presence, turn tokens).

Run separately:
    uvicorn services.teams-relay.app:app --host 0.0.0.0 --port 8765

Design:
    * Stateless routing — no LLM, no persistence.
    * Each WebSocket client sends ``{"type": "join", "room_code": "..."}``
      to subscribe to a room.
    * All subsequent messages are broadcast to every other client in the
      same room.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

logger = logging.getLogger("teams-relay")

app = FastAPI(title="HomePilot Teams Relay", version="0.1.0")

# room_code -> set of websockets
ROOMS: Dict[str, Set[WebSocket]] = {}
LOCK = asyncio.Lock()


@app.get("/health")
async def health():
    """Health-check endpoint."""
    total = sum(len(v) for v in ROOMS.values())
    return {"status": "ok", "rooms": len(ROOMS), "connections": total}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    """Main relay WebSocket handler."""
    await ws.accept()
    room_code: str | None = None
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            # ── Join a room ──────────────────────────────────────────
            if msg.get("type") == "join":
                room_code = (msg.get("room_code") or "").strip()
                if not room_code:
                    await ws.send_text(
                        json.dumps({"type": "error", "detail": "room_code required"})
                    )
                    continue
                async with LOCK:
                    ROOMS.setdefault(room_code, set()).add(ws)
                await ws.send_text(
                    json.dumps({"type": "joined", "room_code": room_code})
                )
                logger.info("Client joined room %s", room_code)
                continue

            # ── Broadcast to peers ───────────────────────────────────
            if not room_code:
                await ws.send_text(
                    json.dumps({"type": "error", "detail": "join a room first"})
                )
                continue

            async with LOCK:
                peers = list(ROOMS.get(room_code, set()))
            for peer in peers:
                if peer is ws:
                    continue
                try:
                    await peer.send_text(raw)
                except Exception:
                    pass

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("Relay error: %s", exc)
    finally:
        if room_code:
            async with LOCK:
                peers = ROOMS.get(room_code)
                if peers and ws in peers:
                    peers.discard(ws)
                if peers is not None and len(peers) == 0:
                    ROOMS.pop(room_code, None)
            logger.info("Client left room %s", room_code)
