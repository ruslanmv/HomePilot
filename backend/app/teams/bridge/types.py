# backend/app/teams/bridge/types.py
"""
Vendor-agnostic event types for external meeting bridges.

These types define the stable API boundary between HomePilot's meeting
engine and any external meeting service (MS Teams, Zoom, Google Meet).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

EventType = Literal[
    "meeting.message",
    "meeting.join",
    "meeting.leave",
    "meeting.start",
    "meeting.end",
]


@dataclass
class MeetingEvent:
    """A single event flowing between HomePilot and an external meeting."""

    type: EventType
    room_id: str
    sender_id: str
    sender_name: str
    content: str
    timestamp: float
    external_ref: Optional[str] = None  # vendor-specific ID (e.g. Teams msg ID)
    metadata: dict = field(default_factory=dict)
