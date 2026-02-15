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
#   R2_BUCKET        — R2 bucket name (default: homepilot-personas)
#   WORKER_NAME      — Worker name   (default: homepilot-persona-gallery)
#   PAGES_NAME       — Pages project (default: homepilot-persona-gallery-pages)
#   SAMPLE_DIR       — Path to sample files (default: ./sample)
#   PAGES_DIR        — Path to pages files  (default: ./pages)
#   PERSONA_ID       — Sample persona ID    (default: scarlett_exec_secretary)
#   VERSION          — Sample version        (default: 1.0.0)
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

# R2 object keys
REGISTRY_KEY="registry/registry.json"
PKG_KEY="packages/${PERSONA_ID}/${VERSION}/persona.hpersona"
PREVIEW_KEY="previews/${PERSONA_ID}/${VERSION}/preview.webp"
CARD_KEY="previews/${PERSONA_ID}/${VERSION}/card.json"

# Local files
LOCAL_REGISTRY="${SAMPLE_DIR}/registry.json"
LOCAL_CARD="${SAMPLE_DIR}/card.json"

# ── Helpers ─────────────────────────────────────────────────────────────────
log()  { echo -e "\033[1;36m[INFO]\033[0m $*"; }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; }
err()  { echo -e "\033[1;31m[ERR]\033[0m $*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Missing: $1 — install it first."; exit 1; }
}

# ── Checks ──────────────────────────────────────────────────────────────────
need_cmd wrangler
need_cmd node

log "Verifying Cloudflare login..."
if ! wrangler whoami >/dev/null 2>&1; then
  err "Not logged in. Run: wrangler login"
  exit 1
fi

for f in "$LOCAL_REGISTRY" "$LOCAL_CARD"; do
  if [[ ! -f "$f" ]]; then
    err "Missing required file: $f"
    exit 1
  fi
done

# ── 1) R2 Bucket ───────────────────────────────────────────────────────────
log "Ensuring R2 bucket: ${R2_BUCKET}"
if wrangler r2 bucket list 2>/dev/null | awk '{print $1}' | grep -qx "${R2_BUCKET}"; then
  log "  Bucket exists."
else
  log "  Creating bucket..."
  wrangler r2 bucket create "${R2_BUCKET}"
  log "  Bucket created."
fi

# ── 2) Upload sample objects ───────────────────────────────────────────────
log "Uploading registry -> r2://${R2_BUCKET}/${REGISTRY_KEY}"
wrangler r2 object put "${R2_BUCKET}/${REGISTRY_KEY}" \
  --file "${LOCAL_REGISTRY}" \
  --content-type "application/json; charset=utf-8"

log "Uploading card -> r2://${R2_BUCKET}/${CARD_KEY}"
wrangler r2 object put "${R2_BUCKET}/${CARD_KEY}" \
  --file "${LOCAL_CARD}" \
  --content-type "application/json; charset=utf-8"

# Optional: upload .hpersona package if present
LOCAL_PKG="${SAMPLE_DIR}/persona.hpersona"
if [[ -f "$LOCAL_PKG" ]]; then
  log "Uploading package -> r2://${R2_BUCKET}/${PKG_KEY}"
  wrangler r2 object put "${R2_BUCKET}/${PKG_KEY}" \
    --file "${LOCAL_PKG}" \
    --content-type "application/octet-stream"
else
  warn "No sample .hpersona at ${LOCAL_PKG} — skipping package upload."
fi

# Optional: upload preview image if present
LOCAL_PREVIEW="${SAMPLE_DIR}/preview.webp"
if [[ -f "$LOCAL_PREVIEW" ]]; then
  log "Uploading preview -> r2://${R2_BUCKET}/${PREVIEW_KEY}"
  wrangler r2 object put "${R2_BUCKET}/${PREVIEW_KEY}" \
    --file "${LOCAL_PREVIEW}" \
    --content-type "image/webp"
else
  warn "No sample preview at ${LOCAL_PREVIEW} — skipping preview upload."
fi

# ── 3) Deploy Worker ───────────────────────────────────────────────────────
WORKER_DIR="$(dirname "$0")/worker"
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

# ── 4) Deploy Pages (optional) ────────────────────────────────────────────
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
log "Bootstrap complete!"
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
