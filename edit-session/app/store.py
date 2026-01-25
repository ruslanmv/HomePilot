"""
Session storage module with SQLite and Redis backends.

Provides persistent storage for edit session state including:
- Active image URL per conversation
- Image history for undo/branch operations
- TTL-based automatic expiration
"""

import json
import sqlite3
import time
import os
from dataclasses import dataclass
from typing import Optional, List

from .config import settings

# Optional Redis import
try:
    import redis  # type: ignore
except ImportError:
    redis = None  # type: ignore


@dataclass
class SessionRecord:
    """
    Represents the state of an edit session.

    Attributes:
        conversation_id: Unique session identifier
        active_image_url: Currently active image for editing (None if no image set)
        history: List of previous image URLs (most recent first)
        updated_at: Unix timestamp of last update
    """
    conversation_id: str
    active_image_url: Optional[str]
    history: List[str]
    updated_at: float


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

    def set_active(self, conversation_id: str, image_url: str) -> SessionRecord:
        """
        Set the active image for a conversation.

        Also adds the image to history.

        Args:
            conversation_id: Unique session identifier
            image_url: URL of the image to set as active

        Returns:
            Updated SessionRecord
        """
        raise NotImplementedError

    def push_history(self, conversation_id: str, image_url: str) -> SessionRecord:
        """
        Add an image to history without changing active image.

        Used when edit results are generated but not yet selected.

        Args:
            conversation_id: Unique session identifier
            image_url: URL of the image to add to history

        Returns:
            Updated SessionRecord
        """
        raise NotImplementedError

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

    def get(self, conversation_id: str) -> SessionRecord:
        """Retrieve session state."""
        con = self._conn()
        try:
            row = con.execute(
                "SELECT active_image_url, history_json, updated_at "
                "FROM edit_sessions WHERE conversation_id=?",
                (conversation_id,),
            ).fetchone()

            if not row:
                return SessionRecord(conversation_id, None, [], time.time())

            active, history_json, updated_at = row
            history = json.loads(history_json) if history_json else []
            rec = SessionRecord(
                conversation_id,
                active,
                history,
                float(updated_at)
            )
            return self._prune_if_needed(rec)
        finally:
            con.close()

    def _save(self, rec: SessionRecord) -> None:
        """Persist session record to database."""
        con = self._conn()
        try:
            con.execute(
                """
                INSERT INTO edit_sessions
                    (conversation_id, active_image_url, history_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(conversation_id) DO UPDATE SET
                    active_image_url=excluded.active_image_url,
                    history_json=excluded.history_json,
                    updated_at=excluded.updated_at
                """,
                (
                    rec.conversation_id,
                    rec.active_image_url,
                    json.dumps(rec.history[: settings.HISTORY_LIMIT]),
                    rec.updated_at,
                ),
            )
            con.commit()
        finally:
            con.close()

    def set_active(self, conversation_id: str, image_url: str) -> SessionRecord:
        """Set active image and add to history."""
        rec = self.get(conversation_id)

        # Add to history, removing duplicates and keeping most recent first
        history = [image_url] + [h for h in rec.history if h != image_url]
        history = history[: settings.HISTORY_LIMIT]

        rec = SessionRecord(
            conversation_id,
            image_url,
            history,
            time.time()
        )
        self._save(rec)
        return rec

    def push_history(self, conversation_id: str, image_url: str) -> SessionRecord:
        """Add image to history without changing active image."""
        rec = self.get(conversation_id)

        # Add to history, removing duplicates
        history = [image_url] + [h for h in rec.history if h != image_url]
        history = history[: settings.HISTORY_LIMIT]

        rec = SessionRecord(
            conversation_id,
            rec.active_image_url,
            history,
            time.time()
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

    def get(self, conversation_id: str) -> SessionRecord:
        """Retrieve session state."""
        k = self._key(conversation_id)
        raw = self.r.get(k)

        if not raw:
            return SessionRecord(conversation_id, None, [], time.time())

        data = json.loads(raw)
        return SessionRecord(
            conversation_id=conversation_id,
            active_image_url=data.get("active_image_url"),
            history=data.get("history") or [],
            updated_at=float(data.get("updated_at") or time.time()),
        )

    def _save(self, rec: SessionRecord) -> None:
        """Persist session record to Redis with TTL."""
        k = self._key(rec.conversation_id)
        data = {
            "active_image_url": rec.active_image_url,
            "history": rec.history[: settings.HISTORY_LIMIT],
            "updated_at": rec.updated_at,
        }
        self.r.setex(k, settings.TTL_SECONDS, json.dumps(data))

    def set_active(self, conversation_id: str, image_url: str) -> SessionRecord:
        """Set active image and add to history."""
        rec = self.get(conversation_id)

        history = [image_url] + [h for h in rec.history if h != image_url]
        history = history[: settings.HISTORY_LIMIT]

        rec = SessionRecord(
            conversation_id,
            image_url,
            history,
            time.time()
        )
        self._save(rec)
        return rec

    def push_history(self, conversation_id: str, image_url: str) -> SessionRecord:
        """Add image to history without changing active image."""
        rec = self.get(conversation_id)

        history = [image_url] + [h for h in rec.history if h != image_url]
        history = history[: settings.HISTORY_LIMIT]

        rec = SessionRecord(
            conversation_id,
            rec.active_image_url,
            history,
            time.time()
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
