#!/bin/bash
set -e

echo "========================================"
echo "  HomePilot - Self-Hosted Container"
echo "========================================"

# Ensure data directories exist
mkdir -p /home/user/app/data/uploads
mkdir -p /home/user/app/data/comfy_cache
mkdir -p /home/user/app/data/models

# Configure backend mode
export HOMEPILOT_MODE="${HOMEPILOT_MODE:-container}"
export HOMEPILOT_LLM_BACKEND="${HOMEPILOT_LLM_BACKEND:-openai}"
export HOMEPILOT_PORT=8000

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
echo "  - Nginx (reverse proxy) on port 7860"
echo "  - Backend (FastAPI) on port 8000"
echo ""
echo "Access HomePilot at: http://localhost:7860"
echo "========================================"

exec supervisord -c /etc/supervisor/conf.d/supervisord.conf
