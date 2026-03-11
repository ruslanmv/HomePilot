"""
PersonaBridge — Connects a HomePilot persona to a Teams meeting via browser automation.

Unlike TeamsBridge (which uses Graph API and requires Azure registration),
PersonaBridge uses the teams-mcp-server's persona tools to:
  1. Join a meeting as a named guest (headless browser)
  2. Show a static face via virtual camera
  3. Speak via TTS through virtual microphone
  4. Listen via tab audio capture + STT
  5. Read/post in meeting chat via DOM automation

Usage:
    bridge = PersonaBridge(
        room_id="abc-123",
        join_url="https://teams.microsoft.com/l/meetup-join/...",
        display_name="Diana",
        face_image="/path/to/diana.png",
        mcp_base_url="http://localhost:9106",
    )
    await bridge.connect()
    # Persona is now visible in the meeting
    await bridge.speak("Hello everyone, I'm Diana.")
    async for event in bridge.incoming_events():
        # Respond to meeting participants
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

logger = logging.getLogger("homepilot.teams.bridge.persona")


class PersonaBridge(MeetingBridge):
    """Bridge that joins a Teams meeting as a persona using browser automation."""

    def __init__(
        self,
        room_id: str,
        join_url: str,
        display_name: str,
        face_image: Optional[str] = None,
        tts_voice: str = "en_US-amy-medium",
        mcp_base_url: str = "http://localhost:9106",
        poll_interval: float = 5.0,
        voice_enabled: bool = False,
        headless: bool = True,
    ) -> None:
        self.room_id = room_id
        self.join_url = join_url
        self.display_name = display_name
        self.face_image = face_image
        self.tts_voice = tts_voice
        self.mcp_base_url = mcp_base_url.rstrip("/")
        self.poll_interval = poll_interval
        self.voice_enabled = voice_enabled
        self.headless = headless

        # State
        self.session_id: Optional[str] = None
        self._connected = False
        self._seen_messages: Set[str] = set()
        self._stop_event = asyncio.Event()
        self._listen_task: Optional[asyncio.Task] = None

    # -----------------------------------------------------------------
    # MCP RPC helper
    # -----------------------------------------------------------------

    async def _rpc(self, tool_name: str, arguments: Dict[str, Any] | None = None) -> Dict[str, Any]:
        """Call a tool on the teams-mcp-server via JSON-RPC."""
        payload = {
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments or {}},
            "id": f"persona-{int(time.time() * 1000)}",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{self.mcp_base_url}/rpc", json=payload)
            r.raise_for_status()
            return r.json().get("result", {})

    def _extract_text(self, result: Dict[str, Any]) -> str:
        """Extract text from MCP tool result."""
        content_parts = result.get("content", [])
        for part in content_parts:
            if part.get("type") == "text":
                return part.get("text", "")
        return ""

    # -----------------------------------------------------------------
    # MeetingBridge interface
    # -----------------------------------------------------------------

    async def connect(self) -> None:
        """Join the Teams meeting as a persona via headless browser."""
        logger.info(
            "Persona '%s' joining meeting: %s",
            self.display_name, self.join_url[:80],
        )

        # Step 1: Join meeting as guest
        join_args: Dict[str, Any] = {
            "join_url": self.join_url,
            "display_name": self.display_name,
            "headless": self.headless,
            "tts_voice": self.tts_voice,
        }
        if self.face_image:
            join_args["face_image"] = self.face_image

        result = await self._rpc("teams.persona.join", join_args)
        result_text = self._extract_text(result)

        # Parse session_id from response
        for line in result_text.split("\n"):
            if "session_id:" in line:
                self.session_id = line.split("session_id:")[1].strip()
                break

        if not self.session_id:
            raise ConnectionError(
                f"Failed to join meeting as persona. Response: {result_text}"
            )

        self._connected = True
        logger.info(
            "Persona '%s' joined. Session: %s",
            self.display_name, self.session_id,
        )

    async def disconnect(self) -> None:
        """Leave the meeting and close the browser."""
        self._stop_event.set()
        self._connected = False

        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()

        if self.session_id:
            try:
                await self._rpc("teams.persona.leave", {
                    "session_id": self.session_id,
                })
            except Exception as e:
                logger.warning("Error leaving persona session: %s", e)

        logger.info(
            "Persona '%s' disconnected. Session: %s",
            self.display_name, self.session_id,
        )

    async def incoming_events(self) -> AsyncIterator[MeetingEvent]:
        """Poll meeting chat via DOM and yield new messages."""
        if not self._connected or not self.session_id:
            return

        while not self._stop_event.is_set():
            try:
                events = await self._poll_chat()
                for event in events:
                    yield event
            except Exception as e:
                logger.error("Persona chat poll error: %s", e)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.poll_interval,
                )
                break
            except asyncio.TimeoutError:
                continue

    async def send_event(self, event: MeetingEvent) -> None:
        """Send a persona response to the meeting.

        In persona mode, the persona can both speak (TTS) and post in chat.
        """
        if not self.session_id:
            logger.warning("Cannot send event: no persona session")
            return

        if event.type == "meeting.message" and event.content:
            # Post in chat
            await self._rpc("teams.persona.chat_post", {
                "session_id": self.session_id,
                "text": event.content,
            })

            # Also speak via TTS if voice is enabled
            if self.voice_enabled:
                try:
                    await self._rpc("teams.persona.speak", {
                        "session_id": self.session_id,
                        "text": event.content,
                    })
                except Exception as e:
                    logger.warning("TTS speak failed: %s", e)

            logger.info("Persona '%s' responded: %s", self.display_name, event.content[:60])

    # -----------------------------------------------------------------
    # Persona-specific methods
    # -----------------------------------------------------------------

    async def speak(self, text: str, voice_model: Optional[str] = None) -> Dict[str, Any]:
        """Make the persona speak via TTS."""
        if not self.session_id:
            return {"error": "No active session"}
        args: Dict[str, Any] = {
            "session_id": self.session_id,
            "text": text,
        }
        if voice_model:
            args["voice_model"] = voice_model
        return await self._rpc("teams.persona.speak", args)

    async def listen(self, duration_ms: int = 3000) -> str:
        """Capture and transcribe meeting audio."""
        if not self.session_id:
            return ""
        result = await self._rpc("teams.persona.listen", {
            "session_id": self.session_id,
            "duration_ms": duration_ms,
        })
        return self._extract_text(result)

    async def get_status(self) -> Dict[str, Any]:
        """Get persona session status."""
        if not self.session_id:
            return {"status": "not_connected"}
        result = await self._rpc("teams.persona.status", {
            "session_id": self.session_id,
        })
        return result

    # -----------------------------------------------------------------
    # Internal polling (DOM-based chat)
    # -----------------------------------------------------------------

    async def _poll_chat(self) -> List[MeetingEvent]:
        """Read meeting chat via DOM and return new messages."""
        result = await self._rpc("teams.persona.chat_read", {
            "session_id": self.session_id,
            "last_n": 25,
        })

        text = self._extract_text(result)
        events: List[MeetingEvent] = []

        for line in text.split("\n"):
            if not line.strip().startswith("["):
                continue
            try:
                # Format: [sender]: content
                bracket_end = line.index("]")
                sender = line[line.index("[") + 1:bracket_end]
                content = line[bracket_end + 2:].strip()  # skip "]: "

                msg_id = f"{sender}|{content[:50]}"
                if msg_id in self._seen_messages:
                    continue
                self._seen_messages.add(msg_id)

                # Skip our own messages
                if sender == self.display_name:
                    continue

                events.append(MeetingEvent(
                    type="meeting.message",
                    room_id=self.room_id,
                    sender_id=sender.lower().replace(" ", "_"),
                    sender_name=sender.strip(),
                    content=content.strip(),
                    timestamp=time.time(),
                    external_ref=msg_id,
                    metadata={"source": "persona_dom", "mode": "persona"},
                ))
            except (ValueError, IndexError):
                continue

        return events

    # -----------------------------------------------------------------
    # Voice control
    # -----------------------------------------------------------------

    async def toggle_voice(self, enabled: bool) -> Dict[str, Any]:
        """Toggle TTS voice output for persona responses."""
        self.voice_enabled = enabled
        return {"voice_enabled": enabled, "session_id": self.session_id}

    async def get_voice_status(self) -> Dict[str, Any]:
        """Get voice status."""
        return {
            "voice_enabled": self.voice_enabled,
            "tts_voice": self.tts_voice,
            "session_id": self.session_id,
        }

    # -----------------------------------------------------------------
    # Info
    # -----------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize bridge state for API responses."""
        return {
            "provider": "teams",
            "mode": "persona",
            "join_url": self.join_url,
            "session_id": self.session_id,
            "display_name": self.display_name,
            "face_image": self.face_image,
            "connected": self._connected,
            "voice_enabled": self.voice_enabled,
            "tts_voice": self.tts_voice,
            "poll_interval": self.poll_interval,
            "messages_seen": len(self._seen_messages),
        }
