#!/usr/bin/env bash
# ==============================================================================
#  HomePilot — Persona MCP Server Launcher
#  Reads a .hpersona package (or extracted folder) and starts exactly the
#  MCP servers + A2A agents that the persona declares in its dependencies.
#
#  HEALTH-CHECK-FIRST design:
#    For each required server, the launcher first checks if it's already
#    running locally (native process or existing container). Only servers
#    that fail the health check are started via Docker Compose. This avoids
#    pulling/starting containers when services are already available, and
#    prevents port collisions with locally-running processes.
#
#  Usage:
#    ./scripts/persona-launch.sh <persona>              # Start servers
#    ./scripts/persona-launch.sh <persona> --check      # Dry-run: show status
#    ./scripts/persona-launch.sh <persona> --stop       # Stop persona's servers
#    ./scripts/persona-launch.sh <persona> --status     # Show running status
#    ./scripts/persona-launch.sh <persona> --force      # Restart all (ignore health)
#    ./scripts/persona-launch.sh --list                 # List available personas
#    ./scripts/persona-launch.sh --running              # Show all running MCP services
#
#  <persona> can be:
#    - A .hpersona file:     community/sample/diana.hpersona
#    - An extracted folder:  community/sample/diana/
#    - A slug name:          diana  (searches community/sample/)
#
#  Environment:
#    COMPOSE_FILE         - Compose file path    (default: docker-compose.mcp.yml)
#    COMPOSE_PROJECT_NAME - Compose project name (default: homepilot)
#    MCP_GATEWAY_URL      - Gateway URL          (default: http://localhost:4444)
#    BASIC_AUTH_USER      - Gateway auth user     (default: admin)
#    BASIC_AUTH_PASSWORD   - Gateway auth pass     (default: changeme)
#    AUTO_REGISTER        - Register tools after startup (default: true)
#    HEALTH_TIMEOUT       - Seconds to wait per health check (default: 5)
#    STARTUP_TIMEOUT      - Seconds to wait after starting (default: 30)
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-$ROOT/docker-compose.mcp.yml}"
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-homepilot}"
SAMPLE_DIR="$ROOT/community/sample"
AUTO_REGISTER="${AUTO_REGISTER:-true}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-5}"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:-30}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

ok()   { echo -e "  ${GREEN}✓${NC} $1"; }
warn() { echo -e "  ${YELLOW}⚠${NC} $1"; }
err()  { echo -e "  ${RED}✗${NC} $1"; }
info() { echo -e "  ${CYAN}▶${NC} $1"; }
rocket() { echo -e "  ${BLUE}🚀${NC} $1"; }

# ── Known port map: service name → default port ────────────────────────────
# Used when docker compose config is unavailable (native/local servers).
# Kept in sync with docker-compose.mcp.yml.
declare -A PORT_MAP=(
    [personal-assistant]=9101
    [knowledge]=9102
    [decision-copilot]=9103
    [executive-briefing]=9104
    [web-search]=9105
    [local-notes]=9110
    [local-projects]=9111
    [web-fetch]=9112
    [shell-safe]=9113
    [gmail]=9114
    [google-calendar]=9115
    [microsoft-graph]=9116
    [slack]=9117
    [github]=9118
    [notion]=9119
    [everyday-assistant]=9201
    [chief-of-staff]=9202
)

# ── Name mapping: MCP server name → docker-compose service name ─────────────
# .hpersona packages use names like "mcp-local-notes" or "hp-personal-assistant".
# docker-compose.mcp.yml uses service names like "local-notes" or "personal-assistant".
# This function normalises any known format to the compose service name.
map_server_to_service() {
    local name="$1"

    # Strip common prefixes
    local service="$name"
    service="${service#mcp-}"          # mcp-local-notes    → local-notes
    service="${service#hp-}"           # hp-personal-assistant → personal-assistant

    # Underscore → hyphen (compose services use hyphens)
    service="${service//_/-}"

    # Known aliases that don't follow the simple strip-prefix pattern
    case "$service" in
        web)               service="web-fetch" ;;
        web-mcp)           service="web-fetch" ;;
        web-search)        service="web-search" ;;
        microsoft-graph)   service="microsoft-graph" ;;
        google-calendar)   service="google-calendar" ;;
        shell-safe)        service="shell-safe" ;;
        local-notes)       service="local-notes" ;;
        local-projects)    service="local-projects" ;;
        everyday-assistant) service="everyday-assistant" ;;
        chief-of-staff)    service="chief-of-staff" ;;
    esac

    echo "$service"
}

