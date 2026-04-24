"""Tests for the wizard-time persona asset-library build phase.

generator_auto._run_generate_all now has a Phase 3 that pre-renders
the persona asset library when project_type='persona_live'. These
tests lock in:

* Phase 3 is a no-op for non-persona_live projects
* Phase 3 is a no-op when audience_profile has no persona_project_id
* Phase 3 skips when the persona has no committed portrait
* Phase 3 runs build_library with the persona's allow_explicit flag
* Phase 3 emits library_* SSE events so the wizard modal can show
  progress
* A whole-pass exception is non-fatal — the wizard still returns a
  result and the stats carry ok=False

No DB, no network, no ComfyUI — pal.build_library is monkey-patched
so we observe the call arguments and the event stream.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from app.interactive.playback import persona_asset_library as pal
from app.interactive.routes import generator_auto


def _fake_experience(**kw: Any) -> Any:
    return SimpleNamespace(
        id="exp_test",
        title=kw.get("title", "Lina session"),
        description="",
        objective="",
        experience_mode=kw.get("experience_mode", "mature_gated"),
        project_type=kw.get("project_type", "persona_live"),
        audience_profile=kw.get("audience_profile", {
            "persona_project_id": "persona_lina",
        }),
    )


@pytest.mark.asyncio
async def test_phase3_is_noop_for_standard_project():
    exp = _fake_experience(project_type="standard")
    events: List[tuple] = []
    result = await generator_auto._build_persona_library(
        exp, on_event=lambda k, p: events.append((k, p)),
    )
    assert result == {"skipped": True, "reason": "not_persona_live"}
    assert events == []


@pytest.mark.asyncio
async def test_phase3_is_noop_without_persona_project_id():
    exp = _fake_experience(audience_profile={})
    events: List[tuple] = []
    result = await generator_auto._build_persona_library(
        exp, on_event=lambda k, p: events.append((k, p)),
    )
    assert result == {"skipped": True, "reason": "no_persona_project_id"}


def _patch_persona(monkeypatch, persona: Dict[str, Any]) -> None:
    """Patch the module-level ``_lookup_persona_project`` seam.

    Uses the explicit in-module helper rather than monkeypatching
    ``app.projects.get_project_by_id``. Earlier attempts that patched
    the real projects module ran afoul of test-ordering pollution
    from other interactive tests that had already bound ``projects``
    into their own namespaces. Patching the seam function on the
    generator_auto module itself is stable regardless of import order.
    """
    monkeypatch.setattr(
        generator_auto, "_lookup_persona_project", lambda pid: persona,
    )


@pytest.mark.asyncio
async def test_phase3_skips_when_persona_has_no_portrait(monkeypatch):
    """render_scene_async bails out without a portrait — we detect up
    front and emit a clear reason rather than firing off a doomed pass."""
    _patch_persona(monkeypatch, {
        "id": "persona_lina",
        "persona_agent": {"persona_class": "companion", "safety": {}},
        "persona_appearance": {"selected_filename": ""},
    })

    exp = _fake_experience()
    events: List[tuple] = []
    result = await generator_auto._build_persona_library(
        exp, on_event=lambda k, p: events.append((k, p)),
    )
    assert result["skipped"] is True
    assert result["reason"] == "no_persona_portrait"
    assert ("library_skipped", {"reason": "no_persona_portrait"}) in events


@pytest.mark.asyncio
async def test_phase3_runs_build_library_and_forwards_allow_explicit(monkeypatch):
    """Persona with allow_explicit=True must reach build_library with
    that flag set so NSFW rows actually get rendered in the wizard pass."""
    _patch_persona(monkeypatch, {
        "id": "persona_lina",
        "name": "Lina",
        "persona_agent": {
            "persona_class": "flirty companion",
            "safety": {"allow_explicit": True},
        },
        "persona_appearance": {
            "selected_filename": "projects/persona_lina/persona/appearance/avatar.png",
        },
    })

    captured: Dict[str, Any] = {}

    async def _stub_build(pid, *, render_fn, max_tier, allow_explicit, on_progress=None):
        captured["pid"] = pid
        captured["max_tier"] = max_tier
        captured["allow_explicit"] = allow_explicit
        # Drive a single progress tick so the caller's event forwarder fires.
        if on_progress:
            on_progress("build_started", {"total": 1})
        return pal.BuildStats(total=1, rendered=1, skipped=0, failed=0)

    monkeypatch.setattr(pal, "build_library", _stub_build)

    exp = _fake_experience()
    events: List[tuple] = []
    result = await generator_auto._build_persona_library(
        exp, on_event=lambda k, p: events.append((k, p)),
    )

    assert captured["pid"] == "persona_lina"
    assert captured["max_tier"] == 1
    assert captured["allow_explicit"] is True
    assert result["ok"] is True
    assert result["persona_project_id"] == "persona_lina"
    assert result["allow_explicit"] is True
    # Progress ticks are forwarded with a library_ prefix so the SSE
    # event stream stays distinct from the scene render events.
    forwarded = [k for k, _ in events]
    assert "library_build_started" in forwarded


@pytest.mark.asyncio
async def test_phase3_defaults_to_tier_1_for_wizard_run(monkeypatch):
    """Tier 1 (idles + expressions + default outfit + medium cam) is
    the v1 spec's 'must pre-generate' floor. Higher tiers stay
    available via the explicit endpoint — don't slow the wizard."""
    _patch_persona(monkeypatch, {
        "id": "persona_lina", "name": "Lina",
        "persona_agent": {"persona_class": "companion", "safety": {}},
        "persona_appearance": {"selected_filename": "a.png"},
    })

    recorded: Dict[str, Any] = {}
    async def _stub_build(pid, *, render_fn, max_tier, allow_explicit, on_progress=None):
        recorded["max_tier"] = max_tier
        return pal.BuildStats()
    monkeypatch.setattr(pal, "build_library", _stub_build)

    await generator_auto._build_persona_library(
        _fake_experience(), on_event=lambda k, p: None,
    )
    assert recorded["max_tier"] == 1


