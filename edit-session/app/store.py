"""
Session storage module with SQLite and Redis backends.

Provides persistent storage for edit session state including:
- Active image URL per conversation
- Image history with version metadata for undo/branch operations
- TTL-based automatic expiration
- Version tracking with prompts, timestamps, and settings
"""

import json
import sqlite3
import time
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

from .config import settings

# Optional Redis import
try:
    import redis  # type: ignore
except ImportError:
    redis = None  # type: ignore


@dataclass
class VersionEntry:
    """
    Represents a single version in the edit history.

    Attributes:
        url: Image URL for this version
        instruction: The edit instruction/prompt used to create this version
        created_at: Unix timestamp when this version was created
        parent_url: URL of the parent image (for branching support)
        settings: Optional dict of edit settings (steps, cfg, denoise, etc.)
    """
    url: str
    instruction: str = ""
    created_at: float = field(default_factory=time.time)
    parent_url: Optional[str] = None
    settings: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "url": self.url,
            "instruction": self.instruction,
            "created_at": self.created_at,
            "parent_url": self.parent_url,
            "settings": self.settings,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VersionEntry":
        """Create VersionEntry from dictionary."""
        return cls(
            url=data.get("url", ""),
            instruction=data.get("instruction", ""),
            created_at=data.get("created_at", time.time()),
            parent_url=data.get("parent_url"),
            settings=data.get("settings", {}),
        )

    @classmethod
    def from_url(cls, url: str) -> "VersionEntry":
        """Create a VersionEntry from just a URL (legacy compatibility)."""
        return cls(url=url, instruction="", created_at=time.time())


@dataclass
class SessionRecord:
    """
    Represents the state of an edit session.

    Attributes:
        conversation_id: Unique session identifier
        active_image_url: Currently active image for editing (None if no image set)
        versions: List of VersionEntry objects (most recent first)
        original_image_url: The first image uploaded to this session
        updated_at: Unix timestamp of last update
    """
    conversation_id: str
    active_image_url: Optional[str]
    versions: List[VersionEntry]
    updated_at: float
    original_image_url: Optional[str] = None

    @property
    def history(self) -> List[str]:
        """
        Legacy compatibility: return list of URLs from versions.
        """
        return [v.url for v in self.versions]

    def get_version_by_url(self, url: str) -> Optional[VersionEntry]:
        """Find a version entry by its URL."""
        for v in self.versions:
            if v.url == url:
                return v
        return None


