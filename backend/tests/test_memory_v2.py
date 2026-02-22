"""
Tests for Memory V2 (brain-inspired) engine — additive.

Validates:
  - Math helpers (activation decay, reinforcement, clamping)
  - Stable hashing (deterministic across calls)
  - Keyword scoring (token overlap relevance)
  - "Remember this" detection (pinned memory)
  - Clean value sanitization
  - V2Config defaults
  - MemoryV2Engine ingest/consolidate/prune/retrieve lifecycle
  - Schema extension safety (ensure_v2_columns idempotent)

Non-destructive: uses tmp_path from pytest for SQLite isolation.
CI-friendly: no network, no LLM.
"""
import math
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------

class TestMathHelpers:
    """Unit tests for activation, reinforcement, clamping."""

    def test_clamp_within_range(self):
        from app.memory_v2 import _clamp
        assert _clamp(0.5, 0.0, 1.0) == 0.5

    def test_clamp_below(self):
        from app.memory_v2 import _clamp
        assert _clamp(-0.5, 0.0, 1.0) == 0.0

    def test_clamp_above(self):
        from app.memory_v2 import _clamp
        assert _clamp(1.5, 0.0, 1.0) == 1.0

    def test_activation_no_decay_at_zero_dt(self):
        from app.memory_v2 import _activation, _now
        # If last access is right now, activation = strength
        act = _activation(0.8, _now(), tau=3600.0)
        assert abs(act - 0.8) < 0.01

    def test_activation_decays_over_time(self):
        from app.memory_v2 import _activation, _now
        past = _now() - 7200  # 2 hours ago
        tau = 3600.0  # 1 hour
        act = _activation(1.0, past, tau)
        expected = math.exp(-2.0)  # e^{-2h/1h}
        assert abs(act - expected) < 0.01

    def test_activation_zero_strength(self):
        from app.memory_v2 import _activation, _now
        assert _activation(0.0, _now(), tau=3600.0) == 0.0

    def test_reinforce_increases_strength(self):
        from app.memory_v2 import _reinforce
        s = _reinforce(0.5, eta=0.25)
        assert s > 0.5
        assert s < 1.0

    def test_reinforce_already_max(self):
        from app.memory_v2 import _reinforce
        s = _reinforce(1.0, eta=0.25)
        assert abs(s - 1.0) < 0.001

    def test_reinforce_from_zero(self):
        from app.memory_v2 import _reinforce
        s = _reinforce(0.0, eta=0.25)
        assert s > 0.0


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

class TestStableHash:
    """Verify deterministic hashing (not Python's hash())."""

    def test_stable_hash_deterministic(self):
        from app.memory_v2 import _stable_hash
        h1 = _stable_hash("hello world")
        h2 = _stable_hash("hello world")
        assert h1 == h2

    def test_stable_hash_different_inputs(self):
        from app.memory_v2 import _stable_hash
        h1 = _stable_hash("hello")
        h2 = _stable_hash("world")
        assert h1 != h2

    def test_stable_hash_length(self):
        from app.memory_v2 import _stable_hash
        assert len(_stable_hash("test")) == 12


# ---------------------------------------------------------------------------
# Keyword scoring
# ---------------------------------------------------------------------------

class TestKeywordScore:
    """Token-overlap relevance scoring."""

    def test_identical_text(self):
        from app.memory_v2 import _keyword_score
        score = _keyword_score("hello world test", "hello world test")
        assert score > 0.5

    def test_no_overlap(self):
        from app.memory_v2 import _keyword_score
        score = _keyword_score("cats dogs", "airplanes trains")
        assert score == 0.0

    def test_empty_query(self):
        from app.memory_v2 import _keyword_score
        assert _keyword_score("", "some text") == 0.0

    def test_empty_text(self):
        from app.memory_v2 import _keyword_score
        assert _keyword_score("some query", "") == 0.0

    def test_partial_overlap(self):
        from app.memory_v2 import _keyword_score
        score = _keyword_score("coffee morning routine", "love morning coffee")
        assert score > 0.0


# ---------------------------------------------------------------------------
# Remember-this detection
# ---------------------------------------------------------------------------

class TestRememberDetection:
    """Test the 'remember this' regex pattern."""

    def test_remember_this(self):
        from app.memory_v2 import _RE_REMEMBER
        assert _RE_REMEMBER.search("please remember this about me")

    def test_dont_forget(self):
        from app.memory_v2 import _RE_REMEMBER
        assert _RE_REMEMBER.search("don't forget that I have a cat")

    def test_no_match(self):
        from app.memory_v2 import _RE_REMEMBER
        assert _RE_REMEMBER.search("I like coffee") is None


# ---------------------------------------------------------------------------
# Clean value
# ---------------------------------------------------------------------------

