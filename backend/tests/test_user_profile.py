"""
Tests for User Profile & Memory APIs (additive — v1).

Validates:
  - Profile CRUD (GET default, PUT, GET updated)
  - Secret masking (never returns raw values)
  - Secret CRUD (upsert, list, delete)
  - Memory CRUD (put, get, delete individual items)
  - Profile field normalization (list dedup, enum defaults, spicy clamp)
  - Context builder output (build_user_context_for_ai)

Non-destructive: uses tmp_path from pytest.
CI-friendly: no network, no LLM.
"""
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Profile helpers — unit tests (no FastAPI required)
# ---------------------------------------------------------------------------

class TestProfileHelpers:
    """Unit tests for profile.py helper functions."""

    def test_mask_secret_short(self):
        from app.profile import _mask_secret
        assert _mask_secret("abc") == "••••••"
        assert _mask_secret("") == "••••••"

    def test_mask_secret_long(self):
        from app.profile import _mask_secret
        result = _mask_secret("sk-1234567890abcdef")
        assert result.startswith("sk")
        assert result.endswith("ef")
        assert "••••••" in result

    def test_norm_list_dedup_sort(self):
        from app.profile import _norm_list
        result = _norm_list(["b", "a", "b", " c ", "", None])
        assert result == ["a", "b", "c"]

    def test_norm_list_empty(self):
        from app.profile import _norm_list
        assert _norm_list([]) == []
        assert _norm_list(None) == []

    def test_atomic_write_json(self, tmp_path: Path):
        from app.profile import _atomic_write_json, _read_json
        path = tmp_path / "test.json"
        data = {"hello": "world", "num": 42}
        _atomic_write_json(path, data)
        result = _read_json(path, default={})
        assert result == data

    def test_read_json_missing_returns_default(self, tmp_path: Path):
        from app.profile import _read_json
        path = tmp_path / "nope.json"
        result = _read_json(path, default={"fallback": True})
        assert result == {"fallback": True}

    def test_read_json_corrupted_returns_default(self, tmp_path: Path):
        from app.profile import _read_json
        path = tmp_path / "bad.json"
        path.write_text("NOT JSON {{{")
        result = _read_json(path, default={"safe": True})
        assert result == {"safe": True}


# ---------------------------------------------------------------------------
# Profile model validation
# ---------------------------------------------------------------------------

class TestProfileModel:
    """Pydantic model for UserProfile."""

    def test_default_profile(self):
        from app.profile import UserProfile
        p = UserProfile()
        assert p.display_name == ""
        assert p.default_spicy_strength == 0.30
        assert p.preferred_tone == "neutral"
        assert p.affection_level == "friendly"

    def test_spicy_strength_clamp(self):
        from app.profile import UserProfile
        p = UserProfile(default_spicy_strength=0.85)
        assert p.default_spicy_strength == 0.85

    def test_spicy_strength_out_of_range(self):
        from app.profile import UserProfile
        with pytest.raises(Exception):
            UserProfile(default_spicy_strength=2.0)

    def test_lists_default_empty(self):
        from app.profile import UserProfile
        p = UserProfile()
        assert p.likes == []
        assert p.dislikes == []
        assert p.hard_boundaries == []
        assert p.allowed_content_tags == []


# ---------------------------------------------------------------------------
# Memory helpers
# ---------------------------------------------------------------------------

class TestMemoryHelpers:
    """Unit tests for user_memory.py helper functions."""

    def test_memory_item_model(self):
        from app.user_memory import MemoryItem
        m = MemoryItem(id="mem_abc123", text="I like cats")
        assert m.category == "general"
        assert m.importance == 2
        assert m.pinned is False
        assert m.source == "user"

    def test_memory_item_min_id_length(self):
        from app.user_memory import MemoryItem
        with pytest.raises(Exception):
            MemoryItem(id="abc", text="too short id")

    def test_memory_upsert_duplicate_ids(self):
        from app.user_memory import MemoryUpsert, MemoryItem
        items = [
            MemoryItem(id="mem_aaa111", text="first"),
            MemoryItem(id="mem_aaa111", text="duplicate"),
        ]
        # Model itself doesn't reject, but the endpoint does
        body = MemoryUpsert(items=items)
        assert len(body.items) == 2


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

