"""
Batch 5/8 — script + scene + asset adapter tests.

Covers:
  - Tone application (formal/casual substitutions)
  - Duration estimation
  - Safety rewriter redactions for universal + profile-scoped terms
  - Generator fills narration/title/prompts, idempotent on re-run
  - Storyboard planner attaches shot + interaction_layout per node
  - Scene-type-specific layout decisions
  - Asset library register/query + mood-based ranking
  - Attach-asset + register-segment idempotency
"""
from __future__ import annotations

from app.interactive.assets.library import (
    query_library,
    register_library_asset,
    seed_library_defaults,
)
from app.interactive.assets.music import pick_music_track
from app.interactive.assets.voice import synthesize_voice_clip
from app.interactive.branching import build_graph, validate_graph
from app.interactive.config import InteractiveConfig
from app.interactive.planner import parse_prompt
from app.interactive.policy.profiles import load_profile
from app.interactive.scene.interaction_layout import plan_interaction_layout
from app.interactive.scene.shot import select_shot
from app.interactive.scene.storyboard import plan_storyboard
from app.interactive.script.generator import (
    fill_scripts,
    generate_narration_for_node,
)
from app.interactive.script.i18n import generate_language_variants
from app.interactive.script.safety_rewriter import rewrite_for_safety
from app.interactive.script.tone import (
    ToneSpec,
    apply_tone,
    default_tone_for_mode,
    estimate_duration_sec,
)


def _cfg():
    return InteractiveConfig(
        enabled=True, max_branches=12, max_depth=6,
        max_nodes_per_experience=200, llm_model="llama3:8b",
        storage_root="", require_consent_for_mature=True,
        enforce_region_block=True, moderate_mature_narration=True,
        region_block=[], runtime_latency_target_ms=200,
    )


# ─────────────────────────────────────────────────────────────────
# Tone
# ─────────────────────────────────────────────────────────────────

def test_apply_tone_formal_expands_contractions():
    out = apply_tone("You don't know what you're doing", ToneSpec(formality=0.9))
    assert "do not" in out
    assert "you are" in out


def test_apply_tone_casual_contracts():
    out = apply_tone("You do not know what you are doing", ToneSpec(formality=0.1))
    assert "don't" in out
    assert "you're" in out


def test_estimate_duration_floors_and_ceils():
    assert estimate_duration_sec("hi", ToneSpec(pace_wps=2.5)) == 3
    long = "word " * 200
    assert estimate_duration_sec(long, ToneSpec(pace_wps=2.5)) == 20


def test_default_tone_per_mode_differs():
    assert default_tone_for_mode("enterprise_training").formality > 0.7
    assert default_tone_for_mode("mature_gated").warmth > 0.7


# ─────────────────────────────────────────────────────────────────
# Safety rewriter
# ─────────────────────────────────────────────────────────────────

def test_rewriter_redacts_universal_terms():
    prof = load_profile("sfw_general")
    r = rewrite_for_safety("This child is in danger", prof)
    assert "[redacted-age]" in r.text
    assert r.changed is True


def test_rewriter_redacts_explicit_in_narrow_profile():
    prof = load_profile("sfw_education")
    r = rewrite_for_safety("Show me your pussy", prof)
    assert "[redacted-explicit]" in r.text


def test_rewriter_leaves_explicit_alone_in_mature():
    prof = load_profile("mature_gated")
    r = rewrite_for_safety("Show me your pussy", prof)
    # mature_gated doesn't have a narrow allowlist → explicit stays
    assert "[redacted-explicit]" not in r.text


# ─────────────────────────────────────────────────────────────────
# Generator
# ─────────────────────────────────────────────────────────────────

def test_generator_fills_every_node():
    intent = parse_prompt("Quick demo", cfg=_cfg(), mode="sfw_general")
    graph = build_graph(intent)
    fill_scripts(graph, intent)
    for n in graph.nodes:
        assert n.title
        assert n.narration


def test_generator_is_idempotent():
    intent = parse_prompt("Quick demo", cfg=_cfg(), mode="sfw_general")
    graph = build_graph(intent)
    fill_scripts(graph, intent)
    first_narr = [n.narration for n in graph.nodes]
    # Hand-edit one node, then re-run
    graph.nodes[0].narration = "My custom intro"
    fill_scripts(graph, intent)
    assert graph.nodes[0].narration == "My custom intro"  # preserved
    # Others unchanged too
    for i, n in enumerate(graph.nodes):
        if i == 0:
            continue
        assert n.narration == first_narr[i]


