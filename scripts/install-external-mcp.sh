#!/usr/bin/env bash
# ==============================================================================
#  install-external-mcp.sh — Enterprise MCP Server Installer for HomePilot
#
#  Installs, starts, and registers an external MCP server declared in a
#  persona's dependencies/mcp_servers.json (source.type == "external").
#
#  Called automatically by persona-launch.sh, or standalone:
#
#    ./scripts/install-external-mcp.sh \
#        --name mcp-news \
#        --git  https://github.com/HomePilotAI/hp-news \
#        --ref  master \
#        --port 8787 \
#        --tools-file /path/to/tools.json
#
#  Pipeline:
#    1. Clone repo  (or update if already present)
#    2. Create venv + install deps
#    3. Start server (HTTP mode, backgrounded)
#    4. Health-check loop
#    5. Register tools with MCP Context Forge gateway
#    6. Persist state for management (status/stop/restart)
#
#  Environment:
#    EXTERNAL_MCP_DIR     — Clone target  (default: $ROOT/external-mcp)
#    MCP_GATEWAY_URL      — Forge gateway (default: http://localhost:4444)
#    BASIC_AUTH_USER       — Gateway user  (default: admin)
#    BASIC_AUTH_PASSWORD   — Gateway pass  (default: changeme)
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# ── Colors ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'
CYAN='\033[0;36m'; BLUE='\033[0;34m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

ok()     { echo -e "  ${GREEN}✓${NC} $1"; }
warn()   { echo -e "  ${YELLOW}⚠${NC} $1"; }
err()    { echo -e "  ${RED}✗${NC} $1"; }
info()   { echo -e "  ${CYAN}▶${NC} $1"; }
rocket() { echo -e "  ${BLUE}🚀${NC} $1"; }

# ── Argument parsing ─────────────────────────────────────────────────────────
NAME="" GIT_URL="" GIT_REF="master" PORT="" SUBDIR=""
HEALTH_PATH="/health" REGISTER_TOOLS="true" TOOLS_FILE="" QUIET="false"
SKIP_START="false"  # --status / --stop modes

while [[ $# -gt 0 ]]; do
    case "$1" in
        --name)        NAME="$2";        shift 2 ;;
        --git)         GIT_URL="$2";     shift 2 ;;
        --ref)         GIT_REF="$2";     shift 2 ;;
        --port)        PORT="$2";        shift 2 ;;
        --subdir)      SUBDIR="$2";      shift 2 ;;
        --health)      HEALTH_PATH="$2"; shift 2 ;;
        --no-register) REGISTER_TOOLS="false"; shift ;;
        --tools-file)  TOOLS_FILE="$2";  shift 2 ;;
        --quiet|-q)    QUIET="true";     shift ;;
        --status)      SKIP_START="status"; shift ;;
        --stop)        SKIP_START="stop";   shift ;;
        --help|-h)
            echo "Usage: $0 --name <name> --git <url> --port <port> [options]"
            echo "  --ref <branch>      Git ref          (default: master)"
            echo "  --subdir <path>     Subdir in repo   (default: root)"
            echo "  --health <path>     Health endpoint   (default: /health)"
            echo "  --tools-file <json> Tool schemas file (from .hpersona)"
            echo "  --no-register       Skip Context Forge registration"
            echo "  --status            Show server status"
            echo "  --stop              Stop the server"
            exit 0
            ;;
        *) err "Unknown option: $1"; exit 1 ;;
    esac
done

if [ -z "$NAME" ] || [ -z "$PORT" ]; then
    err "Required: --name, --port"; exit 1
fi

EXTERNAL_DIR="${EXTERNAL_MCP_DIR:-$ROOT/external-mcp}"
SERVER_DIR="$EXTERNAL_DIR/$NAME"
WORK_DIR="$SERVER_DIR"
[ -n "$SUBDIR" ] && WORK_DIR="$SERVER_DIR/$SUBDIR"
PID_FILE="$EXTERNAL_DIR/.${NAME}.pid"
STATE_FILE="$EXTERNAL_DIR/.${NAME}.state"
MCP_GATEWAY_URL="${MCP_GATEWAY_URL:-http://localhost:4444}"
AUTH_USER="${BASIC_AUTH_USER:-admin}"
AUTH_PASS="${BASIC_AUTH_PASSWORD:-changeme}"

