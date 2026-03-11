"""
BridgeManager — Singleton registry for active meeting bridges.

Manages the lifecycle of TeamsBridge + ChatPoller pairs:
  - Connect a HomePilot room to a Teams meeting
  - Disconnect
  - Query status
  - Toggle voice detection

This is the main entry point for bridge operations from the API routes.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .chat_poller import ChatPoller
from .teams_bridge import TeamsBridge
from .persona_bridge import PersonaBridge
from .types import MeetingEvent

logger = logging.getLogger("homepilot.teams.bridge.manager")


class BridgeManager:
    """Registry and lifecycle manager for active meeting bridges."""

    def __init__(self) -> None:
        self._bridges: Dict[str, TeamsBridge] = {}   # room_id -> bridge
        self._pollers: Dict[str, ChatPoller] = {}     # room_id -> poller
        self._on_new_messages: Optional[Callable] = None

    def set_reaction_callback(
        self,
        callback: Callable[[str, List[MeetingEvent]], Coroutine],
    ) -> None:
        """Set a callback to trigger persona reactions on new external messages."""
        self._on_new_messages = callback

    # -----------------------------------------------------------------
    # Connect / Disconnect
    # -----------------------------------------------------------------

    async def connect(
        self,
        room_id: str,
        join_url: str,
        mcp_base_url: str = "http://localhost:9106",
        poll_interval: float = 5.0,
        voice_enabled: bool = False,
        mode: str = "native",
        display_name: str = "",
        face_image: str = "",
        tts_voice: str = "en_US-amy-medium",
        headless: bool = True,
    ) -> Dict[str, Any]:
        """Connect a room to a Teams meeting.

        Parameters
        ----------
        mode : str
            "native" — Graph API mode (requires Azure registration).
            "persona" — Browser-based guest join (no Azure needed).
        display_name : str
            Persona display name (required for persona mode).
        face_image : str
            Path to persona face image (persona mode only).
        tts_voice : str
            Piper TTS voice model (persona mode only).
        headless : bool
            Run browser headless (persona mode only).

        Returns bridge status dict.
        """
        # Disconnect existing bridge if any
        if room_id in self._bridges:
            await self.disconnect(room_id)

        if mode == "persona":
            if not display_name:
                raise ValueError("display_name is required for persona mode.")
            bridge = PersonaBridge(
                room_id=room_id,
                join_url=join_url,
                display_name=display_name,
                face_image=face_image or None,
                tts_voice=tts_voice,
                mcp_base_url=mcp_base_url,
                poll_interval=poll_interval,
                voice_enabled=voice_enabled,
                headless=headless,
            )
        else:
            bridge = TeamsBridge(
                room_id=room_id,
                join_url=join_url,
                mcp_base_url=mcp_base_url,
                poll_interval=poll_interval,
                voice_enabled=voice_enabled,
            )

        await bridge.connect()
        self._bridges[room_id] = bridge

        # Start chat poller
        poller = ChatPoller(
            bridge=bridge,
            on_new_messages=self._on_new_messages,
        )
        await poller.start()
        self._pollers[room_id] = poller

        mode_label = "persona" if mode == "persona" else "native"
        logger.info(f"Bridge connected ({mode_label}): room={room_id}")
        return self.get_status(room_id)

    async def disconnect(self, room_id: str) -> Dict[str, Any]:
        """Disconnect a room from its Teams meeting."""
        status = {"room_id": room_id, "status": "disconnected"}

        # Stop poller
        poller = self._pollers.pop(room_id, None)
        if poller:
            await poller.stop()

        # Disconnect bridge
        bridge = self._bridges.pop(room_id, None)
        if bridge:
            await bridge.disconnect()
            status["messages_seen"] = len(bridge._seen_messages)

        logger.info(f"Bridge disconnected: room={room_id}")
        return status

    # -----------------------------------------------------------------
    # Status
    # -----------------------------------------------------------------

    def get_status(self, room_id: str) -> Dict[str, Any]:
        """Get bridge status for a room."""
        bridge = self._bridges.get(room_id)
        if not bridge:
            return {
                "room_id": room_id,
                "connected": False,
                "status": "not_connected",
            }

        poller = self._pollers.get(room_id)
        result = {
            "room_id": room_id,
            "connected": True,
            "status": "active" if (poller and poller.is_running) else "connected",
            "bridge": bridge.to_dict(),
        }
        if poller:
            result["poller"] = poller.to_dict()
        return result

    def list_active(self) -> List[Dict[str, Any]]:
        """List all active bridge connections."""
        return [self.get_status(rid) for rid in self._bridges]

    def is_connected(self, room_id: str) -> bool:
        """Check if a room has an active bridge."""
        return room_id in self._bridges and self._bridges[room_id]._connected

    # -----------------------------------------------------------------
    # Voice control
    # -----------------------------------------------------------------

    async def toggle_voice(self, room_id: str, enabled: bool) -> Dict[str, Any]:
        """Toggle voice detection for a bridge."""
        bridge = self._bridges.get(room_id)
        if not bridge:
            return {"error": "No active bridge for this room"}
        result = await bridge.toggle_voice(enabled)
        return {"room_id": room_id, "voice_enabled": enabled, "result": result}

    async def get_voice_status(self, room_id: str) -> Dict[str, Any]:
        """Get voice detection status for a bridge."""
        bridge = self._bridges.get(room_id)
        if not bridge:
            return {"error": "No active bridge for this room"}
        return await bridge.get_voice_status()

    # -----------------------------------------------------------------
    # Send event (persona response → Teams)
    # -----------------------------------------------------------------

    async def send_to_meeting(
        self,
        room_id: str,
        sender_name: str,
        content: str,
    ) -> bool:
        """Send a persona response to the Teams meeting chat."""
        bridge = self._bridges.get(room_id)
        if not bridge:
            return False
        event = MeetingEvent(
            type="meeting.message",
            room_id=room_id,
            sender_id=sender_name.lower().replace(" ", "_"),
            sender_name=sender_name,
            content=content,
            timestamp=0,  # not used for outgoing
        )
        await bridge.send_event(event)
        return True


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

bridge_manager = BridgeManager()
