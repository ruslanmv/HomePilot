#!/usr/bin/env bash
# Render the essay-to-video master timeline (Remotion Assembly composition).
#
# Usage:
#   ./scripts/render-essay-assembly.sh <canvas> <props.json> <out.mp4> [extra remotion args...]
#
#   canvas: youtube-16-9 | shorts-9-16 | social-1-1
#   props:  {"scenes":[...], "audioUrl":"...", "captions":[...]}
#           (see frontend/src/ui/studio/remotion/README.md)
#
# Finds a usable headless Chromium automatically (system Chrome, Playwright
# browsers, or lets Remotion download its own). Remotion v4 bundles its own
# encoder - no system ffmpeg required.
set -euo pipefail

CANVAS="${1:?canvas required: youtube-16-9 | shorts-9-16 | social-1-1}"
PROPS="${2:?props.json required}"
OUT="${3:?output .mp4 path required}"
shift 3 || true

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="$REPO_ROOT/frontend/src/ui/studio/remotion"
PROPS="$(cd "$(dirname "$PROPS")" && pwd)/$(basename "$PROPS")"
mkdir -p "$(dirname "$OUT")"
OUT="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"

if [ ! -d "$WORKSPACE/node_modules" ]; then
  echo "[render] installing Remotion workspace deps (first run)..."
  (cd "$WORKSPACE" && npm install --no-audit --no-fund)
fi

# Best-available browser executable; empty lets Remotion manage its own.
BROWSER=""
for candidate in \
  "${REMOTION_BROWSER_EXECUTABLE:-}" \
  /opt/pw-browsers/chromium_headless_shell-*/chrome-linux/headless_shell \
  "$(command -v google-chrome || true)" \
  "$(command -v chromium || true)" \
  "$(command -v chromium-browser || true)"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    BROWSER="$candidate"
    break
  fi
done

ARGS=(remotion render index.ts "Assembly-$CANVAS" "$OUT" "--props=$PROPS")
[ -n "$BROWSER" ] && ARGS+=("--browser-executable=$BROWSER")

echo "[render] Assembly-$CANVAS -> $OUT"
(cd "$WORKSPACE" && npx "${ARGS[@]}" "$@")
