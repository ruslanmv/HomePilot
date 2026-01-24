"""
Repository layer for Studio video projects and professional projects.

In-memory storage for MVP. Replace with proper database in production.
"""
from __future__ import annotations

import secrets
import time
import uuid
from typing import Any, Dict, List, Optional

from .models import (
    StudioVideo, StudioVideoCreate, StudioScene, StudioSceneCreate, StudioSceneUpdate,
    StudioProject, StudioProjectCreate, StudioAsset, AudioTrack, CaptionSegment,
    VersionSnapshot, ShareLink, CanvasSpec, AssetKind, TrackKind,
)
from .library import normalize_project_type, default_canvas

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


# ============================================================================
# Professional Project System (Creator Studio Pro)
# ============================================================================

# In-memory stores for professional projects
_PROJECT_STORE: Dict[str, StudioProject] = {}
_ASSET_STORE: Dict[str, StudioAsset] = {}
_AUDIO_STORE: Dict[str, AudioTrack] = {}
_CAPTION_STORE: Dict[str, CaptionSegment] = {}
_VERSION_STORE: Dict[str, VersionSnapshot] = {}
_SHARE_STORE: Dict[str, ShareLink] = {}


# ============================================================================
# Project CRUD
# ============================================================================

def _project_type_to_preset(pt: str) -> str:
    """Convert project type to platform preset."""
    mapping = {
        "youtube_video": "youtube_16_9",
        "youtube_short": "shorts_9_16",
        "slides": "slides_16_9",
    }
    return mapping.get(pt, "youtube_16_9")


def create_project(inp: StudioProjectCreate) -> StudioProject:
    """Create a new professional project."""
    now = time.time()
    pt = normalize_project_type(inp.projectType)
    canvas = default_canvas(pt)
    preset = _project_type_to_preset(pt)

    proj = StudioProject(
        id=str(uuid.uuid4()),
        title=inp.title,
        description=inp.description,
        tags=inp.tags or [],
        projectType=pt,
        platformPreset=preset,
        canvas=canvas,
        templateId=inp.templateId,
        styleKitId=inp.styleKitId,
        targetDurationSec=inp.targetDurationSec,
        status="draft",
        contentRating=inp.contentRating,
        policyMode=inp.policyMode,
        providerPolicy=inp.providerPolicy,
        createdAt=now,
        updatedAt=now,
    )
    _PROJECT_STORE[proj.id] = proj
    return proj


