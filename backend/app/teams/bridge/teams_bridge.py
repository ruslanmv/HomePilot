"""
TeamsBridge — Connects a HomePilot meeting room to a live Microsoft Teams meeting.

This bridge:
  1. Resolves a Teams meeting join URL to its chat thread ID
  2. Polls the meeting chat for new messages via teams-mcp-server
  3. Injects external messages into the HomePilot room transcript
  4. Can post persona responses back to the Teams meeting chat
  5. Optionally enables voice detection (STT) via the MCP server

Usage:
    bridge = TeamsBridge(
        room_id="abc-123",
        join_url="https://teams.microsoft.com/l/meetup-join/...",
        mcp_base_url="http://localhost:9106",
    )
    await bridge.connect()
    async for event in bridge.incoming_events():
        # event.type == "meeting.message"
        # event.sender_name == "John Doe"
        # event.content == "Let's discuss the quarterly report"
        pass
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional, Set

import httpx

from .base import MeetingBridge
from .types import MeetingEvent

logger = logging.getLogger("homepilot.teams.bridge.teams")


class TeamsBridge(MeetingBridge):
    """Bridge between a HomePilot room and a live Microsoft Teams meeting."""

    def __init__(
        self,
        room_id: str,
        join_url: str,
        mcp_base_url: str = "http://localhost:9106",
        poll_interval: float = 5.0,
        voice_enabled: bool = False,
    ) -> None:
        self.room_id = room_id
        self.join_url = join_url
        self.mcp_base_url = mcp_base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.voice_enabled = voice_enabled

        # State
        self.session_id: Optional[str] = None
        self.chat_id: Optional[str] = None
        self._connected = False
        self._seen_messages: Set[str] = set()  # message IDs already processed
        self._stop_event = asyncio.Event()

    # -----------------------------------------------------------------
    # MCP RPC helper
    # -----------------------------------------------------------------

    async def _rpc(self, tool_name: str, arguments: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Call a tool on the teams-mcp-server via JSON-RPC."""
        payload = {
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
            "id": f"bridge-{int(time.time() * 1000)}",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{self.mcp_base_url}/rpc", json=payload)
            r.raise_for_status()
            return r.json().get("result", {})

    # -----------------------------------------------------------------
    # MeetingBridge interface
    # -----------------------------------------------------------------

    async def connect(self) -> None:
        """Connect to the Teams meeting: resolve chat, create session."""
        logger.info(f"Connecting to Teams meeting: {self.join_url[:80]}...")

        # Step 1: Connect via meeting.connect tool
        result = await self._rpc("teams.meeting.connect", {
            "join_url": self.join_url,
            "room_id": self.room_id,
        })
        self.session_id = result.get("session_id")
        self.chat_id = result.get("chat_id")

        if not self.chat_id:
            # Try resolving via meeting_chat.resolve
            resolve_result = await self._rpc("teams.meeting_chat.resolve", {
                "join_url": self.join_url,
            })
            self.chat_id = resolve_result.get("chat_id")

        if not self.chat_id:
            raise ConnectionError(
                "Could not resolve Teams meeting chat. "
                "The meeting may not have started yet. Try again after joining the meeting."
            )

        # Step 2: Enable voice if requested
        if self.voice_enabled:
            await self._rpc("teams.voice.toggle", {"enabled": True})

        self._connected = True
        logger.info(f"Connected. Session: {self.session_id}, Chat: {self.chat_id}")

    async def disconnect(self) -> None:
        """Disconnect from the Teams meeting."""
        self._stop_event.set()
        self._connected = False

        if self.session_id:
            try:
                await self._rpc("teams.meeting.disconnect", {
                    "session_id": self.session_id,
                })
            except Exception as e:
                logger.warning(f"Error disconnecting session: {e}")

        # Disable voice if it was enabled
        if self.voice_enabled:
            try:
                await self._rpc("teams.voice.toggle", {"enabled": False})
            except Exception:
                pass

        logger.info(f"Disconnected from Teams meeting. Session: {self.session_id}")

    async def incoming_events(self) -> AsyncIterator[MeetingEvent]:
        """Poll Teams meeting chat and yield new messages as MeetingEvents."""
        if not self._connected or not self.chat_id:
            return

        while not self._stop_event.is_set():
            try:
                events = await self._poll_chat()
                for event in events:
                    yield event
            except Exception as e:
                logger.error(f"Chat poll error: {e}")

            # Wait for next poll cycle (interruptible)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval)
                break  # stop event was set
            except asyncio.TimeoutError:
                continue  # normal timeout, poll again

    async def send_event(self, event: MeetingEvent) -> None:
        """Send a persona response to the Teams meeting chat."""
        if not self.chat_id:
            logger.warning("Cannot send event: no chat_id")
            return

        if event.type == "meeting.message" and event.content:
            # Format: "[PersonaName]: message"
            text = f"[{event.sender_name}]: {event.content}"
            await self._rpc("teams.meeting_chat.post", {
                "chat_id": self.chat_id,
                "text": text,
            })
            logger.info(f"Posted to Teams chat: {event.sender_name}")

    # -----------------------------------------------------------------
    # Internal polling
    # -----------------------------------------------------------------

    async def _poll_chat(self) -> List[MeetingEvent]:
        """Read recent chat messages and return only new ones as events."""
        result = await self._rpc("teams.meeting_chat.read", {
            "chat_id": self.chat_id,
            "top": 25,
        })

        # Parse the text content to extract messages
        content_parts = result.get("content", [])
        text = ""
        for part in content_parts:
            if part.get("type") == "text":
                text = part.get("text", "")
                break

        events: List[MeetingEvent] = []
        for line in text.split("\n"):
            if not line.startswith("["):
                continue
            # Format: [timestamp] sender: content
            try:
                ts_end = line.index("]", 1)
                ts_str = line[1:ts_end]
                rest = line[ts_end + 2:]  # skip "] "
                if ": " in rest:
                    sender, content = rest.split(": ", 1)
                else:
                    sender = "unknown"
                    content = rest

                # Create a unique ID from timestamp + sender
                msg_id = f"{ts_str}|{sender}"
                if msg_id in self._seen_messages:
                    continue
                self._seen_messages.add(msg_id)

                # Skip system messages and our own posted messages
                if sender == "SYSTEM":
                    continue
                if content.startswith("[") and "]: " in content:
                    # This is a message we posted via send_event, skip it
                    continue

                events.append(MeetingEvent(
                    type="meeting.message",
                    room_id=self.room_id,
                    sender_id=sender.lower().replace(" ", "_"),
                    sender_name=sender.strip(),
                    content=content.strip(),
                    timestamp=time.time(),
                    external_ref=msg_id,
                    metadata={"source": "teams_chat", "raw_timestamp": ts_str},
                ))
            except (ValueError, IndexError):
                continue

        return events

    # -----------------------------------------------------------------
    # Voice control
    # -----------------------------------------------------------------

    async def toggle_voice(self, enabled: bool) -> Dict[str, Any]:
        """Toggle voice detection (STT) on the MCP server."""
        self.voice_enabled = enabled
        result = await self._rpc("teams.voice.toggle", {"enabled": enabled})
        return result

    async def get_voice_status(self) -> Dict[str, Any]:
        """Get current voice detection status."""
        return await self._rpc("teams.voice.status", {})

    # -----------------------------------------------------------------
    # Info
    # -----------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize bridge state for API responses."""
        return {
            "provider": "teams",
            "join_url": self.join_url,
            "session_id": self.session_id,
            "chat_id": self.chat_id,
            "connected": self._connected,
            "voice_enabled": self.voice_enabled,
            "poll_interval": self.poll_interval,
            "messages_seen": len(self._seen_messages),
        }
