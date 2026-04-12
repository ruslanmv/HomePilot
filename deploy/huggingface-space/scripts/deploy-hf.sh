#!/usr/bin/env bash
# =============================================================================
# HomePilot — Hugging Face Space deploy script
# =============================================================================
# Required: HF_TOKEN
# Optional: HF_SPACE (default: ruslanmv/HomePilot), HF_BRANCH (default: main)
# =============================================================================

set -euo pipefail

if [[ -z "${HF_TOKEN:-}" ]]; then
  echo "error: HF_TOKEN is required" >&2
  exit 1
fi

HF_SPACE="${HF_SPACE:-ruslanmv/HomePilot}"
HF_BRANCH="${HF_BRANCH:-main}"
COMMIT_MSG="${COMMIT_MSG:-chore(hf): sync HomePilot to HF Space}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPACE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SPACE_DIR/../.." && pwd)"

STAGE_ROOT="${REPO_ROOT}/.hf-stage"
mkdir -p "$STAGE_ROOT"
STAGE_DIR="$(mktemp -d -p "$STAGE_ROOT" bundle.XXXXXX)"
trap 'rm -rf "$STAGE_DIR"' EXIT

echo "========================================"
echo " HomePilot HF Space Deploy"
echo "========================================"
echo ">> source:    $REPO_ROOT"
echo ">> target:    https://huggingface.co/spaces/$HF_SPACE"
echo ""

HF_REMOTE="https://user:${HF_TOKEN}@huggingface.co/spaces/${HF_SPACE}"

# Clone or init
if git -c credential.helper= clone --quiet --depth 1 --branch "$HF_BRANCH" "$HF_REMOTE" "$STAGE_DIR" 2>/dev/null; then
  echo ">> cloned existing Space"
else
  rm -rf "$STAGE_DIR"
  mkdir -p "$STAGE_DIR"
  git -C "$STAGE_DIR" init -q -b "$HF_BRANCH"
  git -C "$STAGE_DIR" remote add origin "$HF_REMOTE"
fi

find "$STAGE_DIR" -mindepth 1 -maxdepth 1 -not -name '.git' -exec rm -rf {} +

# ── Assemble deploy bundle ──────────────────────────────
echo ">> copying Dockerfile + README + scripts"
install -m 0644 "$SPACE_DIR/Dockerfile"  "$STAGE_DIR/Dockerfile"
install -m 0644 "$SPACE_DIR/README.md"   "$STAGE_DIR/README.md"
install -m 0755 "$SPACE_DIR/start.sh"    "$STAGE_DIR/start.sh"

# Deploy scripts (hf_wrapper, auto_import)
mkdir -p "$STAGE_DIR/deploy/huggingface-space"
install -m 0644 "$SPACE_DIR/hf_wrapper.py"          "$STAGE_DIR/deploy/huggingface-space/hf_wrapper.py"
install -m 0644 "$SPACE_DIR/auto_import_personas.py" "$STAGE_DIR/deploy/huggingface-space/auto_import_personas.py"

echo ">> copying backend/"
mkdir -p "$STAGE_DIR/backend"
cp -R "$REPO_ROOT/backend/app" "$STAGE_DIR/backend/app"
cp    "$REPO_ROOT/backend/requirements.txt" "$STAGE_DIR/backend/requirements.txt"
# Ensure __init__.py exists
touch "$STAGE_DIR/backend/app/__init__.py"

echo ">> copying frontend/"
mkdir -p "$STAGE_DIR/frontend"
while IFS= read -r -d '' entry; do
  name="$(basename "$entry")"
  case "$name" in
    node_modules|dist|.turbo) continue ;;
  esac
  cp -R "$entry" "$STAGE_DIR/frontend/"
done < <(find "$REPO_ROOT/frontend" -mindepth 1 -maxdepth 1 -print0)

echo ">> copying community/sample/"
mkdir -p "$STAGE_DIR/community/sample"
if [[ -d "$REPO_ROOT/community/sample" ]]; then
  cp -R "$REPO_ROOT/community/sample/"* "$STAGE_DIR/community/sample/" 2>/dev/null || true
fi

echo ">> copying chata-personas/"
mkdir -p "$STAGE_DIR/deploy/huggingface-space/chata-personas"
cp "$SPACE_DIR/chata-personas/"*.hpersona "$STAGE_DIR/deploy/huggingface-space/chata-personas/" 2>/dev/null || true
cp "$SPACE_DIR/chata-personas/public_packs.json" "$STAGE_DIR/deploy/huggingface-space/chata-personas/" 2>/dev/null || true

# Cache-bust
echo "$(date -u +%s)" > "$STAGE_DIR/frontend/.cache-bust"

