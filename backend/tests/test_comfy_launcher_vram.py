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


def test_dynamic_vram_is_turned_off_when_ram_is_short() -> None:
    """ComfyUI 0.41's dynamic loading pins about twice a checkpoint's size in RAM. On a 16 GB
    WSL VM with 4.7 GB available, every image failed at step 0: "pread failed (errno=12)"."""
    assert 'DYNAMIC_VRAM="${COMFY_DYNAMIC_VRAM:-auto}"' in LAUNCHER
    assert "grep -qi microsoft /proc/version" in LAUNCHER      # WSL: off by default
    assert "MemAvailable" in LAUNCHER
    assert '"$MEM_AVAILABLE_MB" -lt 8192' in LAUNCHER
    assert 'EXTRA_ARGS+=("--disable-dynamic-vram")' in LAUNCHER
