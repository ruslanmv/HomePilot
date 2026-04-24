"""Unit tests for the Persona Live intent catalog.

The Live Action panel used to expose CHARACTER OUTPUT names (Tease /
Smirk / Blush) as if they were player buttons. The catalog flips that
to intent-driven choices ("Say something playful") and translates each
intent into a renderer key ("smirk") at action time. These tests lock
in:

* every catalog entry maps to a real legacy reaction key
* _default_levels reads from the catalog (no orphaned ids)
* _actions_for_level surfaces the intent labels (not title-cased ids)
* _intent_to_render_key translates intents AND falls through cleanly
* explicit_only intents stay in the level-5 tier
* legacy action ids still resolve so old sessions don't break
"""
from __future__ import annotations

import pytest

from app.interactive.routes.persona_live import (
    _ACTION_CATEGORY_MAP,
    _INTENT_CATALOG,
    _actions_for_level,
    _apply_emotion_delta,
    _default_levels,
    _intent_to_render_key,
    _normalize_emotion,
)
from app.interactive.playback.edit_recipes import ACTION_RECIPES


# ── Catalog integrity ───────────────────────────────────────────────────────

def test_every_catalog_entry_has_required_fields():
    required = {"label", "category", "reaction_intent", "delta", "level"}
    for action_id, entry in _INTENT_CATALOG.items():
        missing = required - entry.keys()
        assert not missing, f"{action_id} missing fields: {missing}"


def test_every_reaction_intent_is_a_real_recipe_key():
    """If a reaction_intent doesn't exist in ACTION_RECIPES, the action
    endpoint will fall through to default_recipe and the player will
    see a generic edit instead of the matching reaction."""
    for action_id, entry in _INTENT_CATALOG.items():
        reaction = entry["reaction_intent"]
        assert reaction in ACTION_RECIPES, (
            f"intent {action_id} → {reaction} not in ACTION_RECIPES"
        )


def test_category_map_covers_all_intent_ids():
    for action_id in _INTENT_CATALOG:
        assert action_id in _ACTION_CATEGORY_MAP


def test_legacy_action_ids_still_in_category_map():
    """Old sessions / programmatic API users key off the legacy ids."""
    legacy = {"tease", "smirk", "blush", "ahegao", "dance", "closer_pose",
              "turn_around", "outfit_change", "move_to_beach",
              "make_it_rain", "zoom_out"}
    for aid in legacy:
        assert aid in _ACTION_CATEGORY_MAP


# ── _intent_to_render_key ───────────────────────────────────────────────────

def test_intent_translates_to_renderer_key():
    assert _intent_to_render_key("compliment") == "blush"
    assert _intent_to_render_key("say_playful") == "smirk"
    assert _intent_to_render_key("get_closer") == "closer_pose"
    assert _intent_to_render_key("suggest_outfit") == "outfit_change"
    assert _intent_to_render_key("change_location") == "move_to_beach"


def test_intent_translation_falls_through_for_legacy_ids():
    """Legacy ids must pass through unchanged so existing sessions work."""
    for legacy in ("tease", "smirk", "blush", "closer_pose", "outfit_change"):
        assert _intent_to_render_key(legacy) == legacy


def test_intent_translation_handles_empty_and_unknown():
    assert _intent_to_render_key("") == ""
    assert _intent_to_render_key("not_a_real_intent") == "not_a_real_intent"


# ── _default_levels ─────────────────────────────────────────────────────────

def test_default_levels_use_intent_ids_at_every_level():
    levels = _default_levels(vibe="", allow_explicit=True)
    flat = [aid for block in levels for aid in block.get("actions", [])]
    # Every action surfaced by the level ladder must be a known intent
    for aid in flat:
        assert aid in _INTENT_CATALOG, f"{aid} not in intent catalog"


def test_default_levels_have_no_legacy_character_state_buttons():
    """Level 1 must NOT expose Tease / Smirk / Blush as buttons."""
    levels = _default_levels(vibe="", allow_explicit=False)
    level_1 = next(b for b in levels if b["level"] == 1)
    # The smoking-gun set the user complained about
    forbidden = {"tease", "smirk", "blush", "dance", "closer_pose",
                 "turn_around", "outfit_change"}
    assert not (set(level_1["actions"]) & forbidden), (
        f"Level 1 still exposes character outputs: "
        f"{set(level_1['actions']) & forbidden}"
    )


