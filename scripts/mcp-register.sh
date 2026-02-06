#!/usr/bin/env bash
# ==============================================================================
#  MCP Context Forge - Registration Script for HomePilot
#  Registers tools, gateways, agents, and virtual servers with the MCP Gateway.
#
#  Usage:
#    ./scripts/mcp-register.sh tool      <json-file-or-inline>
#    ./scripts/mcp-register.sh gateway   <json-file-or-inline>
#    ./scripts/mcp-register.sh agent     <json-file-or-inline>
#    ./scripts/mcp-register.sh server    <json-file-or-inline>
#    ./scripts/mcp-register.sh homepilot                        # Register HomePilot default tools
#    ./scripts/mcp-register.sh list      [tools|gateways|agents|servers]
#    ./scripts/mcp-register.sh refresh   <gateway-id>
#
#  Environment:
#    MCP_GATEWAY_URL    - Gateway base URL (default: http://localhost:4444)
#    BASIC_AUTH_USER    - Auth user         (default: admin)
#    BASIC_AUTH_PASSWORD- Auth password     (default: changeme)
# ==============================================================================
set -euo pipefail

GATEWAY_URL="${MCP_GATEWAY_URL:-http://localhost:4444}"
AUTH_USER="${BASIC_AUTH_USER:-admin}"
AUTH_PASS="${BASIC_AUTH_PASSWORD:-changeme}"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
err()  { echo -e "${RED}✗${NC} $1"; }
info() { echo -e "${CYAN}▶${NC} $1"; }

api_call() {
    local method="$1" path="$2" body="${3:-}"
    if [ -n "$body" ]; then
        curl -s -X "$method" "${GATEWAY_URL}${path}" \
            -u "${AUTH_USER}:${AUTH_PASS}" \
            -H "Content-Type: application/json" \
            -d "$body"
    else
        curl -s -X "$method" "${GATEWAY_URL}${path}" \
            -u "${AUTH_USER}:${AUTH_PASS}"
    fi
}

# ── Register a tool ──────────────────────────────────────────────────────────
register_tool() {
    local payload="$1"
    # If it's a file, read it
    if [ -f "$payload" ]; then
        payload=$(cat "$payload")
    fi
    info "Registering tool..."
    local response
    response=$(api_call POST /tools "$payload")
    local tool_id
    tool_id=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")
    if [ -n "$tool_id" ] && [ "$tool_id" != "" ]; then
        ok "Tool registered: $tool_id"
        echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'id':d.get('id'),'name':d.get('name'),'enabled':d.get('enabled')}, indent=2))" 2>/dev/null || echo "$response"
    else
        err "Failed to register tool"
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    fi
}

# ── Register a gateway ───────────────────────────────────────────────────────
register_gateway() {
    local payload="$1"
    if [ -f "$payload" ]; then
        payload=$(cat "$payload")
    fi
    info "Registering gateway..."
    local response
    response=$(api_call POST /gateways "$payload")
    local gw_id
    gw_id=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")
    if [ -n "$gw_id" ] && [ "$gw_id" != "" ]; then
        ok "Gateway registered: $gw_id"
        echo ""
        info "Refreshing tools from gateway..."
        api_call POST "/gateways/${gw_id}/refresh" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f\"  Tools added: {d.get('tools_added',0)}\")
print(f\"  Tools updated: {d.get('tools_updated',0)}\")
" 2>/dev/null || warn "Could not refresh (manual refresh: make mcp-refresh GW_ID=$gw_id)"
    else
        err "Failed to register gateway"
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    fi
}

# ── Register an A2A agent ────────────────────────────────────────────────────
register_agent() {
    local payload="$1"
    if [ -f "$payload" ]; then
        payload=$(cat "$payload")
    fi
    info "Registering A2A agent..."
    local response
    response=$(api_call POST /a2a "$payload")
    local agent_id
    agent_id=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")
    if [ -n "$agent_id" ] && [ "$agent_id" != "" ]; then
        ok "Agent registered: $agent_id"
        echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps({'id':d.get('id'),'name':d.get('name'),'agent_type':d.get('agent_type'),'endpoint_url':d.get('endpoint_url')}, indent=2))" 2>/dev/null || echo "$response"
    else
        err "Failed to register agent"
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    fi
}

# ── Register a virtual server ────────────────────────────────────────────────
register_server() {
    local payload="$1"
    if [ -f "$payload" ]; then
        payload=$(cat "$payload")
    fi
    info "Registering virtual server..."
    local response
    response=$(api_call POST /servers "$payload")
    local srv_id
    srv_id=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")
    if [ -n "$srv_id" ] && [ "$srv_id" != "" ]; then
        ok "Virtual server registered: $srv_id"
        ok "SSE endpoint: ${GATEWAY_URL}/servers/${srv_id}/sse"
    else
        err "Failed to register virtual server"
        echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    fi
}

