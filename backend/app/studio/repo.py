"""
Repository layer for Studio video projects.

In-memory storage for MVP. Replace with proper database in production.
"""
from __future__ import annotations

import time
import uuid
from typing import Dict, List, Optional

from .models import StudioVideo, StudioVideoCreate, StudioScene, StudioSceneCreate, StudioSceneUpdate

# In-memory store (replace with DB in production)
_VIDEO_STORE: Dict[str, StudioVideo] = {}
_SCENE_STORE: Dict[str, StudioScene] = {}  # scene_id -> scene


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
        # Also delete associated scenes
        scene_ids = [s.id for s in _SCENE_STORE.values() if s.videoId == video_id]
        for sid in scene_ids:
            del _SCENE_STORE[sid]
        return True
    return False


# ============================================================================
# Scene CRUD
# ============================================================================

def create_scene(video_id: str, inp: StudioSceneCreate) -> Optional[StudioScene]:
    """Create a new scene for a video project."""
    v = get_video(video_id)
    if not v:
        return None

    # Get next scene index
    existing = list_scenes(video_id)
    next_idx = max([s.idx for s in existing], default=-1) + 1

    now = time.time()
    scene = StudioScene(
        id=str(uuid.uuid4()),
        videoId=video_id,
        idx=next_idx,
        narration=inp.narration,
        imagePrompt=inp.imagePrompt,
        negativePrompt=inp.negativePrompt,
        durationSec=inp.durationSec,
        status="pending",
        createdAt=now,
        updatedAt=now,
    )
    _SCENE_STORE[scene.id] = scene

    # Touch the video to update its timestamp
    touch(video_id)

    return scene


def list_scenes(video_id: str) -> List[StudioScene]:
    """List all scenes for a video, sorted by idx."""
    scenes = [s for s in _SCENE_STORE.values() if s.videoId == video_id]
    scenes.sort(key=lambda x: x.idx)
    return scenes


def get_scene(scene_id: str) -> Optional[StudioScene]:
    """Get a scene by ID."""
    return _SCENE_STORE.get(scene_id)


def update_scene(scene_id: str, updates: StudioSceneUpdate) -> Optional[StudioScene]:
    """Update a scene's fields."""
    scene = _SCENE_STORE.get(scene_id)
    if not scene:
        return None

    update_data = updates.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(scene, key) and value is not None:
            setattr(scene, key, value)

    scene.updatedAt = time.time()
    _SCENE_STORE[scene_id] = scene

    # Touch the video to update its timestamp
    touch(scene.videoId)

    return scene


def delete_scene(scene_id: str) -> bool:
    """Delete a scene. Returns True if deleted."""
    scene = _SCENE_STORE.get(scene_id)
    if scene:
        video_id = scene.videoId
        del _SCENE_STORE[scene_id]
        touch(video_id)
        return True
    return False
