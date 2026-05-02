#!/usr/bin/env bash
# test_expert_ollama.sh — end-to-end smoke test for the Expert backend against a
# real local LLM running in Ollama.
#
# What this does:
#   1. Ensures `ollama` is installed (fetches the linux-amd64 tarball from the
#      GitHub release directly — works in environments where the ollama.com
#      install script / registry is blocked).
#   2. Ensures a lightweight model is available (pulled from the HuggingFace
#      registry as a fallback when ollama.com is blocked).
#   3. Starts `ollama serve` if it is not already listening on 11434.
#   4. Starts the HomePilot backend with ``EXPERT_ENABLED=true`` and the Expert
#      local-model env vars pointed at the Ollama model.
#   5. Sends "hello" through all four ``thinking_mode`` values that the Expert
#      router supports — fast, think, auto, heavy — and asserts every response
#      carries the full contract fields.
#   6. Cleans up everything it spawned (unless --keep-running is passed).
#
# Usage:
#   bash scripts/test_expert_ollama.sh                 # run & cleanup
#   bash scripts/test_expert_ollama.sh --keep-running  # leave stack up afterwards
#   bash scripts/test_expert_ollama.sh --model MODEL   # override the HF model
#
# Prereqs assumed to already exist: python3 3.10+, uv, curl, zstd (auto-
# installed via apt if missing and running as root), and ``make install``
# already run in the repo so ``backend/.venv`` is populated.

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
# Default to the smallest Qwen Instruct GGUF. Roughly 491 MB, pulls from
# huggingface.co which is reachable even when ollama.com is DNS-blocked.
MODEL="${EXPERT_TEST_MODEL:-hf.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF:Q4_K_M}"
OLLAMA_RELEASE="${OLLAMA_RELEASE:-v0.21.1}"
KEEP_RUNNING=0

# ── CLI parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --keep-running) KEEP_RUNNING=1; shift ;;
    --model)        MODEL="$2"; shift 2 ;;
    -h|--help)      sed -n '2,28p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

log()  { printf '\033[36m[test]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m  ✓\033[0m %s\n' "$*"; }
warn() { printf '\033[33m  !\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[31m  ✗\033[0m %s\n' "$*" >&2; exit 1; }

OLLAMA_PID=""
BACKEND_PID=""

