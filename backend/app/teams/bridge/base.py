# backend/app/teams/bridge/base.py
"""
Abstract base class for external meeting bridges.

Implementations:
  * TeamsBridge   — Microsoft Teams bot connector (Phase 3+)
  * ZoomBridge    — Zoom SDK connector (Phase 3+)
  * MeetBridge    — Google Meet connector (Phase 3+)

Each bridge:
  1. Connects to the external meeting platform.
  2. Yields incoming events (human speech via STT, chat messages).
  3. Sends outgoing events (persona responses via TTS or chat).
"""
from __future__ import annotations

import abc
from typing import AsyncIterator

from .types import MeetingEvent


class MeetingBridge(abc.ABC):
    """Vendor-agnostic contract for external meeting integration."""

    @abc.abstractmethod
    async def connect(self) -> None:
        """Establish connection to the external meeting service."""
        ...

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect from the external meeting service."""
        ...

    @abc.abstractmethod
    async def incoming_events(self) -> AsyncIterator[MeetingEvent]:
        """Yield events arriving from external meeting into HomePilot."""
        yield  # type: ignore[misc]  # pragma: no cover

    @abc.abstractmethod
    async def send_event(self, event: MeetingEvent) -> None:
        """Send a HomePilot meeting event to the external meeting."""
        ...
