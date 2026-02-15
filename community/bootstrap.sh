#!/usr/bin/env bash
# ============================================================================
# HomePilot Community Gallery — Bootstrap Script
#
# One-shot setup for the Cloudflare R2 + Worker + Pages persona gallery.
#
# Prerequisites:
#   - Node.js 18+
#   - wrangler CLI (npm i -g wrangler)
#   - Cloudflare account (wrangler login)
#
# Usage:
#   chmod +x bootstrap.sh
#   ./bootstrap.sh
#
# Environment overrides:
#   R2_BUCKET              — R2 bucket name (default: homepilot)
#   CLOUDFLARE_ACCOUNT_ID  — Cloudflare account ID (auto-detected if not set)
#   CLOUDFLARE_API_TOKEN   — API token (falls back to wrangler OAuth token)
#   WORKER_NAME            — Worker name   (default: homepilot-persona-gallery)
#   PAGES_NAME             — Pages project (default: homepilot-persona-gallery-pages)
#   SAMPLE_DIR             — Path to sample files (default: ./sample)
#   PAGES_DIR              — Path to pages files  (default: ./pages)
#   PERSONA_ID             — Sample persona ID    (default: scarlett_exec_secretary)
#   VERSION                — Sample version        (default: 1.0.0)
#   MAX_RETRIES            — Upload retry attempts (default: 4)
# ============================================================================
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────────────
R2_BUCKET="${R2_BUCKET:-homepilot}"
WORKER_NAME="${WORKER_NAME:-homepilot-persona-gallery}"
PAGES_NAME="${PAGES_NAME:-homepilot-persona-gallery-pages}"
SAMPLE_DIR="${SAMPLE_DIR:-./sample}"
PAGES_DIR="${PAGES_DIR:-./pages}"
PERSONA_ID="${PERSONA_ID:-scarlett_exec_secretary}"
VERSION="${VERSION:-1.0.0}"
MAX_RETRIES="${MAX_RETRIES:-4}"

# R2 object keys — Scarlett
REGISTRY_KEY="registry/registry.json"
PKG_KEY="packages/${PERSONA_ID}/${VERSION}/persona.hpersona"
PREVIEW_KEY="previews/${PERSONA_ID}/${VERSION}/preview.webp"
CARD_KEY="previews/${PERSONA_ID}/${VERSION}/card.json"

# R2 object keys — Atlas
ATLAS_ID="atlas_research_assistant"
ATLAS_PKG_KEY="packages/${ATLAS_ID}/${VERSION}/persona.hpersona"
ATLAS_CARD_KEY="previews/${ATLAS_ID}/${VERSION}/card.json"
ATLAS_PREVIEW_KEY="previews/${ATLAS_ID}/${VERSION}/preview.webp"

# Local files
LOCAL_REGISTRY="${SAMPLE_DIR}/registry.json"
LOCAL_CARD="${SAMPLE_DIR}/card.json"

# Paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
R2_UPLOAD_SCRIPT="${SCRIPT_DIR}/scripts/r2-upload.mjs"

# Track failures
UPLOAD_FAILURES=0

# ── Helpers ─────────────────────────────────────────────────────────────────
log()  { echo -e "\033[1;36m[INFO]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
err()  { echo -e "\033[1;31m[ERR]\033[0m $*"; }
ok()   { echo -e "\033[1;32m[ OK ]\033[0m $*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Missing: $1 — install it first."; exit 1; }
}

