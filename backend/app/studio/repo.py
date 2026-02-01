"""
Repository layer for Studio video projects and professional projects.

SQLite-backed persistence for production use.
Data survives server restarts and is stored in the same database as Play Story.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from ..config import SQLITE_PATH
from .. import storage

from .models import (
    StudioVideo, StudioVideoCreate, StudioScene, StudioSceneCreate, StudioSceneUpdate,
    StudioProject, StudioProjectCreate, StudioAsset, AudioTrack, CaptionSegment,
    VersionSnapshot, ShareLink, CanvasSpec, AssetKind, TrackKind,
)
from .library import normalize_project_type, default_canvas


# =============================================================================
# Database Connection Helpers
# =============================================================================

def _get_db_path() -> str:
    """Reuse the same database path resolution as main storage."""
    return storage._get_db_path()


def _db() -> sqlite3.Connection:
    """Get a database connection with Row factory."""
    con = sqlite3.connect(_get_db_path())
    con.row_factory = sqlite3.Row
    return con


def _now() -> float:
    """Get current timestamp."""
    return time.time()


# =============================================================================
# Database Initialization
# =============================================================================

_INITIALIZED = False


def init_studio_db() -> None:
    """
    Create all Studio tables if they don't exist.
    Safe to call multiple times.
    """
    global _INITIALIZED
    if _INITIALIZED:
        return

    con = _db()
    cur = con.cursor()

    # Studio Videos table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS studio_videos (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            logline TEXT DEFAULT '',
            tags_json TEXT DEFAULT '[]',
            status TEXT DEFAULT 'draft',
            platform_preset TEXT DEFAULT 'youtube_16_9',
            target_duration_sec INTEGER DEFAULT 180,
            content_rating TEXT DEFAULT 'sfw',
            policy_mode TEXT DEFAULT 'youtube_safe',
            provider_policy_json TEXT DEFAULT '{}',
            metadata_json TEXT DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
    """)

    # Studio Scenes table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS studio_scenes (
            id TEXT PRIMARY KEY,
            video_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            narration TEXT DEFAULT '',
            image_prompt TEXT DEFAULT '',
            negative_prompt TEXT DEFAULT '',
            image_url TEXT,
            video_url TEXT,
            audio_url TEXT,
            status TEXT DEFAULT 'pending',
            duration_sec REAL DEFAULT 5.0,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (video_id) REFERENCES studio_videos(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_studio_scenes_video ON studio_scenes(video_id)")

    # Lightweight migration: add video_url column if missing (existing installations)
    cur.execute("PRAGMA table_info(studio_scenes);")
    cols = [r[1] for r in cur.fetchall()]
    if "video_url" not in cols:
        cur.execute("ALTER TABLE studio_scenes ADD COLUMN video_url TEXT;")
        con.commit()

    # Studio Projects table (professional projects)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS studio_projects (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            tags_json TEXT DEFAULT '[]',
            project_type TEXT NOT NULL,
            platform_preset TEXT DEFAULT 'youtube_16_9',
            canvas_json TEXT DEFAULT '{}',
            template_id TEXT,
            style_kit_id TEXT,
            target_duration_sec INTEGER,
            status TEXT DEFAULT 'draft',
            content_rating TEXT DEFAULT 'sfw',
            policy_mode TEXT DEFAULT 'youtube_safe',
            provider_policy_json TEXT DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
    """)

    # Studio Assets table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS studio_assets (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            filename TEXT NOT NULL,
            mime TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            url TEXT NOT NULL,
            created_at REAL NOT NULL,
            FOREIGN KEY (project_id) REFERENCES studio_projects(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_studio_assets_project ON studio_assets(project_id)")

    # Audio Tracks table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS studio_audio_tracks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            asset_id TEXT,
            url TEXT,
            volume REAL DEFAULT 1.0,
            start_sec REAL DEFAULT 0.0,
            end_sec REAL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            FOREIGN KEY (project_id) REFERENCES studio_projects(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_studio_audio_project ON studio_audio_tracks(project_id)")

    # Captions table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS studio_captions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            start_sec REAL NOT NULL,
            end_sec REAL NOT NULL,
            text TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES studio_projects(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_studio_captions_project ON studio_captions(project_id)")

    # Version Snapshots table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS studio_versions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            label TEXT DEFAULT 'autosave',
            state_json TEXT DEFAULT '{}',
            created_at REAL NOT NULL,
            FOREIGN KEY (project_id) REFERENCES studio_projects(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_studio_versions_project ON studio_versions(project_id)")

    # Share Links table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS studio_share_links (
            token TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            mode TEXT DEFAULT 'view',
            created_at REAL NOT NULL,
            expires_at REAL,
            FOREIGN KEY (project_id) REFERENCES studio_projects(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_studio_share_project ON studio_share_links(project_id)")

    con.commit()
    con.close()

    _INITIALIZED = True
    print("[STUDIO] Database tables initialized")


# =============================================================================
# Video CRUD
# =============================================================================

def create_video(inp: StudioVideoCreate) -> StudioVideo:
    """Create a new video project."""
    init_studio_db()
    now = _now()
    vid_id = str(uuid.uuid4())

    con = _db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO studio_videos (
            id, title, logline, tags_json, status, platform_preset,
            target_duration_sec, content_rating, policy_mode, provider_policy_json,
            metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        vid_id,
        inp.title,
        inp.logline or "",
        json.dumps(inp.tags or []),
        "draft",
        inp.platformPreset,
        inp.targetDurationSec or 180,
        inp.contentRating,
        inp.policyMode,
        inp.providerPolicy.model_dump_json() if inp.providerPolicy else "{}",
        "{}",
        now,
        now,
    ))
    con.commit()
    con.close()

    return _load_video(vid_id)


def _load_video(video_id: str) -> Optional[StudioVideo]:
    """Load a video from the database."""
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM studio_videos WHERE id = ?", (video_id,))
    row = cur.fetchone()
    con.close()

    if not row:
        return None

    from .models import ProviderPolicy
    provider_policy = ProviderPolicy()
    try:
        pp_data = json.loads(row["provider_policy_json"] or "{}")
        provider_policy = ProviderPolicy.model_validate(pp_data)
    except Exception:
        pass

    return StudioVideo(
        id=row["id"],
        title=row["title"],
        logline=row["logline"] or "",
        tags=json.loads(row["tags_json"] or "[]"),
        status=row["status"],
        platformPreset=row["platform_preset"],
        targetDurationSec=row["target_duration_sec"],
        contentRating=row["content_rating"],
        policyMode=row["policy_mode"],
        providerPolicy=provider_policy,
        metadata=json.loads(row["metadata_json"] or "{}"),
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def list_videos(
    q: Optional[str] = None,
    status: Optional[str] = None,
    preset: Optional[str] = None,
    contentRating: Optional[str] = None,
    limit: int = 100,
) -> List[StudioVideo]:
    """List video projects with optional filters."""
    init_studio_db()
    con = _db()
    cur = con.cursor()

    query = "SELECT * FROM studio_videos WHERE 1=1"
    params = []

    if q:
        query += " AND (title LIKE ? OR logline LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])

    if status:
        query += " AND status = ?"
        params.append(status)

    if preset:
        query += " AND platform_preset = ?"
        params.append(preset)

    if contentRating:
        query += " AND content_rating = ?"
        params.append(contentRating)

    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = cur.fetchall()
    con.close()

    videos = []
    for row in rows:
        vid = _row_to_video(row)
        if vid:
            videos.append(vid)
    return videos


def _row_to_video(row) -> Optional[StudioVideo]:
    """Convert a database row to StudioVideo."""
    if not row:
        return None

    from .models import ProviderPolicy
    provider_policy = ProviderPolicy()
    try:
        pp_data = json.loads(row["provider_policy_json"] or "{}")
        provider_policy = ProviderPolicy.model_validate(pp_data)
    except Exception:
        pass

    return StudioVideo(
        id=row["id"],
        title=row["title"],
        logline=row["logline"] or "",
        tags=json.loads(row["tags_json"] or "[]"),
        status=row["status"],
        platformPreset=row["platform_preset"],
        targetDurationSec=row["target_duration_sec"],
        contentRating=row["content_rating"],
        policyMode=row["policy_mode"],
        providerPolicy=provider_policy,
        metadata=json.loads(row["metadata_json"] or "{}"),
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def get_video(video_id: str) -> Optional[StudioVideo]:
    """Get a video by ID."""
    init_studio_db()
    return _load_video(video_id)


def update_video(video_id: str, **updates) -> Optional[StudioVideo]:
    """Update a video's fields."""
    init_studio_db()
    vid = get_video(video_id)
    if not vid:
        return None

    # Map model field names to database column names
    field_map = {
        "title": "title",
        "logline": "logline",
        "tags": "tags_json",
        "status": "status",
        "platformPreset": "platform_preset",
        "targetDurationSec": "target_duration_sec",
        "contentRating": "content_rating",
        "policyMode": "policy_mode",
        "providerPolicy": "provider_policy_json",
        "metadata": "metadata_json",
    }

    con = _db()
    cur = con.cursor()

    for key, value in updates.items():
        if key in field_map and value is not None:
            col = field_map[key]
            if col.endswith("_json"):
                if hasattr(value, "model_dump_json"):
                    value = value.model_dump_json()
                else:
                    value = json.dumps(value)
            cur.execute(f"UPDATE studio_videos SET {col} = ? WHERE id = ?", (value, video_id))

    cur.execute("UPDATE studio_videos SET updated_at = ? WHERE id = ?", (_now(), video_id))
    con.commit()
    con.close()

    return get_video(video_id)


def touch(video_id: str) -> None:
    """Update the video's updatedAt timestamp."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute("UPDATE studio_videos SET updated_at = ? WHERE id = ?", (_now(), video_id))
    con.commit()
    con.close()


def delete_video(video_id: str) -> bool:
    """Delete a video and all associated scenes."""
    init_studio_db()
    con = _db()
    cur = con.cursor()

    # Delete associated scenes first
    cur.execute("DELETE FROM studio_scenes WHERE video_id = ?", (video_id,))
    # Delete the video
    cur.execute("DELETE FROM studio_videos WHERE id = ?", (video_id,))
    deleted = cur.rowcount > 0

    con.commit()
    con.close()
    return deleted


# =============================================================================
# Scene CRUD
# =============================================================================

def create_scene(video_id: str, inp: StudioSceneCreate) -> Optional[StudioScene]:
    """Create a new scene for a video project."""
    init_studio_db()
    vid = get_video(video_id)
    if not vid:
        return None

    # Get next scene index
    existing = list_scenes(video_id)
    next_idx = max([s.idx for s in existing], default=-1) + 1

    now = _now()
    scene_id = str(uuid.uuid4())

    con = _db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO studio_scenes (
            id, video_id, idx, narration, image_prompt, negative_prompt,
            status, duration_sec, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        scene_id,
        video_id,
        next_idx,
        inp.narration,
        inp.imagePrompt,
        inp.negativePrompt,
        "pending",
        inp.durationSec,
        now,
        now,
    ))
    con.commit()
    con.close()

    touch(video_id)
    return get_scene(scene_id)


def list_scenes(video_id: str) -> List[StudioScene]:
    """List all scenes for a video, sorted by idx."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM studio_scenes WHERE video_id = ? ORDER BY idx ASC",
        (video_id,)
    )
    rows = cur.fetchall()
    con.close()

    return [_row_to_scene(row) for row in rows if row]