echo ">> commit + push"
cd "$STAGE_DIR"

# Enable Git LFS for binary files (HF requires Xet/LFS for binaries)
git lfs install --local 2>/dev/null || true
git lfs track "*.hpersona" "*.png" "*.jpg" "*.jpeg" "*.webp" "*.svg" "*.woff" "*.woff2" "*.ico" 2>/dev/null || true
git add .gitattributes 2>/dev/null || true

git -c user.email="bot@homepilot.dev" -c user.name="HomePilot Deploy Bot" add -A

if git diff --cached --quiet; then
  echo ">> no changes"
  exit 0
fi

git -c user.email="bot@homepilot.dev" -c user.name="HomePilot Deploy Bot" \
  commit -q -m "$COMMIT_MSG"

MAX_RETRIES=4
DELAY=2
for i in $(seq 1 $MAX_RETRIES); do
  if git push --force "$HF_REMOTE" "HEAD:${HF_BRANCH}" 2>&1; then
    break
  fi
  if [[ $i -eq $MAX_RETRIES ]]; then
    echo "error: push failed after $MAX_RETRIES attempts" >&2
    exit 1
  fi
  echo ">> retry in ${DELAY}s..."
  sleep "$DELAY"
  DELAY=$((DELAY * 2))
done

echo ""
echo "========================================"
echo " Builder Space deployed"
echo " https://huggingface.co/spaces/${HF_SPACE}"
echo "========================================"

# ─────────────────────────────────────────────────────────
# Auto-sync Installer Space
# ─────────────────────────────────────────────────────────
INSTALLER_SPACE="${HF_INSTALLER_SPACE:-ruslanmv/HomePilot-Installer}"
INSTALLER_DIR="$REPO_ROOT/hf/installer"

if [[ -d "$INSTALLER_DIR" ]]; then
  echo ""
  echo ">> syncing Installer Space: $INSTALLER_SPACE"

  INST_STAGE="$(mktemp -d -p "$STAGE_ROOT" installer.XXXXXX)"
  INST_REMOTE="https://user:${HF_TOKEN}@huggingface.co/spaces/${INSTALLER_SPACE}"

  # Clone or init installer Space
  if git -c credential.helper= clone --quiet --depth 1 --branch main "$INST_REMOTE" "$INST_STAGE" 2>/dev/null; then
    :
  else
    rm -rf "$INST_STAGE"
    mkdir -p "$INST_STAGE"
    git -C "$INST_STAGE" init -q -b main
    git -C "$INST_STAGE" remote add origin "$INST_REMOTE"
  fi

  # Wipe and copy installer files (Docker-based: server.py + static/ + Dockerfile)
  find "$INST_STAGE" -mindepth 1 -maxdepth 1 -not -name '.git' -exec rm -rf {} +
  cp "$INSTALLER_DIR/Dockerfile"       "$INST_STAGE/" 2>/dev/null || true
  cp "$INSTALLER_DIR/server.py"        "$INST_STAGE/" 2>/dev/null || true
  cp "$INSTALLER_DIR/requirements.txt" "$INST_STAGE/"
  cp "$INSTALLER_DIR/README.md"        "$INST_STAGE/"
  cp "$INSTALLER_DIR/app.py"           "$INST_STAGE/" 2>/dev/null || true
  if [[ -d "$INSTALLER_DIR/static" ]]; then
    cp -R "$INSTALLER_DIR/static"      "$INST_STAGE/"
  fi

  cd "$INST_STAGE"
  git -c user.email="bot@homepilot.dev" -c user.name="HomePilot Deploy Bot" add -A

  if git diff --cached --quiet; then
    echo ">> installer: no changes"
  else
    git -c user.email="bot@homepilot.dev" -c user.name="HomePilot Deploy Bot" \
      commit -q -m "chore: sync installer from monorepo"

    for i in $(seq 1 $MAX_RETRIES); do
      if git push --force "$INST_REMOTE" "HEAD:main" 2>&1; then
        break
      fi
      if [[ $i -eq $MAX_RETRIES ]]; then
        echo ">> warning: installer push failed (non-fatal)"
        break
      fi
      sleep "$DELAY"
    done
    echo ">> installer synced"
  fi

  rm -rf "$INST_STAGE"
else
  echo ">> installer not found at $INSTALLER_DIR — skipping"
fi

echo ""
echo "========================================"
echo " All Spaces deployed"
echo "   Builder:   https://huggingface.co/spaces/${HF_SPACE}"
echo "   Installer: https://huggingface.co/spaces/${INSTALLER_SPACE}"
echo "========================================"