class TestCleanValue:
    """Value sanitization."""

    def test_trims_whitespace(self):
        from app.memory_v2 import _clean_value
        assert _clean_value("  hello  ", 100) == "hello"

    def test_collapses_spaces(self):
        from app.memory_v2 import _clean_value
        assert _clean_value("hello   world", 100) == "hello world"

    def test_truncates(self):
        from app.memory_v2 import _clean_value
        result = _clean_value("a" * 200, 50)
        assert len(result) <= 52  # 49 chars + "..."
        assert result.endswith("...")

    def test_empty(self):
        from app.memory_v2 import _clean_value
        assert _clean_value("", 100) == ""


# ---------------------------------------------------------------------------
# V2Config defaults
# ---------------------------------------------------------------------------

class TestV2Config:
    """Verify configuration defaults."""

    def test_defaults(self):
        from app.memory_v2 import V2Config
        cfg = V2Config()
        assert cfg.tau_working == 6 * 3600
        assert cfg.tau_semantic == 30 * 24 * 3600
        assert cfg.eta_user_confirmed == 0.25
        assert cfg.eta_inferred == 0.05
        assert cfg.consolidate_min_repeats == 2
        assert cfg.top_pinned == 4
        assert cfg.top_semantic == 8


# ---------------------------------------------------------------------------
# Engine lifecycle (with real SQLite in tmp_path)
# ---------------------------------------------------------------------------

@pytest.fixture
def v2_db(tmp_path):
    """Set up an isolated SQLite DB with persona_memory table + V2 columns."""
    db_path = str(tmp_path / "test.db")

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

    # Patch _get_db_path to return our test DB
    with patch("app.memory_v2._get_db_path", return_value=db_path):
        # Run V2 column migration
        from app.memory_v2 import ensure_v2_columns
        ensure_v2_columns()
        yield db_path


class TestEnsureV2Columns:
    """Schema extension is safe and idempotent."""

    def test_adds_columns(self, v2_db):
        con = sqlite3.connect(v2_db)
        cur = con.cursor()
        cur.execute("PRAGMA table_info(persona_memory)")
        cols = {row[1] for row in cur.fetchall()}
        con.close()

        assert "mem_type" in cols
        assert "strength" in cols
        assert "importance" in cols
        assert "last_access_at" in cols
        assert "access_count" in cols
        assert "last_seen_at" in cols

    def test_idempotent(self, v2_db):
        """Running ensure_v2_columns twice should not error."""
        with patch("app.memory_v2._get_db_path", return_value=v2_db):
            from app.memory_v2 import ensure_v2_columns
            ensure_v2_columns()  # Second call — should be safe


