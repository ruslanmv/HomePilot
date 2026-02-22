"""
Tests for LTM V1 Hardening — TTL, caps, dedupe, and maintenance.

Validates:
  - Policy config (TTL_MAP, CAP_MAP, TOTAL_CAP)
  - Near-duplicate detection (Jaccard similarity)
  - Schema extension (ensure_v1_hardening_columns idempotent)
  - TTL expiry (deletes expired, skips pinned, skips no-TTL categories)
  - Per-category cap enforcement
  - Total cap enforcement
  - Full maintenance pass
  - Dedup on upsert (ltm.py integration)
  - Access metadata tracking (access_count, last_access_at)
  - Memory stats reporting

Non-destructive: uses tmp_path from pytest for SQLite isolation.
CI-friendly: no network, no LLM.
"""
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def v1_db(tmp_path):
    """Set up an isolated SQLite DB with persona_memory table + V2 + V1 hardening columns."""
    db_path = str(tmp_path / "test_v1.db")

    # Create base table (as storage.py does)
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS persona_memory(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            confidence REAL DEFAULT 1.0,
            source_session TEXT,
            source_type TEXT DEFAULT 'inferred',
            visibility TEXT DEFAULT 'private',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            user_id TEXT DEFAULT NULL,
            UNIQUE(project_id, category, key)
        )
    """)
    con.commit()
    con.close()

    # Patch _get_db_path for both modules
    with patch("app.memory_v2._get_db_path", return_value=db_path), \
         patch("app.ltm_v1_maintenance._get_db_path", return_value=db_path), \
         patch("app.ltm._get_db_path", return_value=db_path):
        # Run V2 column migration first
        from app.memory_v2 import ensure_v2_columns
        ensure_v2_columns()
        # Run V1 hardening column migration
        from app.ltm_v1_maintenance import ensure_v1_hardening_columns
        ensure_v1_hardening_columns()
        yield db_path


def _insert_memory(db_path, project_id, category, key, value,
                   confidence=1.0, source_type="inferred",
                   updated_at=None, is_pinned=0, expires_at=0):
    """Direct insert helper for test setup."""
    now = updated_at or time.strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO persona_memory(project_id, category, key, value, confidence,
                                    source_type, created_at, updated_at,
                                    is_pinned, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, category, key, value, confidence, source_type, now, now,
         is_pinned, expires_at),
    )
    con.commit()
    con.close()


def _count_memories(db_path, project_id):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM persona_memory WHERE project_id = ?", (project_id,))
    count = cur.fetchone()[0]
    con.close()
    return count


# ---------------------------------------------------------------------------
# Policy config tests
# ---------------------------------------------------------------------------

class TestPolicy:
    """Verify policy defaults are sensible."""

    def test_ttl_map_has_known_categories(self):
        from app.ltm_v1_policy import TTL_MAP
        assert "fact" in TTL_MAP
        assert "preference" in TTL_MAP
        assert "summary" in TTL_MAP

    def test_facts_never_expire(self):
        from app.ltm_v1_policy import get_ttl
        assert get_ttl("fact") == 0

    def test_summary_expires(self):
        from app.ltm_v1_policy import get_ttl
        assert get_ttl("summary") > 0

    def test_cap_map_has_known_categories(self):
        from app.ltm_v1_policy import CAP_MAP
        assert "fact" in CAP_MAP
        assert CAP_MAP["fact"] > 0

    def test_default_cap_for_unknown_category(self):
        from app.ltm_v1_policy import get_cap
        assert get_cap("nonexistent_category") > 0

    def test_total_cap(self):
        from app.ltm_v1_policy import TOTAL_CAP
        assert TOTAL_CAP == 200


# ---------------------------------------------------------------------------
# Dedup tests
# ---------------------------------------------------------------------------

class TestDedupe:
    """Near-duplicate detection (Jaccard similarity)."""

    def test_identical_is_duplicate(self):
        from app.ltm_v1_policy import is_duplicate
        assert is_duplicate("The user works at Google", "The user works at Google")

    def test_near_identical_is_duplicate(self):
        from app.ltm_v1_policy import is_duplicate
        # Same content, minor wording change
        assert is_duplicate(
            "The user works at Google as a software engineer",
            "The user works at Google as software engineer",
        )

    def test_different_is_not_duplicate(self):
        from app.ltm_v1_policy import is_duplicate
        assert not is_duplicate(
            "The user works at Google",
            "The user likes pizza and coffee",
        )

    def test_empty_not_duplicate(self):
        from app.ltm_v1_policy import is_duplicate
        assert not is_duplicate("", "hello world")
        assert not is_duplicate("hello world", "")

    def test_short_tokens_ignored(self):
        from app.ltm_v1_policy import is_duplicate
        # "I am at" has only 2-char tokens, should be filtered out
        assert not is_duplicate("I am at", "I am at the store")


# ---------------------------------------------------------------------------
# Schema extension tests
# ---------------------------------------------------------------------------

class TestSchemaExtension:
    """V1 hardening columns are added and idempotent."""

    def test_adds_columns(self, v1_db):
        con = sqlite3.connect(v1_db)
        cur = con.cursor()
        cur.execute("PRAGMA table_info(persona_memory)")
        cols = {row[1] for row in cur.fetchall()}
        con.close()

        # V1 hardening columns
        assert "is_pinned" in cols
        assert "expires_at" in cols
        # V2 columns (already present)
        assert "mem_type" in cols
        assert "strength" in cols

    def test_idempotent(self, v1_db):
        """Running ensure_v1_hardening_columns twice should not error."""
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import ensure_v1_hardening_columns
            ensure_v1_hardening_columns()  # Second call


# ---------------------------------------------------------------------------
# TTL expiry tests
# ---------------------------------------------------------------------------

class TestTTLExpiry:
    """TTL-based expiration of memory entries."""

    def test_expired_entry_deleted(self, v1_db):
        """An old summary entry (TTL=30d) should be expired."""
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import expire_by_ttl
            # Insert summary entry with old timestamp (60 days ago)
            old_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 60 * 24 * 3600))
            _insert_memory(v1_db, "proj1", "summary", "session_sum", "We talked about cats",
                           updated_at=old_time)

            assert _count_memories(v1_db, "proj1") == 1
            expired = expire_by_ttl("proj1")
            assert expired == 1
            assert _count_memories(v1_db, "proj1") == 0

    def test_non_expired_entry_kept(self, v1_db):
        """A recent fact entry (TTL=0, never expires) should be kept."""
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import expire_by_ttl
            _insert_memory(v1_db, "proj1", "fact", "name", "Alice")

            expired = expire_by_ttl("proj1")
            assert expired == 0
            assert _count_memories(v1_db, "proj1") == 1

    def test_pinned_entry_survives_ttl(self, v1_db):
        """Pinned entries should never be expired, even if old."""
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import expire_by_ttl
            old_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 365 * 24 * 3600))
            _insert_memory(v1_db, "proj1", "summary", "pinned_sum", "Important note",
                           updated_at=old_time, is_pinned=1)

            expired = expire_by_ttl("proj1")
            assert expired == 0
            assert _count_memories(v1_db, "proj1") == 1

    def test_explicit_expires_at_honored(self, v1_db):
        """Entry with explicit expires_at in the past should be deleted."""
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import expire_by_ttl
            past_ts = time.time() - 3600  # 1 hour ago
            _insert_memory(v1_db, "proj1", "fact", "temp_fact", "Temporary",
                           expires_at=past_ts)

            expired = expire_by_ttl("proj1")
            assert expired == 1

    def test_explicit_expires_at_future_kept(self, v1_db):
        """Entry with explicit expires_at in the future should be kept."""
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import expire_by_ttl
            future_ts = time.time() + 365 * 24 * 3600  # 1 year from now
            _insert_memory(v1_db, "proj1", "fact", "future_fact", "Will last",
                           expires_at=future_ts)

            expired = expire_by_ttl("proj1")
            assert expired == 0
            assert _count_memories(v1_db, "proj1") == 1


# ---------------------------------------------------------------------------
# Category cap tests
# ---------------------------------------------------------------------------

class TestCategoryCaps:
    """Per-category cap enforcement."""

    def test_cap_evicts_overflow(self, v1_db):
        """Insert more than cap, verify oldest are evicted."""
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import enforce_category_caps
            from app.ltm_v1_policy import get_cap

            cap = get_cap("emotion_pattern")  # 15

            # Insert cap + 5 entries
            for i in range(cap + 5):
                ts = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(time.time() - (cap + 5 - i) * 60),
                )
                _insert_memory(v1_db, "proj1", "emotion_pattern", f"mood_{i}",
                               f"feeling {i}", updated_at=ts)

            assert _count_memories(v1_db, "proj1") == cap + 5
            evicted = enforce_category_caps("proj1")
            assert evicted == 5

            # Remaining should be exactly cap
            con = sqlite3.connect(v1_db)
            cur = con.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM persona_memory WHERE project_id = ? AND category = ?",
                ("proj1", "emotion_pattern"),
            )
            remaining = cur.fetchone()[0]
            con.close()
            assert remaining == cap

    def test_pinned_exempt_from_cap(self, v1_db):
        """Pinned entries should not be evicted by cap enforcement."""
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import enforce_category_caps

            # Insert 5 pinned + 12 non-pinned in boundary (cap=10)
            for i in range(5):
                _insert_memory(v1_db, "proj1", "boundary", f"pinned_{i}",
                               f"pinned boundary {i}", is_pinned=1)
            for i in range(12):
                ts = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(time.time() - (12 - i) * 60),
                )
                _insert_memory(v1_db, "proj1", "boundary", f"regular_{i}",
                               f"regular boundary {i}", updated_at=ts)

            assert _count_memories(v1_db, "proj1") == 17
            evicted = enforce_category_caps("proj1")

            # Should have evicted some non-pinned, all 5 pinned remain
            con = sqlite3.connect(v1_db)
            cur = con.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM persona_memory WHERE project_id = ? AND is_pinned = 1",
                ("proj1",),
            )
            pinned_remaining = cur.fetchone()[0]
            con.close()
            assert pinned_remaining == 5


# ---------------------------------------------------------------------------
# Total cap tests
# ---------------------------------------------------------------------------

class TestTotalCap:
    """Total cap enforcement across all categories."""

    def test_total_cap_enforced(self, v1_db):
        """Insert more than TOTAL_CAP, verify oldest are evicted."""
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import enforce_total_cap
            from app.ltm_v1_policy import TOTAL_CAP

            # Insert TOTAL_CAP + 10 entries across categories
            for i in range(TOTAL_CAP + 10):
                cat = "fact" if i % 2 == 0 else "preference"
                ts = time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(time.time() - (TOTAL_CAP + 10 - i) * 60),
                )
                _insert_memory(v1_db, "proj1", cat, f"item_{i}",
                               f"value {i}", updated_at=ts)

            assert _count_memories(v1_db, "proj1") == TOTAL_CAP + 10
            evicted = enforce_total_cap("proj1")
            assert evicted == 10
            assert _count_memories(v1_db, "proj1") == TOTAL_CAP

    def test_under_total_cap_no_eviction(self, v1_db):
        """If under TOTAL_CAP, no eviction should occur."""
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import enforce_total_cap

            _insert_memory(v1_db, "proj1", "fact", "name", "Alice")
            _insert_memory(v1_db, "proj1", "preference", "food", "Pizza")

            evicted = enforce_total_cap("proj1")
            assert evicted == 0
            assert _count_memories(v1_db, "proj1") == 2


# ---------------------------------------------------------------------------
# Full maintenance pass
# ---------------------------------------------------------------------------

class TestFullMaintenance:
    """End-to-end maintenance run."""

    def test_run_maintenance_returns_summary(self, v1_db):
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import run_maintenance

            # Insert some entries
            _insert_memory(v1_db, "proj1", "fact", "name", "Alice")
            _insert_memory(v1_db, "proj1", "preference", "food", "Pizza")

            result = run_maintenance("proj1")
            assert "project_id" in result
            assert "expired_by_ttl" in result
            assert "evicted_by_category_cap" in result
            assert "evicted_by_total_cap" in result
            assert "total_cleaned" in result
            assert result["project_id"] == "proj1"


# ---------------------------------------------------------------------------
# LTM upsert dedup integration
# ---------------------------------------------------------------------------

class TestLtmDedup:
    """Test that ltm.py upsert_memory deduplicates near-identical values."""

    def test_dedup_on_upsert(self, v1_db):
        """Inserting near-identical value should reinforce existing, not create new."""
        with patch("app.ltm._get_db_path", return_value=v1_db):
            from app.ltm import upsert_memory

            # Insert first entry
            upsert_memory("proj1", "fact", "job", "User works at Google as software engineer")

            # Insert near-duplicate with different key
            result = upsert_memory("proj1", "fact", "job2", "User works at Google as a software engineer")

            # Should be deduplicated
            assert result.get("deduplicated") is True
            assert _count_memories(v1_db, "proj1") == 1  # Only 1 entry

    def test_different_value_not_deduped(self, v1_db):
        """Inserting clearly different value should create new entry."""
        with patch("app.ltm._get_db_path", return_value=v1_db):
            from app.ltm import upsert_memory

            upsert_memory("proj1", "fact", "name", "User name is Alice")
            upsert_memory("proj1", "fact", "job", "User works at Google")

            assert _count_memories(v1_db, "proj1") == 2  # Both entries exist

    def test_same_key_upserts_normally(self, v1_db):
        """Same key should update normally (not trigger dedup)."""
        with patch("app.ltm._get_db_path", return_value=v1_db):
            from app.ltm import upsert_memory

            upsert_memory("proj1", "fact", "name", "User name is Alice")
            result = upsert_memory("proj1", "fact", "name", "User name is Bob")

            assert result.get("deduplicated") is None  # Normal upsert
            assert _count_memories(v1_db, "proj1") == 1

            # Value should be updated
            con = sqlite3.connect(v1_db)
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            cur.execute("SELECT value FROM persona_memory WHERE project_id = ? AND key = ?",
                        ("proj1", "name"))
            assert cur.fetchone()["value"] == "User name is Bob"
            con.close()


# ---------------------------------------------------------------------------
# Access metadata
# ---------------------------------------------------------------------------

class TestAccessMetadata:
    """Access count and last_access_at are updated on upsert."""

    def test_access_count_increments(self, v1_db):
        """Upserting the same key should increment access_count."""
        with patch("app.ltm._get_db_path", return_value=v1_db):
            from app.ltm import upsert_memory

            upsert_memory("proj1", "fact", "name", "Alice")
            upsert_memory("proj1", "fact", "name", "Alice v2")
            upsert_memory("proj1", "fact", "name", "Alice v3")

            con = sqlite3.connect(v1_db)
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            cur.execute("SELECT access_count, last_access_at FROM persona_memory WHERE key = ?",
                        ("name",))
            row = cur.fetchone()
            con.close()

            assert row["access_count"] >= 3
            assert row["last_access_at"] > 0  # Should be a unix timestamp

    def test_new_entry_has_access_count_1(self, v1_db):
        """New entry should start with access_count=1."""
        with patch("app.ltm._get_db_path", return_value=v1_db):
            from app.ltm import upsert_memory

            upsert_memory("proj1", "fact", "name", "Alice")

            con = sqlite3.connect(v1_db)
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            cur.execute("SELECT access_count FROM persona_memory WHERE key = ?", ("name",))
            row = cur.fetchone()
            con.close()

            assert row["access_count"] == 1


# ---------------------------------------------------------------------------
# Memory stats
# ---------------------------------------------------------------------------

class TestMemoryStats:
    """Stats endpoint returns useful data."""

    def test_stats_structure(self, v1_db):
        with patch("app.ltm_v1_maintenance._get_db_path", return_value=v1_db):
            from app.ltm_v1_maintenance import get_memory_stats

            _insert_memory(v1_db, "proj1", "fact", "name", "Alice")
            _insert_memory(v1_db, "proj1", "preference", "food", "Pizza", is_pinned=1)

            stats = get_memory_stats("proj1")
            assert stats["project_id"] == "proj1"
            assert stats["total"] == 2
            assert stats["total_cap"] == 200
            assert "fact" in stats["by_category"]
            assert "preference" in stats["by_category"]
            assert stats["pinned_count"] == 1
