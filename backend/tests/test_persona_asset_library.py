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

def test_lookup_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PERSONA_LIVE_LIBRARY_LOOKUP", raising=False)
    assert pal.lookup_enabled() is False


def test_lookup_enabled_when_env_true(monkeypatch):
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
