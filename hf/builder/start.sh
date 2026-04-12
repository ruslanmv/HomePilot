#!/bin/bash
# =============================================================================
# HomePilot — HF Spaces Startup Script
# =============================================================================
# Starts Ollama (sidecar) + HomePilot (FastAPI + React frontend) in a single
# container. Chata personas are auto-imported on first run.
# =============================================================================

set -e

echo ""
echo "  ┌──────────────────────────────────────┐"
echo "  │       🏠 HomePilot HF Space          │"
echo "  │    Private AI · Persistent Personas   │"
echo "  └──────────────────────────────────────┘"
echo ""

# ── Writable directories (HF only allows /tmp) ──────────
mkdir -p /tmp/ollama/models /tmp/homepilot/data /tmp/homepilot/uploads /tmp/homepilot/outputs
export OLLAMA_MODELS=/tmp/ollama/models
export HOME=/tmp

# ── Environment ──────────────────────────────────────────
export SQLITE_PATH=/tmp/homepilot/data/homepilot.db
export UPLOAD_DIR=/tmp/homepilot/uploads
export OUTPUT_DIR=/tmp/homepilot/outputs
export DEFAULT_PROVIDER=${DEFAULT_PROVIDER:-ollama}
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=${OLLAMA_MODEL:-qwen2.5:1.5b}
export COMFY_BASE_URL=""
export MEDIA_BASE_URL=""
export AVATAR_SERVICE_URL=""
export CORS_ORIGINS="*"
export API_KEY=${API_KEY:-}

# ── 1. Start Ollama ─────────────────────────────────────
echo "[1/4] Starting Ollama..."
ollama serve &
OLLAMA_PID=$!

for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
        echo "       ✓ Ollama ready (${i}s)"
        break
    fi
    sleep 1
done

# ── 2. Pull default model ───────────────────────────────
echo "[2/4] Checking model: ${OLLAMA_MODEL}..."
MODEL_CHECK=$(curl -sf http://127.0.0.1:11434/api/tags 2>/dev/null || echo '{"models":[]}')
if echo "$MODEL_CHECK" | grep -q "${OLLAMA_MODEL}"; then
    echo "       ✓ Model ${OLLAMA_MODEL} available"
else
    echo "       ↓ Pulling ${OLLAMA_MODEL} (first start only)..."
    ollama pull "${OLLAMA_MODEL}" 2>&1 | tail -3
    echo "       ✓ Model pulled"
fi

# ── 3. Auto-import Chata personas ────────────────────────
echo "[3/4] Importing Chata personas..."
MARKER="/tmp/homepilot/data/.personas_imported"
if [ -f "$MARKER" ]; then
    echo "       ✓ Already imported ($(cat "$MARKER"))"
else
    python3 /app/auto_import_personas.py /app/chata-personas /tmp/homepilot/data
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$MARKER"
    echo "       ✓ Personas imported"
fi

# ── 4. Start HomePilot ───────────────────────────────────
echo "[4/4] Starting HomePilot on :7860..."
echo ""
echo "  ┌──────────────────────────────────────┐"
echo "  │  Ready!                               │"
echo "  │                                       │"
echo "  │  App:      /                          │"
echo "  │  Health:   /health                    │"
echo "  │  API:      /docs                      │"
echo "  │  Gallery:  /community/registry        │"
echo "  │  Chat:     /v1/chat/completions       │"
echo "  └──────────────────────────────────────┘"
echo ""

exec python3 /app/hf_wrapper.py