def _row_to_scene(row) -> StudioScene:
    """Convert a database row to StudioScene."""
    return StudioScene(
        id=row["id"],
        videoId=row["video_id"],
        idx=row["idx"],
        narration=row["narration"] or "",
        imagePrompt=row["image_prompt"] or "",
        negativePrompt=row["negative_prompt"] or "",
        imageUrl=row["image_url"],
        videoUrl=row["video_url"] if "video_url" in row.keys() else None,
        audioUrl=row["audio_url"],
        status=row["status"],
        durationSec=row["duration_sec"],
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def get_scene(scene_id: str) -> Optional[StudioScene]:
    """Get a scene by ID."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM studio_scenes WHERE id = ?", (scene_id,))
    row = cur.fetchone()
    con.close()

    if not row:
        return None
    return _row_to_scene(row)


def update_scene(scene_id: str, updates: StudioSceneUpdate) -> Optional[StudioScene]:
    """Update a scene's fields."""
    init_studio_db()
    scene = get_scene(scene_id)
    if not scene:
        return None

    update_data = updates.model_dump(exclude_unset=True)
    if not update_data:
        return scene

    # CamelCase field map
    field_map = {
        "narration": "narration",
        "imagePrompt": "image_prompt",
        "negativePrompt": "negative_prompt",
        "imageUrl": "image_url",
        "videoUrl": "video_url",
        "audioUrl": "audio_url",
        "status": "status",
        "durationSec": "duration_sec",
    }

    # Snake_case field map (for frontend compatibility)
    snake_map = {
        "image_url": "image_url",
        "video_url": "video_url",
        "audio_url": "audio_url",
        "image_prompt": "image_prompt",
        "negative_prompt": "negative_prompt",
        "duration_sec": "duration_sec",
    }

    con = _db()
    cur = con.cursor()

    # Process camelCase keys
    for key, value in update_data.items():
        if key in field_map:
            # IMPORTANT: Allow null/None updates so UI can "Remove Video" by setting videoUrl = null
            col = field_map[key]
            cur.execute(f"UPDATE studio_scenes SET {col} = ? WHERE id = ?", (value, scene_id))

    # Process snake_case keys
    for key, value in update_data.items():
        if key in snake_map:
            col = snake_map[key]
            cur.execute(f"UPDATE studio_scenes SET {col} = ? WHERE id = ?", (value, scene_id))

    cur.execute("UPDATE studio_scenes SET updated_at = ? WHERE id = ?", (_now(), scene_id))
    con.commit()
    con.close()

    touch(scene.videoId)
    return get_scene(scene_id)


def delete_scene(scene_id: str) -> bool:
    """Delete a scene."""
    init_studio_db()
    scene = get_scene(scene_id)
    if not scene:
        return False

    video_id = scene.videoId

    con = _db()
    cur = con.cursor()
    cur.execute("DELETE FROM studio_scenes WHERE id = ?", (scene_id,))
    deleted = cur.rowcount > 0
    con.commit()
    con.close()

    if deleted:
        touch(video_id)
    return deleted


# =============================================================================
# Professional Project CRUD
# =============================================================================

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
    init_studio_db()
    now = _now()
    pt = normalize_project_type(inp.projectType)
    canvas = default_canvas(pt)
    preset = _project_type_to_preset(pt)
    proj_id = str(uuid.uuid4())

    con = _db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO studio_projects (
            id, title, description, tags_json, project_type, platform_preset,
            canvas_json, template_id, style_kit_id, target_duration_sec,
            status, content_rating, policy_mode, provider_policy_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        proj_id,
        inp.title,
        inp.description or "",
        json.dumps(inp.tags or []),
        pt,
        preset,
        canvas.model_dump_json(),
        inp.templateId,
        inp.styleKitId,
        inp.targetDurationSec,
        "draft",
        inp.contentRating,
        inp.policyMode,
        inp.providerPolicy.model_dump_json() if inp.providerPolicy else "{}",
        now,
        now,
    ))
    con.commit()
    con.close()

    return get_project(proj_id)


