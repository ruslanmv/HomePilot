#!/usr/bin/env bash
# Deploy the HomePilot Installer Space (Gradio)
set -euo pipefail

if [[ -z "${HF_TOKEN:-}" ]]; then
  echo "error: HF_TOKEN is required" >&2
  exit 1
fi

HF_SPACE="${HF_SPACE:-ruslanmv/HomePilot-Installer}"
HF_BRANCH="${HF_BRANCH:-main}"
COMMIT_MSG="${COMMIT_MSG:-chore: sync installer}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HF_REMOTE="https://user:${HF_TOKEN}@huggingface.co/spaces/${HF_SPACE}"

STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT

# Clone or init
if git -c credential.helper= clone --quiet --depth 1 --branch "$HF_BRANCH" "$HF_REMOTE" "$STAGE_DIR" 2>/dev/null; then
  echo ">> cloned existing Space"
else
  rm -rf "$STAGE_DIR"
  mkdir -p "$STAGE_DIR"
  git -C "$STAGE_DIR" init -q -b "$HF_BRANCH"
  git -C "$STAGE_DIR" remote add origin "$HF_REMOTE"
fi

# Wipe and copy
find "$STAGE_DIR" -mindepth 1 -maxdepth 1 -not -name '.git' -exec rm -rf {} +
cp "$SCRIPT_DIR/app.py" "$STAGE_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$STAGE_DIR/"
cp "$SCRIPT_DIR/README.md" "$STAGE_DIR/"

# Commit + push
cd "$STAGE_DIR"
git -c user.email="bot@homepilot.dev" -c user.name="HomePilot Installer Bot" add -A

if git diff --cached --quiet; then
  echo ">> no changes"
  exit 0
fi

git -c user.email="bot@homepilot.dev" -c user.name="HomePilot Installer Bot" \
  commit -q -m "$COMMIT_MSG"
git push --force "$HF_REMOTE" "HEAD:${HF_BRANCH}"

echo ">> deployed: https://huggingface.co/spaces/${HF_SPACE}"