# ── Validate that a service exists in docker-compose.mcp.yml ────────────────
VALID_SERVICES=""
load_valid_services() {
    if [ -z "$VALID_SERVICES" ]; then
        VALID_SERVICES=$(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null || echo "")
    fi
}

service_exists() {
    load_valid_services
    echo "$VALID_SERVICES" | grep -qx "$1"
}

# ── Health check: is this service already responding? ───────────────────────
# Checks the /health endpoint on the service's port. Works regardless of
# whether the server is running natively, in Docker, or on a remote host.
# Returns 0 if healthy, 1 if not.
health_check() {
    local port="$1"
    curl -sf --connect-timeout "$HEALTH_TIMEOUT" \
        "http://localhost:${port}/health" >/dev/null 2>&1
}

# ── Get port for a service ──────────────────────────────────────────────────
get_service_port() {
    local service="$1"

    # Fast path: use built-in port map
    if [ -n "${PORT_MAP[$service]:-}" ]; then
        echo "${PORT_MAP[$service]}"
        return
    fi

    # Fallback: extract from compose config (slower, requires docker)
    docker compose -f "$COMPOSE_FILE" config --format json 2>/dev/null | \
        python3 -c "
import json, sys
try:
    cfg = json.load(sys.stdin)
    svc = cfg.get('services', {}).get('$service', {})
    env = svc.get('environment', {})
    print(env.get('PORT', ''))
except:
    pass
" 2>/dev/null || echo ""
}

# ── Extract mcp_servers.json from .hpersona or folder ───────────────────────
extract_mcp_servers() {
    local source="$1"
    local tmpdir=""

    if [ -f "$source" ] && [[ "$source" == *.hpersona ]]; then
        # ZIP file — extract dependencies/mcp_servers.json
        tmpdir=$(mktemp -d)
        unzip -qo "$source" "dependencies/mcp_servers.json" -d "$tmpdir" 2>/dev/null || true
        if [ -f "$tmpdir/dependencies/mcp_servers.json" ]; then
            cat "$tmpdir/dependencies/mcp_servers.json"
        else
            echo "{}"
        fi
        rm -rf "$tmpdir"
    elif [ -d "$source" ]; then
        # Extracted folder
        if [ -f "$source/dependencies/mcp_servers.json" ]; then
            cat "$source/dependencies/mcp_servers.json"
        else
            echo "{}"
        fi
    else
        echo "{}"
    fi
}

# ── Extract a2a_agents.json from .hpersona or folder ───────────────────────
extract_a2a_agents() {
    local source="$1"
    local tmpdir=""

    if [ -f "$source" ] && [[ "$source" == *.hpersona ]]; then
        tmpdir=$(mktemp -d)
        unzip -qo "$source" "dependencies/a2a_agents.json" -d "$tmpdir" 2>/dev/null || true
        if [ -f "$tmpdir/dependencies/a2a_agents.json" ]; then
            cat "$tmpdir/dependencies/a2a_agents.json"
        else
            echo "{}"
        fi
        rm -rf "$tmpdir"
    elif [ -d "$source" ]; then
        if [ -f "$source/dependencies/a2a_agents.json" ]; then
            cat "$source/dependencies/a2a_agents.json"
        else
            echo "{}"
        fi
    else
        echo "{}"
    fi
}

# ── Extract persona name from manifest ──────────────────────────────────────
extract_persona_name() {
    local source="$1"
    local tmpdir=""
    local name=""

    if [ -f "$source" ] && [[ "$source" == *.hpersona ]]; then
        tmpdir=$(mktemp -d)
        unzip -qo "$source" "blueprint/persona_agent.json" -d "$tmpdir" 2>/dev/null || true
        if [ -f "$tmpdir/blueprint/persona_agent.json" ]; then
            name=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('label',''))" "$tmpdir/blueprint/persona_agent.json" 2>/dev/null || echo "")
        fi
        rm -rf "$tmpdir"
    elif [ -d "$source" ]; then
        if [ -f "$source/blueprint/persona_agent.json" ]; then
            name=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('label',''))" "$source/blueprint/persona_agent.json" 2>/dev/null || echo "")
        fi
    fi

    echo "${name:-Unknown Persona}"
}