# Upload a file to R2 with exponential backoff retries.
# Uses Node.js helper (api.cloudflare.com) as primary method,
# falls back to wrangler CLI if the helper is unavailable.
r2_upload() {
  local r2_key="$1"
  local local_file="$2"
  local content_type="$3"
  local attempt=1
  local wait_secs=2

  while (( attempt <= MAX_RETRIES )); do
    log "  Attempt ${attempt}/${MAX_RETRIES}: ${r2_key}"

    # Primary: Node.js helper via Cloudflare API (works in WSL)
    if [[ -f "${R2_UPLOAD_SCRIPT}" ]]; then
      if node "${R2_UPLOAD_SCRIPT}" "${R2_BUCKET}" "${r2_key}" "${local_file}" "${content_type}" 2>&1; then
        ok "  Uploaded: ${r2_key}"
        return 0
      fi
    # Fallback: wrangler CLI (uses R2 S3 endpoint, may timeout in WSL)
    else
      if wrangler r2 object put "${R2_BUCKET}/${r2_key}" \
           --file "${local_file}" \
           --content-type "${content_type}" \
           --remote 2>&1; then
        ok "  Uploaded: ${r2_key}"
        return 0
      fi
    fi

    if (( attempt < MAX_RETRIES )); then
      warn "  Upload failed, retrying in ${wait_secs}s..."
      sleep "${wait_secs}"
      wait_secs=$(( wait_secs * 2 ))
    fi
    attempt=$(( attempt + 1 ))
  done

  err "  Failed after ${MAX_RETRIES} attempts: ${r2_key}"
  UPLOAD_FAILURES=$(( UPLOAD_FAILURES + 1 ))
  return 1
}

# ── Checks ──────────────────────────────────────────────────────────────────
need_cmd wrangler
need_cmd node

log "Verifying Cloudflare login..."
if ! wrangler whoami >/dev/null 2>&1; then
  err "Not logged in. Run: wrangler login"
  exit 1
fi