def test_generator_writes_image_and_video_prompts():
    intent = parse_prompt("About fire safety", cfg=_cfg(), mode="enterprise_training")
    graph = build_graph(intent)
    fill_scripts(graph, intent)
    for n in graph.nodes:
        assert n.metadata.get("image_prompt")
        assert n.metadata.get("video_prompt")


# ─────────────────────────────────────────────────────────────────
# Scene
# ─────────────────────────────────────────────────────────────────

def test_shot_decision_has_choice_cta_overlay():
    spec = select_shot("decision", mode="sfw_general", duration_sec=5)
    assert "choice_cta" in spec.overlays


def test_shot_ending_uses_dolly_out():
    spec = select_shot("ending", mode="sfw_general", duration_sec=5)
    assert spec.move == "dolly_out"
    assert spec.transition == "crossfade"


def test_interaction_layout_education_hides_action_panel():
    layout = plan_interaction_layout("scene", mode="sfw_education")
    assert layout.show_action_panel is False


def test_interaction_layout_mature_shows_action_panel():
    layout = plan_interaction_layout("scene", mode="mature_gated")
    assert layout.show_action_panel is True


def test_interaction_layout_decision_hides_chat():
    layout = plan_interaction_layout("decision", mode="sfw_general")
    assert layout.chat_visible is False


def test_storyboard_populates_every_node():
    intent = parse_prompt("Quick demo", cfg=_cfg(), mode="sfw_education")
    graph = build_graph(intent)
    fill_scripts(graph, intent)
    plan_storyboard(graph, intent)
    for n in graph.nodes:
        sb = n.metadata.get("storyboard")
        assert sb
        assert "shot" in sb
        assert "interaction" in sb


def test_storyboard_preserves_manual_override():
    intent = parse_prompt("x", cfg=_cfg(), mode="sfw_general")
    graph = build_graph(intent)
    graph.nodes[0].metadata["storyboard"] = {"shot": {"camera": "custom"}}
    plan_storyboard(graph, intent)
    assert graph.nodes[0].metadata["storyboard"]["shot"]["camera"] == "custom"


# ─────────────────────────────────────────────────────────────────
# i18n
# ─────────────────────────────────────────────────────────────────

def test_i18n_variants_skip_authoring_language():
    intent = parse_prompt("x", cfg=_cfg(), mode="sfw_general")
    graph = build_graph(intent)
    fill_scripts(graph, intent)
    variants = generate_language_variants(graph, target_languages=["en", "es", "it"])
    # 'en' is the authoring language → no variants for it
    languages = {v["language"] for v in variants}
    assert "en" not in languages
    assert "es" in languages and "it" in languages


# ─────────────────────────────────────────────────────────────────
# Asset library
# ─────────────────────────────────────────────────────────────────

def test_register_and_query_library():
    register_library_asset(
        persona_id="persona_test",
        asset_id="file_xxx",
        kind="reaction",
        mood_tags=["flirty"],
        action_tags=["a_tease"],
        duration_sec=2.5,
        intensity=0.7,
    )
    results = query_library(
        "persona_test",
        mood="flirty",
        action="a_tease",
    )
    assert results
    assert results[0].asset_id == "file_xxx"


def test_query_ranks_matches_over_non_matches():
    # Seed one matching + one non-matching row for the same persona.
    register_library_asset(
        persona_id="persona_rank", asset_id="match",
        kind="reaction", mood_tags=["flirty"], action_tags=["a_tease"],
        intensity=0.5,
    )
    register_library_asset(
        persona_id="persona_rank", asset_id="no-match",
        kind="reaction", mood_tags=["shy"], action_tags=["a_greet"],
        intensity=0.9,
    )
    results = query_library("persona_rank", mood="flirty", action="a_tease")
    # Match beats higher intensity because it scored more on tags.
    assert results[0].asset_id == "match"


def test_seed_defaults_is_idempotent():
    ids_a = seed_library_defaults("persona_seed")
    ids_b = seed_library_defaults("persona_seed")
    assert len(ids_a) == 2
    assert len(ids_b) == 0  # already seeded


# ─────────────────────────────────────────────────────────────────
# Music + voice
# ─────────────────────────────────────────────────────────────────

def test_music_returns_track_for_known_mode_mood():
    t = pick_music_track("social_romantic", "warm")
    assert t.mood == "warm"
    assert t.id.startswith("t_")


def test_music_falls_back_when_mood_unknown():
    t = pick_music_track("sfw_education", "no_such_mood")
    assert t.id  # something returned
    assert t.mood == "neutral"  # fell back to (mode, 'neutral')


def test_voice_placeholder_returns_valid_descriptor():
    clip = synthesize_voice_clip(text="hello world", voice="coco", language="en")
    assert clip.voice == "coco"
    assert clip.language == "en"
    assert clip.duration_sec >= 1.0
