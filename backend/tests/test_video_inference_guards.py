from pathlib import Path

import pytest

from app import comfy, video_presets


def _touch(root: Path, name: str) -> None:
    (root / name).write_bytes(b"test")


def test_ltx_medium_prefers_fp8(tmp_path: Path) -> None:
    _touch(tmp_path, "t5xxl_fp8_e4m3fn.safetensors")
    _touch(tmp_path, "t5xxl_fp16.safetensors")

    assert (
        video_presets.select_ltx_t5_encoder(tmp_path, "medium")
        == "t5xxl_fp8_e4m3fn.safetensors"
    )


def test_ltx_medium_uses_installed_fp16_when_fp8_is_unavailable(tmp_path: Path) -> None:
    _touch(tmp_path, "t5xxl_fp16.safetensors")

    assert (
        video_presets.select_ltx_t5_encoder(tmp_path, "medium")
        == "t5xxl_fp16.safetensors"
    )


def test_ltx_ultra_prefers_fp16(tmp_path: Path) -> None:
    _touch(tmp_path, "t5xxl_fp8_e4m3fn.safetensors")
    _touch(tmp_path, "t5xxl_fp16.safetensors")

    assert (
        video_presets.select_ltx_t5_encoder(tmp_path, "ultra")
        == "t5xxl_fp16.safetensors"
    )


def test_ltx_ultra_can_fallback_to_fp8(tmp_path: Path) -> None:
    _touch(tmp_path, "t5xxl_fp8_e4m3fn.safetensors")

    assert (
        video_presets.select_ltx_t5_encoder(tmp_path, "ultra")
        == "t5xxl_fp8_e4m3fn.safetensors"
    )


def test_ltx_medium_default_matches_12gb_cap() -> None:
    video_presets.reload_presets()
    values = video_presets.apply_preset_to_workflow_vars(
        "medium", "ltx", aspect_ratio="16:9"
    )

    assert values["frames"] == 65
    assert values["fps"] == 24
    assert values["seconds"] == pytest.approx(65 / 24, abs=0.01)


def test_ltx_medium_explicit_four_seconds_reports_actual_clamped_duration() -> None:
    video_presets.reload_presets()
    values = video_presets.apply_preset_to_workflow_vars(
        "medium", "ltx", aspect_ratio="16:9", vid_seconds=4
    )

    assert values["requested_seconds"] == 4
    assert values["frames"] == 65
    assert values["seconds"] == pytest.approx(65 / 24, abs=0.01)


def test_ltx_high_default_is_about_four_seconds() -> None:
    video_presets.reload_presets()
    values = video_presets.apply_preset_to_workflow_vars(
        "high", "ltx", aspect_ratio="16:9"
    )

    assert values["frames"] == 97
    assert values["seconds"] == pytest.approx(97 / 24, abs=0.01)


def test_local_comfy_output_is_copied_without_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "output"
    input_dir = tmp_path / "input"
    output_dir.mkdir()
    source = output_dir / "starter.png"
    source.write_bytes(b"starter image")
    monkeypatch.setenv("COMFY_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("COMFY_INPUT_DIR", str(input_dir))
    monkeypatch.setattr(comfy, "COMFY_BASE_URL", "http://localhost:8188")

    class NoHttpClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("local Comfy output must not use HTTP")

    monkeypatch.setattr(comfy.httpx, "Client", NoHttpClient)
    filename = comfy._download_image_for_comfyui(
        "http://localhost:8188/view?filename=starter.png&type=output"
    )

    assert filename.startswith("starter_")
    assert (input_dir / filename).read_bytes() == b"starter image"


def test_local_comfy_output_rejects_path_traversal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not allowed")
    monkeypatch.setenv("COMFY_OUTPUT_DIR", str(output_dir))
    monkeypatch.setattr(comfy, "COMFY_BASE_URL", "http://localhost:8188")

    assert (
        comfy._local_comfy_view_file(
            "http://localhost:8188/view?filename=outside.png&subfolder=..&type=output"
        )
        is None
    )


def test_local_comfy_video_url_uses_homepilot_proxy() -> None:
    url = comfy.proxy_comfy_view_url(
        "http://localhost:8188/view?filename=ltx_video.webm&subfolder=clips&type=output"
    )

    assert url == "/comfy/view/ltx_video.webm?subfolder=clips&type=output"
