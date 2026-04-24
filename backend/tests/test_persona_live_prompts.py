"""Unit tests for the Persona Live prompt-vocabulary builder.

The module is pure — no I/O, no LLM calls — so these tests lock in:
* ``effective_tier`` clamping (explicit requires allow_explicit)
* ``compose_system_prompt`` tier-aware clauses
* ``compose_image_prompt`` ladder selection + environment gating
* ``negative_prompt_for`` tightening at safe tier

No fixtures, no DB, no network.
"""
from __future__ import annotations

import pytest

from app.interactive.playback.persona_live_prompts import (
    BASE_NEGATIVE,
    EMOTIONAL_LADDER,
    ENVIRONMENT_LIB,
    EXPRESSION_LADDER,
    OUTFIT_LADDER,
    POSE_LADDER,
    PROGRESSION_LIBRARY,
    SAFE_NEGATIVE_EXTRA,
    TIER_STYLE_TAGS,
    compose_image_prompt,
    compose_system_prompt,
    effective_tier,
    negative_prompt_for,
)


# ── effective_tier ──────────────────────────────────────────────────────────

def test_effective_tier_clamps_explicit_when_persona_disallows():
    assert effective_tier("explicit", allow_explicit=False) == "suggestive"


def test_effective_tier_passes_explicit_when_persona_allows():
    assert effective_tier("explicit", allow_explicit=True) == "explicit"


def test_effective_tier_passes_suggestive_unchanged():
    assert effective_tier("suggestive", allow_explicit=False) == "suggestive"
    assert effective_tier("suggestive", allow_explicit=True) == "suggestive"


def test_effective_tier_passes_safe_unchanged():
    assert effective_tier("safe", allow_explicit=False) == "safe"
    assert effective_tier("safe", allow_explicit=True) == "safe"


def test_effective_tier_unknown_falls_back_to_safe():
    assert effective_tier("garbage", allow_explicit=True) == "safe"  # type: ignore[arg-type]
    assert effective_tier("", allow_explicit=True) == "safe"         # type: ignore[arg-type]


# ── compose_system_prompt ───────────────────────────────────────────────────

def test_system_prompt_safe_bans_nudity_vocabulary():
    out = compose_system_prompt(tier="safe", allow_explicit=False)
    lowered = out.lower()
    assert "strictly safe-for-work" in lowered
    assert "no nudity" in lowered
    assert "boudoir" not in lowered
    assert "lingerie" not in lowered


def test_system_prompt_suggestive_allows_flirty_not_explicit():
    out = compose_system_prompt(tier="suggestive", allow_explicit=False)
    lowered = out.lower()
    assert "flirty" in lowered or "fan-service" in lowered
    # Suggestive must NOT carry explicit-tier boudoir tokens
    assert "lingerie" not in lowered
    assert "boudoir" not in lowered or "boudoir-lite" in lowered


def test_system_prompt_explicit_requires_allow_explicit():
    """If the persona disallows explicit, the prompt must downgrade to
    suggestive even if the caller requested explicit."""
    out_disallowed = compose_system_prompt(tier="explicit", allow_explicit=False)
    assert "boudoir photography" not in out_disallowed.lower()

    out_allowed = compose_system_prompt(tier="explicit", allow_explicit=True)
    lowered = out_allowed.lower()
    assert "mature (gated)" in lowered
    assert "boudoir" in lowered
    # Even the explicit tier must forbid hardcore / minor-suggestive.
    assert "hardcore" in lowered  # the prompt explicitly names it as BANNED
    assert "non-consensual" in lowered


def test_system_prompt_includes_persona_style_when_provided():
    out = compose_system_prompt(
        tier="suggestive",
        allow_explicit=True,
        persona_archetype="flirty companion",
        persona_style_hint="playful dominant",
    )
    lowered = out.lower()
    assert "flirty companion" in lowered
    assert "playful dominant" in lowered


def test_system_prompt_mentions_progression():
    """Emotional progression guidance is always present — it's what
    keeps scenes from collapsing onto the same beat every turn."""
    for tier in ("safe", "suggestive", "explicit"):
        out = compose_system_prompt(tier=tier, allow_explicit=True)  # type: ignore[arg-type]
        assert "progression" in out.lower()


# ── compose_image_prompt ────────────────────────────────────────────────────

