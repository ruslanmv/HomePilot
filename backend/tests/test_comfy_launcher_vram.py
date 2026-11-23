import os
import shutil
import subprocess
from pathlib import Path

import pytest

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


# ── The launcher run for real, against a fake ComfyUI ────────────────────────
#
# A ComfyUI without dynamic VRAM rejects --disable-dynamic-vram and exits at once, which took
# image and video generation down on a WSL machine (warmup then waited 600 s for nothing).
# These run the launcher with a stand-in python that reports a GPU and prints the arguments
# main.py would have received.

FAKE_PYTHON = """#!/usr/bin/env bash
if [[ "${1:-}" == "-" ]]; then cat >/dev/null; exit 0; fi          # CUDA probe: available
if [[ "${1:-}" == "-c" ]]; then
  case "$2" in *get_device_name*) echo "Fake GPU";; *total_memory*) echo 12281;; esac; exit 0
fi
shift; echo "ARGS: $*"                                               # main.py <args>
"""


def _run_launcher(tmp_path, cli_args_source: str) -> str:
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "start-comfyui.sh", tmp_path / "scripts" / "start-comfyui.sh")
    comfy = tmp_path / "ComfyUI"
    (comfy / "comfy").mkdir(parents=True)
    (comfy / ".venv" / "bin").mkdir(parents=True)
    (comfy / "main.py").write_text("")
    (comfy / "comfy" / "cli_args.py").write_text(cli_args_source)
    py = comfy / ".venv" / "bin" / "python"
    py.write_text(FAKE_PYTHON)
    py.chmod(0o755)
    env = {**os.environ, "COMFY_DYNAMIC_VRAM": "0", "DATA_DIR": str(tmp_path / "data")}
    for k in ("COMFY_FORCE_CPU", "COMFY_VRAM_MODE", "VIDEO_MODEL"):
        env.pop(k, None)
    out = subprocess.run(
        ["bash", str(tmp_path / "scripts" / "start-comfyui.sh")],
        check=False, env=env, capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return next(line for line in out.stdout.splitlines() if line.startswith("ARGS:"))


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_flag_is_passed_to_a_comfyui_that_has_it(tmp_path) -> None:
    has_it = 'parser.add_argument("--disable-dynamic-vram", action="store_true")\n'
    assert "--disable-dynamic-vram" in _run_launcher(tmp_path, has_it)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_flag_is_left_out_for_a_comfyui_that_would_refuse_it(tmp_path) -> None:
    lacks_it = 'parser.add_argument("--disable-pinned-memory", action="store_true")\n'
    args = _run_launcher(tmp_path, lacks_it)
    assert "--disable-dynamic-vram" not in args
    assert "--listen" in args, "ComfyUI is still started"
