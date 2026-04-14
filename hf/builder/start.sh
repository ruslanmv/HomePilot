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
# On HF Spaces (SPACE_ID is set) default to qwen2.5:0.5b for faster
# first-token latency on CPU-basic.  Non-destructive — explicit
# OLLAMA_MODEL env always wins.
if [ -z "${OLLAMA_MODEL:-}" ] && [ -n "${SPACE_ID:-}" ]; then
    export OLLAMA_MODEL="qwen2.5:0.5b"
fi
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

# ── 2b. Pre-warm the Ollama runner (non-blocking) ───────
# Loads the model into RAM so the first real user chat doesn't pay
# the cold-start cost.  Override: OLLAMA_WARMUP=false
if [ "${OLLAMA_WARMUP:-true}" = "true" ]; then
    echo "       · pre-warming runner (background)..."
    (
        curl -sSf -X POST http://127.0.0.1:11434/api/chat \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"${OLLAMA_MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":false,\"options\":{\"num_predict\":1}}" \
            > /dev/null 2>&1 || true
    ) &
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

# ── Chata: additive persona -> project bootstrap ──────────────────
# Imports every bundled .hpersona as a HomePilot Project so the UI
# is populated on first visit.  Optional — can be disabled via env:
#   ENABLE_PROJECT_BOOTSTRAP=false
# to ship a clean HomePilot without any pre-installed personas.
#
# Runs in the background AFTER the main server starts (so /health is
# reachable).  Output is tee'd to stdout so failures are visible in
# the HF Space run logs.  Idempotent — gated by a marker file.
if [ "${ENABLE_PROJECT_BOOTSTRAP:-true}" = "true" ] \
   && [ -f /app/chata_project_bootstrap.py ]; then
    (
        sleep 5
        for attempt in 1 2; do
            python3 /app/chata_project_bootstrap.py \
                --personas-dir "${CHATA_PERSONAS_DIR:-/app/chata-personas}" \
                --api-base http://127.0.0.1:7860 \
                --marker /tmp/homepilot/data/.projects_bootstrapped \
                $([ "$attempt" -gt 1 ] && echo "--force") \
                && break
            echo "[chata-bootstrap] retry in 30s..."
            sleep 30
        done
    ) 2>&1 | tee -a /tmp/homepilot/data/bootstrap.log &
fi

exec python3 /app/hf_wrapper.py
