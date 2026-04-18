#!/bin/bash
set -e

echo "========================================"
echo "  HomePilot - Self-Hosted Container"
echo "========================================"

# Ensure data directories exist
mkdir -p /home/user/app/data/uploads
mkdir -p /home/user/app/data/comfy_cache
mkdir -p /home/user/app/data/models

# ComfyUI persistence. The image ships ComfyUI at /opt/ComfyUI (read-only
# from the user's perspective). The named volume at /home/user/app/data
# is the only writable area that survives container recreation
# (applyUpdate stop + remove + start), so point ComfyUI's models /
# output / input dirs at it via symlinks.
#
# If a previous version of the image wrote to /opt/ComfyUI/{models,
# output,input}, we preserve that content by moving it into the volume
# the first time the symlink is set up.
mkdir -p /home/user/app/data/comfy/models
mkdir -p /home/user/app/data/comfy/output
mkdir -p /home/user/app/data/comfy/input
for sub in models output input; do
    target="/opt/ComfyUI/${sub}"
    persist="/home/user/app/data/comfy/${sub}"
    if [ -d "$target" ] && [ ! -L "$target" ]; then
        if [ -n "$(ls -A "$target" 2>/dev/null || true)" ]; then
            cp -n -R "$target"/. "$persist"/ 2>/dev/null || true
        fi
        rm -rf "$target"
    fi
    ln -snf "$persist" "$target"
done

# Configure backend mode
export HOMEPILOT_MODE="${HOMEPILOT_MODE:-container}"
export HOMEPILOT_LLM_BACKEND="${HOMEPILOT_LLM_BACKEND:-openai}"
export HOMEPILOT_PORT=8000
# Backend → ComfyUI on loopback. supervisord also sets this in the
# backend program's environment; the export here is a belt-and-braces
# guarantee for anything that reads it before supervisord hands over.
export COMFY_BASE_URL="${COMFY_BASE_URL:-http://127.0.0.1:8188}"

# Detect GPU availability
if command -v nvidia-smi &> /dev/null; then
    echo "GPU detected:"
    nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null || true
    export HOMEPILOT_GPU_AVAILABLE="true"
else
    echo "No GPU detected - running in CPU mode"
    export HOMEPILOT_GPU_AVAILABLE="false"
fi

# Detect RunPod environment
if [ -n "$RUNPOD_POD_ID" ]; then
    echo "RunPod environment detected (Pod: $RUNPOD_POD_ID)"
    export HOMEPILOT_RUNTIME="runpod"
fi

# Detect Colab environment
if [ -n "$COLAB_RELEASE_TAG" ] || [ -d "/content" ]; then
    echo "Google Colab environment detected"
    export HOMEPILOT_RUNTIME="colab"
fi

echo ""
echo "Starting services via supervisord..."
echo "  - Nginx (reverse proxy)  on port 7860"
echo "  - Backend (FastAPI)      on port 8000 (loopback)"
echo "  - ComfyUI (diffusion)    on port 8188 (loopback)"
echo ""
echo "Access HomePilot at: http://localhost:7860"
echo "========================================"

exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