def _row_to_project(row) -> Optional[StudioProject]:
    """Convert a database row to StudioProject."""
    if not row:
        return None

    from .models import ProviderPolicy
    provider_policy = ProviderPolicy()
    try:
        pp_data = json.loads(row["provider_policy_json"] or "{}")
        provider_policy = ProviderPolicy.model_validate(pp_data)
    except Exception:
        pass

    canvas = CanvasSpec(width=1920, height=1080, fps=30)
    try:
        canvas_data = json.loads(row["canvas_json"] or "{}")
        canvas = CanvasSpec.model_validate(canvas_data)
    except Exception:
        pass

    return StudioProject(
        id=row["id"],
        title=row["title"],
        description=row["description"] or "",
        tags=json.loads(row["tags_json"] or "[]"),
        projectType=row["project_type"],
        platformPreset=row["platform_preset"],
        canvas=canvas,
        templateId=row["template_id"],
        styleKitId=row["style_kit_id"],
        targetDurationSec=row["target_duration_sec"],
        status=row["status"],
        contentRating=row["content_rating"],
        policyMode=row["policy_mode"],
        providerPolicy=provider_policy,
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def list_projects(
    q: Optional[str] = None,
    project_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[StudioProject]:
    """List professional projects with optional filters."""
    init_studio_db()
    con = _db()
    cur = con.cursor()

    query = "SELECT * FROM studio_projects WHERE 1=1"
    params = []

    if q:
        query += " AND (title LIKE ? OR description LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])

    if project_type:
        pt = normalize_project_type(project_type)
        query += " AND project_type = ?"
        params.append(pt)

    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)

    cur.execute(query, params)
    rows = cur.fetchall()
    con.close()

    projects = []
    for row in rows:
        proj = _row_to_project(row)
        if proj:
            projects.append(proj)
    return projects


def get_project(project_id: str) -> Optional[StudioProject]:
    """Get a professional project by ID."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM studio_projects WHERE id = ?", (project_id,))
    row = cur.fetchone()
    con.close()
    return _row_to_project(row)


def update_project(project_id: str, **updates) -> Optional[StudioProject]:
    """Update a professional project's fields."""
    init_studio_db()
    proj = get_project(project_id)
    if not proj:
        return None

    field_map = {
        "title": "title",
        "description": "description",
        "tags": "tags_json",
        "status": "status",
        "templateId": "template_id",
        "styleKitId": "style_kit_id",
        "targetDurationSec": "target_duration_sec",
        "contentRating": "content_rating",
        "policyMode": "policy_mode",
        "providerPolicy": "provider_policy_json",
        "canvas": "canvas_json",
    }

    con = _db()
    cur = con.cursor()

    for key, value in updates.items():
        if key in field_map and value is not None:
            col = field_map[key]
            if col.endswith("_json"):
                if hasattr(value, "model_dump_json"):
                    value = value.model_dump_json()
                else:
                    value = json.dumps(value)
            cur.execute(f"UPDATE studio_projects SET {col} = ? WHERE id = ?", (value, project_id))

    cur.execute("UPDATE studio_projects SET updated_at = ? WHERE id = ?", (_now(), project_id))
    con.commit()
    con.close()

    return get_project(project_id)


def touch_project(project_id: str) -> None:
    """Update the project's updatedAt timestamp."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute("UPDATE studio_projects SET updated_at = ? WHERE id = ?", (_now(), project_id))
    con.commit()
    con.close()


def delete_project(project_id: str) -> bool:
    """Delete a project and all associated data."""
    init_studio_db()
    con = _db()
    cur = con.cursor()

    # Delete associated data first
    cur.execute("DELETE FROM studio_assets WHERE project_id = ?", (project_id,))
    cur.execute("DELETE FROM studio_audio_tracks WHERE project_id = ?", (project_id,))
    cur.execute("DELETE FROM studio_captions WHERE project_id = ?", (project_id,))
    cur.execute("DELETE FROM studio_versions WHERE project_id = ?", (project_id,))
    cur.execute("DELETE FROM studio_share_links WHERE project_id = ?", (project_id,))

    # Delete the project
    cur.execute("DELETE FROM studio_projects WHERE id = ?", (project_id,))
    deleted = cur.rowcount > 0

    con.commit()
    con.close()
    return deleted


# =============================================================================
# Asset CRUD
# =============================================================================

def create_asset(
    project_id: str,
    kind: AssetKind,
    filename: str,
    mime: str,
    size_bytes: int,
    url: str,
) -> Optional[StudioAsset]:
    """Create a new asset for a project."""
    init_studio_db()
    if not get_project(project_id):
        return None

    now = _now()
    asset_id = str(uuid.uuid4())

    con = _db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO studio_assets (id, project_id, kind, filename, mime, size_bytes, url, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (asset_id, project_id, kind, filename, mime, size_bytes, url, now))
    con.commit()
    con.close()

    touch_project(project_id)
    return get_asset(asset_id)


def list_assets(project_id: str, kind: Optional[AssetKind] = None) -> List[StudioAsset]:
    """List assets for a project, optionally filtered by kind."""
    init_studio_db()
    con = _db()
    cur = con.cursor()

    if kind:
        cur.execute(
            "SELECT * FROM studio_assets WHERE project_id = ? AND kind = ? ORDER BY created_at DESC",
            (project_id, kind)
        )
    else:
        cur.execute(
            "SELECT * FROM studio_assets WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,)
        )

    rows = cur.fetchall()
    con.close()

    return [StudioAsset(
        id=row["id"],
        projectId=row["project_id"],
        kind=row["kind"],
        filename=row["filename"],
        mime=row["mime"],
        sizeBytes=row["size_bytes"],
        url=row["url"],
        createdAt=row["created_at"],
    ) for row in rows]


def get_asset(asset_id: str) -> Optional[StudioAsset]:
    """Get an asset by ID."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM studio_assets WHERE id = ?", (asset_id,))
    row = cur.fetchone()
    con.close()

    if not row:
        return None

    return StudioAsset(
        id=row["id"],
        projectId=row["project_id"],
        kind=row["kind"],
        filename=row["filename"],
        mime=row["mime"],
        sizeBytes=row["size_bytes"],
        url=row["url"],
        createdAt=row["created_at"],
    )


