#!/usr/bin/env bash
# ==============================================================================
#  MCP Context Forge - Start Script for HomePilot
#  Starts the MCP Gateway + MCP servers + auto-registers tools & gateways.
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
#    MCP_SERVER_BASE_PORT   - First server port  (default: 9100)
#    MCP_SERVERS            - Space-separated list of servers to start
#    MCP_AGENT_PORT         - LangChain agent port (default: 9200)
#    BASIC_AUTH_USER        - Gateway auth user   (default: admin)
#    BASIC_AUTH_PASSWORD    - Gateway auth pass   (default: changeme)
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MCP_DIR="$ROOT/mcp-context-forge"
MCP_GATEWAY_PORT="${MCP_GATEWAY_PORT:-4444}"
MCP_GATEWAY_HOST="${MCP_GATEWAY_HOST:-127.0.0.1}"
MCP_SERVER_BASE_PORT="${MCP_SERVER_BASE_PORT:-9100}"
MCP_AGENT_PORT="${MCP_AGENT_PORT:-9200}"
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

# ── Validate installation ────────────────────────────────────────────────────
if [ ! -d "$MCP_DIR/.venv" ]; then
    echo "  ❌ MCP Context Forge not installed. Run: make install"
    exit 1
fi

PIDS=""

# ── Start MCP Gateway ────────────────────────────────────────────────────────
echo "  Starting MCP Gateway on port $MCP_GATEWAY_PORT..."

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

# ── Wait for gateway to be ready ─────────────────────────────────────────────
echo "  Waiting for gateway to be ready..."
for i in $(seq 1 30); do
    if curl -s "http://${MCP_GATEWAY_HOST}:${MCP_GATEWAY_PORT}/health" >/dev/null 2>&1; then
        echo "  ✓ MCP Gateway ready"
        break
    fi
    if [ "$i" = "30" ]; then
        echo "  ⚠  Gateway may still be starting (timeout waiting for health check)"
    fi
    sleep 1
done

# ── Optionally start bundled MCP servers ─────────────────────────────────────
STARTED_SERVERS=""
if [ "$WITH_SERVERS" = true ]; then
    MCP_SERVERS_PYTHON="$MCP_DIR/mcp-servers/python"
    SERVERS="${MCP_SERVERS:-csv_pandas_chat_server plotly_server python_sandbox_server}"
    PORT=$MCP_SERVER_BASE_PORT

    for server_name in $SERVERS; do
        server_path="$MCP_SERVERS_PYTHON/$server_name"
        if [ -d "$server_path/.venv" ]; then
            echo "  Starting MCP server: $server_name (HTTP on port $PORT)..."
            cd "$server_path"

            # Start with native HTTP transport
            .venv/bin/python -m "${server_name}.server_fastmcp" \
                --transport http --host 127.0.0.1 --port "$PORT" \
                2>/dev/null &
            PIDS="$PIDS $!"
            STARTED_SERVERS="$STARTED_SERVERS $server_name:$PORT"
            cd "$ROOT"
            PORT=$((PORT + 1))
        fi
    done

    # Wait a moment for servers to start
    sleep 2

    # ── Auto-register servers as gateways with Context Forge ──────────────
    echo ""
    echo "  Registering MCP servers with the gateway..."
    GATEWAY_URL="http://${MCP_GATEWAY_HOST}:${MCP_GATEWAY_PORT}"

    for entry in $STARTED_SERVERS; do
        srv_name="${entry%%:*}"
        srv_port="${entry##*:}"
        srv_url="http://127.0.0.1:${srv_port}/mcp/"

        # Register as gateway (federation) so tools are auto-discovered
        response=$(curl -s -X POST "${GATEWAY_URL}/gateways" \
            -u "${AUTH_USER}:${AUTH_PASS}" \
            -H "Content-Type: application/json" \
            -d "{
                \"gateway\": {
                    \"name\": \"${srv_name}\",
                    \"url\": \"${srv_url}\",
                    \"description\": \"HomePilot bundled MCP server: ${srv_name}\",
                    \"transport\": \"STREAMABLEHTTP\"
                }
            }" 2>/dev/null || echo '{"error":"failed"}')

        gw_id=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

        if [ -n "$gw_id" ] && [ "$gw_id" != "" ]; then
            echo "    ✓ Registered $srv_name (gateway: $gw_id)"

            # Trigger refresh to discover tools
            curl -s -X POST "${GATEWAY_URL}/gateways/${gw_id}/refresh" \
                -u "${AUTH_USER}:${AUTH_PASS}" >/dev/null 2>&1 || true
            echo "    ✓ Tools refreshed for $srv_name"
        else
            echo "    ⚠  Could not register $srv_name (may already exist)"
        fi
    done
fi

# ── Optionally start LangChain agent ─────────────────────────────────────────
if [ "$WITH_AGENT" = true ]; then
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

        # Wait for agent to start, then register with gateway
        sleep 3
        echo "  Registering LangChain Agent with the gateway..."

        GATEWAY_URL="http://${MCP_GATEWAY_HOST}:${MCP_GATEWAY_PORT}"
        curl -s -X POST "${GATEWAY_URL}/a2a" \
            -u "${AUTH_USER}:${AUTH_PASS}" \
            -H "Content-Type: application/json" \
            -d "{
                \"agent\": {
                    \"name\": \"homepilot-langchain-agent\",
                    \"endpoint_url\": \"http://127.0.0.1:${MCP_AGENT_PORT}\",
                    \"agent_type\": \"generic\",
                    \"description\": \"HomePilot LangChain agent with tool-use capabilities\",
                    \"capabilities\": {
                        \"chat\": true,
                        \"tool_use\": true,
                        \"streaming\": true
                    }
                }
            }" >/dev/null 2>&1 || echo "    ⚠  Agent registration skipped (may already exist)"

        echo "    ✓ LangChain Agent registered"
    else
        echo "  ⚠  LangChain Agent not installed. Run: make install-mcp"
    fi
fi

# ── Export PIDs for the parent process to manage ─────────────────────────────
echo "$PIDS"