# ── Helper: check if server is healthy on its port ───────────────────────────
is_healthy() {
    curl -sf --connect-timeout 3 "http://localhost:${PORT}${HEALTH_PATH}" >/dev/null 2>&1
}

# ── Helper: get running PID (0 if not running) ──────────────────────────────
get_pid() {
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            echo "$pid"
            return
        fi
    fi
    echo "0"
}

# ── Sub-command: --status ────────────────────────────────────────────────────
if [ "$SKIP_START" = "status" ]; then
    pid=$(get_pid)
    if [ "$pid" != "0" ] && is_healthy; then
        ok "$NAME is running (PID: $pid, port: $PORT)"
    elif [ "$pid" != "0" ]; then
        warn "$NAME process alive (PID: $pid) but health check failed"
    else
        echo -e "  ${DIM}○${NC} $NAME is not running"
    fi
    exit 0
fi

# ── Sub-command: --stop ──────────────────────────────────────────────────────
if [ "$SKIP_START" = "stop" ]; then
    pid=$(get_pid)
    if [ "$pid" != "0" ]; then
        kill "$pid" 2>/dev/null || true
        rm -f "$PID_FILE"
        ok "Stopped $NAME (PID: $pid)"
    else
        echo -e "  ${DIM}○${NC} $NAME was not running"
    fi
    exit 0
fi

# ══════════════════════════════════════════════════════════════════════════════
# MAIN INSTALL FLOW
# ══════════════════════════════════════════════════════════════════════════════

# If already healthy, skip everything
if is_healthy; then
    ok "$NAME already running and healthy on port $PORT"
    # Still register with forge if requested
    if [ "$REGISTER_TOOLS" = "true" ]; then
        # Jump to registration (step 5)
        :
    else
        exit 0
    fi
else
    # ── 1. Clone or update ────────────────────────────────────────────────────
    if [ -z "$GIT_URL" ]; then
        err "Required: --git <url>"
        exit 1
    fi

    mkdir -p "$EXTERNAL_DIR"

    if [ -d "$SERVER_DIR/.git" ]; then
        info "Updating $NAME..."
        cd "$SERVER_DIR"
        git fetch origin "$GIT_REF" --quiet 2>/dev/null || true
        git checkout "$GIT_REF" --quiet 2>/dev/null || true
        git pull origin "$GIT_REF" --quiet 2>/dev/null || true
        cd "$ROOT"
        ok "Repository updated"
    else
        info "Cloning $NAME from $GIT_URL..."
        if ! git clone --depth 1 --branch "$GIT_REF" "$GIT_URL" "$SERVER_DIR" 2>&1 | \
            { [ "$QUIET" = "true" ] && cat >/dev/null || cat; }; then
            err "Failed to clone $GIT_URL"
            err "Check network connectivity and that the repository exists"
            exit 1
        fi
        ok "Repository cloned"
    fi

    # ── 2. Python venv + dependencies ─────────────────────────────────────────
    info "Installing dependencies..."
    cd "$WORK_DIR"

    if [ ! -d ".venv" ]; then
        python3 -m venv .venv 2>/dev/null || {
            err "Failed to create Python venv — ensure python3-venv is installed"
            exit 1
        }
    fi

    # Upgrade pip quietly, then install deps
    .venv/bin/pip install -q --upgrade pip 2>/dev/null || true

    if [ -f "requirements.txt" ]; then
        .venv/bin/pip install -q -r requirements.txt 2>&1 | tail -3
    elif [ -f "pyproject.toml" ]; then
        .venv/bin/pip install -q -e . 2>&1 | tail -3
    elif [ -f "setup.py" ]; then
        .venv/bin/pip install -q -e . 2>&1 | tail -3
    else
        warn "No requirements.txt or pyproject.toml found — skipping dependency install"
    fi

    ok "Dependencies installed"
    cd "$ROOT"

    # ── 3. Stop old instance if any ───────────────────────────────────────────
    old_pid=$(get_pid)
    if [ "$old_pid" != "0" ]; then
        info "Stopping previous instance (PID: $old_pid)..."
        kill "$old_pid" 2>/dev/null || true
        sleep 1
    fi

    # ── 4. Start the server ───────────────────────────────────────────────────
    info "Starting $NAME on port $PORT..."
    cd "$WORK_DIR"
    mkdir -p data 2>/dev/null || true

    # Log file for the server
    LOG_FILE="$EXTERNAL_DIR/${NAME}.log"

    # Detect the best startup method:
    #   - Makefile with run-http target
    #   - app/main.py with --http flag (hp-news pattern)
    #   - server.py / main.py with PORT env
    if [ -f "app/main.py" ]; then
        NEWS_MCP_HTTP_PORT="$PORT" \
        NEWS_MCP_HTTP_HOST="0.0.0.0" \
        NEWS_DB_PATH="$WORK_DIR/data/news.sqlite3" \
        LOG_LEVEL="WARNING" \
            .venv/bin/python -m app.main --http >> "$LOG_FILE" 2>&1 &
        SERVER_PID=$!
    elif [ -f "server.py" ]; then
        PORT="$PORT" .venv/bin/python server.py >> "$LOG_FILE" 2>&1 &
        SERVER_PID=$!
    elif [ -f "main.py" ]; then
        PORT="$PORT" .venv/bin/python main.py >> "$LOG_FILE" 2>&1 &
        SERVER_PID=$!
    else
        err "Cannot determine how to start $NAME"
        err "Expected app/main.py, server.py, or main.py"
        exit 1
    fi

    cd "$ROOT"

    # Persist PID + state
    echo "$SERVER_PID" > "$PID_FILE"
    python3 -c "
