#!/usr/bin/env bash
# ==============================================================================
#  HomePilot Agentic Servers — start + seed
#
#  Starts 6 core MCP servers + 2 A2A agents.  Optional servers (local-notes,
#  gmail, github, etc.) are managed by the backend's ServerManager and can
#  be installed/uninstalled via the UI (POST /v1/agentic/servers/{id}/install).
#
#  Usage:
#    ./scripts/agentic-start.sh              # start core + seed
#    ./scripts/agentic-start.sh --no-seed    # start core only
#
#  Core servers (always started):
#    MCP  9101  personal-assistant
#    MCP  9102  knowledge
#    MCP  9103  decision-copilot
#    MCP  9104  executive-briefing
#    MCP  9105  web-search
#    MCP  9120  inventory
#    A2A  9201  everyday-assistant
#    A2A  9202  chief-of-staff
#
#  Optional servers (install via UI):
#    MCP  9110  local-notes         MCP  9114  gmail
#    MCP  9111  local-projects      MCP  9115  google-calendar
#    MCP  9112  web-fetch           MCP  9116  microsoft-graph
#    MCP  9113  shell-safe          MCP  9117  slack
#    MCP  9118  github              MCP  9119  notion
#
#  Environment:
#    MCPGATEWAY_URL        (default: http://localhost:4444)
#    BASIC_AUTH_USER        (default: admin)
#    BASIC_AUTH_PASSWORD    (default: changeme)
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTIC_DIR="$ROOT/agentic"

# Python — prefer the backend venv (has httpx, pyyaml, fastapi, uvicorn)
PYTHON="${AGENTIC_PYTHON:-$ROOT/backend/.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    echo "  Backend venv not found at $PYTHON — run: make install"
    exit 1
fi

MCPGATEWAY_URL="${MCPGATEWAY_URL:-http://localhost:4444}"
PA_PORT="${MCP_PERSONAL_ASSISTANT_PORT:-9101}"
KNOWLEDGE_PORT="${MCP_KNOWLEDGE_PORT:-9102}"
DECISION_PORT="${MCP_DECISION_COPILOT_PORT:-9103}"
BRIEFING_PORT="${MCP_EXECUTIVE_BRIEFING_PORT:-9104}"
WEB_SEARCH_PORT="${MCP_WEB_SEARCH_PORT:-9105}"
INVENTORY_PORT="${MCP_INVENTORY_PORT:-9120}"
EVERYDAY_A2A_PORT="${A2A_EVERYDAY_ASSISTANT_PORT:-9201}"
COS_A2A_PORT="${A2A_CHIEF_OF_STAFF_PORT:-9202}"
SEED=true
for arg in "$@"; do
    case "$arg" in
        --no-seed) SEED=false ;;
    esac
done

PIDS=""

# ── Graceful shutdown: stop all child processes on exit ───────────────────
cleanup() {
    echo ""
    echo "  Shutting down MCP servers..."
    for pid in $PIDS; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
        fi
    done
    # Give processes up to 5 seconds to exit gracefully
    for _ in $(seq 1 10); do
        all_dead=true
        for pid in $PIDS; do
            if kill -0 "$pid" 2>/dev/null; then
                all_dead=false
                break
            fi
        done
        if $all_dead; then break; fi
        sleep 0.5
    done
    # Force-kill any remaining
    for pid in $PIDS; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    done
    echo "  All MCP servers stopped"
}
trap cleanup EXIT INT TERM

# ── Helper: start a uvicorn process ──────────────────────────────────────────
start_server() {
    local label="$1"   # e.g. "MCP personal-assistant"
    local module="$2"  # e.g. "agentic.integrations.mcp.personal_assistant_server:app"
    local port="$3"

    echo "  Starting $label on port $port..."
    PYTHONPATH="$ROOT" "$PYTHON" -m uvicorn "$module" \
        --host 127.0.0.1 --port "$port" --log-level warning &
    PIDS="$PIDS $!"
}