def delete_asset(asset_id: str) -> bool:
    """Delete an asset."""
    init_studio_db()
    asset = get_asset(asset_id)
    if not asset:
        return False

    project_id = asset.projectId

    con = _db()
    cur = con.cursor()
    cur.execute("DELETE FROM studio_assets WHERE id = ?", (asset_id,))
    deleted = cur.rowcount > 0
    con.commit()
    con.close()

    if deleted:
        touch_project(project_id)
    return deleted


# =============================================================================
# Audio Track CRUD
# =============================================================================

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
    init_studio_db()
    if not get_project(project_id):
        return None

    now = _now()
    track_id = str(uuid.uuid4())

    con = _db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO studio_audio_tracks (id, project_id, kind, asset_id, url, volume, start_sec, end_sec, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (track_id, project_id, kind, asset_id, url, volume, start_sec, end_sec, now, now))
    con.commit()
    con.close()

    touch_project(project_id)
    return get_audio_track(track_id)


def list_audio_tracks(project_id: str, kind: Optional[TrackKind] = None) -> List[AudioTrack]:
    """List audio tracks for a project."""
    init_studio_db()
    con = _db()
    cur = con.cursor()

    if kind:
        cur.execute(
            "SELECT * FROM studio_audio_tracks WHERE project_id = ? AND kind = ? ORDER BY start_sec",
            (project_id, kind)
        )
    else:
        cur.execute(
            "SELECT * FROM studio_audio_tracks WHERE project_id = ? ORDER BY start_sec",
            (project_id,)
        )

    rows = cur.fetchall()
    con.close()

    return [AudioTrack(
        id=row["id"],
        projectId=row["project_id"],
        kind=row["kind"],
        assetId=row["asset_id"],
        url=row["url"],
        volume=row["volume"],
        startSec=row["start_sec"],
        endSec=row["end_sec"],
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    ) for row in rows]