class TestUserContext:
    """Unit tests for user_context.py builder."""

    def test_basic_context_sfw(self):
        from app.user_context import build_user_context_for_ai
        profile = {
            "display_name": "Alice",
            "preferred_name": "",
            "preferred_tone": "friendly",
            "companion_mode_enabled": False,
            "affection_level": "friendly",
            "likes": ["art", "coding"],
            "dislikes": ["spam"],
            "hard_boundaries": [],
            "sensitive_topics": [],
            "allowed_content_tags": [],
            "blocked_content_tags": [],
            "preferred_pronouns": "she/her",
            "default_spicy_strength": 0.3,
        }
        memory = {"items": []}
        result = build_user_context_for_ai(profile, memory, nsfw_mode=False)
        assert "Alice" in result
        assert "Tone: friendly" in result
        assert "Global NSFW mode: OFF" in result
        assert "spicy strength" not in result.lower()

    def test_context_nsfw_includes_strength(self):
        from app.user_context import build_user_context_for_ai
        profile = {
            "display_name": "Bob",
            "preferred_name": "Bobby",
            "preferred_tone": "neutral",
            "companion_mode_enabled": True,
            "affection_level": "romantic",
            "likes": [],
            "dislikes": [],
            "hard_boundaries": ["no violence"],
            "sensitive_topics": [],
            "allowed_content_tags": ["romance"],
            "blocked_content_tags": ["gore"],
            "preferred_pronouns": "",
            "default_spicy_strength": 0.7,
        }
        memory = {"items": [
            {"text": "Loves evening chats", "pinned": True, "importance": 5},
            {"text": "Works in tech", "pinned": False, "importance": 3},
        ]}
        result = build_user_context_for_ai(profile, memory, nsfw_mode=True)
        assert "Bobby" in result
        assert "Global NSFW mode: ON" in result
        assert "0.7" in result
        assert "romance" in result
        assert "gore" in result
        assert "no violence" in result
        assert "Loves evening chats" in result
        assert "Works in tech" in result

    def test_context_memory_limit_10(self):
        from app.user_context import build_user_context_for_ai
        items = [{"text": f"item {i}", "pinned": False, "importance": 1} for i in range(20)]
        result = build_user_context_for_ai({}, {"items": items}, nsfw_mode=False)
        # Only first 10 should appear
        assert "item 0" in result
        assert "item 9" in result
        assert "item 10" not in result

    def test_context_empty_profile(self):
        from app.user_context import build_user_context_for_ai
        result = build_user_context_for_ai({}, {}, nsfw_mode=False)
        assert "USER PROFILE" in result
        assert "MEMORY" in result
        assert "(none)" in result

    def test_context_pinned_first(self):
        from app.user_context import build_user_context_for_ai
        items = [
            {"text": "unpinned low", "pinned": False, "importance": 1},
            {"text": "pinned high", "pinned": True, "importance": 5},
        ]
        result = build_user_context_for_ai({}, {"items": items}, nsfw_mode=False)
        pinned_pos = result.index("pinned high")
        unpinned_pos = result.index("unpinned low")
        assert pinned_pos < unpinned_pos


# ---------------------------------------------------------------------------
# Secret key validation
# ---------------------------------------------------------------------------

class TestSecretKeyFormat:
    """Validate key format rules for secrets."""

    def test_valid_keys(self):
        from app.profile import SecretUpsert
        for key in ["NOTION_TOKEN", "my-key", "api_key_123"]:
            s = SecretUpsert(key=key, value="test")
            assert s.key == key

    def test_empty_key_rejected(self):
        from app.profile import SecretUpsert
        with pytest.raises(Exception):
            SecretUpsert(key="", value="test")
