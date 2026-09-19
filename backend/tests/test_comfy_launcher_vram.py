from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = (ROOT / "scripts" / "start-comfyui.sh").read_text(encoding="utf-8")


def test_normal_vram_is_the_safe_default() -> None:
    assert 'VRAM_MODE="${COMFY_VRAM_MODE:-normal}"' in LAUNCHER


def test_large_video_models_guard_consumer_gpus_from_highvram() -> None:
    assert '"${GPU_VRAM_MB:-0}" -le 16384' in LAUNCHER
    assert '"$VIDEO_MODEL_LOWER" =~ (ltx|hunyuan|mochi|wan)' in LAUNCHER
    assert 'COMFY_ALLOW_HIGHVRAM_VIDEO:-0' in LAUNCHER
    assert 'VRAM_MODE="normal"' in LAUNCHER
