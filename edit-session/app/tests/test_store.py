"""
Tests for the session storage module.
"""

import os
import tempfile
import pytest
from app.store import SQLiteStore, SessionRecord


class TestSQLiteStore:
    """Test suite for SQLite storage backend."""

    def test_get_nonexistent_returns_empty_session(self):
        """Getting a non-existent session returns empty record."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db.sqlite")
            store = SQLiteStore(path)

            rec = store.get("nonexistent-conversation")

            assert rec.conversation_id == "nonexistent-conversation"
            assert rec.active_image_url is None
            assert rec.history == []

    def test_set_active_creates_session(self):
        """Setting active image creates new session."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db.sqlite")
            store = SQLiteStore(path)

            rec = store.set_active("c1", "http://example.com/a.png")

            assert rec.active_image_url == "http://example.com/a.png"
            assert rec.history[0] == "http://example.com/a.png"
            assert len(rec.history) == 1

    def test_set_active_updates_history(self):
        """Setting new active image adds to history."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db.sqlite")
            store = SQLiteStore(path)

            store.set_active("c1", "http://example.com/a.png")
            rec = store.set_active("c1", "http://example.com/b.png")

            assert rec.active_image_url == "http://example.com/b.png"
            assert rec.history[0] == "http://example.com/b.png"
            assert rec.history[1] == "http://example.com/a.png"
            assert len(rec.history) == 2

    def test_set_active_deduplicates_history(self):
        """Setting same URL again moves it to front without duplicating."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db.sqlite")
            store = SQLiteStore(path)

            store.set_active("c1", "http://example.com/a.png")
            store.set_active("c1", "http://example.com/b.png")
            rec = store.set_active("c1", "http://example.com/a.png")

            assert rec.active_image_url == "http://example.com/a.png"
            assert rec.history[0] == "http://example.com/a.png"
            assert rec.history[1] == "http://example.com/b.png"
            assert len(rec.history) == 2

    def test_push_history_adds_without_changing_active(self):
        """Push history adds to history without changing active image."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db.sqlite")
            store = SQLiteStore(path)

            store.set_active("c1", "http://example.com/a.png")
            rec = store.push_history("c1", "http://example.com/result.png")

            assert rec.active_image_url == "http://example.com/a.png"
            assert "http://example.com/result.png" in rec.history

    def test_clear_removes_session(self):
        """Clear removes all session data."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db.sqlite")
            store = SQLiteStore(path)

            store.set_active("c1", "http://example.com/a.png")
            store.clear("c1")
            rec = store.get("c1")

            assert rec.active_image_url is None
            assert rec.history == []

    def test_persistence_across_instances(self):
        """Data persists across store instances."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db.sqlite")

            # Create and populate
            store1 = SQLiteStore(path)
            store1.set_active("c1", "http://example.com/a.png")

            # New instance
            store2 = SQLiteStore(path)
            rec = store2.get("c1")

            assert rec.active_image_url == "http://example.com/a.png"

    def test_multiple_conversations(self):
        """Multiple conversations are isolated."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db.sqlite")
            store = SQLiteStore(path)

            store.set_active("c1", "http://example.com/a.png")
            store.set_active("c2", "http://example.com/b.png")

            rec1 = store.get("c1")
            rec2 = store.get("c2")

            assert rec1.active_image_url == "http://example.com/a.png"
            assert rec2.active_image_url == "http://example.com/b.png"

    def test_cleanup_expired(self):
        """Cleanup removes expired sessions."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "db.sqlite")
            store = SQLiteStore(path)

            # Create session with old timestamp
            import time
            from app import config

            original_ttl = config.settings.TTL_SECONDS
            config.settings.TTL_SECONDS = 1  # 1 second TTL

            try:
                store.set_active("c1", "http://example.com/a.png")
                time.sleep(2)  # Wait for expiry
                count = store.cleanup_expired()
                assert count == 1

                rec = store.get("c1")
                assert rec.active_image_url is None
            finally:
                config.settings.TTL_SECONDS = original_ttl