cleanup() {
  local code=$?
  if [[ "$KEEP_RUNNING" -eq 0 ]]; then
    [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null || true
    [[ -n "$OLLAMA_PID"  ]] && kill "$OLLAMA_PID"  2>/dev/null || true
    wait 2>/dev/null || true
  else
    log "--keep-running: leaving ollama (pid=$OLLAMA_PID) and backend (pid=$BACKEND_PID) alive."
  fi
  exit $code
}
trap cleanup EXIT INT TERM

# ── 1. Install Ollama ─────────────────────────────────────────────────────
if ! command -v ollama >/dev/null 2>&1; then
  log "Installing Ollama $OLLAMA_RELEASE from the GitHub release …"
  # zstd is required to unpack the release tarball.
  if ! command -v zstd >/dev/null 2>&1; then
    if [[ "$EUID" -eq 0 ]] && command -v apt-get >/dev/null 2>&1; then
      apt-get install -y zstd >/dev/null 2>&1 || die "failed to apt-get install zstd"
    else
      die "zstd missing — install it (apt install zstd) and re-run"
    fi
  fi
  tmp_tar="$(mktemp --suffix=.tar.zst)"
  url="https://github.com/ollama/ollama/releases/download/${OLLAMA_RELEASE}/ollama-linux-amd64.tar.zst"
  curl -sSL -o "$tmp_tar" "$url" \
    || die "failed to download $url"
  mkdir -p /opt/ollama
  tar --use-compress-program=unzstd -xf "$tmp_tar" -C /opt/ollama \
    || die "failed to extract $tmp_tar"
  rm -f "$tmp_tar"
  ln -sf /opt/ollama/bin/ollama /usr/local/bin/ollama \
    || die "failed to symlink /usr/local/bin/ollama (need root?)"
  ok "installed $(ollama --version 2>&1 | head -1)"
else
  ok "ollama present ($(ollama --version 2>&1 | head -1))"
fi

# ── 2. Start ollama serve if not running ──────────────────────────────────
if curl -s --max-time 2 "http://127.0.0.1:${OLLAMA_PORT}/api/tags" >/dev/null 2>&1; then
  ok "ollama already serving on :${OLLAMA_PORT}"
else
  log "Starting ollama serve on :${OLLAMA_PORT} …"
  OLLAMA_HOST="127.0.0.1:${OLLAMA_PORT}" ollama serve >/tmp/ollama.log 2>&1 &
  OLLAMA_PID=$!
  for _ in $(seq 1 20); do
    sleep 1
    curl -s --max-time 2 "http://127.0.0.1:${OLLAMA_PORT}/api/tags" >/dev/null 2>&1 && break
  done
  curl -s --max-time 2 "http://127.0.0.1:${OLLAMA_PORT}/api/tags" >/dev/null \
    || die "ollama serve did not come up — see /tmp/ollama.log"
  ok "ollama serving (pid=$OLLAMA_PID, log=/tmp/ollama.log)"
fi

# ── 3. Pull the model if missing ──────────────────────────────────────────
if ollama list | awk 'NR>1 {print $1}' | grep -Fxq "$MODEL"; then
  ok "model already present: $MODEL"
else
  log "Pulling model: $MODEL …"
  ollama pull "$MODEL" 2>&1 | tail -3 || die "ollama pull failed for $MODEL"
  ok "model ready: $MODEL"
fi

# ── 4. Start backend with Expert routes ───────────────────────────────────
if curl -s --max-time 2 "http://127.0.0.1:${BACKEND_PORT}/v1/expert/info" >/dev/null 2>&1; then
  ok "backend already serving Expert routes on :${BACKEND_PORT}"
else
  [[ -x "$REPO_ROOT/backend/.venv/bin/uvicorn" ]] \
    || die "backend/.venv missing — run 'make install' first"
  log "Starting backend on :${BACKEND_PORT} with EXPERT_LOCAL_MODEL=$MODEL …"
  (
    cd "$REPO_ROOT/backend" && \
    EXPERT_ENABLED=true \
    EXPERT_LOCAL_MODEL="$MODEL" \
    EXPERT_LOCAL_FAST_MODEL="$MODEL" \
    EXPERT_LOCAL_AUTO_FALLBACK=true \
    OLLAMA_BASE_URL="http://127.0.0.1:${OLLAMA_PORT}" \
    EXPERT_OLLAMA_URL="http://127.0.0.1:${OLLAMA_PORT}" \
    .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" \
      >/tmp/backend.log 2>&1
  ) &
  BACKEND_PID=$!
  for _ in $(seq 1 30); do
    sleep 1
    curl -s --max-time 2 "http://127.0.0.1:${BACKEND_PORT}/v1/expert/info" >/dev/null 2>&1 && break
  done
  curl -s --max-time 2 "http://127.0.0.1:${BACKEND_PORT}/v1/expert/info" >/dev/null \
    || die "backend did not come up — see /tmp/backend.log"
  ok "backend up (pid=$BACKEND_PID, log=/tmp/backend.log)"
fi

# ── 5. Sanity-check /v1/expert/info ───────────────────────────────────────
log "Expert info:"
curl -s --max-time 5 "http://127.0.0.1:${BACKEND_PORT}/v1/expert/info" | python3 -m json.tool | sed 's/^/    /'

# ── 6. Run the 4-mode test ────────────────────────────────────────────────
FAILED_MODES=()

check_mode() {
  local mode="$1"
  log "POST /v1/expert/chat  thinking_mode=${mode}  query='hello'"
  local body_file
  body_file="$(mktemp)"
  curl -s --max-time 300 -X POST "http://127.0.0.1:${BACKEND_PORT}/v1/expert/chat" \
    -H 'content-type: application/json' \
    -d "{\"query\":\"hello\",\"thinking_mode\":\"${mode}\",\"provider\":\"auto\"}" \
    > "$body_file"
  if [[ ! -s "$body_file" ]]; then
    warn "  ${mode}: empty response"
    FAILED_MODES+=("$mode")
    rm -f "$body_file"
    return
  fi
  # Pass the JSON file path as argv[1] — avoids bash-substitution escaping
  # pitfalls when the response contains backslashes, quotes, or newlines
  # (common for 'think' and 'heavy' which include multi-line `steps`).
  if ! python3 - "$body_file" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    d = json.load(f)
required = ("content", "provider_used", "thinking_mode_used",
            "strategy_used", "fallback_applied", "notices", "latency_ms")
missing = [k for k in required if k not in d]
if missing:
    print(f"    missing fields: {missing}")
    sys.exit(1)
if not d["content"].strip():
    print("    empty content")
    sys.exit(1)
print(f"    content      : {d['content'][:60].strip()!r}")
print(f"    provider     : {d['provider_used']}")
print(f"    mode_used    : {d['thinking_mode_used']}")
print(f"    strategy     : {d['strategy_used']}")
print(f"    latency_ms   : {d['latency_ms']}")
print(f"    notices      : {d['notices']}")
PY
  then
    warn "  ${mode}: contract check failed"
    FAILED_MODES+=("$mode")
    rm -f "$body_file"
    return
  fi
  rm -f "$body_file"
  ok "${mode} ✓"
}

for m in fast think auto heavy; do
  check_mode "$m"
done

# ── 7. Summary ────────────────────────────────────────────────────────────
if [[ "${#FAILED_MODES[@]}" -eq 0 ]]; then
  log "All 4 Expert modes passed end-to-end ✓"
  exit 0
else
  warn "Failed modes: ${FAILED_MODES[*]}"
  exit 1
fi