# ── List registered entities ─────────────────────────────────────────────────
list_entities() {
    local entity="${1:-tools}"
    case "$entity" in
        tools)
            info "Registered tools:"
            api_call GET /tools | python3 -c "
import sys,json
tools=json.load(sys.stdin)
if isinstance(tools,list):
    for t in tools:
        status='ON' if t.get('enabled',True) else 'OFF'
        print(f\"  [{status}] {t.get('name','?'):30s} {t.get('description','')[:50]}\")
    print(f\"\n  Total: {len(tools)} tools\")
else:
    print(json.dumps(tools,indent=2))
" 2>/dev/null || api_call GET /tools
            ;;
        gateways)
            info "Registered gateways:"
            api_call GET /gateways | python3 -c "
import sys,json
gws=json.load(sys.stdin)
if isinstance(gws,list):
    for g in gws:
        print(f\"  {g.get('id','?')[:8]}  {g.get('name','?'):25s} {g.get('url','')}\")
    print(f\"\n  Total: {len(gws)} gateways\")
else:
    print(json.dumps(gws,indent=2))
" 2>/dev/null || api_call GET /gateways
            ;;
        agents|a2a)
            info "Registered A2A agents:"
            api_call GET /a2a | python3 -c "
import sys,json
data=json.load(sys.stdin)
agents=data if isinstance(data,list) else data.get('agents',[])
for a in agents:
    status='ON' if a.get('enabled',True) else 'OFF'
    print(f\"  [{status}] {a.get('name','?'):30s} {a.get('endpoint_url','')}\")
print(f\"\n  Total: {len(agents)} agents\")
" 2>/dev/null || api_call GET /a2a
            ;;
        servers)
            info "Registered virtual servers:"
            api_call GET /servers | python3 -c "
import sys,json
srvs=json.load(sys.stdin)
if isinstance(srvs,list):
    for s in srvs:
        print(f\"  {s.get('id','?')[:8]}  {s.get('name','?'):25s} {s.get('description','')[:40]}\")
    print(f\"\n  Total: {len(srvs)} servers\")
else:
    print(json.dumps(srvs,indent=2))
" 2>/dev/null || api_call GET /servers
            ;;
        *)
            err "Unknown entity: $entity (use: tools, gateways, agents, servers)"
            exit 1
            ;;
    esac
}

# ── Refresh gateway tools ────────────────────────────────────────────────────
refresh_gateway() {
    local gw_id="$1"
    info "Refreshing gateway $gw_id..."
    local response
    response=$(api_call POST "/gateways/${gw_id}/refresh")
    echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
}

# ── Register HomePilot default tools ─────────────────────────────────────────
register_homepilot_defaults() {
    echo ""
    echo -e "${BOLD}  Registering HomePilot Default Tools${NC}"
    echo "  ────────────────────────────────────"
    echo ""

    # Tool 1: Image generation (wraps ComfyUI)
    info "Registering: homepilot_imagine"
    register_tool '{
        "tool": {
            "name": "homepilot_imagine",
            "description": "Generate images from text descriptions using ComfyUI (FLUX, SDXL). Supports style presets and resolution options.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Text description of the image to generate"},
                    "negative_prompt": {"type": "string", "description": "What to avoid in the image", "default": ""},
                    "model": {"type": "string", "enum": ["flux-schnell", "sdxl", "flux-dev"], "default": "flux-schnell"},
                    "width": {"type": "integer", "default": 1024},
                    "height": {"type": "integer", "default": 1024}
                },
                "required": ["prompt"]
            },
            "url": "http://localhost:8000/api/imagine",
            "integration_type": "REST",
            "request_type": "POST"
        }
    }'

    echo ""

    # Tool 2: Chat with LLM (wraps Ollama)
    info "Registering: homepilot_chat"
    register_tool '{
        "tool": {
            "name": "homepilot_chat",
            "description": "Send a message to the HomePilot LLM (Ollama) and get a response. Supports multi-turn conversation.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "User message to send to the LLM"},
                    "conversation_id": {"type": "string", "description": "Conversation ID for context continuity"},
                    "model": {"type": "string", "description": "LLM model to use", "default": "llama3:8b"}
                },
                "required": ["message"]
            },
            "url": "http://localhost:8000/api/chat",
            "integration_type": "REST",
            "request_type": "POST"
        }
    }'

    echo ""

    # Tool 3: Story generation
    info "Registering: homepilot_story"
    register_tool '{
        "tool": {
            "name": "homepilot_story",
            "description": "Generate an AI story with scenes, narration, and auto-generated images. Supports multiple genres and styles.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Story title"},
                    "genre": {"type": "string", "enum": ["fantasy", "sci-fi", "drama", "comedy", "horror", "adventure"], "default": "fantasy"},
                    "num_scenes": {"type": "integer", "description": "Number of scenes to generate", "default": 5, "minimum": 1, "maximum": 20},
                    "style": {"type": "string", "description": "Visual style for scene images", "default": "cinematic"}
                },
                "required": ["title"]
            },
            "url": "http://localhost:8000/api/story/generate",
            "integration_type": "REST",
            "request_type": "POST"
        }
    }'

    echo ""

    # Tool 4: Health check
    info "Registering: homepilot_health"
    register_tool '{
        "tool": {
            "name": "homepilot_health",
            "description": "Check the health status of all HomePilot services (backend, ComfyUI, Ollama, media).",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            },
            "url": "http://localhost:8000/health/detailed",
            "integration_type": "REST",
            "request_type": "GET",
            "annotations": {
                "readOnlyHint": true,
                "idempotentHint": true
            }
        }
    }'

    echo ""
    # Tool 5: Agentic image generation (Phase 3 — routes through /v1/agentic/invoke)
    info "Registering: homepilot_agentic_imagine"
    register_tool '{
        "tool": {
            "name": "homepilot_agentic_imagine",
            "description": "Generate images using the HomePilot agentic adapter. Supports fast/balanced/quality profiles with server-enforced defaults.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Text description of the image to generate"},
                    "profile": {"type": "string", "enum": ["fast", "balanced", "quality"], "default": "fast", "description": "Speed vs quality preference"},
                    "model": {"type": "string", "enum": ["sdxl", "flux-schnell", "flux-dev"], "default": "sdxl"}
                },
                "required": ["prompt"]
            },
            "url": "http://localhost:8000/v1/agentic/invoke",
            "integration_type": "REST",
            "request_type": "POST"
        }
    }'

    echo ""

    # Tool 6: Agentic video generation (Phase 3 — routes through /v1/agentic/invoke)
    info "Registering: homepilot_agentic_animate"
    register_tool '{
        "tool": {
            "name": "homepilot_agentic_animate",
            "description": "Generate videos using the HomePilot agentic adapter. Supports fast/balanced/quality profiles with server-enforced defaults.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Text description of the video to generate"},
                    "profile": {"type": "string", "enum": ["fast", "balanced", "quality"], "default": "fast", "description": "Speed vs quality preference"}
                },
                "required": ["prompt"]
            },
            "url": "http://localhost:8000/v1/agentic/invoke",
            "integration_type": "REST",
            "request_type": "POST"
        }
    }'

    echo ""

    ok "HomePilot default tools registered!"
    echo ""
    echo "  View all tools:    make mcp-list-tools"
    echo "  View admin UI:     ${GATEWAY_URL}/admin"
    echo ""
}