def get_audio_track(track_id: str) -> Optional[AudioTrack]:
    """Get an audio track by ID."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM studio_audio_tracks WHERE id = ?", (track_id,))
    row = cur.fetchone()
    con.close()

    if not row:
        return None

    return AudioTrack(
        id=row["id"],
        projectId=row["project_id"],
        kind=row["kind"],
        assetId=row["asset_id"],
        url=row["url"],
        volume=row["volume"],
        startSec=row["start_sec"],
        endSec=row["end_sec"],
        createdAt=row["created_at"],
        updatedAt=row["updated_at"],
    )


def update_audio_track(track_id: str, **updates) -> Optional[AudioTrack]:
    """Update an audio track."""
    init_studio_db()
    track = get_audio_track(track_id)
    if not track:
        return None

    field_map = {
        "assetId": "asset_id",
        "url": "url",
        "volume": "volume",
        "startSec": "start_sec",
        "endSec": "end_sec",
    }

    con = _db()
    cur = con.cursor()

    for key, value in updates.items():
        if key in field_map and value is not None:
            col = field_map[key]
            cur.execute(f"UPDATE studio_audio_tracks SET {col} = ? WHERE id = ?", (value, track_id))

    cur.execute("UPDATE studio_audio_tracks SET updated_at = ? WHERE id = ?", (_now(), track_id))
    con.commit()
    con.close()

    touch_project(track.projectId)
    return get_audio_track(track_id)


def delete_audio_track(track_id: str) -> bool:
    """Delete an audio track."""
    init_studio_db()
    track = get_audio_track(track_id)
    if not track:
        return False

    project_id = track.projectId

    con = _db()
    cur = con.cursor()
    cur.execute("DELETE FROM studio_audio_tracks WHERE id = ?", (track_id,))
    deleted = cur.rowcount > 0
    con.commit()
    con.close()

    if deleted:
        touch_project(project_id)
    return deleted


# =============================================================================
# Caption CRUD
# =============================================================================

def create_caption(
    project_id: str,
    start_sec: float,
    end_sec: float,
    text: str,
) -> Optional[CaptionSegment]:
    """Create a new caption segment."""
    init_studio_db()
    if not get_project(project_id):
        return None

    cap_id = str(uuid.uuid4())

    con = _db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO studio_captions (id, project_id, start_sec, end_sec, text)
        VALUES (?, ?, ?, ?, ?)
    """, (cap_id, project_id, start_sec, end_sec, text))
    con.commit()
    con.close()

    touch_project(project_id)
    return get_caption(cap_id)