# ── Resolve persona source path ─────────────────────────────────────────────
resolve_persona() {
    local input="$1"

    # Already a file or directory
    if [ -f "$input" ] || [ -d "$input" ]; then
        echo "$input"
        return
    fi

    # Try as slug in community/sample/
    if [ -f "$SAMPLE_DIR/${input}.hpersona" ]; then
        echo "$SAMPLE_DIR/${input}.hpersona"
        return
    fi
    if [ -d "$SAMPLE_DIR/${input}" ]; then
        echo "$SAMPLE_DIR/${input}"
        return
    fi

    # Try with absolute path from ROOT
    if [ -f "$ROOT/$input" ]; then
        echo "$ROOT/$input"
        return
    fi
    if [ -d "$ROOT/$input" ]; then
        echo "$ROOT/$input"
        return
    fi

    echo ""
}

# ── Parse dependencies into service name + port pairs ───────────────────────
# Output: one line per service in format "service_name:port"
get_required_services() {
    local source="$1"
    local services=()

    # MCP servers
    local mcp_json
    mcp_json=$(extract_mcp_servers "$source")
    local mcp_names
    mcp_names=$(echo "$mcp_json" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for s in data.get('servers', []):
        print(s.get('name', ''))
except:
    pass
" 2>/dev/null || echo "")

    for name in $mcp_names; do
        [ -z "$name" ] && continue
        local svc
        svc=$(map_server_to_service "$name")
        services+=("$svc")
    done

    # A2A agents
    local a2a_json
    a2a_json=$(extract_a2a_agents "$source")
    local a2a_names
    a2a_names=$(echo "$a2a_json" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    for a in data.get('agents', []):
        print(a.get('name', ''))
except:
    pass
" 2>/dev/null || echo "")

    for name in $a2a_names; do
        [ -z "$name" ] && continue
        local svc
        svc=$(map_server_to_service "$name")
        services+=("$svc")
    done

    # Deduplicate
    printf '%s\n' "${services[@]}" | sort -u
}

# ── Build the image if not yet built ────────────────────────────────────────
ensure_image() {
    local image_id
    image_id=$(docker images -q homepilot/mcp-server:latest 2>/dev/null || echo "")
    if [ -z "$image_id" ]; then
        info "Building homepilot/mcp-server image (first time)..."
        docker compose -f "$COMPOSE_FILE" build mcp-base
        ok "Image built"
    fi
}

# ── Wait for a service to become healthy after startup ──────────────────────
wait_for_health() {
    local port="$1"
    local max_wait="$STARTUP_TIMEOUT"

    for i in $(seq 1 "$max_wait"); do
        if health_check "$port"; then
            return 0
        fi
        sleep 1
    done
    return 1
}

# ==============================================================================
# Commands
# ==============================================================================

# ── --list: Show available personas ─────────────────────────────────────────
cmd_list() {
    echo ""
    echo -e "${BOLD}  Available Personas${NC}"
    echo "  ──────────────────"
    echo ""

    if [ ! -d "$SAMPLE_DIR" ]; then
        warn "No personas found in $SAMPLE_DIR"
        return
    fi

    for pkg in "$SAMPLE_DIR"/*.hpersona; do
        [ ! -f "$pkg" ] && continue
        local slug
        slug=$(basename "$pkg" .hpersona)
        local name
        name=$(extract_persona_name "$pkg")

        # Count required services
        local services
        services=$(get_required_services "$pkg" 2>/dev/null || echo "")
        local count=0
        if [ -n "$services" ]; then
            count=$(echo "$services" | wc -l)
        fi

        printf "  %-12s %-25s " "$slug" "$name"
        echo -e "${DIM}($count MCP servers)${NC}"
    done

    echo ""
    echo -e "  ${DIM}Usage: ./scripts/persona-launch.sh <slug>${NC}"
    echo ""
}

# ── --running: Show running MCP services ────────────────────────────────────
cmd_running() {
    echo ""
    echo -e "${BOLD}  Running MCP Services${NC}"
    echo "  ────────────────────"
    echo ""

    local any_found=false

    for svc in "${!PORT_MAP[@]}"; do
        local port="${PORT_MAP[$svc]}"
        if health_check "$port"; then
            ok "$svc (port $port) — healthy"
            any_found=true
        fi
    done | sort

    if [ "$any_found" = false ]; then
        # Check with docker too
        local running
        running=$(docker compose -f "$COMPOSE_FILE" ps --format "table {{.Service}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "")

        if [ -z "$running" ] || [ "$(echo "$running" | wc -l)" -le 1 ]; then
            warn "No MCP services running"
        else
            echo "$running" | while IFS= read -r line; do
                echo "  $line"
            done
        fi
    fi

    echo ""
}

# ── --check: Dry-run, show what's running and what would start ──────────────
cmd_check() {
    local source="$1"
    local persona_name
    persona_name=$(extract_persona_name "$source")

    echo ""
    echo -e "${BOLD}  Persona: ${persona_name}${NC}"
    echo "  ──────────────────────────"
    echo ""

    local services
    services=$(get_required_services "$source")

    if [ -z "$services" ]; then
        warn "No MCP servers or A2A agents declared"
        echo ""
        return
    fi

    local already_running=()
    local needs_start=()

    while IFS= read -r svc; do
        [ -z "$svc" ] && continue
        local port
        port=$(get_service_port "$svc")

        if [ -n "$port" ] && health_check "$port"; then
            ok "$svc (port $port) — ${GREEN}already running${NC}"
            already_running+=("$svc")
        else
            echo -e "  ${DIM}○${NC} $svc (port ${port:-?}) — ${DIM}not running${NC}"
            needs_start+=("$svc")
        fi
    done <<< "$services"

    echo ""

    if [ ${#needs_start[@]} -eq 0 ]; then
        ok "All services already running — nothing to start"
    else
        info "Would start ${#needs_start[@]} service(s): ${needs_start[*]}"
        echo -e "  ${DIM}docker compose -f docker-compose.mcp.yml up -d ${needs_start[*]}${NC}"
    fi

    if [ ${#already_running[@]} -gt 0 ]; then
        echo -e "  ${DIM}Already running (skipped): ${already_running[*]}${NC}"
    fi

    echo ""
}

# ── --stop: Stop persona's servers ──────────────────────────────────────────
cmd_stop() {
    local source="$1"
    local persona_name
    persona_name=$(extract_persona_name "$source")

    echo ""
    echo -e "${BOLD}  Stopping servers for: ${persona_name}${NC}"
    echo ""

    local services
    services=$(get_required_services "$source")

    if [ -z "$services" ]; then
        warn "No services to stop"
        return
    fi

    local svc_list
    svc_list=$(echo "$services" | tr '\n' ' ')
    docker compose -f "$COMPOSE_FILE" stop $svc_list 2>/dev/null
    ok "Stopped: $svc_list"
    echo ""
}

# ── --status: Show status of persona's servers ──────────────────────────────
cmd_status() {
    local source="$1"
    local persona_name
    persona_name=$(extract_persona_name "$source")

    echo ""
    echo -e "${BOLD}  Server Status: ${persona_name}${NC}"
    echo "  ──────────────────────────────"
    echo ""

    local services
    services=$(get_required_services "$source")

    if [ -z "$services" ]; then
        warn "No MCP servers declared"
        return
    fi

    local total=0
    local healthy=0

    while IFS= read -r svc; do
        [ -z "$svc" ] && continue
        total=$((total + 1))
        local port
        port=$(get_service_port "$svc")

        if [ -n "$port" ] && health_check "$port"; then
            ok "$svc (port $port) — ${GREEN}healthy${NC}"
            healthy=$((healthy + 1))
        else
            # Check if Docker container is running but unhealthy
            local state
            state=$(docker compose -f "$COMPOSE_FILE" ps --format "{{.State}}" "$svc" 2>/dev/null || echo "")

            if [ "$state" = "running" ]; then
                warn "$svc (port ${port:-?}) — container running, health check failed"
            elif [ -n "$state" ]; then
                err "$svc (port ${port:-?}) — container state: $state"
            else
                echo -e "  ${DIM}○${NC} $svc (port ${port:-?}) — ${DIM}not running${NC}"
            fi
        fi
    done <<< "$services"

    echo ""
    if [ "$healthy" -eq "$total" ] && [ "$total" -gt 0 ]; then
        ok "All $total services healthy"
    elif [ "$healthy" -gt 0 ]; then
        warn "$healthy/$total services healthy"
    else
        err "No services responding"
    fi
    echo ""
}

# ── Main launch command (health-check-first) ────────────────────────────────
cmd_launch() {
    local source="$1"
    local force="${2:-false}"
    local persona_name
    persona_name=$(extract_persona_name "$source")

    echo ""
    echo "  ══════════════════════════════════════════════════════════════"
    echo -e "  ${BOLD}HomePilot — Launching Persona${NC}"
    echo -e "  ${CYAN}${persona_name}${NC}"
    echo "  ══════════════════════════════════════════════════════════════"
    echo ""

    # 1. Parse dependencies
    local services
    services=$(get_required_services "$source")

    if [ -z "$services" ]; then
        warn "No MCP servers or A2A agents declared in this persona."
        warn "The persona will work but without tool integrations."
        echo ""
        return 0
    fi

    # 2. Health-check-first: classify each service
    local already_running=()
    local needs_start=()
    local invalid_services=()

    load_valid_services
    info "Checking which services are already running..."
    echo ""

    while IFS= read -r svc; do
        [ -z "$svc" ] && continue
        local port
        port=$(get_service_port "$svc")

        if [ "$force" = "true" ]; then
            # --force: skip health check, always restart
            if service_exists "$svc" || [ -n "${PORT_MAP[$svc]:-}" ]; then
                needs_start+=("$svc")
                echo -e "  ${DIM}○${NC} $svc (port ${port:-?}) — force restart"
            else
                invalid_services+=("$svc")
                err "$svc — not found in docker-compose.mcp.yml"
            fi
        elif [ -n "$port" ] && health_check "$port"; then
            # Already running and healthy — skip
            already_running+=("$svc")
            ok "$svc (port $port) — ${GREEN}already running${NC}"
        elif service_exists "$svc" || [ -n "${PORT_MAP[$svc]:-}" ]; then
            # Not running, but we know how to start it
            needs_start+=("$svc")
            echo -e "  ${DIM}○${NC} $svc (port ${port:-?}) — not running"
        else
            # Unknown service
            invalid_services+=("$svc")
            err "$svc — not found in docker-compose.mcp.yml"
        fi
    done <<< "$services"

    echo ""

    # 3. Report invalid services
    if [ ${#invalid_services[@]} -gt 0 ]; then
        warn "Unknown services (skipped): ${invalid_services[*]}"
        echo ""
    fi

    # 4. If everything is already running, we're done
    if [ ${#needs_start[@]} -eq 0 ]; then
        if [ ${#already_running[@]} -gt 0 ]; then
            ok "All ${#already_running[@]} service(s) already running — nothing to start!"
        else
            err "No valid services to start."
            return 1
        fi
    else
        # 5. Ensure Docker image exists (only if we need to start something)
        ensure_image

        # 6. Start only the missing services
        local svc_list="${needs_start[*]}"
        info "Starting ${#needs_start[@]} service(s): $svc_list"
        echo ""

        docker compose -f "$COMPOSE_FILE" up -d $svc_list

        echo ""

        # 7. Wait for newly started services to become healthy
        info "Waiting for services to become healthy..."
        echo ""

        local started_ok=()
        local started_fail=()

        for svc in "${needs_start[@]}"; do
            local port
            port=$(get_service_port "$svc")
            if [ -n "$port" ]; then
                if wait_for_health "$port"; then
                    rocket "$svc (port $port) — ${GREEN}started and healthy${NC}"
                    started_ok+=("$svc")
                else
                    err "$svc (port $port) — started but health check timed out"
                    started_fail+=("$svc")
                fi
            else
                rocket "$svc — started"
                started_ok+=("$svc")
            fi
        done
    fi

    echo ""

    # 8. Optional: register tools with Context Forge gateway
    if [ "$AUTO_REGISTER" = "true" ] && [ -f "$ROOT/scripts/mcp-register.sh" ]; then
        local gateway_url="${MCP_GATEWAY_URL:-http://localhost:4444}"
        if curl -sf --connect-timeout 3 "${gateway_url}/health" >/dev/null 2>&1; then
            info "Registering tools with Context Forge..."
            bash "$ROOT/scripts/mcp-register.sh" homepilot 2>/dev/null && \
                ok "Tools registered with gateway" || \
                warn "Tool registration skipped (gateway may need setup)"
        else
            echo -e "  ${DIM}Skipping tool registration (gateway not running on $gateway_url)${NC}"
        fi
    fi

    # 9. Summary
    echo ""
    echo "  ──────────────────────────────────────────────────────────────"

    local total_ok=$(( ${#already_running[@]} + ${#started_ok[@]:-0} ))
    local total_fail=${#started_fail[@]:-0}
    local total_req=$(( total_ok + total_fail + ${#invalid_services[@]} ))

    if [ "$total_fail" -eq 0 ] && [ ${#invalid_services[@]} -eq 0 ]; then
        ok "${BOLD}${persona_name}${NC} ${GREEN}is ready!${NC}  ($total_ok/$total_req services)"
    else
        warn "${BOLD}${persona_name}${NC} ${YELLOW}started with warnings${NC}  ($total_ok/$total_req healthy)"
    fi

    echo ""

    # Show what happened
    if [ ${#already_running[@]} -gt 0 ]; then
        echo -e "  ${DIM}Already running:  ${already_running[*]}${NC}"
    fi
    if [ ${#started_ok[@]:-0} -gt 0 ]; then
        echo -e "  ${DIM}Newly started:    ${started_ok[*]}${NC}"
    fi
    if [ ${#started_fail[@]:-0} -gt 0 ]; then
        echo -e "  ${DIM}Failed to start:  ${started_fail[*]}${NC}"
    fi

    local slug
    slug=$(basename "$source" .hpersona)
    echo ""
    echo -e "  ${DIM}Status:    ./scripts/persona-launch.sh $slug --status${NC}"
    echo -e "  ${DIM}Stop:      ./scripts/persona-launch.sh $slug --stop${NC}"
    echo -e "  ${DIM}Restart:   ./scripts/persona-launch.sh $slug --force${NC}"
    echo ""
}

# ==============================================================================
# Usage
# ==============================================================================
usage() {
    echo ""
    echo -e "${BOLD}  HomePilot Persona Launcher${NC}"
    echo ""
    echo "  Reads a persona's MCP server dependencies and starts only what's missing."
    echo "  Servers already running locally are detected and skipped (health-check-first)."
    echo ""
    echo "  Usage:"
    echo "    $(basename "$0") <persona>              Start missing MCP servers"
    echo "    $(basename "$0") <persona> --check      Dry-run: show what's running/missing"
    echo "    $(basename "$0") <persona> --stop       Stop persona's MCP servers"
    echo "    $(basename "$0") <persona> --status     Show health status"
    echo "    $(basename "$0") <persona> --force      Force restart all (ignore health)"
    echo "    $(basename "$0") --list                 List available personas"
    echo "    $(basename "$0") --running              Show all running MCP services"
    echo ""
    echo "  <persona> can be:"
    echo "    - A .hpersona file:     community/sample/diana.hpersona"
    echo "    - An extracted folder:  community/sample/diana/"
    echo "    - A slug name:          diana"
    echo ""
    echo "  Examples:"
    echo "    $(basename "$0") diana                  # Start Microsoft Graph for Diana"
    echo "    $(basename "$0") kai --check            # Check which servers Kai needs"
    echo "    $(basename "$0") nora --stop            # Stop Nora's notes server"
    echo "    $(basename "$0") diana --force          # Force restart Diana's servers"
    echo ""
    echo "  Statuses:"
    echo "    ${GREEN}✓${NC} already running    Server healthy on port — skipped"
    echo "    ${BLUE}🚀${NC} started            Was missing — started via Docker, now healthy"
    echo "    ${RED}✗${NC} failed             Started but health check timed out"
    echo "    ${DIM}○${NC} not running        Server not responding — will be started"
    echo ""
    echo "  Environment:"
    echo "    COMPOSE_FILE         docker-compose path   (default: docker-compose.mcp.yml)"
    echo "    AUTO_REGISTER        register with Forge   (default: true)"
    echo "    MCP_GATEWAY_URL      Forge gateway URL     (default: http://localhost:4444)"
    echo "    HEALTH_TIMEOUT       health check timeout  (default: 5s)"
    echo "    STARTUP_TIMEOUT      post-start wait time  (default: 30s)"
    echo ""
}

# ==============================================================================
# Main
# ==============================================================================
ARG1="${1:-}"
ARG2="${2:-}"

case "$ARG1" in
    --list|-l)
        cmd_list
        exit 0
        ;;
    --running|-r)
        cmd_running
        exit 0
        ;;
    --help|-h|"")
        usage
        exit 0
        ;;
esac

# Resolve persona source
SOURCE=$(resolve_persona "$ARG1")
if [ -z "$SOURCE" ]; then
    err "Persona not found: $ARG1"
    echo ""
    echo "  Try: $(basename "$0") --list"
    echo ""
    exit 1
fi

case "$ARG2" in
    --check|-c)    cmd_check  "$SOURCE" ;;
    --stop|-s)     cmd_stop   "$SOURCE" ;;
    --status|-S)   cmd_status "$SOURCE" ;;
    --force|-f)    cmd_launch "$SOURCE" "true" ;;
    "")            cmd_launch "$SOURCE" ;;
    *)
        err "Unknown option: $ARG2"
        usage
        exit 1
        ;;
esac
