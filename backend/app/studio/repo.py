"""
Repository layer for Studio video projects.

In-memory storage for MVP. Replace with proper database in production.
"""
from __future__ import annotations

import time
import uuid
from typing import Dict, List, Optional

from .models import StudioVideo, StudioVideoCreate

# In-memory store (replace with DB in production)
_VIDEO_STORE: Dict[str, StudioVideo] = {}


def create_video(inp: StudioVideoCreate) -> StudioVideo:
    """Create a new video project."""
    now = time.time()
    vid = StudioVideo(
        id=str(uuid.uuid4()),
        title=inp.title,
        logline=inp.logline or "",
        tags=inp.tags or [],
        status="draft",
        platformPreset=inp.platformPreset,
        targetDurationSec=inp.targetDurationSec or 180,
        contentRating=inp.contentRating,
        policyMode=inp.policyMode,
        providerPolicy=inp.providerPolicy,
        createdAt=now,
        updatedAt=now,
    )
    _VIDEO_STORE[vid.id] = vid
    return vid


def list_videos(
    q: Optional[str] = None,
    status: Optional[str] = None,
    preset: Optional[str] = None,
    contentRating: Optional[str] = None,
    limit: int = 100,
) -> List[StudioVideo]:
    """
    List video projects with optional filters.

    Args:
        q: Search query (matches title and logline)
        status: Filter by status
        preset: Filter by platform preset
        contentRating: Filter by content rating
        limit: Maximum number of results

    Returns:
        List of matching videos, sorted by updatedAt desc
    """
    items = list(_VIDEO_STORE.values())

    if q:
        ql = q.lower()
        items = [v for v in items if ql in v.title.lower() or ql in (v.logline or "").lower()]

    if status:
        items = [v for v in items if v.status == status]

    if preset:
        items = [v for v in items if v.platformPreset == preset]

    if contentRating:
        items = [v for v in items if v.contentRating == contentRating]

    # Sort by updatedAt descending
    items.sort(key=lambda x: x.updatedAt, reverse=True)

    return items[:limit]


def get_video(video_id: str) -> Optional[StudioVideo]:
    """Get a video by ID."""
    return _VIDEO_STORE.get(video_id)


def update_video(video_id: str, **updates) -> Optional[StudioVideo]:
    """Update a video's fields."""
    v = _VIDEO_STORE.get(video_id)
    if not v:
        return None

    for key, value in updates.items():
        if hasattr(v, key):
            setattr(v, key, value)

    v.updatedAt = time.time()
    _VIDEO_STORE[video_id] = v
    return v


def touch(video_id: str) -> None:
    """Update the video's updatedAt timestamp."""
    v = _VIDEO_STORE.get(video_id)
    if v:
        v.updatedAt = time.time()
        _VIDEO_STORE[video_id] = v


def delete_video(video_id: str) -> bool:
    """Delete a video. Returns True if deleted."""
    if video_id in _VIDEO_STORE:
        del _VIDEO_STORE[video_id]
        return True
    return False