def list_captions(project_id: str) -> List[CaptionSegment]:
    """List captions for a project, sorted by start time."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM studio_captions WHERE project_id = ? ORDER BY start_sec",
        (project_id,)
    )
    rows = cur.fetchall()
    con.close()

    return [CaptionSegment(
        id=row["id"],
        projectId=row["project_id"],
        startSec=row["start_sec"],
        endSec=row["end_sec"],
        text=row["text"],
    ) for row in rows]


def get_caption(caption_id: str) -> Optional[CaptionSegment]:
    """Get a caption by ID."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM studio_captions WHERE id = ?", (caption_id,))
    row = cur.fetchone()
    con.close()

    if not row:
        return None

    return CaptionSegment(
        id=row["id"],
        projectId=row["project_id"],
        startSec=row["start_sec"],
        endSec=row["end_sec"],
        text=row["text"],
    )


def update_caption(caption_id: str, **updates) -> Optional[CaptionSegment]:
    """Update a caption segment."""
    init_studio_db()
    cap = get_caption(caption_id)
    if not cap:
        return None

    field_map = {
        "startSec": "start_sec",
        "endSec": "end_sec",
        "text": "text",
    }

    con = _db()
    cur = con.cursor()

    for key, value in updates.items():
        if key in field_map and value is not None:
            col = field_map[key]
            cur.execute(f"UPDATE studio_captions SET {col} = ? WHERE id = ?", (value, caption_id))

    con.commit()
    con.close()

    touch_project(cap.projectId)
    return get_caption(caption_id)


