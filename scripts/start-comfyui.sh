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

# ── Where ComfyUI runs: here (linux) or on the WSL host (windows) ──────────────
# COMFY_RUNTIME=auto|linux|windows (default auto). Under WSL with the models on a
# Windows drive, Linux ComfyUI reads every model through the /mnt bridge (~64 MB/s
# measured vs ~2,200 MB/s natively), so a Windows-native ComfyUI is much faster.
# auto picks windows only when ALL hold: this is WSL, the models resolve to /mnt/*,
# the Windows env is installed (backend/data/comfy-windows.env), and WSL networking
# is mirrored (so the backend reaches it on localhost). Otherwise — native Linux,
# cloud, Docker, or anything missing — it runs here exactly as before.
WIN_ENV_FILE="${DATA_DIR:-$ROOT/backend/data}/comfy-windows.env"
if [[ -f "$WIN_ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; . "$WIN_ENV_FILE"; set +a
  # Written on Windows: drop a trailing CR (CRLF line endings) from the value.
  COMFY_WIN_VENV="${COMFY_WIN_VENV:-}"; COMFY_WIN_VENV="${COMFY_WIN_VENV%$'\r'}"
fi
is_wsl() { grep -qi microsoft /proc/version 2>/dev/null; }
models_on_windows_drive() {
  local p; p="$(readlink -f "$COMFY_DIR/models" 2>/dev/null || echo "$COMFY_DIR/models")"
  [[ "$p" == /mnt/* ]]
}
win_env_ready() {
  [[ -n "${COMFY_WIN_VENV:-}" ]] && command -v wslpath >/dev/null 2>&1 \
    && [[ -f "$(wslpath -u "$COMFY_WIN_VENV" 2>/dev/null)/Scripts/python.exe" ]]
}
wsl_mirrored() { [[ "$(wslinfo --networking-mode 2>/dev/null)" == "mirrored" ]]; }

RUNTIME="${COMFY_RUNTIME:-auto}"
if [[ "$RUNTIME" == "auto" ]]; then
  RUNTIME="linux"
  if is_wsl && models_on_windows_drive && win_env_ready; then
    if wsl_mirrored; then
      RUNTIME="windows"
    else
      echo "ℹ️  ComfyUI: a Windows environment is installed, but WSL networking is not mirrored,"
      echo "   so the backend could not reach it on localhost. Running in Linux instead."
      echo "   Enable it: [wsl2] networkingMode=mirrored in %UserProfile%\\.wslconfig, then wsl --shutdown."
    fi
  fi
fi

if [[ "$RUNTIME" == "windows" ]]; then
  is_wsl || { echo "❌ COMFY_RUNTIME=windows only works under WSL." >&2; exit 1; }
  win_env_ready || { echo "❌ No Windows ComfyUI environment. Run: make install-comfyui-windows COMFY_WIN_VENV=<path>" >&2; exit 1; }
  PS1_WIN="$(wslpath -w "$SCRIPT_DIR/start-comfyui.ps1")"
  echo "🪟 ComfyUI: running natively on Windows — models are read straight from disk, not through /mnt."
  stop_windows_comfy() {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS1_WIN" -Stop -Port "$COMFY_PORT" >/dev/null 2>&1 || true
  }
  trap 'stop_windows_comfy; exit 0' INT TERM
  COMFY_WIN_VENV="$COMFY_WIN_VENV" powershell.exe -NoProfile -ExecutionPolicy Bypass \
    -File "$PS1_WIN" -Port "$COMFY_PORT" -Venv "$COMFY_WIN_VENV" &
  child=$!
  wait "$child"
  exit $?
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

  # Dynamic VRAM (ComfyUI 0.4x) streams weights through a page-locked host buffer about
  # twice the checkpoint's size. With little RAM to spare — a WSL VM shares the laptop's
  # memory with everything else on it — that buffer cannot be locked, and every image fails
  # at its first step with "pread failed (errno=12)" / "HostBuffer.read_file_slice failed".
  # Below 8 GiB available, the classic estimate-based loader is used instead: a checkpoint
  # that fits the GPU runs as before; a bigger one offloads the old way, slower.
  # COMFY_DYNAMIC_VRAM=1 / 0 decides outright.
  DYNAMIC_VRAM="${COMFY_DYNAMIC_VRAM:-auto}"
  MEM_AVAILABLE_MB="$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo 2>/dev/null || echo 0)"
  MEM_AVAILABLE_MB="${MEM_AVAILABLE_MB:-0}"
  if [[ "$DYNAMIC_VRAM" == "auto" ]]; then
    if grep -qi microsoft /proc/version 2>/dev/null; then
      # WSL: the VM's memory is a slice of the laptop's, shared with every container and tool
      # on it, and page cache counts as "available" while pinned buffers need free pages — the
      # pinned read failed here with 9 GB "available". Off unless asked for.
      DYNAMIC_VRAM="0"
      echo "💾 ComfyUI: --disable-dynamic-vram under WSL — dynamic loading pins about twice a checkpoint's"
      echo "   size in RAM and failed here with 'pread failed (errno=12)'. COMFY_DYNAMIC_VRAM=1 turns it on."
    elif [[ "$MEM_AVAILABLE_MB" -gt 0 && "$MEM_AVAILABLE_MB" -lt 8192 ]]; then
      DYNAMIC_VRAM="0"
      echo "💾 ComfyUI: --disable-dynamic-vram — ${MEM_AVAILABLE_MB} MB of RAM is available, and dynamic loading"
      echo "   pins about twice a checkpoint's size in RAM. Free RAM, or set COMFY_DYNAMIC_VRAM=1."
    else
      DYNAMIC_VRAM="1"
    fi
  fi
  # Only a ComfyUI with dynamic VRAM knows --disable-dynamic-vram. Older checkouts, and builds
  # where it is gone again, have no such flag: argparse rejects it and ComfyUI exits at once
  # ("unrecognized arguments: --disable-dynamic-vram"), so the whole of image and video
  # generation was down while warmup waited 600 s for a server that had already quit. Such a
  # ComfyUI always uses the estimate-based loader the flag asks for, so leaving the flag out
  # changes nothing about how it loads models. Ask the checkout itself, not its version number.
  if [[ "${DYNAMIC_VRAM,,}" =~ ^(0|off|false|no)$ ]]; then
    if grep -q -- '"--disable-dynamic-vram"' "$COMFY_DIR/comfy/cli_args.py" 2>/dev/null; then
      EXTRA_ARGS+=("--disable-dynamic-vram")
    else
      echo "💾 ComfyUI: this checkout has no dynamic VRAM, so models already load the classic way;"
      echo "   --disable-dynamic-vram is not passed (this ComfyUI would refuse it)."
    fi
  fi
fi

# ComfyUI's SQLite database (user/comfyui.db) must not live on a Windows drive under WSL:
# SQLite file locking over the /mnt/c bridge can block forever, and ComfyUI's main thread
# then froze in that call, so every request (status, /prompt, images) timed out while the
# process still looked alive. Keep it on the Linux disk instead; the existing file is
# copied over once so nothing is lost. COMFY_DATABASE_URL overrides this.
if [[ -n "${COMFY_DATABASE_URL:-}" ]]; then
  EXTRA_ARGS+=("--database-url" "$COMFY_DATABASE_URL")
elif grep -qi microsoft /proc/version 2>/dev/null && [[ "$COMFY_DIR" == /mnt/* ]] \
    && grep -q -- '"--database-url"' "$COMFY_DIR/comfy/cli_args.py" 2>/dev/null; then
  DB_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/homepilot/comfyui"
  mkdir -p "$DB_DIR"
  if [[ ! -f "$DB_DIR/comfyui.db" && -f "$COMFY_DIR/user/comfyui.db" ]]; then
    cp "$COMFY_DIR/user/comfyui.db" "$DB_DIR/comfyui.db" 2>/dev/null || true
  fi
  EXTRA_ARGS+=("--database-url" "sqlite:///$DB_DIR/comfyui.db")
  echo "🗄️  ComfyUI: database at $DB_DIR/comfyui.db (on the Linux disk; SQLite on /mnt/c can hang under WSL)."
fi

cd "$COMFY_DIR"
exec "$PYTHON" main.py \
  --listen 0.0.0.0 \
  --port "$COMFY_PORT" \
  "${EXTRA_ARGS[@]}" \
  "$@"
