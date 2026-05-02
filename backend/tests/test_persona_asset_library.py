"""Unit tests for the persona asset-library pre-render pack.

Covers:
* manifest integrity (tier coverage, reaction_intent → ACTION_RECIPES)
* plan_library tier filtering
* pending_specs subtracts already-built assets
* asset_id_for_intent mapping (player intent → library asset)
* resolve_asset_url_for_intent fast path
* build_library idempotent + per-asset failure handling
* lookup_enabled env toggle

No DB, no network — storage helpers are monkey-patched against a
synthetic projects module so we can observe the update_project path
without touching real persona projects.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app.interactive.playback import persona_asset_library as pal
from app.interactive.playback.edit_recipes import ACTION_RECIPES


# ── Manifest integrity ──────────────────────────────────────────────────────

def test_manifest_tier_1_covers_required_states():
    tier_1 = pal.plan_library(max_tier=1)
    ids = {spec.asset_id for spec in tier_1}
    # Per the v1 spec: idles + all expressions + default outfit + medium cam
    assert "idle_neutral" in ids
    assert "idle_soft_smile" in ids
    assert "expr_blush" in ids
    assert "expr_smirk" in ids
    assert "expr_smile" in ids
    assert "expr_neutral_attentive" in ids
    assert "expr_curious" in ids
    assert "outfit_casual" in ids
    assert "cam_medium" in ids


def test_manifest_tier_ladder_is_monotonic():
    tier_1 = {s.asset_id for s in pal.plan_library(max_tier=1)}
    tier_2 = {s.asset_id for s in pal.plan_library(max_tier=2)}
    tier_3 = {s.asset_id for s in pal.plan_library(max_tier=3)}
    # Higher tiers must be supersets of lower tiers
    assert tier_1.issubset(tier_2)
    assert tier_2.issubset(tier_3)


def test_reaction_intents_map_to_real_edit_recipes():
    """Every library asset's reaction_intent must resolve to a valid
    ACTION_RECIPES key, so the build_library render callback can reuse
    the existing recipe router without a second code path."""
    for spec in pal.ASSET_MANIFEST:
        assert spec.reaction_intent in ACTION_RECIPES, (
            f"{spec.asset_id}.reaction_intent '{spec.reaction_intent}' "
            f"not in ACTION_RECIPES"
        )


def test_every_manifest_spec_has_non_empty_prompt_fragment():
    for spec in pal.ASSET_MANIFEST:
        assert spec.prompt_fragment.strip(), f"{spec.asset_id} has empty prompt"


# ── plan_library + pending_specs ────────────────────────────────────────────

def test_plan_library_clamps_tier_arg():
    """Invalid tier args must not crash and must not leak higher tiers."""
    assert pal.plan_library(max_tier=0) == pal.plan_library(max_tier=1)
    assert pal.plan_library(max_tier=99) == pal.plan_library(max_tier=3)


def test_pending_specs_subtracts_already_built():
    built = {"expr_blush": {"asset_url": "/files/x.png"}, "idle_neutral": {}}
    pending = pal.pending_specs(max_tier=1, already_built=built)
    pending_ids = {s.asset_id for s in pending}
    assert "expr_blush" not in pending_ids
    assert "idle_neutral" not in pending_ids
    assert "expr_smirk" in pending_ids  # not yet built


def test_pending_specs_empty_when_everything_built():
    tier_1 = pal.plan_library(max_tier=1)
    built = {s.asset_id: {} for s in tier_1}
    assert pal.pending_specs(max_tier=1, already_built=built) == []


# ── Intent → asset mapping ──────────────────────────────────────────────────

def test_intent_mapping_for_level_1_intents():
    """Level-1 intents that the Live Action panel exposes must all map
    to a real library asset — otherwise the fast path has holes."""
    for intent in ("say_playful", "compliment", "ask_about_her", "stay_quiet"):
        asset_id = pal.asset_id_for_intent(intent)
        assert asset_id, f"{intent} has no library mapping"
        # And the mapped asset must exist in the manifest
        all_ids = {s.asset_id for s in pal.ASSET_MANIFEST}
        assert asset_id in all_ids


def test_intent_mapping_falls_through_for_unknown():
    assert pal.asset_id_for_intent("") == ""
    assert pal.asset_id_for_intent("not_a_real_intent") == ""
    # Level-5 intents intentionally fall through to live render —
    # tier-gated content is rare enough that the "special moment"
    # live render is the right call.
    assert pal.asset_id_for_intent("lean_in") == ""


# ── resolve_asset_url_for_intent ────────────────────────────────────────────

def test_resolve_url_empty_when_library_empty(monkeypatch):
    # Stub `app.projects.get_project_by_id` so load_library returns {}.
    import types
    stub = types.ModuleType("projects_stub")
    stub.get_project_by_id = lambda pid: {}  # type: ignore[attr-defined]
    import sys
    monkeypatch.setitem(sys.modules, "app.projects", stub)
    monkeypatch.setattr(pal, "load_library", lambda pid: {})
    assert pal.resolve_asset_url_for_intent("pid", "compliment") == ""


def test_resolve_url_hits_when_library_has_mapped_asset(monkeypatch):
    monkeypatch.setattr(pal, "load_library", lambda pid: {
        "expr_blush": {"asset_url": "/files/blush.png"},
    })
    assert pal.resolve_asset_url_for_intent("pid", "compliment") == "/files/blush.png"


def test_resolve_url_empty_for_unmapped_intent(monkeypatch):
    """Intent with no library mapping must return empty even when the
    library has rows — so the action endpoint falls through cleanly."""
    monkeypatch.setattr(pal, "load_library", lambda pid: {
        "expr_blush": {"asset_url": "/files/blush.png"},
    })
    assert pal.resolve_asset_url_for_intent("pid", "lean_in") == ""


# ── lookup_enabled env toggle ──────────────────────────────────────────────
#
# Default flipped from OFF → ON: the wizard's Phase 3 builds the
# library on every persona_live experience create now, so keeping the
# fast-path lookup gated meant generated images sat unused on disk
# while the player live-rendered things it had cached. The env var is
# now a kill-switch (set to "false" to bypass the cache) rather than
# an opt-in.

def test_lookup_enabled_by_default(monkeypatch):
    monkeypatch.delenv("PERSONA_LIVE_LIBRARY_LOOKUP", raising=False)
    assert pal.lookup_enabled() is True


def test_lookup_disabled_when_env_false(monkeypatch):
    """Explicit OFF kill-switch — every action click forces a fresh
    live render. Useful for verifying renders pass-by-pass."""
    monkeypatch.setenv("PERSONA_LIVE_LIBRARY_LOOKUP", "false")
    assert pal.lookup_enabled() is False


def test_lookup_enabled_when_env_true(monkeypatch):
    """Explicit ON also works (no-op, but documents the expected
    behaviour for operators flipping the var to confirm)."""
    monkeypatch.setenv("PERSONA_LIVE_LIBRARY_LOOKUP", "true")
    assert pal.lookup_enabled() is True


# ── build_library (with a mock render callback) ─────────────────────────────

@pytest.mark.asyncio
async def test_build_library_renders_pending_specs_and_persists(monkeypatch):
    """Full build pass: every pending spec goes through render_fn and
    save_asset_record is called per success."""
    saved: List[Dict[str, Any]] = []

    monkeypatch.setattr(pal, "load_library", lambda pid: {})

    def _save(pid, record):
        saved.append({
            "pid": pid, "asset_id": record.asset_id,
            "asset_url": record.asset_url,
        })
        return True
    monkeypatch.setattr(pal, "save_asset_record", _save)

    async def _render(spec: pal.AssetSpec) -> str:
        return f"/files/{spec.asset_id}.png"

    stats = await pal.build_library(
        "persona_test", render_fn=_render, max_tier=1,
    )
    assert stats.failed == 0
    assert stats.rendered == len(pal.plan_library(1))
    assert stats.skipped == 0
    # Every saved row must carry the expected url format
    for row in saved:
        assert row["asset_url"].endswith(f"{row['asset_id']}.png")


@pytest.mark.asyncio
async def test_build_library_skips_already_built(monkeypatch):
    """Idempotent build: assets already in the library must not be
    re-rendered on a second pass."""
    already_built = {
        "idle_neutral": {"asset_url": "/files/idle_neutral.png"},
        "expr_blush":   {"asset_url": "/files/expr_blush.png"},
    }
    monkeypatch.setattr(pal, "load_library", lambda pid: dict(already_built))
    monkeypatch.setattr(pal, "save_asset_record", lambda pid, rec: True)

    render_calls: List[str] = []
    async def _render(spec: pal.AssetSpec) -> str:
        render_calls.append(spec.asset_id)
        return f"/files/{spec.asset_id}.png"

    stats = await pal.build_library(
        "persona_test", render_fn=_render, max_tier=1,
    )
    assert "idle_neutral" not in render_calls
    assert "expr_blush" not in render_calls
    assert stats.skipped == 2
    assert stats.rendered == len(pal.plan_library(1)) - 2


@pytest.mark.asyncio
async def test_build_library_records_per_asset_failures(monkeypatch):
    """Per-asset failures are non-fatal — other assets still render."""
    monkeypatch.setattr(pal, "load_library", lambda pid: {})
    monkeypatch.setattr(pal, "save_asset_record", lambda pid, rec: True)

    async def _render(spec: pal.AssetSpec) -> str:
        if spec.asset_id == "expr_smirk":
            raise RuntimeError("comfy down")
        if spec.asset_id == "expr_curious":
            return ""  # render returned empty
        return f"/files/{spec.asset_id}.png"

    stats = await pal.build_library(
        "persona_test", render_fn=_render, max_tier=1,
    )
    assert stats.failed == 2
    failure_ids = {f["asset_id"] for f in stats.failures}
    assert "expr_smirk" in failure_ids
    assert "expr_curious" in failure_ids
    # Others must still have rendered
    assert stats.rendered == len(pal.plan_library(1)) - 2


# ── NSFW gating ─────────────────────────────────────────────────────────────

def test_plan_library_excludes_nsfw_by_default():
    """Default SFW persona must not see any explicit_only specs."""
    for tier in (1, 2, 3):
        plan = pal.plan_library(max_tier=tier, allow_explicit=False)
        for spec in plan:
            assert spec.explicit_only is False, (
                f"tier={tier} leaked explicit spec {spec.asset_id}"
            )


def test_plan_library_includes_nsfw_when_allow_explicit():
    """allow_explicit=True must surface the NSFW rows at their tier."""
    tier_1 = pal.plan_library(max_tier=1, allow_explicit=True)
    ids = {s.asset_id for s in tier_1}
    assert "expr_heated" in ids
    assert "expr_breathless" in ids

    tier_2 = pal.plan_library(max_tier=2, allow_explicit=True)
    tier_2_ids = {s.asset_id for s in tier_2}
    assert "pose_reclining" in tier_2_ids
    assert "outfit_lingerie" in tier_2_ids
    assert "outfit_silk_robe" in tier_2_ids

    tier_3 = pal.plan_library(max_tier=3, allow_explicit=True)
    tier_3_ids = {s.asset_id for s in tier_3}
    assert "env_boudoir" in tier_3_ids
    assert "env_bedroom_intimate" in tier_3_ids


def test_nsfw_tier_strictly_grows_the_plan():
    """For every tier, allow_explicit=True must be a proper superset
    of allow_explicit=False — we should only ever ADD rows, never
    swap them out."""
    for tier in (1, 2, 3):
        sfw = {s.asset_id for s in pal.plan_library(tier, allow_explicit=False)}
        nsfw = {s.asset_id for s in pal.plan_library(tier, allow_explicit=True)}
        assert sfw.issubset(nsfw)
        assert len(nsfw) > len(sfw)


def test_asset_id_for_intent_prefers_nsfw_when_allow_explicit():
    """suggest_outfit → outfit_fitness (SFW) becomes outfit_lingerie
    (NSFW) when the persona allows explicit content."""
    assert pal.asset_id_for_intent("suggest_outfit", allow_explicit=False) == "outfit_fitness"
    assert pal.asset_id_for_intent("suggest_outfit", allow_explicit=True) == "outfit_lingerie"
    assert pal.asset_id_for_intent("change_location", allow_explicit=True) == "env_boudoir"
    assert pal.asset_id_for_intent("change_location", allow_explicit=False) == "env_couch"


def test_level_5_intents_resolve_only_for_explicit_personas():
    """lean_in / playful_dare had no SFW mapping; with the NSFW
    override layer they resolve ONLY when allow_explicit=True."""
    assert pal.asset_id_for_intent("lean_in", allow_explicit=False) == ""
    assert pal.asset_id_for_intent("lean_in", allow_explicit=True) == "expr_breathless"
    assert pal.asset_id_for_intent("playful_dare", allow_explicit=False) == ""
    assert pal.asset_id_for_intent("playful_dare", allow_explicit=True) == "pose_closer_intimate"


def test_resolve_url_prefers_nsfw_row_when_both_exist(monkeypatch):
    """When the library has both the SFW and NSFW rows and the persona
    allows explicit, the NSFW row wins for an intent that has both."""
    monkeypatch.setattr(pal, "load_library", lambda pid: {
        "outfit_fitness":   {"asset_url": "/files/fitness.png"},
        "outfit_lingerie":  {"asset_url": "/files/lingerie.png"},
    })
    sfw = pal.resolve_asset_url_for_intent("pid", "suggest_outfit", allow_explicit=False)
    nsfw = pal.resolve_asset_url_for_intent("pid", "suggest_outfit", allow_explicit=True)
    assert sfw == "/files/fitness.png"
    assert nsfw == "/files/lingerie.png"


def test_resolve_url_falls_back_to_sfw_when_nsfw_row_missing(monkeypatch):
    """Explicit persona + library built only at SFW tier: the lookup
    must gracefully fall back to the SFW row instead of returning
    empty and forcing a live render on every click."""
    monkeypatch.setattr(pal, "load_library", lambda pid: {
        # Only the SFW outfit is built.
        "outfit_fitness": {"asset_url": "/files/fitness.png"},
    })
    url = pal.resolve_asset_url_for_intent("pid", "suggest_outfit", allow_explicit=True)
    assert url == "/files/fitness.png"


def test_level_5_intent_returns_empty_without_library_nsfw_row(monkeypatch):
    """Explicit persona, but the NSFW tier hasn't been built yet.
    lean_in has NO SFW fallback — must return empty so the action
    endpoint falls through to live render."""
    monkeypatch.setattr(pal, "load_library", lambda pid: {
        "outfit_fitness": {"asset_url": "/files/fitness.png"},
    })
    url = pal.resolve_asset_url_for_intent("pid", "lean_in", allow_explicit=True)
    assert url == ""


@pytest.mark.asyncio
async def test_build_library_respects_allow_explicit_gate(monkeypatch):
    """Building with allow_explicit=False must render ONLY SFW specs —
    the NSFW rows stay skipped at every tier."""
    rendered: List[str] = []
    monkeypatch.setattr(pal, "load_library", lambda pid: {})
    monkeypatch.setattr(pal, "save_asset_record", lambda pid, rec: True)

    async def _render(spec: pal.AssetSpec) -> str:
        rendered.append(spec.asset_id)
        return f"/files/{spec.asset_id}.png"

    await pal.build_library(
        "persona_sfw", render_fn=_render, max_tier=3, allow_explicit=False,
    )
    assert "expr_heated" not in rendered
    assert "expr_breathless" not in rendered
    assert "outfit_lingerie" not in rendered
    assert "env_boudoir" not in rendered


@pytest.mark.asyncio
async def test_build_library_includes_nsfw_when_persona_allows(monkeypatch):
    """allow_explicit=True must render the NSFW rows alongside SFW."""
    rendered: List[str] = []
    monkeypatch.setattr(pal, "load_library", lambda pid: {})
    monkeypatch.setattr(pal, "save_asset_record", lambda pid, rec: True)

    async def _render(spec: pal.AssetSpec) -> str:
        rendered.append(spec.asset_id)
        return f"/files/{spec.asset_id}.png"

    await pal.build_library(
        "persona_explicit", render_fn=_render, max_tier=3, allow_explicit=True,
    )
    for required in (
        "expr_heated", "expr_breathless",
        "pose_reclining", "outfit_lingerie", "outfit_silk_robe",
        "env_boudoir",
    ):
        assert required in rendered, f"NSFW spec {required} not built"


@pytest.mark.asyncio
async def test_build_library_emits_progress_events(monkeypatch):
    events: List[Dict[str, Any]] = []
    monkeypatch.setattr(pal, "load_library", lambda pid: {})
    monkeypatch.setattr(pal, "save_asset_record", lambda pid, rec: True)
    async def _render(spec: pal.AssetSpec) -> str:
        return f"/files/{spec.asset_id}.png"

    await pal.build_library(
        "persona_test",
        render_fn=_render,
        max_tier=1,
        # Capture as (event_name, payload) tuples so the spec's own
        # ``kind`` field in the payload can't collide with our marker.
        on_progress=lambda kind, payload: events.append({"event": kind, "payload": payload}),
    )

    names = [e["event"] for e in events]
    assert "build_started" in names
    assert "rendering_asset" in names
    assert "asset_rendered" in names
    assert "build_done" in names
