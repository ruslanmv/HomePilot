"""
Tests for render_adapter.render_scene_async.

The two heavy deps — run_workflow and register_asset — are both
imported lazily inside the adapter, so we monkeypatch them at
the module level. Every test runs in-process and never touches a
real ComfyUI / SQLite.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

import pytest

from app.interactive.playback.playback_config import PlaybackConfig
from app.interactive.playback.render_adapter import render_scene_async


def _config(*, render_enabled: bool = True, timeout: float = 5.0) -> PlaybackConfig:
    return PlaybackConfig(
        llm_enabled=False,
        llm_timeout_s=12.0,
        llm_max_tokens=350,
        llm_temperature=0.65,
        render_enabled=render_enabled,
        render_workflow="animate",
        image_workflow="avatar_txt2img",
        render_timeout_s=timeout,
    )


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    workflow_return: Dict[str, Any] | Exception,
    captured_vars: List[Dict[str, Any]] | None = None,
    captured_reg: List[Dict[str, Any]] | None = None,
    async_delay_s: float = 0.0,
) -> None:
    """Install stand-ins for app.comfy.run_workflow and
    app.asset_registry.register_asset on their real modules
    (the adapter late-imports them)."""
    import app.comfy as comfy_mod
    import app.asset_registry as registry_mod

    def _fake_run_workflow(name: str, variables: Dict[str, Any]) -> Any:
        if captured_vars is not None:
            captured_vars.append({"workflow": name, "variables": dict(variables)})
        if async_delay_s:
            import time
            time.sleep(async_delay_s)
        if isinstance(workflow_return, Exception):
            raise workflow_return
        return workflow_return

    def _fake_register_asset(**kwargs: Any) -> str:
        if captured_reg is not None:
            captured_reg.append(dict(kwargs))
        return f"a_fake_{len(captured_reg or [])}"

    monkeypatch.setattr(comfy_mod, "run_workflow", _fake_run_workflow)
    monkeypatch.setattr(registry_mod, "register_asset", _fake_register_asset)


def _run(coro):
    return asyncio.run(coro)


# ── Happy paths ─────────────────────────────────────────────────

def test_returns_asset_id_for_video_output(monkeypatch):
    captured_vars: List[Dict[str, Any]] = []
    captured_reg: List[Dict[str, Any]] = []
    _install_fakes(
        monkeypatch,
        {"videos": ["http://comfy:8188/view?file=scene.mp4"], "images": []},
        captured_vars, captured_reg,
    )
    asset_id = _run(render_scene_async(
        scene_prompt="warm smile, soft light",
        duration_sec=5, session_id="ixs_abc",
        persona_hint="dark goth girl",
        config=_config(),
    ))
    assert asset_id is not None
    assert asset_id.startswith("a_fake_")
    # Variables include both persona hint and scene prompt, joined.
    vars_ = captured_vars[0]["variables"]
    assert "dark goth girl" in vars_["prompt"]
    assert "warm smile" in vars_["prompt"]
    assert vars_["seconds"] == 5
    # Registry called with kind='video' and feature='animate'
    reg = captured_reg[0]
    assert reg["kind"] == "video"
    assert reg["feature"] == "animate"
    assert reg["project_id"] == "ixs_abc"
    assert reg["origin"] == "interactive_playback"


def test_falls_back_to_image_when_no_video(monkeypatch):
    captured_reg: List[Dict[str, Any]] = []
    _install_fakes(
        monkeypatch,
        {"images": ["http://comfy:8188/view?file=frame.png"], "videos": []},
        None, captured_reg,
    )
    asset_id = _run(render_scene_async(
        scene_prompt="scene cues",
        duration_sec=4, session_id="ixs_fallback",
        config=_config(),
    ))
    assert asset_id is not None
    assert captured_reg[0]["kind"] == "image"
    assert captured_reg[0]["mime"] == "image/png"


# ── Feature-flag / guard paths ─────────────────────────────────

def test_returns_none_when_render_disabled(monkeypatch):
    # If disabled, we shouldn't even reach run_workflow.
    called: List[int] = []
    import app.comfy as comfy_mod
    def _should_not_call(*args, **kwargs):
        called.append(1)
        return {"videos": ["http://x"]}
    monkeypatch.setattr(comfy_mod, "run_workflow", _should_not_call)

    asset_id = _run(render_scene_async(
        scene_prompt="x", duration_sec=5, session_id="ixs_off",
        config=_config(render_enabled=False),
    ))
    assert asset_id is None
    assert called == []


def test_returns_none_for_empty_scene_prompt(monkeypatch):
    _install_fakes(monkeypatch, {"videos": ["http://x"], "images": []})
    asset_id = _run(render_scene_async(
        scene_prompt="   ", duration_sec=5, session_id="ixs_empty",
        config=_config(),
    ))
    assert asset_id is None


# ── Failure paths ──────────────────────────────────────────────

def test_returns_none_on_pipeline_exception(monkeypatch):
    _install_fakes(monkeypatch, RuntimeError("comfy down"))
    asset_id = _run(render_scene_async(
        scene_prompt="scene", duration_sec=5, session_id="ixs_err",
        config=_config(),
    ))
    assert asset_id is None


def test_returns_none_when_workflow_emits_no_media(monkeypatch):
    _install_fakes(monkeypatch, {"videos": [], "images": []})
    asset_id = _run(render_scene_async(
        scene_prompt="scene", duration_sec=5, session_id="ixs_nothing",
        config=_config(),
    ))
    assert asset_id is None


def test_returns_none_on_timeout(monkeypatch):
    # Simulate a long-running workflow by delaying the sync call.
    _install_fakes(
        monkeypatch,
        {"videos": ["http://comfy:8188/view?file=scene.mp4"], "images": []},
        async_delay_s=0.4,
    )
    asset_id = _run(render_scene_async(
        scene_prompt="scene", duration_sec=5, session_id="ixs_slow",
        config=_config(timeout=0.05),
    ))
    assert asset_id is None


def test_returns_none_when_registry_fails(monkeypatch):
    _install_fakes(
        monkeypatch,
        {"videos": ["http://x/scene.mp4"], "images": []},
    )
    # Override register_asset post-install to raise.
    import app.asset_registry as registry_mod
    def _boom(**kwargs):
        raise RuntimeError("db locked")
    monkeypatch.setattr(registry_mod, "register_asset", _boom)

    asset_id = _run(render_scene_async(
        scene_prompt="scene", duration_sec=5, session_id="ixs_reg",
        config=_config(),
    ))
    assert asset_id is None


# ── MIME guessing ──────────────────────────────────────────────

def test_mime_inferred_from_extension(monkeypatch):
    captured_reg: List[Dict[str, Any]] = []
    _install_fakes(
        monkeypatch,
        {"videos": ["http://x/clip.webm"], "images": []},
        None, captured_reg,
    )
    _run(render_scene_async(
        scene_prompt="scene", duration_sec=5, session_id="ixs_mime",
        config=_config(),
    ))
    assert captured_reg[0]["mime"] == "video/webm"


# ── Workflow-variable defaults (regression) ────────────────────
#
# Older _build_variables didn't provide ``t5_encoder``, ``image_path``
# or ``denoise`` defaults. LTX-style video workflows have
# ``{{t5_encoder}}`` / ``{{image_path}}`` / ``{{denoise}}`` placeholders;
# without the corresponding variables the submitted prompt landed
# literal ``{{t5_encoder}}`` in CLIPLoader → ComfyUI rejected it with
# "Value not in list: clip_name: '{{t5_encoder}}' not in [...]".
# These tests lock in the defaults so the wizard video path stops
# producing that false-positive "missing model" error.

def test_build_variables_provides_t5_encoder_default(monkeypatch):
    from app.interactive.playback.render_adapter import _build_variables

    # Simulate ComfyUI reporting one real T5 encoder available.
    import app.comfy as comfy_mod
    def _fake_object_info(force=False):
        return {
            "CLIPLoader": {"input": {"required": {
                "clip_name": [["clip_l.safetensors", "t5xxl_fp16.safetensors"]],
            }}},
        }
    monkeypatch.setattr(comfy_mod, "_fetch_object_info", _fake_object_info)

    vars_ = _build_variables("persona portrait", 5, "hint", media_type="video")
    assert vars_["t5_encoder"] == "t5xxl_fp16.safetensors", (
        "Default must pick an installed T5 model instead of an unresolved "
        "{{t5_encoder}} placeholder — that's what was triggering the "
        "'not in list' ComfyUI validation failures."
    )
    assert "image_path" in vars_
    assert "denoise" in vars_


def test_build_variables_falls_back_when_comfy_unreachable(monkeypatch):
    """When ComfyUI is down or hasn't cached /object_info yet, the
    picker falls back to the standard filename rather than raising."""
    from app.interactive.playback.render_adapter import _build_variables
    import app.comfy as comfy_mod
    def _boom(force=False):
        raise RuntimeError("comfy offline")
    monkeypatch.setattr(comfy_mod, "_fetch_object_info", _boom)

    vars_ = _build_variables("persona portrait", 5, "hint", media_type="video")
    assert vars_["t5_encoder"] == "t5xxl_fp16.safetensors"


def test_build_variables_picks_first_installed_when_no_t5(monkeypatch):
    """If no preferred model matches, pick the first installed encoder
    so we use whatever the operator actually has on disk."""
    from app.interactive.playback.render_adapter import _build_variables
    import app.comfy as comfy_mod
    def _fake_object_info(force=False):
        return {
            "CLIPLoader": {"input": {"required": {
                "clip_name": [["umt5_xxl_fp8_e4m3fn.safetensors", "clip_l.safetensors"]],
            }}},
        }
    monkeypatch.setattr(comfy_mod, "_fetch_object_info", _fake_object_info)

    vars_ = _build_variables("persona portrait", 5, "hint", media_type="video")
    # umt5 doesn't match "t5xxl_fp16"/"t5xxl_fp8_e4m3fn" but does match "t5" substring
    assert vars_["t5_encoder"] == "umt5_xxl_fp8_e4m3fn.safetensors"