class TestMemoryV2Engine:
    """End-to-end engine tests with isolated DB."""

    def test_ingest_working_trace(self, v2_db):
        with patch("app.memory_v2._get_db_path", return_value=v2_db):
            from app.memory_v2 import MemoryV2Engine, _select_memories
            engine = MemoryV2Engine()
            engine.ingest_user_text("proj1", "I enjoy hiking on weekends")

            mem = _select_memories("proj1")
            working = [m for m in mem if m.get("mem_type") == "W"]
            assert len(working) >= 1
            assert any("hiking" in (m.get("value") or "") for m in working)

    def test_ingest_pinned_remember(self, v2_db):
        with patch("app.memory_v2._get_db_path", return_value=v2_db):
            from app.memory_v2 import MemoryV2Engine, _select_memories
            engine = MemoryV2Engine()
            engine.ingest_user_text("proj1", "Please remember this: I am allergic to peanuts")

            mem = _select_memories("proj1")
            pinned = [m for m in mem if m.get("mem_type") == "P"]
            assert len(pinned) >= 1
            assert any("peanuts" in (m.get("value") or "") for m in pinned)

    def test_ingest_short_text_ignored(self, v2_db):
        with patch("app.memory_v2._get_db_path", return_value=v2_db):
            from app.memory_v2 import MemoryV2Engine, _select_memories
            engine = MemoryV2Engine()
            engine.ingest_user_text("proj1", "hi")

            mem = _select_memories("proj1")
            assert len(mem) == 0

    def test_build_context_empty(self, v2_db):
        with patch("app.memory_v2._get_db_path", return_value=v2_db):
            from app.memory_v2 import MemoryV2Engine
            engine = MemoryV2Engine()
            ctx = engine.build_context("proj_empty", "hello")
            assert ctx == ""

    def test_build_context_with_pinned(self, v2_db):
        with patch("app.memory_v2._get_db_path", return_value=v2_db):
            from app.memory_v2 import MemoryV2Engine
            engine = MemoryV2Engine()
            engine.ingest_user_text("proj2", "Remember this: my cat is named Luna")

            ctx = engine.build_context("proj2", "tell me about pets")
            assert "PINNED" in ctx
            assert "Luna" in ctx

    def test_build_context_with_working(self, v2_db):
        with patch("app.memory_v2._get_db_path", return_value=v2_db):
            from app.memory_v2 import MemoryV2Engine
            engine = MemoryV2Engine()
            engine.ingest_user_text("proj3", "I went to the store today and bought groceries")

            ctx = engine.build_context("proj3", "what did you do today")
            assert "WORKING" in ctx
            assert "groceries" in ctx

    def test_prune_removes_low_activation(self, v2_db):
        with patch("app.memory_v2._get_db_path", return_value=v2_db):
            from app.memory_v2 import MemoryV2Engine, _upsert_memory, _select_memories, _now
            engine = MemoryV2Engine()

            # Insert a semantic memory with very old access time and low importance
            _upsert_memory(
                project_id="proj4",
                category="fact",
                key="old_fact",
                value="something very old and unimportant",
                mem_type="S",
                source_type="inferred",
                confidence=0.4,
                strength=0.01,  # Very weak
                importance=0.1,  # Very low
                seen_now=False,
            )
            # Force last_access_at to distant past
            con = sqlite3.connect(v2_db)
            con.execute(
                "UPDATE persona_memory SET last_access_at = ?, last_seen_at = ? WHERE key = ?",
                (_now() - 365 * 24 * 3600, _now() - 365 * 24 * 3600, "old_fact"),
            )
            con.commit()
            con.close()

            mem_before = _select_memories("proj4")
            assert len(mem_before) == 1

            engine.prune("proj4")

            mem_after = _select_memories("proj4")
            assert len(mem_after) == 0  # Pruned!

    def test_prune_preserves_pinned(self, v2_db):
        with patch("app.memory_v2._get_db_path", return_value=v2_db):
            from app.memory_v2 import MemoryV2Engine, _upsert_memory, _select_memories, _now
            engine = MemoryV2Engine()

            # Insert a pinned memory with old access time
            _upsert_memory(
                project_id="proj5",
                category="user",
                key="pinned_old",
                value="pinned memory should never be pruned",
                mem_type="P",
                source_type="user",
                confidence=1.0,
                strength=0.01,
                importance=0.1,
                seen_now=False,
            )
            con = sqlite3.connect(v2_db)
            con.execute(
                "UPDATE persona_memory SET last_access_at = ?, last_seen_at = ? WHERE key = ?",
                (_now() - 365 * 24 * 3600, _now() - 365 * 24 * 3600, "pinned_old"),
            )
            con.commit()
            con.close()

            engine.prune("proj5")

            mem = _select_memories("proj5")
            assert len(mem) == 1  # Pinned survives!
            assert mem[0]["mem_type"] == "P"

    def test_working_trim_keeps_latest_25(self, v2_db):
        with patch("app.memory_v2._get_db_path", return_value=v2_db):
            from app.memory_v2 import MemoryV2Engine, _upsert_memory, _select_memories
            engine = MemoryV2Engine()

            # Insert 30 working items
            for i in range(30):
                _upsert_memory(
                    project_id="proj6",
                    category="working",
                    key=f"w:item_{i}",
                    value=f"working item number {i}",
                    mem_type="W",
                    source_type="user",
                    confidence=0.5,
                    strength=0.5,
                    importance=0.25,
                )

            engine.prune("proj6")

            mem = _select_memories("proj6")
            working = [m for m in mem if m.get("mem_type") == "W"]
            assert len(working) <= 25

    def test_v1_entries_coexist(self, v2_db):
        """V1 entries (no mem_type set) coexist safely with V2 entries."""
        with patch("app.memory_v2._get_db_path", return_value=v2_db):
            from app.memory_v2 import MemoryV2Engine, _select_memories

            # Insert a V1-style entry (mem_type defaults to 'S')
            con = sqlite3.connect(v2_db)
            con.execute(
                """INSERT INTO persona_memory
                   (project_id, category, key, value, confidence, source_type)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("proj7", "fact", "name", "User name is Alice", 0.9, "inferred"),
            )
            con.commit()
            con.close()

            engine = MemoryV2Engine()
            engine.ingest_user_text("proj7", "Remember this: I work at Google")

            mem = _select_memories("proj7")
            assert len(mem) == 2

            # V1 entry treated as Semantic
            v1_entry = [m for m in mem if m["key"] == "name"][0]
            assert v1_entry.get("mem_type") == "S"  # default

            # V2 pinned entry
            v2_entry = [m for m in mem if m.get("mem_type") == "P"]
            assert len(v2_entry) == 1


class TestSingleton:
    """Singleton pattern works."""

    def test_get_memory_v2_returns_same_instance(self):
        from app.memory_v2 import get_memory_v2, _engine
        import app.memory_v2 as mod
        mod._engine = None  # Reset
        e1 = get_memory_v2()
        e2 = get_memory_v2()
        assert e1 is e2
        mod._engine = None  # Clean up
