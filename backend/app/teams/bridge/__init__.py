# backend/app/teams/bridge/__init__.py
"""External meeting bridge — Teams integration (Phase 3).

Components:
  - MeetingBridge: abstract base class
  - MeetingEvent: vendor-agnostic event type
  - TeamsBridge: Microsoft Teams implementation via MCP server
  - ChatPoller: background task for continuous chat ingestion
  - BridgeManager: singleton lifecycle manager
"""
from .base import MeetingBridge
from .types import MeetingEvent
from .teams_bridge import TeamsBridge
from .chat_poller import ChatPoller
from .manager import bridge_manager

__all__ = [
    "MeetingBridge",
    "MeetingEvent",
    "TeamsBridge",
    "ChatPoller",
    "bridge_manager",
]