class BaseStore:
    """Abstract base class for session storage backends."""

    def get(self, conversation_id: str) -> SessionRecord:
        """
        Retrieve session state for a conversation.

        Args:
            conversation_id: Unique session identifier

        Returns:
            SessionRecord with current state (empty if not found)
        """
        raise NotImplementedError

    def set_active(
        self,
        conversation_id: str,
        image_url: str,
        instruction: str = "",
        settings: Optional[Dict[str, Any]] = None,
    ) -> SessionRecord:
        """
        Set the active image for a conversation.

        Also adds the image to version history with metadata.

        Args:
            conversation_id: Unique session identifier
            image_url: URL of the image to set as active
            instruction: The edit instruction that created this image
            settings: Optional edit settings (steps, cfg, etc.)

        Returns:
            Updated SessionRecord
        """
        raise NotImplementedError

    def push_version(
        self,
        conversation_id: str,
        image_url: str,
        instruction: str = "",
        parent_url: Optional[str] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> SessionRecord:
        """
        Add a version to history without changing active image.

        Used when edit results are generated but not yet selected.

        Args:
            conversation_id: Unique session identifier
            image_url: URL of the image to add to history
            instruction: The edit instruction that created this image
            parent_url: URL of the parent image (for branching)
            settings: Optional edit settings

        Returns:
            Updated SessionRecord
        """
        raise NotImplementedError

    def push_history(self, conversation_id: str, image_url: str) -> SessionRecord:
        """
        Legacy method: Add an image to history without metadata.

        Args:
            conversation_id: Unique session identifier
            image_url: URL of the image to add to history

        Returns:
            Updated SessionRecord
        """
        return self.push_version(conversation_id, image_url)

    def clear(self, conversation_id: str) -> None:
        """
        Clear all session data for a conversation.

        Args:
            conversation_id: Unique session identifier
        """
        raise NotImplementedError


class SQLiteStore(BaseStore):
    """
    SQLite-based session storage.

    Suitable for single-instance deployments or development.
    Data is persisted to disk and survives restarts.
    """

    def __init__(self, path: str):
        """
        Initialize SQLite store.

        Args:
            path: Path to SQLite database file
        """
        self.path = path
        self._ensure_directory()
        self._init_db()

    def _ensure_directory(self) -> None:
        """Create parent directory if it doesn't exist."""
        dir_path = os.path.dirname(self.path)
        if dir_path and not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

    def _conn(self) -> sqlite3.Connection:
        """Create a new database connection."""
        return sqlite3.connect(self.path, check_same_thread=False)

    def _init_db(self) -> None:
        """Create schema if not exists."""
        con = self._conn()
        try:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS edit_sessions (
                    conversation_id TEXT PRIMARY KEY,
                    active_image_url TEXT,
                    original_image_url TEXT,
                    history_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            # Index for TTL cleanup queries
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_edit_sessions_updated
                ON edit_sessions(updated_at)
                """
            )
            con.commit()
        finally:
            con.close()

    def _prune_if_needed(self, rec: SessionRecord) -> SessionRecord:
        """
        Check TTL and clear session if expired.

        Args:
            rec: Session record to check

        Returns:
            Original record if valid, empty record if expired
        """
        if (time.time() - rec.updated_at) > settings.TTL_SECONDS:
            self.clear(rec.conversation_id)
            return SessionRecord(rec.conversation_id, None, [], time.time())
        return rec

    def _parse_history_json(self, history_json: str) -> List[VersionEntry]:
        """
        Parse history JSON with backward compatibility.

        Handles both old format (list of URLs) and new format (list of VersionEntry dicts).
        """
        if not history_json:
            return []

        try:
            data = json.loads(history_json)
        except json.JSONDecodeError:
            return []

        if not isinstance(data, list):
            return []

        versions: List[VersionEntry] = []
        for item in data:
            if isinstance(item, str):
                # Legacy format: just a URL string
                versions.append(VersionEntry.from_url(item))
            elif isinstance(item, dict):
                # New format: VersionEntry dict
                versions.append(VersionEntry.from_dict(item))

        return versions

    def get(self, conversation_id: str) -> SessionRecord:
        """Retrieve session state."""
        con = self._conn()
        try:
            row = con.execute(
                "SELECT active_image_url, original_image_url, history_json, updated_at "
                "FROM edit_sessions WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()

            if not row:
                return SessionRecord(conversation_id, None, [], time.time())

            active, original, history_json, updated_at = row
            versions = self._parse_history_json(history_json)
            rec = SessionRecord(
                conversation_id=conversation_id,
                active_image_url=active,
                versions=versions,
                updated_at=float(updated_at),
                original_image_url=original,
            )
            return self._prune_if_needed(rec)
        finally:
            con.close()

    def _save(self, rec: SessionRecord) -> None:
        """Persist session record to database."""
        con = self._conn()
        try:
            # Serialize versions as list of dicts
            versions_data = [v.to_dict() for v in rec.versions[: settings.HISTORY_LIMIT]]
            con.execute(
                """
                INSERT INTO edit_sessions
                    (conversation_id, active_image_url, original_image_url, history_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    active_image_url=excluded.active_image_url,
                    original_image_url=excluded.original_image_url,
                    history_json=excluded.history_json,
                    updated_at=excluded.updated_at
                """,
                (
                    rec.conversation_id,
                    rec.active_image_url,
                    rec.original_image_url,
                    json.dumps(versions_data),
                    rec.updated_at,
                ),
            )
            con.commit()
        finally:
            con.close()

    def set_active(
        self,
        conversation_id: str,
        image_url: str,
        instruction: str = "",
        settings_dict: Optional[Dict[str, Any]] = None,
    ) -> SessionRecord:
        """Set active image and add to version history."""
        rec = self.get(conversation_id)

        # Create new version entry
        new_version = VersionEntry(
            url=image_url,
            instruction=instruction,
            created_at=time.time(),
            parent_url=rec.active_image_url,
            settings=settings_dict or {},
        )

        # Add to versions, removing duplicates by URL and keeping most recent first
        versions = [new_version] + [v for v in rec.versions if v.url != image_url]
        versions = versions[: settings.HISTORY_LIMIT]

        # Set original_image_url if this is the first image
        original = rec.original_image_url or image_url

        rec = SessionRecord(
            conversation_id=conversation_id,
            active_image_url=image_url,
            versions=versions,
            updated_at=time.time(),
            original_image_url=original,
        )
        self._save(rec)
        return rec

    def push_version(
        self,
        conversation_id: str,
        image_url: str,
        instruction: str = "",
        parent_url: Optional[str] = None,
        settings_dict: Optional[Dict[str, Any]] = None,
    ) -> SessionRecord:
        """Add version to history without changing active image."""
        rec = self.get(conversation_id)

        # Create new version entry
        new_version = VersionEntry(
            url=image_url,
            instruction=instruction,
            created_at=time.time(),
            parent_url=parent_url or rec.active_image_url,
            settings=settings_dict or {},
        )

        # Add to versions, removing duplicates
        versions = [new_version] + [v for v in rec.versions if v.url != image_url]
        versions = versions[: settings.HISTORY_LIMIT]

        rec = SessionRecord(
            conversation_id=conversation_id,
            active_image_url=rec.active_image_url,
            versions=versions,
            updated_at=time.time(),
            original_image_url=rec.original_image_url,
        )
        self._save(rec)
        return rec

    def clear(self, conversation_id: str) -> None:
        """Clear session data."""
        con = self._conn()
        try:
            con.execute(
                "DELETE FROM edit_sessions WHERE conversation_id=?",
                (conversation_id,)
            )
            con.commit()
        finally:
            con.close()

    def cleanup_expired(self) -> int:
        """
        Remove all expired sessions.

        Returns:
            Number of sessions removed
        """
        con = self._conn()
        try:
            cutoff = time.time() - settings.TTL_SECONDS
            cursor = con.execute(
                "DELETE FROM edit_sessions WHERE updated_at < ?",
                (cutoff,)
            )
            con.commit()
            return cursor.rowcount
        finally:
            con.close()


class RedisStore(BaseStore):
    """
    Redis-based session storage.

    Recommended for multi-instance deployments.
    Uses Redis key expiration for automatic TTL enforcement.
    """

    def __init__(self, url: str):
        """
        Initialize Redis store.

        Args:
            url: Redis connection URL

        Raises:
            RuntimeError: If redis package is not installed
        """
        if redis is None:
            raise RuntimeError(
                "redis package not available. "
                "Install with: pip install redis"
            )
        self.r = redis.Redis.from_url(url, decode_responses=True)

    def _key(self, conversation_id: str) -> str:
        """Generate Redis key for a conversation."""
        return f"edit_session:{conversation_id}"

    def _parse_versions(self, data: Any) -> List[VersionEntry]:
        """
        Parse versions/history with backward compatibility.
        """
        # Try new format first (versions field)
        versions_data = data.get("versions")
        if versions_data and isinstance(versions_data, list):
            versions: List[VersionEntry] = []
            for item in versions_data:
                if isinstance(item, dict):
                    versions.append(VersionEntry.from_dict(item))
                elif isinstance(item, str):
                    versions.append(VersionEntry.from_url(item))
            return versions

        # Fall back to legacy format (history field with URL strings)
        history = data.get("history") or []
        return [VersionEntry.from_url(url) if isinstance(url, str) else VersionEntry.from_dict(url) for url in history]

    def get(self, conversation_id: str) -> SessionRecord:
        """Retrieve session state."""
        k = self._key(conversation_id)
        raw = self.r.get(k)

        if not raw:
            return SessionRecord(conversation_id, None, [], time.time())

        data = json.loads(raw)
        versions = self._parse_versions(data)

        return SessionRecord(
            conversation_id=conversation_id,
            active_image_url=data.get("active_image_url"),
            versions=versions,
            updated_at=float(data.get("updated_at") or time.time()),
            original_image_url=data.get("original_image_url"),
        )

    def _save(self, rec: SessionRecord) -> None:
        """Persist session record to Redis with TTL."""
        k = self._key(rec.conversation_id)
        # Serialize versions as list of dicts
        versions_data = [v.to_dict() for v in rec.versions[: settings.HISTORY_LIMIT]]
        data = {
            "active_image_url": rec.active_image_url,
            "original_image_url": rec.original_image_url,
            "versions": versions_data,
            "updated_at": rec.updated_at,
        }
        self.r.setex(k, settings.TTL_SECONDS, json.dumps(data))

    def set_active(
        self,
        conversation_id: str,
        image_url: str,
        instruction: str = "",
        settings_dict: Optional[Dict[str, Any]] = None,
    ) -> SessionRecord:
        """Set active image and add to version history."""
        rec = self.get(conversation_id)

        # Create new version entry
        new_version = VersionEntry(
            url=image_url,
            instruction=instruction,
            created_at=time.time(),
            parent_url=rec.active_image_url,
            settings=settings_dict or {},
        )

        versions = [new_version] + [v for v in rec.versions if v.url != image_url]
        versions = versions[: settings.HISTORY_LIMIT]

        # Set original_image_url if this is the first image
        original = rec.original_image_url or image_url

        rec = SessionRecord(
            conversation_id=conversation_id,
            active_image_url=image_url,
            versions=versions,
            updated_at=time.time(),
            original_image_url=original,
        )
        self._save(rec)
        return rec

    def push_version(
        self,
        conversation_id: str,
        image_url: str,
        instruction: str = "",
        parent_url: Optional[str] = None,
        settings_dict: Optional[Dict[str, Any]] = None,
    ) -> SessionRecord:
        """Add version to history without changing active image."""
        rec = self.get(conversation_id)

        # Create new version entry
        new_version = VersionEntry(
            url=image_url,
            instruction=instruction,
            created_at=time.time(),
            parent_url=parent_url or rec.active_image_url,
            settings=settings_dict or {},
        )

        versions = [new_version] + [v for v in rec.versions if v.url != image_url]
        versions = versions[: settings.HISTORY_LIMIT]

        rec = SessionRecord(
            conversation_id=conversation_id,
            active_image_url=rec.active_image_url,
            versions=versions,
            updated_at=time.time(),
            original_image_url=rec.original_image_url,
        )
        self._save(rec)
        return rec

    def clear(self, conversation_id: str) -> None:
        """Clear session data."""
        self.r.delete(self._key(conversation_id))

    def health_check(self) -> bool:
        """
        Check Redis connectivity.

        Returns:
            True if Redis is accessible
        """
        try:
            self.r.ping()
            return True
        except Exception:
            return False


def get_store() -> BaseStore:
    """
    Factory function to get the configured storage backend.

    Returns:
        SQLiteStore or RedisStore based on STORE setting
    """
    if settings.STORE.lower() == "redis":
        return RedisStore(settings.REDIS_URL)
    return SQLiteStore(settings.SQLITE_PATH)