# ── Main ─────────────────────────────────────────────────────────────────────
usage() {
    echo "Usage: $0 <command> [args]"
    echo ""
    echo "Commands:"
    echo "  tool      <json>       Register an MCP tool"
    echo "  gateway   <json>       Register an MCP gateway (federation)"
    echo "  agent     <json>       Register an A2A agent"
    echo "  server    <json>       Register a virtual server"
    echo "  homepilot              Register HomePilot default tools"
    echo "  list      [entity]     List tools|gateways|agents|servers"
    echo "  refresh   <gw-id>      Refresh tools from a gateway"
    echo ""
    echo "Examples:"
    echo "  $0 tool '{\"tool\":{\"name\":\"my-tool\",\"description\":\"A test tool\"}}'"
    echo "  $0 gateway '{\"gateway\":{\"name\":\"my-gw\",\"url\":\"http://localhost:9100/mcp/\"}}'"
    echo "  $0 agent '{\"agent\":{\"name\":\"my-agent\",\"endpoint_url\":\"http://localhost:9200\"}}'"
    echo "  $0 list tools"
    echo "  $0 homepilot"
    echo ""
}

COMMAND="${1:-}"
shift || true

case "$COMMAND" in
    tool)     register_tool "${1:?'JSON payload required'}" ;;
    gateway)  register_gateway "${1:?'JSON payload required'}" ;;
    agent)    register_agent "${1:?'JSON payload required'}" ;;
    server)   register_server "${1:?'JSON payload required'}" ;;
    homepilot) register_homepilot_defaults ;;
    list)     list_entities "${1:-tools}" ;;
    refresh)  refresh_gateway "${1:?'Gateway ID required'}" ;;
    help|-h|--help) usage ;;
    *)
        if [ -z "$COMMAND" ]; then
            usage
        else
            err "Unknown command: $COMMAND"
            usage
            exit 1
        fi
        ;;
esac
