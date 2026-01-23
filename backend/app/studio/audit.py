"""
Audit logging for Studio content governance.

Tracks all policy decisions and content generation for compliance.
In production, replace in-memory store with persistent database.
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from .models import AuditEvent

# In-memory audit store (replace with DB in production)
_AUDIT_STORE: List[AuditEvent] = []


def log_event(
    video_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    actor: str = "system"
) -> AuditEvent:
    """
    Log an audit event.

    Args:
        video_id: The video project ID
        event_type: Type of event (e.g., create_video, policy_check, generation)
        payload: Additional event data
        actor: Who triggered the event (user ID or "system")

    Returns:
        The created AuditEvent
    """
    evt = AuditEvent(
        eventId=str(uuid.uuid4()),
        videoId=video_id,
        actor=actor,
        type=event_type,
        payload=payload or {},
        timestamp=time.time(),
    )
    _AUDIT_STORE.append(evt)
    return evt


def list_events(
    video_id: str,
    event_type: Optional[str] = None,
    limit: int = 100
) -> List[AuditEvent]:
    """
    List audit events for a video.

    Args:
        video_id: The video project ID
        event_type: Optional filter by event type
        limit: Maximum number of events to return

    Returns:
        List of matching AuditEvents, most recent first
    """
    events = [e for e in _AUDIT_STORE if e.videoId == video_id]

    if event_type:
        events = [e for e in events if e.type == event_type]

    # Sort by timestamp descending (most recent first)
    events.sort(key=lambda x: x.timestamp, reverse=True)

    return events[:limit]


def get_policy_violations(video_id: str) -> List[AuditEvent]:
    """Get all policy violation events for a video."""
    events = list_events(video_id, event_type="policy_check")
    return [e for e in events if not e.payload.get("allowed", True)]


def clear_events(video_id: str) -> int:
    """Clear all audit events for a video. Returns count of deleted events."""
    global _AUDIT_STORE
    before = len(_AUDIT_STORE)
    _AUDIT_STORE = [e for e in _AUDIT_STORE if e.videoId != video_id]
    return before - len(_AUDIT_STORE)