def delete_caption(caption_id: str) -> bool:
    """Delete a caption."""
    init_studio_db()
    cap = get_caption(caption_id)
    if not cap:
        return False

    project_id = cap.projectId

    con = _db()
    cur = con.cursor()
    cur.execute("DELETE FROM studio_captions WHERE id = ?", (caption_id,))
    deleted = cur.rowcount > 0
    con.commit()
    con.close()

    if deleted:
        touch_project(project_id)
    return deleted


# =============================================================================
# Version/Autosave CRUD
# =============================================================================

def create_version(
    project_id: str,
    state: Dict[str, Any],
    label: str = "autosave",
) -> Optional[VersionSnapshot]:
    """Create a new version snapshot."""
    init_studio_db()
    if not get_project(project_id):
        return None

    now = _now()
    ver_id = str(uuid.uuid4())

    con = _db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO studio_versions (id, project_id, label, state_json, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (ver_id, project_id, label, json.dumps(state), now))
    con.commit()
    con.close()

    touch_project(project_id)
    return get_version(ver_id)


def list_versions(project_id: str, limit: int = 50) -> List[VersionSnapshot]:
    """List version snapshots for a project."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM studio_versions WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit)
    )
    rows = cur.fetchall()
    con.close()

    return [VersionSnapshot(
        id=row["id"],
        projectId=row["project_id"],
        label=row["label"],
        state=json.loads(row["state_json"] or "{}"),
        createdAt=row["created_at"],
    ) for row in rows]


def get_version(version_id: str) -> Optional[VersionSnapshot]:
    """Get a version by ID."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM studio_versions WHERE id = ?", (version_id,))
    row = cur.fetchone()
    con.close()

    if not row:
        return None

    return VersionSnapshot(
        id=row["id"],
        projectId=row["project_id"],
        label=row["label"],
        state=json.loads(row["state_json"] or "{}"),
        createdAt=row["created_at"],
    )


