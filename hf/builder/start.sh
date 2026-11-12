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

# ── Durable data root ────────────────────────────────────
# HomePilot is the source of truth for conversations, personas, projects,
# memories and generated media, so they must not live on the container's
# scratch disk. Resolution order:
#   1. DATA_DIR                 — explicit (any mounted volume)
#   2. /data                    — a Hugging Face persistent-storage volume
#   3. /tmp/homepilot           — EPHEMERAL: erased on every restart/rebuild
# Attaching persistent storage to the Space is a paid Hugging Face add-on and
# is a deliberate operator action; nothing here provisions it.
if [ -n "${DATA_DIR:-}" ]; then
    HP_DATA_ROOT="${DATA_DIR%/}"
elif [ -d /data ] && [ -w /data ]; then
    HP_DATA_ROOT="/data/homepilot"
else
    HP_DATA_ROOT="/tmp/homepilot"
fi
export HOMEPILOT_DATA_ROOT="$HP_DATA_ROOT"
mkdir -p /tmp/ollama/models "$HP_DATA_ROOT/data" "$HP_DATA_ROOT/uploads" "$HP_DATA_ROOT/outputs" "$HP_DATA_ROOT/backups"
if [ "$HP_DATA_ROOT" = "/tmp/homepilot" ]; then
    export HOMEPILOT_STORAGE_DURABLE=false
    echo "  ⚠️  STORAGE IS EPHEMERAL: data in /tmp/homepilot is erased when this Space restarts."
    echo "      Attach persistent storage (mounts /data) or set DATA_DIR to keep user data."
else
    export HOMEPILOT_STORAGE_DURABLE=true
    echo "  💾 Durable storage: $HP_DATA_ROOT"
    # One-time, non-destructive migration: if this container already wrote data
    # to the old scratch location and the durable root has no database yet,
    # copy it across. Existing durable data is never overwritten.
    if [ ! -f "$HP_DATA_ROOT/data/homepilot.db" ] && [ -f /tmp/homepilot/data/homepilot.db ]; then
        echo "  📦 Migrating existing data from /tmp/homepilot to $HP_DATA_ROOT ..."
        cp -a /tmp/homepilot/data/. "$HP_DATA_ROOT/data/" 2>/dev/null || true
        cp -a /tmp/homepilot/uploads/. "$HP_DATA_ROOT/uploads/" 2>/dev/null || true
        cp -a /tmp/homepilot/outputs/. "$HP_DATA_ROOT/outputs/" 2>/dev/null || true
    fi
fi
export OLLAMA_MODELS=/tmp/ollama/models
export HOME=/tmp
# Daily snapshot of the database and media onto the durable root (kept: 7).
# Background and best-effort: a failed backup never blocks boot.
if [ "$HOMEPILOT_STORAGE_DURABLE" = "true" ]; then
    ( cd /app && SQLITE_PATH="$HP_DATA_ROOT/data/homepilot.db" UPLOAD_DIR="$HP_DATA_ROOT/uploads" \
      OUTPUT_DIR="$HP_DATA_ROOT/outputs" \
      python3 -m app.durable_storage backup --if-older-than 24 --keep 7 \
      >> "$HP_DATA_ROOT/data/backup.log" 2>&1 || true ) &
fi

# ── Environment ──────────────────────────────────────────
export SQLITE_PATH="$HP_DATA_ROOT/data/homepilot.db"
export UPLOAD_DIR="$HP_DATA_ROOT/uploads"
export OUTPUT_DIR="$HP_DATA_ROOT/outputs"
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
MARKER="$HP_DATA_ROOT/data/.personas_imported"
if [ -f "$MARKER" ]; then
    echo "       ✓ Already imported ($(cat "$MARKER"))"
else
    python3 /app/auto_import_personas.py /app/chata-personas "$HP_DATA_ROOT/data"
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
                --marker "$HP_DATA_ROOT/data/.projects_bootstrapped" \
                $([ "$attempt" -gt 1 ] && echo "--force") \
                && break
            echo "[chata-bootstrap] retry in 30s..."
            sleep 30
        done
    ) 2>&1 | tee -a "$HP_DATA_ROOT/data/bootstrap.log" &
fi

exec python3 /app/hf_wrapper.py
