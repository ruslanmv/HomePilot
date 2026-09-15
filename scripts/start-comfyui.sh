#!/usr/bin/env bash
# Launch ComfyUI with automatic CPU/GPU detection.
#
# Why this exists
# ---------------
# ComfyUI's ``main.py`` fails hard at import time if torch can't
# reach the NVIDIA driver, even on machines that have a GPU but
# a broken WSL2 CUDA pass-through. That one traceback kills the
# whole ``make start`` pipeline and surprises users who are sure
# they have a GPU — the driver just isn't wired.
#
# This script probes ``torch.cuda.is_available()`` in the ComfyUI
# virtualenv before launch. When CUDA is usable, we run the GPU
# path (unchanged). When it isn't, we pass ``--cpu`` so ComfyUI
# still starts and the Interactive pipeline keeps working (slow
# but functional). Either way the user sees a clear one-line
# banner telling them which mode is active.
#
# Exit codes mirror the underlying ``python main.py`` — this
# script is a transparent wrapper.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMFY_DIR="$ROOT/ComfyUI"
PYTHON="$COMFY_DIR/.venv/bin/python"
COMFY_PORT="${COMFY_PORT:-8188}"

# Source the backend-written runtime.env, if present. The Settings
# UI writes VRAM-mode and other launcher-only flags there via
# POST /v1/system/runtime-config so they survive a restart. The
# DATA_DIR override lives outside so operators can relocate the
# data root via env without editing this script.
RUNTIME_ENV_FILE="${DATA_DIR:-$ROOT/backend/data}/runtime.env"
if [[ -f "$RUNTIME_ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; . "$RUNTIME_ENV_FILE"; set +a
  echo "ℹ️  ComfyUI: sourced runtime config from $RUNTIME_ENV_FILE"
fi

if [[ ! -f "$COMFY_DIR/main.py" ]]; then
  echo "❌ ComfyUI not found at $COMFY_DIR. Run: make install" >&2
  exit 1
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "❌ ComfyUI venv not found. Run: make install" >&2
  exit 1
fi

# Auto-link models the first time. Safe to re-run; idempotent.
if [[ -d "$ROOT/models/comfy" && ! -L "$COMFY_DIR/models" ]]; then
  echo "ℹ️  Auto-linking ComfyUI models to $ROOT/models/comfy …"
  rm -rf "$COMFY_DIR/models"
  ln -s "$ROOT/models/comfy" "$COMFY_DIR/models"
fi

# Probe CUDA. The probe runs the same torch the ComfyUI venv
# will use, so a false positive is almost impossible. A print
# of ``0`` = no CUDA, ``1`` = CUDA available; anything else (e.g.
# import error, segfault) also means no CUDA — we default to
# the CPU path.
CUDA_AVAILABLE="0"
if "$PYTHON" - <<'PY' 2>/dev/null
import sys
try:
    import torch
except Exception:
    sys.exit(2)
sys.exit(0 if (torch.cuda.is_available() and torch.cuda.device_count() > 0) else 1)
PY
then
  CUDA_AVAILABLE="1"
fi

EXTRA_ARGS=()
if [[ "$CUDA_AVAILABLE" == "1" ]]; then
  # Resolve the device name for the banner — purely informational,
  # swallowed on any error so a flaky torch build never breaks
  # startup.
  GPU_NAME="$("$PYTHON" -c "import torch; print(torch.cuda.get_device_name(0))" 2>/dev/null || echo "GPU")"
  GPU_VRAM_MB="$("$PYTHON" -c "import torch; print(torch.cuda.get_device_properties(0).total_memory // 1048576)" 2>/dev/null || echo "0")"
  echo "🚀 ComfyUI: GPU mode — $GPU_NAME"
else
  EXTRA_ARGS+=("--cpu")
  cat <<'BANNER' >&2
⚠️  ComfyUI: CPU mode (CUDA unavailable)

    Scene rendering will work but each image/video takes
    considerably longer. If you expected GPU acceleration:

      • Check `nvidia-smi` from this shell succeeds.
      • On WSL2: `wsl --update` on the Windows host, then
        restart WSL. Your NVIDIA driver must be ≥ 472.12.
      • On bare Linux: ensure the CUDA runtime matches the
        driver (`nvcc --version` vs `nvidia-smi`).

    Set `COMFY_FORCE_CPU=1` to silence this banner and always
    skip the probe.
BANNER
fi

# Allow operators to force CPU even when CUDA is available
# (useful for debugging OOM on large models, or for CI).
if [[ "${COMFY_FORCE_CPU:-0}" == "1" ]]; then
  EXTRA_ARGS=("--cpu")
  echo "ℹ️  ComfyUI: CPU mode forced by COMFY_FORCE_CPU=1"
fi

# VRAM mode. NORMAL_VRAM is the safe default for mixed image/video
# workloads. --highvram is useful for a single small image model, but a
# consumer GPU cannot simultaneously retain LTX + T5-XXL + VideoVAE; forcing
# it causes the partial unload/reload cycle visible in ComfyUI's logs.
if [[ "$CUDA_AVAILABLE" == "1" && "${COMFY_FORCE_CPU:-0}" != "1" ]]; then
  VRAM_MODE="${COMFY_VRAM_MODE:-normal}"

  # Protect <=16 GB GPUs from an unsafe persisted high-VRAM setting when a
  # large video family is selected. An operator can deliberately override
  # this guard after measuring their particular workflow.
  VIDEO_MODEL_VALUE="${VIDEO_MODEL:-}"
  VIDEO_MODEL_LOWER="${VIDEO_MODEL_VALUE,,}"
  if [[ "$VRAM_MODE" == "high" && "${GPU_VRAM_MB:-0}" -gt 0 && "${GPU_VRAM_MB:-0}" -le 16384 \
        && "$VIDEO_MODEL_LOWER" =~ (ltx|hunyuan|mochi|wan) \
        && "${COMFY_ALLOW_HIGHVRAM_VIDEO:-0}" != "1" ]]; then
    echo "⚠️  ComfyUI: forcing normal VRAM mode for $VIDEO_MODEL_VALUE on ${GPU_VRAM_MB} MB GPU"
    echo "   Set COMFY_ALLOW_HIGHVRAM_VIDEO=1 only after confirming the full model stack fits."
    VRAM_MODE="normal"
  fi
  case "$VRAM_MODE" in
    high)     EXTRA_ARGS+=("--highvram") ;;
    gpu|gpuonly|gpu-only)  EXTRA_ARGS+=("--gpu-only") ;;
    normal)   : ;;  # ComfyUI default; don't add any flag.
    low)      EXTRA_ARGS+=("--lowvram") ;;
    *)
      echo "⚠️  Unknown COMFY_VRAM_MODE='$VRAM_MODE' — ignoring (using ComfyUI default)" >&2
      ;;
  esac
  if [[ "$VRAM_MODE" == "high" ]]; then
    echo "💾 ComfyUI: --highvram (keeps models resident between calls)"
  fi
fi

cd "$COMFY_DIR"
exec "$PYTHON" main.py \
  --listen 0.0.0.0 \
  --port "$COMFY_PORT" \
  "${EXTRA_ARGS[@]}" \
  "$@"