def get_latest_version(project_id: str) -> Optional[VersionSnapshot]:
    """Get the most recent version for a project."""
    vers = list_versions(project_id, limit=1)
    return vers[0] if vers else None


def delete_version(version_id: str) -> bool:
    """Delete a version snapshot."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute("DELETE FROM studio_versions WHERE id = ?", (version_id,))
    deleted = cur.rowcount > 0
    con.commit()
    con.close()
    return deleted


# =============================================================================
# Share Link CRUD
# =============================================================================

def create_share_link(
    project_id: str,
    expires_in_hours: Optional[int] = None,
) -> Optional[ShareLink]:
    """Create a new share link for a project."""
    init_studio_db()
    if not get_project(project_id):
        return None

    now = _now()
    expires_at = None
    if expires_in_hours:
        expires_at = now + (expires_in_hours * 3600)

    token = secrets.token_urlsafe(24)

    con = _db()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO studio_share_links (token, project_id, mode, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
    """, (token, project_id, "view", now, expires_at))
    con.commit()
    con.close()

    return get_share_link(token)


def get_share_link(token: str) -> Optional[ShareLink]:
    """Get a share link by token."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute("SELECT * FROM studio_share_links WHERE token = ?", (token,))
    row = cur.fetchone()
    con.close()

    if not row:
        return None

    # Check expiration
    if row["expires_at"] and _now() > row["expires_at"]:
        delete_share_link(token)
        return None

    return ShareLink(
        token=row["token"],
        projectId=row["project_id"],
        mode=row["mode"],
        createdAt=row["created_at"],
        expiresAt=row["expires_at"],
    )


def list_share_links(project_id: str) -> List[ShareLink]:
    """List all share links for a project."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute(
        "SELECT * FROM studio_share_links WHERE project_id = ? ORDER BY created_at DESC",
        (project_id,)
    )
    rows = cur.fetchall()
    con.close()

    now = _now()
    links = []
    expired_tokens = []

    for row in rows:
        if row["expires_at"] and now > row["expires_at"]:
            expired_tokens.append(row["token"])
        else:
            links.append(ShareLink(
                token=row["token"],
                projectId=row["project_id"],
                mode=row["mode"],
                createdAt=row["created_at"],
                expiresAt=row["expires_at"],
            ))

    # Clean up expired links
    if expired_tokens:
        con = _db()
        cur = con.cursor()
        for token in expired_tokens:
            cur.execute("DELETE FROM studio_share_links WHERE token = ?", (token,))
        con.commit()
        con.close()

    return links


def delete_share_link(token: str) -> bool:
    """Delete a share link."""
    init_studio_db()
    con = _db()
    cur = con.cursor()
    cur.execute("DELETE FROM studio_share_links WHERE token = ?", (token,))
    deleted = cur.rowcount > 0
    con.commit()
    con.close()
    return deleted
