#!/usr/bin/env bash
# ==============================================================================
#  MCP Context Forge - Start Script for HomePilot
#  Starts the MCP Gateway + optionally bundled MCP servers.
#
#  Supports two installation modes:
#    1. Pip-installed: uses `mcpgateway` command (preferred, lightweight)
#    2. Cloned repo:   uses mcp-context-forge/.venv/bin/python
#
#  Usage:
#    ./scripts/mcp-start.sh                 # Start gateway only
#    ./scripts/mcp-start.sh --with-servers  # Start gateway + bundled MCP servers
#    ./scripts/mcp-start.sh --with-agent    # Start gateway + LangChain agent
#    ./scripts/mcp-start.sh --all           # Start everything
#
#  Environment:
#    MCP_GATEWAY_PORT       - Gateway port       (default: 4444)
#    MCP_GATEWAY_HOST       - Gateway host       (default: 127.0.0.1)
#    BASIC_AUTH_USER        - Gateway auth user   (default: admin)
#    BASIC_AUTH_PASSWORD    - Gateway auth pass   (default: changeme)
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_DIR="$ROOT/mcp-context-forge"
MCP_GATEWAY_PORT="${MCP_GATEWAY_PORT:-4444}"
MCP_GATEWAY_HOST="${MCP_GATEWAY_HOST:-127.0.0.1}"
AUTH_USER="${BASIC_AUTH_USER:-admin}"
AUTH_PASS="${BASIC_AUTH_PASSWORD:-changeme}"

WITH_SERVERS=false
WITH_AGENT=false

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --with-servers) WITH_SERVERS=true ;;
        --with-agent)   WITH_AGENT=true ;;
        --all)          WITH_SERVERS=true; WITH_AGENT=true ;;
    esac
done

# ── Detect installation mode ──────────────────────────────────────────────────
FORGE_MODE=""
if [ -d "$MCP_DIR/.venv" ] && [ -x "$MCP_DIR/.venv/bin/python" ]; then
    FORGE_MODE="repo"
elif command -v mcpgateway >/dev/null 2>&1; then
    FORGE_MODE="pip"
else
    echo "  ❌ MCP Context Forge not installed."
    echo "     Install via: pip install mcp-contextforge-gateway"
    echo "     Or clone + install: make install-mcp"
    exit 1
fi

PIDS=""

# ── Start MCP Gateway ────────────────────────────────────────────────────────
echo "  Starting MCP Gateway on port $MCP_GATEWAY_PORT (mode: $FORGE_MODE)..."

if [ "$FORGE_MODE" = "repo" ]; then
    cd "$MCP_DIR"
    HOST="0.0.0.0" \
        BASIC_AUTH_USER="$AUTH_USER" BASIC_AUTH_PASSWORD="$AUTH_PASS" \
        AUTH_REQUIRED=false \
        MCPGATEWAY_UI_ENABLED=true \
        MCPGATEWAY_ADMIN_API_ENABLED=true \
        .venv/bin/python -m uvicorn mcpgateway.main:app \
        --host "$MCP_GATEWAY_HOST" \
        --port "$MCP_GATEWAY_PORT" \
        --log-level warning &
    PIDS="$PIDS $!"
    cd "$ROOT"
else
    # Pip-installed mode — use the mcpgateway command directly
    HOST="0.0.0.0" \
        BASIC_AUTH_USER="$AUTH_USER" BASIC_AUTH_PASSWORD="$AUTH_PASS" \
        AUTH_REQUIRED=false \
        MCPGATEWAY_UI_ENABLED=true \
        MCPGATEWAY_ADMIN_API_ENABLED=true \
        mcpgateway mcpgateway.main:app \
        --host "$MCP_GATEWAY_HOST" \
        --port "$MCP_GATEWAY_PORT" \
        --log-level warning &
    PIDS="$PIDS $!"
fi

# ── Wait for gateway to be ready ─────────────────────────────────────────────
echo "  Waiting for gateway to be ready..."
for i in $(seq 1 30); do
    if curl -sf "http://${MCP_GATEWAY_HOST}:${MCP_GATEWAY_PORT}/health" >/dev/null 2>&1; then
        echo "  ✓ MCP Gateway ready on port $MCP_GATEWAY_PORT"
        break
    fi
    if [ "$i" = "30" ]; then
        echo "  ⚠  Gateway may still be starting (timeout waiting for health check)"
    fi
    sleep 1
done

# ── Optionally start bundled MCP servers (from cloned repo) ───────────────────
STARTED_SERVERS=""
if [ "$WITH_SERVERS" = true ] && [ "$FORGE_MODE" = "repo" ]; then
    MCP_SERVERS_PYTHON="$MCP_DIR/mcp-servers/python"
    MCP_SERVER_BASE_PORT="${MCP_SERVER_BASE_PORT:-9100}"
    SERVERS="${MCP_SERVERS:-csv_pandas_chat_server plotly_server python_sandbox_server}"
    PORT=$MCP_SERVER_BASE_PORT

    for server_name in $SERVERS; do
        server_path="$MCP_SERVERS_PYTHON/$server_name"
        if [ -d "$server_path/.venv" ]; then
            echo "  Starting MCP server: $server_name (HTTP on port $PORT)..."
            cd "$server_path"
            .venv/bin/python -m "${server_name}.server_fastmcp" \
                --transport http --host 127.0.0.1 --port "$PORT" \
                2>/dev/null &
            PIDS="$PIDS $!"
            STARTED_SERVERS="$STARTED_SERVERS $server_name:$PORT"
            cd "$ROOT"
            PORT=$((PORT + 1))
        fi
    done
    sleep 2
fi

# ── Optionally start LangChain agent ─────────────────────────────────────────
if [ "$WITH_AGENT" = true ] && [ "$FORGE_MODE" = "repo" ]; then
    MCP_AGENT_PORT="${MCP_AGENT_PORT:-9200}"
    AGENT_PATH="$MCP_DIR/agent_runtimes/langchain_agent"
    if [ -d "$AGENT_PATH/.venv" ]; then
        echo ""
        echo "  Starting LangChain Agent on port $MCP_AGENT_PORT..."
        cd "$AGENT_PATH"
        MCP_GATEWAY_URL="http://${MCP_GATEWAY_HOST}:${MCP_GATEWAY_PORT}" \
            .venv/bin/python -m uvicorn app:app \
            --host 127.0.0.1 --port "$MCP_AGENT_PORT" \
            --log-level warning 2>/dev/null &
        PIDS="$PIDS $!"
        cd "$ROOT"
    else
        echo "  ⚠  LangChain Agent not installed. Run: make install-mcp"
    fi
fi

# ── Export PIDs for the parent process to manage ─────────────────────────────
echo "$PIDS"
