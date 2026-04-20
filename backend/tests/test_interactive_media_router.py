"""
Tests for ``app.interactive.media_router`` — PIPE-1 live resolver
for image/video model + Comfy base URL.

Covers:
* Each resolver reads env live on every call (no import-time freeze).
* Resolution order: override arg → INTERACTIVE_* → global env → default.
* Unknown/blank env values fall through cleanly.
* ``resolve_current_providers`` bundles the triple.
* ``render_adapter._build_variables`` threads the resolved model
  names into the workflow variable bag for each media_type.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from app.interactive.media_router import (
    MediaProviders,
    resolve_current_comfy_base_url,
    resolve_current_image_model,
    resolve_current_providers,
    resolve_current_video_model,
)


# ── Resolution order ────────────────────────────────────────────

def test_image_model_defaults_to_sdxl(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_IMAGE_MODEL", raising=False)
    monkeypatch.delenv("IMAGE_MODEL", raising=False)
    assert resolve_current_image_model() == "sdxl"


def test_image_model_reads_global_env(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_IMAGE_MODEL", raising=False)
    monkeypatch.setenv("IMAGE_MODEL", "dreamshaper_8.safetensors")
    assert resolve_current_image_model() == "dreamshaper_8.safetensors"


def test_interactive_scoped_beats_global(monkeypatch):
    monkeypatch.setenv("IMAGE_MODEL", "global-model")
    monkeypatch.setenv("INTERACTIVE_IMAGE_MODEL", "interactive-model")
    assert resolve_current_image_model() == "interactive-model"


def test_override_arg_beats_env(monkeypatch):
    monkeypatch.setenv("IMAGE_MODEL", "env-model")
    monkeypatch.setenv("INTERACTIVE_IMAGE_MODEL", "interactive-env")
    assert resolve_current_image_model(override="arg-model") == "arg-model"


def test_blank_env_treated_as_unset(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_IMAGE_MODEL", "   ")
    monkeypatch.setenv("IMAGE_MODEL", "")
    assert resolve_current_image_model() == "sdxl"


def test_image_model_reads_env_live(monkeypatch):
    monkeypatch.setenv("IMAGE_MODEL", "first")
    assert resolve_current_image_model() == "first"
    monkeypatch.setenv("IMAGE_MODEL", "second")
    assert resolve_current_image_model() == "second"


def test_video_model_defaults_to_svd(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_VIDEO_MODEL", raising=False)
    monkeypatch.delenv("VIDEO_MODEL", raising=False)
    assert resolve_current_video_model() == "svd"


def test_video_model_interactive_beats_global(monkeypatch):
    monkeypatch.setenv("VIDEO_MODEL", "svd_xt_1_1.safetensors")
    monkeypatch.setenv("INTERACTIVE_VIDEO_MODEL", "wan_2.2.safetensors")
    assert resolve_current_video_model() == "wan_2.2.safetensors"


def test_comfy_base_url_reads_env_live(monkeypatch):
    monkeypatch.setenv("COMFY_BASE_URL", "http://comfy.one:8188")
    assert resolve_current_comfy_base_url() == "http://comfy.one:8188"
    monkeypatch.setenv("INTERACTIVE_COMFY_BASE_URL", "http://comfy.two:8188")
    assert resolve_current_comfy_base_url() == "http://comfy.two:8188"


def test_resolve_current_providers_bundles_triple(monkeypatch):
    monkeypatch.setenv("IMAGE_MODEL", "img-x")
    monkeypatch.setenv("VIDEO_MODEL", "vid-y")
    monkeypatch.setenv("COMFY_BASE_URL", "http://c.example:8188")
    providers = resolve_current_providers()
    assert isinstance(providers, MediaProviders)
    assert providers.image_model == "img-x"
    assert providers.video_model == "vid-y"
    assert providers.comfy_base_url == "http://c.example:8188"
    # Compact label includes all three so log lines stay greppable.
    desc = providers.describe()
    assert "img-x" in desc and "vid-y" in desc and "c.example" in desc


# ── render_adapter integration ─────────────────────────────────

def test_build_variables_injects_video_model_for_video_media(monkeypatch):
    monkeypatch.setenv("VIDEO_MODEL", "svd_xt_1_1.safetensors")
    monkeypatch.setenv("IMAGE_MODEL", "dreamshaper_8.safetensors")
    from app.interactive.playback.render_adapter import _build_variables
    vars_ = _build_variables(
        "a cat", 5, "", media_type="video",
    )
    assert vars_["video_model"] == "svd_xt_1_1.safetensors"
    assert vars_["image_model"] == "dreamshaper_8.safetensors"
    # `model` aliases pick the active choice for this media_type.
    assert vars_["model"] == "svd_xt_1_1.safetensors"
    assert vars_["checkpoint"] == "svd_xt_1_1.safetensors"
    assert vars_["ckpt_name"] == "svd_xt_1_1.safetensors"


def test_build_variables_injects_image_model_for_image_media(monkeypatch):
    monkeypatch.setenv("VIDEO_MODEL", "svd_xt_1_1.safetensors")
    monkeypatch.setenv("IMAGE_MODEL", "dreamshaper_8.safetensors")
    from app.interactive.playback.render_adapter import _build_variables
    vars_ = _build_variables(
        "a cat", 5, "", media_type="image",
    )
    assert vars_["model"] == "dreamshaper_8.safetensors"
    assert vars_["checkpoint"] == "dreamshaper_8.safetensors"


def test_build_variables_includes_comfy_base_url(monkeypatch):
    monkeypatch.setenv("COMFY_BASE_URL", "http://comfy.internal:8188")
    from app.interactive.playback.render_adapter import _build_variables
    vars_ = _build_variables("x", 5, "", media_type="video")
    assert vars_["comfy_base_url"] == "http://comfy.internal:8188"
