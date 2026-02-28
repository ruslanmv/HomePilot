# backend/app/teams/federation_agent.py
"""
Federation agent — connects a HomePilot instance to a relay service
so that two (or more) instances can share the same meeting room.

Phase 2 scaffold.  The agent:
  * joins a relay room via WebSocket
  * sends local meeting events (new messages, participant changes)
  * receives remote events and merges them into the local room

Privacy principle:
  Each persona runs on its own machine.
  Only the meeting transcript + minimal metadata crosses the network.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("homepilot.teams.federation_agent")

DEFAULT_INSTANCE_ID = os.environ.get("HOMEPILOT_INSTANCE_ID", f"hp-{uuid.uuid4().hex[:8]}")


# ── Config ────────────────────────────────────────────────────────────────


@dataclass
class FederationConfig:
    relay_url: str  # e.g. "ws://192.168.1.10:8765/ws"
    room_code: str  # e.g. "MEET-7X3K"
    instance_id: str = DEFAULT_INSTANCE_ID


# ── Event types ───────────────────────────────────────────────────────────


@dataclass
class FederationEvent:
    """Wire format for events exchanged through the relay."""

    type: str  # "transcript.message" | "participant.join" | "participant.leave" | "turn.token"
    room_code: str
    instance_id: str
    payload: Dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_json(self) -> str:
        return json.dumps(
            {
                "type": self.type,
                "room_code": self.room_code,
                "instance_id": self.instance_id,
                "payload": self.payload,
                "event_id": self.event_id,
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "FederationEvent":
        d = json.loads(raw)
        return cls(
            type=d.get("type", "unknown"),
            room_code=d.get("room_code", ""),
            instance_id=d.get("instance_id", ""),
            payload=d.get("payload", {}),
            event_id=d.get("event_id", uuid.uuid4().hex),
        )


# ── Agent ─────────────────────────────────────────────────────────────────

EventCallback = Callable[[FederationEvent], Awaitable[None]]


class FederationAgent:
    """
    Lightweight WebSocket client that connects to a Teams relay.

    Usage:
        agent = FederationAgent(FederationConfig(relay_url=..., room_code=...))
        agent.on_event(my_handler)
        await agent.start()    # background task
        await agent.send(evt)
        ...
        await agent.stop()
    """

    def __init__(self, cfg: FederationConfig):
        self.cfg = cfg
        self._ws: Any = None
        self._task: Optional[asyncio.Task] = None
        self._on_event: Optional[EventCallback] = None
        self._stop = asyncio.Event()

    # ── Public API ────────────────────────────────────────────────────

    def on_event(self, cb: EventCallback) -> None:
        """Register a callback for incoming remote events."""
        self._on_event = cb

    async def start(self) -> None:
        """Start the background receive loop."""
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Gracefully stop the agent."""
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        try:
            if self._ws:
                await self._ws.close()
        except Exception:
            pass

    async def send(self, event: FederationEvent) -> None:
        """Send an event to the relay (broadcast to peers)."""
        if not self._ws:
            logger.warning("Cannot send — not connected to relay")
            return
        await self._ws.send(event.to_json())

    @property
    def connected(self) -> bool:
        return self._ws is not None

    # ── Internal ──────────────────────────────────────────────────────

    async def _run(self) -> None:
        """Reconnecting receive loop."""
        try:
            import websockets  # Phase 2 dependency
        except ImportError:
            logger.error(
                "websockets package is required for federation. "
                "Install it with: pip install websockets"
            )
            return

        while not self._stop.is_set():
            try:
                async with websockets.connect(self.cfg.relay_url) as ws:
                    self._ws = ws

                    # Join the room
                    await ws.send(
                        json.dumps({"type": "join", "room_code": self.cfg.room_code})
                    )
                    logger.info(
                        "Federation joined room=%s via %s",
                        self.cfg.room_code,
                        self.cfg.relay_url,
                    )

                    while not self._stop.is_set():
                        raw = await ws.recv()
                        try:
                            evt = FederationEvent.from_json(raw)
                        except Exception:
                            continue
                        # Skip our own events
                        if evt.instance_id == self.cfg.instance_id:
                            continue
                        if self._on_event:
                            await self._on_event(evt)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Federation connection failed: %s", exc)
                # Exponential-ish back-off
                await asyncio.sleep(1.5)
            finally:
                self._ws = None
