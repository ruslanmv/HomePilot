"""
ChatPoller — Background task that continuously polls a Teams meeting chat
and injects new messages into a HomePilot room's transcript.

This is the "engine" that makes the bridge work:
  1. Runs as an asyncio task in the background
  2. Uses TeamsBridge.incoming_events() to get new messages
  3. Calls rooms.add_message() to inject them into the room transcript
  4. Optionally triggers persona reactions after new external messages

Usage:
    poller = ChatPoller(bridge, trigger_reactions=True, llm_settings={...})
    await poller.start()
    ...
    await poller.stop()
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

from .teams_bridge import TeamsBridge
from .types import MeetingEvent

logger = logging.getLogger("homepilot.teams.bridge.poller")


class ChatPoller:
    """Background poller that ingests Teams chat into a HomePilot room."""

    def __init__(
        self,
        bridge: TeamsBridge,
        on_new_messages: Optional[Callable[[str, List[MeetingEvent]], Coroutine]] = None,
        batch_delay: float = 2.0,
    ) -> None:
        self.bridge = bridge
        self.on_new_messages = on_new_messages  # callback(room_id, events)
        self.batch_delay = batch_delay
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the background polling task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run(), name=f"chat-poller-{self.bridge.room_id}")
        logger.info(f"ChatPoller started for room {self.bridge.room_id}")

    async def stop(self) -> None:
        """Stop the background polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(f"ChatPoller stopped for room {self.bridge.room_id}")

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def _run(self) -> None:
        """Main polling loop."""
        batch: List[MeetingEvent] = []
        last_flush = time.time()

        try:
            async for event in self.bridge.incoming_events():
                if not self._running:
                    break

                batch.append(event)

                # Flush batch after delay or when batch is large enough
                now = time.time()
                if now - last_flush >= self.batch_delay or len(batch) >= 5:
                    await self._flush_batch(batch)
                    batch = []
                    last_flush = now

            # Flush remaining
            if batch:
                await self._flush_batch(batch)

        except asyncio.CancelledError:
            if batch:
                await self._flush_batch(batch)
            raise
        except Exception as e:
            logger.error(f"ChatPoller error: {e}", exc_info=True)

    async def _flush_batch(self, events: List[MeetingEvent]) -> None:
        """Process a batch of new messages."""
        if not events:
            return

        # Import here to avoid circular imports
        from .. import rooms

        for event in events:
            if event.type == "meeting.message":
                # Prefix content with source tag so the orchestrator knows it's external
                tagged_content = f"[Teams] {event.content}"
                rooms.add_message(
                    room_id=self.bridge.room_id,
                    content=tagged_content,
                    sender_id=event.sender_id,
                    sender_name=f"{event.sender_name} (Teams)",
                    role="user",  # external participants are "user" role
                )

        logger.info(
            f"Ingested {len(events)} messages from Teams into room {self.bridge.room_id}"
        )

        # Notify callback (e.g., trigger persona reactions)
        if self.on_new_messages:
            try:
                await self.on_new_messages(self.bridge.room_id, events)
            except Exception as e:
                logger.error(f"on_new_messages callback error: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize poller state."""
        return {
            "running": self.is_running,
            "batch_delay": self.batch_delay,
            "bridge": self.bridge.to_dict(),
        }
