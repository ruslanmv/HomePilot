#!/bin/bash
# =============================================================================
# HomePilot — HF Spaces Startup Script
# =============================================================================
# Starts Ollama (sidecar) + HomePilot (FastAPI + React frontend) in a single
# container. Chata personas are auto-imported on first run.
#
# Production-grade behaviours:
#   - Ollama health check waits up to 60s (HF cold-starts can be slow).
#   - Model pull retries up to 3 times, falls through a chain of lightweight
#     free-tier-friendly models, and is NEVER fatal: the app still boots so
#     the admin UI can show the setup wizard even when Ollama is offline.
#   - All paths under /tmp (HF Spaces only grants write access there).
# =============================================================================

# NOTE: no `set -e` at the top. We want the boot to continue even if the
# model pull fails — the admin UI can guide the user through a manual pull.
set -uo pipefail

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
# Primary model — small, multilingual, instruction-tuned, free-tier friendly.
export OLLAMA_MODEL=${OLLAMA_MODEL:-qwen2.5:1.5b}
# Comma-separated fallback chain tried if the primary fails to pull. Each is
# under ~1.5 GB on disk and runs comfortably in the HF free tier (16 GB RAM,
# no GPU). Order: strong-but-larger → smaller → tiny last-resort.
export OLLAMA_FALLBACK_MODELS=${OLLAMA_FALLBACK_MODELS:-qwen2.5:0.5b,llama3.2:1b,smollm2:360m}
export COMFY_BASE_URL=""
export MEDIA_BASE_URL=""
export AVATAR_SERVICE_URL=""
export CORS_ORIGINS="*"
export API_KEY=${API_KEY:-}

# ── 1. Start Ollama ─────────────────────────────────────
echo "[1/4] Starting Ollama..."
ollama serve &
OLLAMA_PID=$!

OLLAMA_READY=false
for i in $(seq 1 60); do
    if curl -sf http://127.0.0.1:11434/api/tags > /dev/null 2>&1; then
        echo "       ✓ Ollama ready (${i}s)"
        OLLAMA_READY=true
        break
    fi
    sleep 1
done

if [ "$OLLAMA_READY" != "true" ]; then
    echo "       ⚠ Ollama did not come up within 60s — continuing anyway"
    echo "         The UI setup wizard can retry the model pull after boot."
fi

# ── 2. Pull default model (with retries + fallback chain) ───
#
# We try the primary model up to 3 times. If all retries fail, we walk the
# OLLAMA_FALLBACK_MODELS chain. The app boots regardless — a missing model
# degrades gracefully to the setup wizard, which is vastly better UX than a
# container crash loop.
pull_with_retries () {
    local model="$1"
    local tries=3
    for attempt in $(seq 1 "$tries"); do
        echo "       ↓ Pulling ${model} (attempt ${attempt}/${tries})..."
        if ollama pull "$model" 2>&1 | tail -3; then
            echo "       ✓ ${model} pulled"
            return 0
        fi
        echo "       ✗ pull failed for ${model}"
        sleep $((attempt * 2))
    done
    return 1
}

MODEL_OK=false
if [ "$OLLAMA_READY" = "true" ]; then
    echo "[2/4] Checking model: ${OLLAMA_MODEL}..."
    MODEL_CHECK=$(curl -sf http://127.0.0.1:11434/api/tags 2>/dev/null || echo '{"models":[]}')
    if echo "$MODEL_CHECK" | grep -q "${OLLAMA_MODEL}"; then
        echo "       ✓ Model ${OLLAMA_MODEL} already available"
        MODEL_OK=true
    else
        # Try primary, then fallback chain.
        if pull_with_retries "$OLLAMA_MODEL"; then
            MODEL_OK=true
        else
            echo "       ↪ Trying fallback chain: ${OLLAMA_FALLBACK_MODELS}"
            IFS=',' read -ra FALLBACKS <<< "$OLLAMA_FALLBACK_MODELS"
            for fb in "${FALLBACKS[@]}"; do
                fb=$(echo "$fb" | xargs)  # trim whitespace
                [ -z "$fb" ] && continue
                if pull_with_retries "$fb"; then
                    export OLLAMA_MODEL="$fb"
                    MODEL_OK=true
                    echo "       ℹ Using fallback model: ${fb}"
                    break
                fi
            done
        fi
    fi

    if [ "$MODEL_OK" != "true" ]; then
        echo "       ⚠ No model could be pulled. App will boot without a default."
        echo "         Users can pull a model later via the Models page or:"
        echo "         curl -X POST http://127.0.0.1:11434/api/pull -d '{\"name\":\"qwen2.5:1.5b\"}'"
    fi
else
    echo "[2/4] Skipping model pull — Ollama not ready."
fi

# ── 3. Auto-import Chata personas ────────────────────────
echo "[3/4] Importing Chata personas..."
MARKER="/tmp/homepilot/data/.personas_imported"
CHATA_PERSONAS_DIR="${CHATA_PERSONAS_DIR:-/app/chata-personas}"
if [ -f "$MARKER" ]; then
    echo "       ✓ Already imported ($(cat "$MARKER"))"
else
    # Additional sources (colon/comma-separated) and an optional remote pack
    # are picked up by the importer from the environment:
    #   EXTRA_PERSONAS_DIRS=/app/extra-personas,/app/my-custom
    #   SHARED_PERSONAS_URL=https://example.com/packs/latest.zip
    EXTRA_ARGS=""
    if [ -d "/app/custom-personas" ]; then EXTRA_ARGS="$EXTRA_ARGS /app/custom-personas"; fi
    if [ -d "/app/shared-personas" ]; then EXTRA_ARGS="$EXTRA_ARGS /app/shared-personas"; fi
    if python3 /app/auto_import_personas.py "$CHATA_PERSONAS_DIR" /tmp/homepilot/data $EXTRA_ARGS; then
        echo "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$MARKER"
        echo "       ✓ Personas imported"
    else
        echo "       ⚠ Persona import reported an error — continuing"
    fi
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
