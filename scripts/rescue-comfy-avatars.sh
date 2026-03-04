#!/usr/bin/env bash
# rescue-comfy-avatars.sh
#
# Rescues ALL generated images from ComfyUI into HomePilot's /files/ storage:
#   - Avatars (avatar_*, avatar_instantid_*, avatar_faceswap_*)
#   - Imagine outputs (ComfyUI_*, imagine_*, txt2img_*)
#   - Animate outputs (animate_*, video_*)
#
# Then repairs persona projects so Avatar Studio shows images again.
#
# Usage:
#   bash scripts/rescue-comfy-avatars.sh
#   bash scripts/rescue-comfy-avatars.sh --backend http://localhost:8000
#   bash scripts/rescue-comfy-avatars.sh --comfy http://localhost:8188
#   bash scripts/rescue-comfy-avatars.sh --dry-run

set -euo pipefail

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
COMFY_URL="${COMFY_URL:-http://localhost:8188}"
DRY_RUN=false

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --backend)  BACKEND_URL="$2"; shift 2 ;;
    --comfy)    COMFY_URL="$2"; shift 2 ;;
    --dry-run)  DRY_RUN=true; shift ;;
    -h|--help)
      echo "Usage: $0 [--backend URL] [--comfy URL] [--dry-run]"
      echo ""
      echo "Rescues ALL ComfyUI generated files into HomePilot /files/ storage."
      echo "Covers: avatars, Imagine images, Animate videos."
      echo "Also repairs persona projects so avatars show up in the UI again."
      echo ""
      echo "Options:"
      echo "  --backend URL   HomePilot backend (default: http://localhost:8000)"
      echo "  --comfy URL     ComfyUI base URL  (default: http://localhost:8188)"
      echo "  --dry-run       List files without copying"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

echo "═══════════════════════════════════════════════════════════════"
echo "  Rescue ALL ComfyUI Files → HomePilot /files/"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  ComfyUI:  $COMFY_URL"
echo "  Backend:  $BACKEND_URL"
echo "  Dry run:  $DRY_RUN"
echo ""

# ── Step 1: Gather ALL filenames from ComfyUI history ───────────────

echo "Fetching ComfyUI history for all generated files..."

declare -A ALL_FILES  # associative array for dedup