# Auto-detect CLOUDFLARE_ACCOUNT_ID if not set
if [[ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]]; then
  # Try .env file in community directory
  if [[ -f "${SCRIPT_DIR}/.env" ]]; then
    DETECTED_ACCOUNT=$(grep -E '^CLOUDFLARE_ACCOUNT_ID=' "${SCRIPT_DIR}/.env" 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'" || true)
  fi
  # Try wrangler whoami output
  if [[ -z "${DETECTED_ACCOUNT:-}" ]]; then
    DETECTED_ACCOUNT=$(wrangler whoami 2>&1 | grep -oE '[a-f0-9]{32}' | head -1 || true)
  fi
  # Try wrangler config files
  if [[ -z "${DETECTED_ACCOUNT:-}" ]]; then
    for cfg in "$HOME/.wrangler/config/default.toml" "$HOME/.config/.wrangler/config/default.toml"; do
      if [[ -f "$cfg" ]]; then
        DETECTED_ACCOUNT=$(grep -E 'account_id' "$cfg" 2>/dev/null | grep -oE '[a-f0-9]{32}' | head -1 || true)
        [[ -n "${DETECTED_ACCOUNT:-}" ]] && break
      fi
    done
  fi
  if [[ -n "${DETECTED_ACCOUNT:-}" ]]; then
    export CLOUDFLARE_ACCOUNT_ID="${DETECTED_ACCOUNT}"
    log "Auto-detected account ID: ${CLOUDFLARE_ACCOUNT_ID}"
  else
    err "CLOUDFLARE_ACCOUNT_ID not set and could not be auto-detected."
    err "Set it via: export CLOUDFLARE_ACCOUNT_ID=<your-account-id>"
    err "Or create ${SCRIPT_DIR}/.env with: CLOUDFLARE_ACCOUNT_ID=<your-account-id>"
    exit 1
  fi
fi

for f in "$LOCAL_REGISTRY" "$LOCAL_CARD"; do
  if [[ ! -f "$f" ]]; then
    err "Missing required file: $f"
    exit 1
  fi
done

# ── 1) R2 Bucket ───────────────────────────────────────────────────────────
log "Ensuring R2 bucket: ${R2_BUCKET}"
CREATE_OUTPUT=$(wrangler r2 bucket create "${R2_BUCKET}" 2>&1) && {
  log "  Bucket created."
} || {
  if echo "$CREATE_OUTPUT" | grep -q "already exists"; then
    log "  Bucket already exists."
  else
    err "  Failed to create bucket: $CREATE_OUTPUT"
    exit 1
  fi
}

# ── 2) Build .hpersona packages from sample dirs if not pre-built ─────────
build_hpersona() {
  local persona_dir="$1"
  local out_file="$2"
  if [[ -d "$persona_dir" ]] && [[ -f "${persona_dir}/manifest.json" ]]; then
    log "  Building package: ${out_file}"

    # Validate: assets/ must exist with at least one avatar image (v2 requirement)
    if [[ ! -d "${persona_dir}/assets" ]]; then
      err "  Missing assets/ directory in ${persona_dir} — refusing to build broken package."
      err "  Persona packages require assets/avatar_*.png and assets/thumb_avatar_*.webp"
      return 1
    fi

    # Build the v2 package with all expected directories
    local zip_dirs="manifest.json blueprint/"
    [[ -d "${persona_dir}/dependencies" ]] && zip_dirs="${zip_dirs} dependencies/"
    [[ -d "${persona_dir}/preview" ]]      && zip_dirs="${zip_dirs} preview/"
    zip_dirs="${zip_dirs} assets/"

    (cd "$persona_dir" && zip -r "${out_file}" ${zip_dirs})

    # Post-build validation: verify avatar files are present in the ZIP
    if ! unzip -l "${out_file}" 2>/dev/null | grep -qE 'assets/avatar_.*\.(png|jpg|jpeg|webp)'; then
      err "  Package validation failed: no avatar_* image found in assets/"
      err "  Expected: assets/avatar_<name>.png (or .jpg/.webp)"
      rm -f "${out_file}"
      return 1
    fi

    if ! unzip -l "${out_file}" 2>/dev/null | grep -qE 'assets/thumb_avatar_.*\.webp'; then
      warn "  Package missing thumbnail (assets/thumb_avatar_*.webp) — gallery previews may be degraded."
    fi

    ok "  Package built and validated: ${out_file}"
  fi
}

SCARLETT_PKG="${SAMPLE_DIR}/scarlett.hpersona"
ATLAS_PKG="${SAMPLE_DIR}/atlas.hpersona"

# Build packages if sample dirs exist but packages don't
[[ ! -f "$SCARLETT_PKG" ]] && build_hpersona "${SAMPLE_DIR}/scarlett" "$(cd "${SAMPLE_DIR}" && pwd)/scarlett.hpersona"
[[ ! -f "$ATLAS_PKG" ]] && build_hpersona "${SAMPLE_DIR}/atlas" "$(cd "${SAMPLE_DIR}" && pwd)/atlas.hpersona"

# ── 3) Upload sample objects (with retries) ──────────────────────────────
log "Uploading registry..."
r2_upload "${REGISTRY_KEY}" "${LOCAL_REGISTRY}" "application/json; charset=utf-8" || true

log "Uploading Scarlett card..."
r2_upload "${CARD_KEY}" "${LOCAL_CARD}" "application/json; charset=utf-8" || true

# Scarlett package
if [[ -f "$SCARLETT_PKG" ]]; then
  log "Uploading Scarlett package..."
  r2_upload "${PKG_KEY}" "${SCARLETT_PKG}" "application/octet-stream" || true
else
  warn "No Scarlett package at ${SCARLETT_PKG} — skipping."
fi

# Scarlett preview image (optional, supports webp/png/jpg)
for ext in webp png jpg jpeg; do
  LOCAL_PREVIEW="${SAMPLE_DIR}/scarlett/preview.${ext}"
  [[ ! -f "$LOCAL_PREVIEW" ]] && LOCAL_PREVIEW="${SAMPLE_DIR}/preview.${ext}"
  if [[ -f "$LOCAL_PREVIEW" ]]; then
    case "$ext" in
      webp) ct="image/webp" ;;
      png)  ct="image/png" ;;
      *)    ct="image/jpeg" ;;
    esac
    PREVIEW_R2_KEY="previews/${PERSONA_ID}/${VERSION}/preview.${ext}"
    log "Uploading Scarlett preview (${ext})..."
    r2_upload "${PREVIEW_R2_KEY}" "${LOCAL_PREVIEW}" "${ct}" || true
    break
  fi
