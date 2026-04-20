"""
Tests for the image-vs-video media_type switch on the scene render
pipeline (MEDIA-TYPE-1).

Covers:
* PlaybackConfig.workflow_for picks the right workflow per media kind.
* render_scene_async honours media_type when submitting to ComfyUI.
* _select_best_media with prefer='image' prefers images over videos.
* _media_type_from_experience reads the wizard-stamped field.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.interactive.playback.playback_config import (
    PlaybackConfig, load_playback_config,
)


def _cfg(**overrides) -> PlaybackConfig:
    base = dict(
        llm_enabled=False,
        llm_timeout_s=12.0,
        llm_max_tokens=350,
        llm_temperature=0.65,
        render_enabled=True,
        render_workflow="animate",
        image_workflow="avatar_txt2img",
        render_timeout_s=5.0,
    )
    base.update(overrides)
    return PlaybackConfig(**base)


# ── PlaybackConfig.workflow_for ────────────────────────────────

def test_workflow_for_defaults_to_video():
    cfg = _cfg()
    assert cfg.workflow_for("") == "animate"
    assert cfg.workflow_for("video") == "animate"
    assert cfg.workflow_for("anything-else") == "animate"


def test_workflow_for_image_uses_image_workflow():
    cfg = _cfg()
    assert cfg.workflow_for("image") == "avatar_txt2img"
    assert cfg.workflow_for("IMAGE") == "avatar_txt2img"


def test_load_playback_config_reads_image_workflow_env(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_PLAYBACK_IMAGE_WORKFLOW", "custom_image_flow")
    cfg = load_playback_config()
    assert cfg.image_workflow == "custom_image_flow"
    assert cfg.workflow_for("image") == "custom_image_flow"


# ── _select_best_media prefer=image ─────────────────────────────

def test_select_best_media_image_preferred_picks_image():
    from app.interactive.playback.render_adapter import _select_best_media
    result = {
        "videos": ["/files/clip.mp4"],
        "images": ["/files/still.png"],
    }
    url, kind = _select_best_media(result, prefer="image")
    assert kind == "image"
    assert url == "/files/still.png"


def test_select_best_media_image_preferred_falls_back_to_video():
    from app.interactive.playback.render_adapter import _select_best_media
    result = {"videos": ["/files/clip.mp4"], "images": []}
    url, kind = _select_best_media(result, prefer="image")
    assert kind == "video"


def test_select_best_media_video_preferred_unchanged():
    from app.interactive.playback.render_adapter import _select_best_media
    result = {
        "videos": ["/files/clip.mp4"],
        "images": ["/files/still.png"],
    }
    url, kind = _select_best_media(result, prefer="video")
    assert kind == "video"
    assert url == "/files/clip.mp4"


# ── render_scene_async end-to-end ──────────────────────────────

def test_render_scene_async_uses_image_workflow_for_image_media(monkeypatch):
    """media_type='image' submits to cfg.image_workflow; default
    stays on cfg.render_workflow."""
    from app.interactive.playback import render_adapter
    captured: Dict[str, Any] = {}

    async def fake_run(workflow: str, variables: Dict[str, Any]):
        captured["workflow"] = workflow
        captured["variables"] = variables
        return {"images": ["/files/still.png"]}

    def fake_register(**kw):
        return "ixa_test_asset"

    monkeypatch.setattr(
        render_adapter, "_run_workflow_off_thread", fake_run,
    )
    monkeypatch.setattr(
        "app.asset_registry.register_asset", fake_register,
    )

    cfg = _cfg()
    asset_id = asyncio.run(render_adapter.render_scene_async(
        scene_prompt="a cat on a couch",
        duration_sec=5,
        session_id="s_1",
        media_type="image",
        config=cfg,
    ))
    assert asset_id == "ixa_test_asset"
    assert captured["workflow"] == "avatar_txt2img"


def test_render_scene_async_defaults_to_video_workflow(monkeypatch):
    from app.interactive.playback import render_adapter
    captured: Dict[str, Any] = {}

    async def fake_run(workflow: str, variables: Dict[str, Any]):
        captured["workflow"] = workflow
        return {"videos": ["/files/clip.mp4"]}

    def fake_register(**kw):
        return "ixa_video_asset"

    monkeypatch.setattr(
        render_adapter, "_run_workflow_off_thread", fake_run,
    )
    monkeypatch.setattr(
        "app.asset_registry.register_asset", fake_register,
    )

    asset_id = asyncio.run(render_adapter.render_scene_async(
        scene_prompt="a cat",
        duration_sec=5,
        session_id="s_1",
        config=_cfg(),
    ))
    assert asset_id == "ixa_video_asset"
    assert captured["workflow"] == "animate"


# ── Route helper: _media_type_from_experience ──────────────────

def test_media_type_helper_reads_audience_profile():
    from app.interactive.routes.playback import _media_type_from_experience
    import types
    exp = types.SimpleNamespace(
        audience_profile={"render_media_type": "image"}
    )
    assert _media_type_from_experience(exp) == "image"


def test_media_type_helper_defaults_to_video_when_missing():
    from app.interactive.routes.playback import _media_type_from_experience
    import types
    assert _media_type_from_experience(types.SimpleNamespace()) == "video"
    assert _media_type_from_experience(
        types.SimpleNamespace(audience_profile={}),
    ) == "video"
    assert _media_type_from_experience(
        types.SimpleNamespace(audience_profile=None),
    ) == "video"


def test_media_type_helper_normalises_unknown_values():
    from app.interactive.routes.playback import _media_type_from_experience
    import types
    exp = types.SimpleNamespace(
        audience_profile={"render_media_type": "hologram"},
    )
    assert _media_type_from_experience(exp) == "video"