def test_image_prompt_safe_contains_no_explicit_tokens():
    out = compose_image_prompt(
        base_subject="Mia, girl next door",
        axis="outfit",
        tier="safe",
        allow_explicit=True,  # persona allows, but tier says safe
        emotional_level=3,
        environment_key="bedroom",
    )
    lowered = out.lower()
    # Safe tier uses only safe-tagged ladder rows
    assert "lingerie" not in lowered
    assert "silk robe" not in lowered
    assert "breathless" not in lowered
    assert "boudoir" not in lowered
    # Style tail MUST be the safe one
    assert TIER_STYLE_TAGS["safe"] in out


def test_image_prompt_explicit_can_surface_mature_vocabulary():
    out = compose_image_prompt(
        base_subject="Mia",
        axis="outfit",
        tier="explicit",
        allow_explicit=True,
        emotional_level=4,
        ladder_index=8,
        environment_key="boudoir",
    )
    lowered = out.lower()
    assert "lingerie" in lowered or "silk robe" in lowered
    assert "boudoir" in lowered
    # Style tail MUST be the explicit one
    assert "boudoir photography" in lowered or "fan service" in lowered


def test_image_prompt_environment_gated_by_tier():
    """Boudoir is explicit-tier; asking for it at safe must silently drop it."""
    out = compose_image_prompt(
        base_subject="Mia",
        axis="outfit",
        tier="safe",
        allow_explicit=False,
        environment_key="boudoir",
    )
    assert "boudoir" not in out.lower()


def test_image_prompt_ladder_index_clamped_to_tier_bound():
    """ladder_index=8 (explicit-only row) at suggestive tier should
    land on the last suggestive-eligible row, not explode or leak."""
    out = compose_image_prompt(
        base_subject="Mia",
        axis="outfit",
        tier="suggestive",
        allow_explicit=False,
        ladder_index=99,
    )
    assert out  # non-empty
    assert "lingerie" not in out.lower()


def test_image_prompt_always_ends_with_tier_style_tag():
    for tier in ("safe", "suggestive", "explicit"):
        out = compose_image_prompt(
            base_subject="Mia",
            axis="expression",
            tier=tier,  # type: ignore[arg-type]
            allow_explicit=True,
            emotional_level=1,
        )
        assert out.endswith(TIER_STYLE_TAGS[tier])


def test_image_prompt_passes_through_extra_fragments():
    out = compose_image_prompt(
        base_subject="Mia",
        axis="expression",
        tier="safe",
        allow_explicit=False,
        emotional_level=1,
        extra_fragments=["with persona_id=abc123", "scene_change=beach"],
    )
    assert "persona_id=abc123" in out
    assert "scene_change=beach" in out


# ── negative_prompt_for ─────────────────────────────────────────────────────

def test_negative_prompt_safe_includes_extra_nsfw_guard():
    neg = negative_prompt_for("safe", allow_explicit=False)
    assert BASE_NEGATIVE in neg
    assert SAFE_NEGATIVE_EXTRA in neg


def test_negative_prompt_suggestive_drops_safe_only_guard():
    neg = negative_prompt_for("suggestive", allow_explicit=False)
    assert BASE_NEGATIVE in neg
    assert SAFE_NEGATIVE_EXTRA not in neg


def test_negative_prompt_explicit_drops_safe_only_guard():
    neg = negative_prompt_for("explicit", allow_explicit=True)
    assert BASE_NEGATIVE in neg
    assert "nsfw" not in neg


# ── PROGRESSION_LIBRARY sanity ──────────────────────────────────────────────

def test_progression_library_levels_are_ordered():
    levels = sorted(PROGRESSION_LIBRARY.keys())
    assert levels == [1, 2, 3, 4, 5]


def test_progression_library_level_5_marked_explicit():
    level_5 = PROGRESSION_LIBRARY[5]
    # Level 5 is the gated boudoir tier — description must flag it
    assert "allow_explicit" in level_5["description"].lower()
    assert "lingerie_tasteful" in level_5["outfits"]


def test_ladders_all_share_tier_vocabulary():
    """Every ladder row must carry one of the three canonical tiers."""
    for ladder in (EXPRESSION_LADDER, POSE_LADDER, OUTFIT_LADDER):
        for _text, tier in ladder:
            assert tier in ("safe", "suggestive", "explicit")
    for _key, (_text, tier) in ENVIRONMENT_LIB.items():
        assert tier in ("safe", "suggestive", "explicit")


def test_emotional_ladder_has_five_levels():
    assert len(EMOTIONAL_LADDER) == 5