done

# Atlas card
ATLAS_CARD_FILE="${SAMPLE_DIR}/atlas/preview/card.json"
if [[ -f "$ATLAS_CARD_FILE" ]]; then
  log "Uploading Atlas card..."
  r2_upload "${ATLAS_CARD_KEY}" "${ATLAS_CARD_FILE}" "application/json; charset=utf-8" || true
fi

# Atlas package
if [[ -f "$ATLAS_PKG" ]]; then
  log "Uploading Atlas package..."
  r2_upload "${ATLAS_PKG_KEY}" "${ATLAS_PKG}" "application/octet-stream" || true
else
  warn "No Atlas package at ${ATLAS_PKG} — skipping."
fi

# Atlas preview image (optional, supports webp/png/jpg)
for ext in webp png jpg jpeg; do
  LOCAL_ATLAS_PREVIEW="${SAMPLE_DIR}/atlas/preview.${ext}"
  if [[ -f "$LOCAL_ATLAS_PREVIEW" ]]; then
    case "$ext" in
      webp) ct="image/webp" ;;
      png)  ct="image/png" ;;
      *)    ct="image/jpeg" ;;
    esac
    log "Uploading Atlas preview (${ext})..."
    r2_upload "${ATLAS_PREVIEW_KEY}" "${LOCAL_ATLAS_PREVIEW}" "${ct}" || true
    break
  fi
done

# Report upload results
if (( UPLOAD_FAILURES > 0 )); then
  warn "${UPLOAD_FAILURES} upload(s) failed. You can re-run the script to retry,"
  warn "or upload manually via Cloudflare Dashboard > R2 > ${R2_BUCKET}."
fi

# ── 4) Deploy Worker ───────────────────────────────────────────────────────
WORKER_DIR="${SCRIPT_DIR}/worker"
if [[ -d "$WORKER_DIR" ]]; then
  log "Deploying Worker: ${WORKER_NAME}"
  pushd "${WORKER_DIR}" >/dev/null
  npm install --silent 2>/dev/null || true
  wrangler deploy
  popd >/dev/null
  log "  Worker deployed."
else
  warn "Worker dir not found at ${WORKER_DIR} — skipping."
fi

# ── 5) Deploy Pages (optional) ────────────────────────────────────────────
if [[ -d "${PAGES_DIR}" ]]; then
  log "Deploying Pages: ${PAGES_NAME}"

  # Create project if it doesn't exist
  if wrangler pages project list 2>/dev/null | grep -q "${PAGES_NAME}"; then
    log "  Pages project exists."
  else
    log "  Creating Pages project..."
    wrangler pages project create "${PAGES_NAME}" --production-branch main 2>/dev/null \
      || warn "  Pages project create failed — create it once in Cloudflare Dashboard, then rerun."
  fi

  wrangler pages deploy "${PAGES_DIR}" --project-name "${PAGES_NAME}" 2>/dev/null \
    || warn "  Pages deploy failed — check Cloudflare Dashboard."
  log "  Pages deployed."
else
  warn "No pages dir at ${PAGES_DIR} — skipping."
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
if (( UPLOAD_FAILURES > 0 )); then
  warn "Bootstrap finished with ${UPLOAD_FAILURES} upload failure(s)."
else
  log "Bootstrap complete!"
fi
echo ""
echo "  Worker endpoints (use the *.workers.dev URL from deploy output):"
echo "    GET /registry.json                   — persona catalog"
echo "    GET /v/${PERSONA_ID}/${VERSION}       — preview image"
echo "    GET /c/${PERSONA_ID}/${VERSION}       — card data"
echo "    GET /p/${PERSONA_ID}/${VERSION}       — .hpersona package"
echo "    GET /health                           — health check"
echo ""
echo "  Next steps:"
echo "    1. Set COMMUNITY_GALLERY_URL in HomePilot .env to your Worker URL"
echo "    2. Restart HomePilot to enable the Community Gallery tab"
echo ""
