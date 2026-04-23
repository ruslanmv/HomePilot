#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${PREPROD_BACKEND_PORT:-18000}"
FRONTEND_PORT="${PREPROD_FRONTEND_PORT:-13000}"
EDIT_SESSION_PORT="${PREPROD_EDIT_SESSION_PORT:-18010}"
COMFY_PORT="${PREPROD_COMFY_PORT:-18188}"
MCP_GATEWAY_PORT="${PREPROD_MCP_GATEWAY_PORT:-14444}"
MCP_GATEWAY_HOST="${PREPROD_MCP_GATEWAY_HOST:-127.0.0.1}"
MCPGATEWAY_URL="http://${MCP_GATEWAY_HOST}:${MCP_GATEWAY_PORT}"
MCP_WEB_SEARCH_PORT="${PREPROD_MCP_WEB_SEARCH_PORT:-19151}"
MCP_DOC_RETRIEVAL_PORT="${PREPROD_MCP_DOC_RETRIEVAL_PORT:-19152}"
MCP_MEMORY_STORE_PORT="${PREPROD_MCP_MEMORY_STORE_PORT:-19153}"
MCP_SAFETY_POLICY_PORT="${PREPROD_MCP_SAFETY_POLICY_PORT:-19154}"
MCP_OBSERVABILITY_PORT="${PREPROD_MCP_OBSERVABILITY_PORT:-19155}"

if [[ ! -x "$ROOT/backend/.venv/bin/uvicorn" ]]; then
  echo "❌ backend/.venv missing. Run: make install"
  exit 1
fi
if [[ ! -x "$ROOT/edit-session/.venv/bin/uvicorn" ]]; then
  echo "❌ edit-session/.venv missing. Run: make install"
  exit 1
fi
if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
  echo "❌ frontend/node_modules missing. Run: make install"
  exit 1
fi