def test_explicit_only_intents_stay_at_tier_5():
    levels = _default_levels(vibe="explicit boudoir", allow_explicit=True)
    level_5 = next(b for b in levels if b["level"] == 5)
    assert "lean_in" in level_5["actions"]
    # And a non-explicit run must NOT include lean_in
    levels_safe = _default_levels(vibe="explicit boudoir", allow_explicit=False)
    level_5_safe = next(b for b in levels_safe if b["level"] == 5)
    assert "lean_in" not in level_5_safe["actions"]


# ── _actions_for_level ──────────────────────────────────────────────────────

def test_actions_for_level_returns_intent_labels():
    levels = _default_levels(vibe="", allow_explicit=False)
    available = _actions_for_level(level=1, levels=levels)["available"]
    labels = {a["label"] for a in available}
    # The shape the user asked for
    assert "Say something playful" in labels
    assert "Compliment her" in labels
    assert "Ask about her day" in labels
    assert "Stay quiet and listen" in labels


def test_actions_for_level_includes_descriptions():
    levels = _default_levels(vibe="", allow_explicit=False)
    available = _actions_for_level(level=1, levels=levels)["available"]
    for item in available:
        assert item.get("description"), f"{item['id']} missing description"


def test_locked_actions_carry_unlock_level():
    levels = _default_levels(vibe="", allow_explicit=False)
    locked = _actions_for_level(level=1, levels=levels)["locked"]
    assert locked  # there must be locked items at level 1
    for item in locked:
        assert item["unlock_level"] >= 2


# ── Emotion deltas ──────────────────────────────────────────────────────────

def test_compliment_increases_affection_more_than_playfulness():
    base = _normalize_emotion(None)
    out = _apply_emotion_delta(base, action_id="compliment", scene_category="private")
    assert out["affection"] > base["affection"]
    # compliment delta is {affection: 3, comfort: 1, playfulness: 1}
    assert out["affection"] - base["affection"] == 3
    assert out["playfulness"] - base["playfulness"] == 1


def test_say_playful_increases_playfulness_most():
    base = _normalize_emotion(None)
    out = _apply_emotion_delta(base, action_id="say_playful", scene_category="private")
    assert out["playfulness"] - base["playfulness"] == 3
    assert out["affection"] - base["affection"] == 1


def test_trust_is_derived_alias_of_affection_plus_comfort():
    """Legacy callers reading emotion.trust must keep getting a value
    that maps to (affection + comfort) // 2."""
    base = _normalize_emotion(None)
    out = _apply_emotion_delta(base, action_id="compliment", scene_category="private")
    assert out["trust"] == (out["affection"] + out["comfort"]) // 2


def test_public_scene_clamps_intimacy_intents():
    base = _normalize_emotion({"trust": 50, "intensity": 30,
                               "affection": 50, "comfort": 50, "playfulness": 30})
    # Same intent in a private scene should grow intimacy stats…
    private = _apply_emotion_delta(base, action_id="get_closer", scene_category="private")
    assert private["affection"] > base["affection"]
    # …but in a public scene should NOT grow them.
    public = _apply_emotion_delta(base, action_id="get_closer", scene_category="public")
    assert public["affection"] <= base["affection"]
    assert public["comfort"] <= base["comfort"]


def test_legacy_action_ids_still_apply_deltas():
    """Old sessions firing raw 'tease' must still see emotional change."""
    base = _normalize_emotion(None)
    out = _apply_emotion_delta(base, action_id="tease", scene_category="private")
    assert out["playfulness"] > base["playfulness"]


def test_normalize_emotion_back_fills_hidden_stats_for_old_sessions():
    """Sessions persisted before the new fields existed must get
    sensible affection / comfort / playfulness defaults derived from
    trust, not zeros that would tank progression."""
    out = _normalize_emotion({"trust": 50, "intensity": 30, "mood": "warm"})
    assert "affection" in out
    assert "comfort" in out
    assert "playfulness" in out
    # affection ≈ trust - 15 (with floor 0); comfort ≈ trust + 15 (with cap 100)
    assert out["affection"] == 35
    assert out["comfort"] == 65