def list_projects(
    q: Optional[str] = None,
    project_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[StudioProject]:
    """List professional projects with optional filters."""
    items = list(_PROJECT_STORE.values())

    if q:
        ql = q.lower()
        items = [p for p in items if ql in p.title.lower() or ql in p.description.lower()]

    if project_type:
        pt = normalize_project_type(project_type)
        items = [p for p in items if p.projectType == pt]

    if status:
        items = [p for p in items if p.status == status]

    items.sort(key=lambda x: x.updatedAt, reverse=True)
    return items[:limit]


def get_project(project_id: str) -> Optional[StudioProject]:
    """Get a professional project by ID."""
    return _PROJECT_STORE.get(project_id)


def update_project(project_id: str, **updates) -> Optional[StudioProject]:
    """Update a professional project's fields."""
    p = _PROJECT_STORE.get(project_id)
    if not p:
        return None

    for key, value in updates.items():
        if hasattr(p, key) and value is not None:
            setattr(p, key, value)

    p.updatedAt = time.time()
    _PROJECT_STORE[project_id] = p
    return p


def touch_project(project_id: str) -> None:
    """Update the project's updatedAt timestamp."""
    p = _PROJECT_STORE.get(project_id)
    if p:
        p.updatedAt = time.time()
        _PROJECT_STORE[project_id] = p


def delete_project(project_id: str) -> bool:
    """Delete a project and all associated data."""
    if project_id not in _PROJECT_STORE:
        return False

    del _PROJECT_STORE[project_id]

    # Delete associated assets
    asset_ids = [a.id for a in _ASSET_STORE.values() if a.projectId == project_id]
    for aid in asset_ids:
        del _ASSET_STORE[aid]

    # Delete associated audio tracks
    track_ids = [t.id for t in _AUDIO_STORE.values() if t.projectId == project_id]
    for tid in track_ids:
        del _AUDIO_STORE[tid]

    # Delete associated captions
    cap_ids = [c.id for c in _CAPTION_STORE.values() if c.projectId == project_id]
    for cid in cap_ids:
        del _CAPTION_STORE[cid]

    # Delete versions
    ver_ids = [v.id for v in _VERSION_STORE.values() if v.projectId == project_id]
    for vid in ver_ids:
        del _VERSION_STORE[vid]

    # Delete share links
    share_ids = [s.token for s in _SHARE_STORE.values() if s.projectId == project_id]
    for sid in share_ids:
        del _SHARE_STORE[sid]

    return True


# ============================================================================
# Asset CRUD
# ============================================================================

def create_asset(
    project_id: str,
    kind: AssetKind,
    filename: str,
    mime: str,
    size_bytes: int,
    url: str,
) -> Optional[StudioAsset]:
    """Create a new asset for a project."""
    if project_id not in _PROJECT_STORE:
        return None

    now = time.time()
    asset = StudioAsset(
        id=str(uuid.uuid4()),
        projectId=project_id,
        kind=kind,
        filename=filename,
        mime=mime,
        sizeBytes=size_bytes,
        url=url,
        createdAt=now,
    )
    _ASSET_STORE[asset.id] = asset
    touch_project(project_id)
    return asset


def list_assets(project_id: str, kind: Optional[AssetKind] = None) -> List[StudioAsset]:
    """List assets for a project, optionally filtered by kind."""
    assets = [a for a in _ASSET_STORE.values() if a.projectId == project_id]
    if kind:
        assets = [a for a in assets if a.kind == kind]
    assets.sort(key=lambda x: x.createdAt, reverse=True)
    return assets


def get_asset(asset_id: str) -> Optional[StudioAsset]:
    """Get an asset by ID."""
    return _ASSET_STORE.get(asset_id)


def delete_asset(asset_id: str) -> bool:
    """Delete an asset."""
    asset = _ASSET_STORE.get(asset_id)
    if asset:
        project_id = asset.projectId
        del _ASSET_STORE[asset_id]
        touch_project(project_id)
        return True
    return False


# ============================================================================
# Audio Track CRUD
# ============================================================================

def create_audio_track(
    project_id: str,
    kind: TrackKind,
    asset_id: Optional[str] = None,
    url: Optional[str] = None,
    volume: float = 1.0,
    start_sec: float = 0.0,
    end_sec: Optional[float] = None,
) -> Optional[AudioTrack]:
    """Create a new audio track for a project."""
    if project_id not in _PROJECT_STORE:
        return None

    now = time.time()
    track = AudioTrack(
        id=str(uuid.uuid4()),
        projectId=project_id,
        kind=kind,
        assetId=asset_id,
        url=url,
        volume=volume,
        startSec=start_sec,
        endSec=end_sec,
        createdAt=now,
        updatedAt=now,
    )
    _AUDIO_STORE[track.id] = track
    touch_project(project_id)
    return track


def list_audio_tracks(project_id: str, kind: Optional[TrackKind] = None) -> List[AudioTrack]:
    """List audio tracks for a project."""
    tracks = [t for t in _AUDIO_STORE.values() if t.projectId == project_id]
    if kind:
        tracks = [t for t in tracks if t.kind == kind]
    tracks.sort(key=lambda x: x.startSec)
    return tracks


def get_audio_track(track_id: str) -> Optional[AudioTrack]:
    """Get an audio track by ID."""
    return _AUDIO_STORE.get(track_id)


def update_audio_track(track_id: str, **updates) -> Optional[AudioTrack]:
    """Update an audio track."""
    track = _AUDIO_STORE.get(track_id)
    if not track:
        return None

    for key, value in updates.items():
        if hasattr(track, key) and value is not None:
            setattr(track, key, value)

    track.updatedAt = time.time()
    _AUDIO_STORE[track_id] = track
    touch_project(track.projectId)
    return track


def delete_audio_track(track_id: str) -> bool:
    """Delete an audio track."""
    track = _AUDIO_STORE.get(track_id)
    if track:
        project_id = track.projectId
        del _AUDIO_STORE[track_id]
        touch_project(project_id)
        return True
    return False


# ============================================================================
# Caption CRUD
# ============================================================================

def create_caption(
    project_id: str,
    start_sec: float,
    end_sec: float,
    text: str,
) -> Optional[CaptionSegment]:
    """Create a new caption segment."""
    if project_id not in _PROJECT_STORE:
        return None

    cap = CaptionSegment(
        id=str(uuid.uuid4()),
        projectId=project_id,
        startSec=start_sec,
        endSec=end_sec,
        text=text,
    )
    _CAPTION_STORE[cap.id] = cap
    touch_project(project_id)
    return cap


def list_captions(project_id: str) -> List[CaptionSegment]:
    """List captions for a project, sorted by start time."""
    caps = [c for c in _CAPTION_STORE.values() if c.projectId == project_id]
    caps.sort(key=lambda x: x.startSec)
    return caps


def get_caption(caption_id: str) -> Optional[CaptionSegment]:
    """Get a caption by ID."""
    return _CAPTION_STORE.get(caption_id)


def update_caption(caption_id: str, **updates) -> Optional[CaptionSegment]:
    """Update a caption segment."""
    cap = _CAPTION_STORE.get(caption_id)
    if not cap:
        return None

    for key, value in updates.items():
        if hasattr(cap, key) and value is not None:
            setattr(cap, key, value)

    _CAPTION_STORE[caption_id] = cap
    touch_project(cap.projectId)
    return cap


def delete_caption(caption_id: str) -> bool:
    """Delete a caption."""
    cap = _CAPTION_STORE.get(caption_id)
    if cap:
        project_id = cap.projectId
        del _CAPTION_STORE[caption_id]
        touch_project(project_id)
        return True
    return False


# ============================================================================
# Version/Autosave CRUD
# ============================================================================

def create_version(
    project_id: str,
    state: Dict[str, Any],
    label: str = "autosave",
) -> Optional[VersionSnapshot]:
    """Create a new version snapshot."""
    if project_id not in _PROJECT_STORE:
        return None

    now = time.time()
    ver = VersionSnapshot(
        id=str(uuid.uuid4()),
        projectId=project_id,
        label=label,
        state=state,
        createdAt=now,
    )
    _VERSION_STORE[ver.id] = ver
    touch_project(project_id)
    return ver


def list_versions(project_id: str, limit: int = 50) -> List[VersionSnapshot]:
    """List version snapshots for a project."""
    vers = [v for v in _VERSION_STORE.values() if v.projectId == project_id]
    vers.sort(key=lambda x: x.createdAt, reverse=True)
    return vers[:limit]


def get_version(version_id: str) -> Optional[VersionSnapshot]:
    """Get a version by ID."""
    return _VERSION_STORE.get(version_id)


def get_latest_version(project_id: str) -> Optional[VersionSnapshot]:
    """Get the most recent version for a project."""
    vers = list_versions(project_id, limit=1)
    return vers[0] if vers else None


def delete_version(version_id: str) -> bool:
    """Delete a version snapshot."""
    if version_id in _VERSION_STORE:
        del _VERSION_STORE[version_id]
        return True
    return False


# ============================================================================
# Share Link CRUD
# ============================================================================

def create_share_link(
    project_id: str,
    expires_in_hours: Optional[int] = None,
) -> Optional[ShareLink]:
    """Create a new share link for a project."""
    if project_id not in _PROJECT_STORE:
        return None

    now = time.time()
    expires_at = None
    if expires_in_hours:
        expires_at = now + (expires_in_hours * 3600)

    token = secrets.token_urlsafe(24)
    link = ShareLink(
        token=token,
        projectId=project_id,
        mode="view",
        createdAt=now,
        expiresAt=expires_at,
    )
    _SHARE_STORE[token] = link
    return link


def get_share_link(token: str) -> Optional[ShareLink]:
    """Get a share link by token."""
    link = _SHARE_STORE.get(token)
    if link:
        # Check expiration
        if link.expiresAt and time.time() > link.expiresAt:
            del _SHARE_STORE[token]
            return None
    return link


def list_share_links(project_id: str) -> List[ShareLink]:
    """List all share links for a project."""
    now = time.time()
    links = []
    expired = []

    for link in _SHARE_STORE.values():
        if link.projectId == project_id:
            if link.expiresAt and now > link.expiresAt:
                expired.append(link.token)
            else:
                links.append(link)

    # Clean up expired links
    for token in expired:
        del _SHARE_STORE[token]

    links.sort(key=lambda x: x.createdAt, reverse=True)
    return links


def delete_share_link(token: str) -> bool:
    """Delete a share link."""
    if token in _SHARE_STORE:
        del _SHARE_STORE[token]
        return True
    return False