import json, datetime
state = {
    'name': '$NAME',
    'git': '$GIT_URL',
    'ref': '$GIT_REF',
    'port': $PORT,
    'pid': $SERVER_PID,
    'dir': '$WORK_DIR',
    'health': 'http://localhost:${PORT}${HEALTH_PATH}',
    'installed_at': datetime.datetime.utcnow().isoformat() + 'Z',
    'log': '$LOG_FILE'
}
with open('$STATE_FILE', 'w') as f:
    json.dump(state, f, indent=2)
" 2>/dev/null || true

    # ── 4b. Wait for health check ────────────────────────────────────────────
    info "Waiting for $NAME to become healthy..."
    READY=false
    for i in $(seq 1 60); do
        # Check the process is still alive
        if ! kill -0 "$SERVER_PID" 2>/dev/null; then
            err "$NAME process exited unexpectedly"
            err "Check log: $LOG_FILE"
            [ -f "$LOG_FILE" ] && tail -10 "$LOG_FILE" 2>/dev/null | while IFS= read -r line; do echo "    $line"; done
            exit 1
        fi
        if is_healthy; then
            READY=true
            break
        fi
        sleep 1
    done

    if [ "$READY" = true ]; then
        rocket "$NAME is running on port $PORT (PID: $SERVER_PID)"
    else
        err "$NAME started but health check failed after 60s"
        err "Check log: $LOG_FILE"
        [ -f "$LOG_FILE" ] && tail -10 "$LOG_FILE" 2>/dev/null | while IFS= read -r line; do echo "    $line"; done
        exit 1
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
# 5. Register tools with MCP Context Forge
# ══════════════════════════════════════════════════════════════════════════════
if [ "$REGISTER_TOOLS" = "true" ]; then
    if ! curl -sf --connect-timeout 3 "${MCP_GATEWAY_URL}/health" >/dev/null 2>&1; then
        echo -e "  ${DIM}Context Forge not running on $MCP_GATEWAY_URL — skipping registration${NC}"
    else
        info "Syncing $NAME with Context Forge..."

        # Authenticate (JWT preferred, basic auth fallback)
        TOKEN=$(curl -sf -X POST "${MCP_GATEWAY_URL}/auth/login" \
            -H "Content-Type: application/json" \
            -d "{\"email\":\"admin@example.com\",\"password\":\"${AUTH_PASS}\"}" 2>/dev/null | \
            python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

        if [ -n "$TOKEN" ]; then
            AUTH_HEADER="Authorization: Bearer $TOKEN"
        else
            AUTH_HEADER="Authorization: Basic $(echo -n "${AUTH_USER}:${AUTH_PASS}" | base64)"
        fi

        # Strategy: register each tool individually from the tool_schemas in tools.json
        # This gives Context Forge full schema awareness for each tool.
        TOOLS_REGISTERED=0
        TOOLS_FAILED=0

        if [ -n "$TOOLS_FILE" ] && [ -f "$TOOLS_FILE" ]; then
            # Read tool schemas from the persona's tools.json
            python3 -c "
import json, sys

with open('$TOOLS_FILE') as f:
    data = json.load(f)

schemas = data.get('tool_schemas', [])
for schema in schemas:
    print(json.dumps(schema))
" 2>/dev/null | while IFS= read -r tool_json; do
                TOOL_NAME=$(echo "$tool_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])" 2>/dev/null)
                TOOL_DESC=$(echo "$tool_json" | python3 -c "import sys,json; print(json.load(sys.stdin)['description'])" 2>/dev/null)
                INPUT_SCHEMA=$(echo "$tool_json" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin).get('inputSchema',{})))" 2>/dev/null)

                # Map tool name to HTTP endpoint
                # news.top → /v1/news/top, news.search → /v1/news/search, etc.
                ENDPOINT_SUFFIX=$(echo "$TOOL_NAME" | python3 -c "
import sys
name = sys.stdin.read().strip()
parts = name.split('.')
if len(parts) == 2:
    print(f'/v1/{parts[0]}/{parts[1]}')
else:
    print(f'/v1/{name}')
" 2>/dev/null)

                PAYLOAD=$(python3 -c "
import json
schema = json.loads('''$INPUT_SCHEMA''')
print(json.dumps({
    'tool': {
        'name': '$TOOL_NAME',
        'description': '''$TOOL_DESC''',
        'inputSchema': schema,
        'url': 'http://localhost:${PORT}${ENDPOINT_SUFFIX}',
        'integration_type': 'REST',
        'request_type': 'GET'
    }
}))
" 2>/dev/null)

                RESP=$(curl -sf -X POST "${MCP_GATEWAY_URL}/tools" \
                    -H "$AUTH_HEADER" \
                    -H "Content-Type: application/json" \
                    -d "$PAYLOAD" 2>/dev/null || echo '{"error":"request failed"}')

                TOOL_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

                if [ -n "$TOOL_ID" ] && [ "$TOOL_ID" != "" ] && [ "$TOOL_ID" != "None" ]; then
                    ok "Registered: $TOOL_NAME"
                else
                    # Check if tool already exists (409 or duplicate)
                    ERR_MSG=$(echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('detail','') or d.get('error',''))" 2>/dev/null || echo "")
                    if echo "$ERR_MSG" | grep -qi "already\|exists\|duplicate\|conflict"; then
                        ok "Already registered: $TOOL_NAME"
                    else
                        warn "Could not register: $TOOL_NAME — $ERR_MSG"
                    fi
                fi
            done
        else
            # No tools file — register as a gateway and let Forge discover
            info "No tool schemas provided — registering as gateway for auto-discovery..."
            GATEWAY_PAYLOAD=$(python3 -c "
import json
print(json.dumps({'gateway': {
    'name': '$NAME',
    'url': 'http://localhost:${PORT}/',
    'transport': 'http',
    'auth_type': 'none'
}}))
" 2>/dev/null)

            RESP=$(curl -sf -X POST "${MCP_GATEWAY_URL}/gateways" \
                -H "$AUTH_HEADER" \
                -H "Content-Type: application/json" \
                -d "$GATEWAY_PAYLOAD" 2>/dev/null || echo "")

            GW_ID=$(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null || echo "")

            if [ -n "$GW_ID" ] && [ "$GW_ID" != "" ] && [ "$GW_ID" != "None" ]; then
                ok "Registered as gateway: $GW_ID"
                curl -sf -X POST "${MCP_GATEWAY_URL}/gateways/${GW_ID}/refresh" \
                    -H "$AUTH_HEADER" >/dev/null 2>&1 && \
                    ok "Tools discovered via gateway refresh" || \
                    warn "Gateway registered — tool refresh may need manual trigger"
            else
                warn "Gateway registration: $(echo "$RESP" | head -c 200)"
            fi
        fi

        ok "Context Forge sync complete"
    fi
fi

# ══════════════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════════════
SERVER_PID=$(get_pid)
echo ""
echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${BOLD}${GREEN}$NAME installed and ready${NC}"
echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  ${DIM}Port:       ${NC}$PORT"
echo -e "  ${DIM}PID:        ${NC}$SERVER_PID"
echo -e "  ${DIM}Health:     ${NC}http://localhost:${PORT}${HEALTH_PATH}"
echo -e "  ${DIM}Directory:  ${NC}$WORK_DIR"
[ -f "${LOG_FILE:-}" ] && echo -e "  ${DIM}Log:        ${NC}${LOG_FILE}"
echo -e "  ${DIM}Stop:       ${NC}$0 --name $NAME --port $PORT --stop"
echo -e "  ${DIM}Status:     ${NC}$0 --name $NAME --port $PORT --status"
echo -e "  ${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