pids=""
cleanup() {
  echo ""
  echo "Stopping preprod services..."
  [[ -n "$pids" ]] && kill $pids 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "════════════════════════════════════════════════════════════════"
echo "Starting HomePilot PREPROD sandbox"
echo "Backend:      http://localhost:${BACKEND_PORT}"
echo "Edit-Session: http://localhost:${EDIT_SESSION_PORT}"
echo "Frontend:     http://localhost:${FRONTEND_PORT}"
echo "ComfyUI:      http://localhost:${COMFY_PORT} (preprod port)"
echo "MCP Gateway:  ${MCPGATEWAY_URL} (preprod port)"
echo "Expert MCP set (preprod):"
echo "  - mcp-web-search   http://127.0.0.1:${MCP_WEB_SEARCH_PORT}"
echo "  - mcp-doc-retrieval http://127.0.0.1:${MCP_DOC_RETRIEVAL_PORT}"
echo "  - mcp-memory-store http://127.0.0.1:${MCP_MEMORY_STORE_PORT}"
echo "  - mcp-safety-policy http://127.0.0.1:${MCP_SAFETY_POLICY_PORT}"
echo "  - mcp-observability http://127.0.0.1:${MCP_OBSERVABILITY_PORT}"
echo "This uses isolated ports and does not replace current prod ports."
echo "════════════════════════════════════════════════════════════════"

(
  cd "$ROOT/backend"
  EXPERT_PREPROD=1 \
  EXPERT_DEBUG=true \
  COMFY_BASE_URL="http://localhost:${COMFY_PORT}" \
  MCPGATEWAY_URL="${MCPGATEWAY_URL}" \
  EXPERT_MCP_ORCHESTRATOR="${EXPERT_MCP_ORCHESTRATOR:-direct}" \
  EXPERT_MCP_WEB_SEARCH_URL="${EXPERT_MCP_WEB_SEARCH_URL:-http://127.0.0.1:${MCP_WEB_SEARCH_PORT}}" \
  EXPERT_MCP_DOC_RETRIEVAL_URL="${EXPERT_MCP_DOC_RETRIEVAL_URL:-http://127.0.0.1:${MCP_DOC_RETRIEVAL_PORT}}" \
  EXPERT_MCP_MEMORY_STORE_URL="${EXPERT_MCP_MEMORY_STORE_URL:-http://127.0.0.1:${MCP_MEMORY_STORE_PORT}}" \
  EXPERT_MCP_SAFETY_POLICY_URL="${EXPERT_MCP_SAFETY_POLICY_URL:-http://127.0.0.1:${MCP_SAFETY_POLICY_PORT}}" \
  EXPERT_MCP_OBSERVABILITY_URL="${EXPERT_MCP_OBSERVABILITY_URL:-http://127.0.0.1:${MCP_OBSERVABILITY_PORT}}" \
  INTERACTIVE_ENABLED=${INTERACTIVE_ENABLED:-true} \
  .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port "$BACKEND_PORT"
) &
pids="$pids $!"

(
  cd "$ROOT/edit-session"
  .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port "$EDIT_SESSION_PORT"
) &
pids="$pids $!"

(
  cd "$ROOT/frontend"
  HOMEPILOT_BACKEND_URL="http://localhost:${BACKEND_PORT}" \
  VITE_EXPERT_CHAT_ENABLED="${VITE_EXPERT_CHAT_ENABLED:-true}" \
  npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT"
) &
pids="$pids $!"

if [[ -f "$ROOT/ComfyUI/main.py" && -x "$ROOT/ComfyUI/.venv/bin/python" ]]; then
  (
    cd "$ROOT"
    COMFY_PORT="$COMFY_PORT" bash scripts/start-comfyui.sh
  ) &
  pids="$pids $!"
else
  echo "⚠️  ComfyUI not found; preprod will run without image/video generation backend."
fi

echo "Starting Expert MCP servers for preprod..."
(
  cd "$ROOT/agentic/integrations/mcp/web_search"
  PYTHONPATH="$ROOT" python3 -m uvicorn app:app --host 127.0.0.1 --port "$MCP_WEB_SEARCH_PORT"
) &
pids="$pids $!"

(
  cd "$ROOT/agentic/integrations/mcp/doc_retrieval"
  PYTHONPATH="$ROOT" python3 -m uvicorn app:app --host 127.0.0.1 --port "$MCP_DOC_RETRIEVAL_PORT"
) &
pids="$pids $!"

(
  cd "$ROOT/agentic/integrations/mcp/memory_store"
  PYTHONPATH="$ROOT" python3 -m uvicorn app:app --host 127.0.0.1 --port "$MCP_MEMORY_STORE_PORT"
) &
pids="$pids $!"

(
  cd "$ROOT/agentic/integrations/mcp/safety_policy"
  PYTHONPATH="$ROOT" python3 -m uvicorn app:app --host 127.0.0.1 --port "$MCP_SAFETY_POLICY_PORT"
) &
pids="$pids $!"

(
  cd "$ROOT/agentic/integrations/mcp/observability"
  PYTHONPATH="$ROOT" python3 -m uvicorn app:app --host 127.0.0.1 --port "$MCP_OBSERVABILITY_PORT"
) &
pids="$pids $!"

if [[ "${AGENTIC:-1}" == "1" ]] && ([[ -d "$ROOT/mcp-context-forge/.venv" ]] || command -v mcpgateway >/dev/null 2>&1); then
  echo "Starting preprod MCP gateway for Expert orchestration..."
  (
    cd "$ROOT"
    MCP_GATEWAY_PORT="$MCP_GATEWAY_PORT" \
    MCP_GATEWAY_HOST="$MCP_GATEWAY_HOST" \
    bash scripts/mcp-start.sh
  ) &
  pids="$pids $!"
else
  echo "⚠️  MCP not installed; preprod starts without MCP gateway (run: make install-preprod)."
fi

echo ""
echo "Preprod sandbox running. Press Ctrl+C to stop."
wait