@pytest.mark.asyncio
async def test_phase3_build_exception_is_non_fatal(monkeypatch):
    """A thrown exception inside build_library must NOT propagate — it
    would sink the whole wizard flow. Instead we log, emit a failure
    event, and return ok=False."""
    _patch_persona(monkeypatch, {
        "id": "persona_lina", "name": "Lina",
        "persona_agent": {"persona_class": "companion", "safety": {}},
        "persona_appearance": {"selected_filename": "a.png"},
    })

    async def _boom(*a, **kw):
        raise RuntimeError("comfy offline")
    monkeypatch.setattr(pal, "build_library", _boom)

    events: List[tuple] = []
    result = await generator_auto._build_persona_library(
        _fake_experience(), on_event=lambda k, p: events.append((k, p)),
    )

    assert result["ok"] is False
    assert result["persona_project_id"] == "persona_lina"
    failed = [p for k, p in events if k == "library_failed"]
    assert failed, "library_failed event must be emitted"


@pytest.mark.asyncio
async def test_run_generate_all_includes_library_in_result(monkeypatch):
    """End-to-end: _run_generate_all returns a payload with
    rendering + library stats for a persona_live project."""
    _patch_persona(monkeypatch, {
        "id": "persona_lina", "name": "Lina",
        "persona_agent": {"persona_class": "companion", "safety": {}},
        "persona_appearance": {"selected_filename": "a.png"},
    })

    # Stub the two phases so the test doesn't touch DB / renderer.
    async def _stub_auto(exp, cfg, *, on_event):
        return {"ok": True, "source": "stub"}
    async def _stub_render(exp, *, on_event):
        return {"total": 0, "rendered": 0, "skipped": 0, "failed": 0}
    async def _stub_build(pid, *, render_fn, max_tier, allow_explicit, on_progress=None):
        return pal.BuildStats(total=9, rendered=9)

    monkeypatch.setattr(generator_auto, "_run_auto_generate", _stub_auto)
    monkeypatch.setattr(generator_auto, "_render_all_scenes", _stub_render)
    monkeypatch.setattr(pal, "build_library", _stub_build)

    result = await generator_auto._run_generate_all(
        _fake_experience(), cfg=None, on_event=lambda k, p: None,
    )
    assert "rendering" in result
    assert "library" in result
    assert result["library"]["rendered"] == 9
    assert result["library"]["persona_project_id"] == "persona_lina"