# Method 1: Query ComfyUI /history for ALL generated filenames
HISTORY=$(curl -sf "${COMFY_URL}/history" 2>/dev/null || echo "{}")
if [ "$HISTORY" != "{}" ]; then
  HISTORY_FILES=$(echo "$HISTORY" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    seen = set()
    for prompt_id, entry in data.items():
        outputs = entry.get('outputs', {})
        for node_id, node_out in outputs.items():
            # Image outputs
            for img in node_out.get('images', []):
                fname = img.get('filename', '')
                if fname and fname not in seen:
                    seen.add(fname)
                    print(fname)
            # Video/GIF outputs
            for vid in node_out.get('gifs', []):
                fname = vid.get('filename', '')
                if fname and fname not in seen:
                    seen.add(fname)
                    print(fname)
            for vid in node_out.get('videos', []):
                fname = vid.get('filename', '')
                if fname and fname not in seen:
                    seen.add(fname)
                    print(fname)
except:
    pass
" 2>/dev/null || true)

  while IFS= read -r f; do
    [ -n "$f" ] && ALL_FILES["$f"]=1
  done <<< "$HISTORY_FILES"
  echo "  Found ${#ALL_FILES[@]} file(s) in ComfyUI history."
fi

# Method 2: Brute-force scan known filename patterns
echo "Scanning for files by pattern (this may take a minute)..."

# All known prefixes used by HomePilot workflows
PREFIXES=(
  "avatar"
  "avatar_instantid"
  "avatar_faceswap"
  "ComfyUI"
  "imagine"
  "txt2img"
  "img2img"
  "animate"
  "video"
  "AnimateDiff"
)

for prefix in "${PREFIXES[@]}"; do
  MISS_COUNT=0
  for i in $(seq 1 500); do
    fname=$(printf "%s_%05d_.png" "$prefix" "$i")
    HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" \
      "${COMFY_URL}/view?filename=${fname}&type=output" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
      ALL_FILES["$fname"]=1
      MISS_COUNT=0
    else
      MISS_COUNT=$((MISS_COUNT + 1))
      # Stop after 10 consecutive misses for this prefix
      if [ "$MISS_COUNT" -ge 10 ]; then
        break
      fi
    fi
  done

  # Also try .mp4 and .gif for animate/video prefixes
  if [[ "$prefix" == "animate" || "$prefix" == "video" || "$prefix" == "AnimateDiff" ]]; then
    for ext in mp4 gif webp; do
      MISS_COUNT=0
      for i in $(seq 1 200); do
        fname=$(printf "%s_%05d_.%s" "$prefix" "$i" "$ext")
        HTTP_CODE=$(curl -sf -o /dev/null -w "%{http_code}" \
          "${COMFY_URL}/view?filename=${fname}&type=output" 2>/dev/null || echo "000")
        if [ "$HTTP_CODE" = "200" ]; then
          ALL_FILES["$fname"]=1
          MISS_COUNT=0
        else
          MISS_COUNT=$((MISS_COUNT + 1))
          if [ "$MISS_COUNT" -ge 10 ]; then
            break
          fi
        fi
      done
    done
  fi
done

TOTAL=${#ALL_FILES[@]}
echo ""
echo "Found $TOTAL total file(s) in ComfyUI."
echo ""

if [ "$TOTAL" -eq 0 ]; then
  echo "No files found in ComfyUI output."
  echo ""
  echo "If you know exact filenames, download manually:"
  echo "  curl -o file.png '${COMFY_URL}/view?filename=FILENAME&type=output'"
  exit 0
fi

# ── Step 2: Download and upload each file ───────────────────────────

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

COPIED=0
SKIPPED=0
FAILED=0

# Sort filenames for nice output
SORTED_FILES=($(echo "${!ALL_FILES[@]}" | tr ' ' '\n' | sort))

for fname in "${SORTED_FILES[@]}"; do
  # Check if already in /files/
  EXISTING=$(curl -sf -o /dev/null -w "%{http_code}" \
    "${BACKEND_URL}/files/${fname}" 2>/dev/null || echo "000")

  if [ "$EXISTING" = "200" ]; then
    echo "  SKIP  $fname (already in /files/)"
    SKIPPED=$((SKIPPED + 1))
    continue
  fi

  if [ "$DRY_RUN" = true ]; then
    echo "  WOULD COPY  $fname"
    COPIED=$((COPIED + 1))
    continue
  fi

  echo -n "  COPY  $fname ... "
  LOCAL="$TMPDIR/$fname"
  if ! curl -sf -o "$LOCAL" "${COMFY_URL}/view?filename=${fname}&type=output"; then
    echo "FAILED (download)"
    FAILED=$((FAILED + 1))
    continue
  fi

  RESP=$(curl -sf -X POST "${BACKEND_URL}/upload" \
    -F "file=@${LOCAL};filename=${fname}" 2>/dev/null || echo "")

  if [ -n "$RESP" ]; then
    URL=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('url',''))" 2>/dev/null || echo "")
    if [ -n "$URL" ]; then
      echo "OK → $URL"
      COPIED=$((COPIED + 1))
    else
      echo "FAILED (no URL in response)"
      FAILED=$((FAILED + 1))
    fi
  else
    echo "FAILED (upload)"
    FAILED=$((FAILED + 1))
  fi

  # Clean up temp file to save disk space
  rm -f "$LOCAL"
done

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Files Rescued:  Copied: $COPIED  Skipped: $SKIPPED  Failed: $FAILED"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# ── Step 3: Repair persona projects (auto-commit avatars) ──────────

echo "Repairing persona projects..."
echo ""

PROJECTS_JSON=$(curl -sf "${BACKEND_URL}/projects" 2>/dev/null || echo "")
if [ -z "$PROJECTS_JSON" ]; then
  echo "  WARNING: Could not reach ${BACKEND_URL}/projects — skipping repair."
else
  PERSONA_IDS=$(echo "$PROJECTS_JSON" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    projects = data.get('projects', data) if isinstance(data, dict) else data
    for p in projects:
        if p.get('project_type') == 'persona':
            pap = p.get('persona_appearance') or {}
            has_thumb = bool(pap.get('selected_thumb_filename'))
            has_sets = len(pap.get('sets') or [])
            pid = p.get('id', '')
            name = p.get('name', 'unnamed')
            print(f'{pid}|{name}|{has_thumb}|{has_sets}')
except:
    pass
" 2>/dev/null || true)

  if [ -z "$PERSONA_IDS" ]; then
    echo "  No persona projects found."
  else
    REPAIRED=0
    P_SKIPPED=0
    P_FAILED=0
    P_OK=0

    while IFS='|' read -r PID PNAME HAS_THUMB HAS_SETS; do
      [ -z "$PID" ] && continue
      echo -n "  [$PNAME] "

      if [ "$HAS_THUMB" = "True" ]; then
        echo "OK (avatar already committed)"
        P_OK=$((P_OK + 1))
        continue
      fi

      if [ "$HAS_SETS" = "0" ]; then
        echo "SKIP (no avatar sets)"
        P_SKIPPED=$((P_SKIPPED + 1))
        continue
      fi

      if [ "$DRY_RUN" = true ]; then
        echo "WOULD REPAIR"
        REPAIRED=$((REPAIRED + 1))
        continue
      fi

      RESP=$(curl -sf -X POST "${BACKEND_URL}/projects/${PID}/persona/avatar/commit" \
        -H "Content-Type: application/json" \
        -d '{"auto": true}' 2>/dev/null || echo "FAIL")

      if echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('ok')" 2>/dev/null; then
        echo "REPAIRED"
        REPAIRED=$((REPAIRED + 1))
      else
        ERR=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('detail','unknown'))" 2>/dev/null || echo "$RESP")
        echo "FAILED ($ERR)"
        P_FAILED=$((P_FAILED + 1))
      fi
    done <<< "$PERSONA_IDS"

    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  Projects:  OK: $P_OK  Repaired: $REPAIRED  Skipped: $P_SKIPPED  Failed: $P_FAILED"
    echo "═══════════════════════════════════════════════════════════════"
  fi
fi

echo ""
if [ "$DRY_RUN" = false ]; then
  echo "Done! Refresh your browser to see your avatars and images."
fi