# ── Start core MCP servers ───────────────────────────────────────────────────
echo ""
echo "  Starting HomePilot core MCP servers..."

start_server "MCP personal-assistant" \
    "agentic.integrations.mcp.personal_assistant_server:app" "$PA_PORT"
start_server "MCP knowledge" \
    "agentic.integrations.mcp.knowledge_server:app" "$KNOWLEDGE_PORT"
start_server "MCP decision-copilot" \
    "agentic.integrations.mcp.decision_copilot_server:app" "$DECISION_PORT"
start_server "MCP executive-briefing" \
    "agentic.integrations.mcp.executive_briefing_server:app" "$BRIEFING_PORT"
start_server "MCP web-search" \
    "agentic.integrations.mcp.web_search_server:app" "$WEB_SEARCH_PORT"
start_server "MCP inventory" \
    "agentic.integrations.mcp.inventory_server:app" "$INVENTORY_PORT"

# ── Start A2A agents ─────────────────────────────────────────────────────────
echo "  Starting HomePilot A2A agents..."
start_server "A2A everyday-assistant" \
    "agentic.integrations.a2a.everyday_assistant_agent:app" "$EVERYDAY_A2A_PORT"
start_server "A2A chief-of-staff" \
    "agentic.integrations.a2a.chief_of_staff_agent:app" "$COS_A2A_PORT"

# ── Wait for core servers to be healthy ──────────────────────────────────────
echo "  Waiting for core servers to be ready..."

CORE_PORTS="$PA_PORT $KNOWLEDGE_PORT $DECISION_PORT $BRIEFING_PORT $WEB_SEARCH_PORT $INVENTORY_PORT $EVERYDAY_A2A_PORT $COS_A2A_PORT"
TOTAL_CORE=8

for attempt in $(seq 1 10); do
    ok=0
    for port in $CORE_PORTS; do
        if curl -sf "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
            ok=$((ok + 1))
        fi
    done
    if [ "$ok" -eq "$TOTAL_CORE" ]; then
        break
    fi
    sleep 1
done
echo "  $ok/$TOTAL_CORE core servers healthy"

# ── Seed Context Forge ───────────────────────────────────────────────────────
if [ "$SEED" = true ]; then
    echo ""
    echo "  Seeding Context Forge..."

    # Wait for Forge gateway to be reachable (up to 15s)
    for i in $(seq 1 15); do
        if curl -sf "${MCPGATEWAY_URL}/health" >/dev/null 2>&1; then
            break
        fi
        if [ "$i" = "15" ]; then
            echo "  Forge gateway not reachable at ${MCPGATEWAY_URL} — skipping seed"
            echo "$PIDS"
            exit 0
        fi
        sleep 1
    done

    MCPGATEWAY_URL="$MCPGATEWAY_URL" \
        "$PYTHON" "$AGENTIC_DIR/forge/seed/seed_all.py" 2>&1 \
        | while IFS= read -r line; do echo "    $line"; done \
        || echo "  Seed script had errors (non-fatal)"

    echo "  Forge seeded — core tools, agents, and virtual servers registered"
    echo "  Optional servers can be installed via the UI (MCP Servers tab)"

    # ── Final verification ────────────────────────────────────────────────
    echo ""
    echo "  Verifying core services..."
    if curl -sf "${MCPGATEWAY_URL}/health" >/dev/null 2>&1; then
        echo "    Context Forge (${MCPGATEWAY_URL}): healthy"
    else
        echo "    Context Forge (${MCPGATEWAY_URL}): not responding"
    fi
    for port in $CORE_PORTS; do
        if curl -sf "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
            echo "    Server on port ${port}: healthy"
        else
            echo "    Server on port ${port}: not responding"
        fi
    done
fi

# ── Export PIDs for the parent process to manage ─────────────────────────────
echo "$PIDS"
