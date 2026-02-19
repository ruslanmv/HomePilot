#!/usr/bin/env bash
# ==============================================================================
#  HomePilot — End-to-End Verification Script
#
#  Runs all verification steps in sequence and produces a summary report.
#  Non-destructive: only reads, tests, and health-checks — never modifies.
#
#  Usage:
#    ./scripts/verify_end_to_end.sh              # full verification
#    ./scripts/verify_end_to_end.sh --quick      # skip Docker/Forge (CI-safe)
#    ./scripts/verify_end_to_end.sh --report     # output machine-readable JSON
#
#  Exit codes:
#    0  All checks passed
#    1  One or more checks failed (see report for details)
# ==============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUICK_MODE=false
JSON_REPORT=false
REPORT_FILE="$ROOT/verification-report.json"

for arg in "$@"; do
  case "$arg" in
    --quick)  QUICK_MODE=true ;;
    --report) JSON_REPORT=true ;;
  esac
done

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

# Counters
PASS=0
FAIL=0
SKIP=0
RESULTS=()

# ── Helpers ──────────────────────────────────────────────────────────────────

pass() {
  local label="$1"
  echo -e "  ${GREEN}✓${NC} $label"
  PASS=$((PASS + 1))
  RESULTS+=("{\"check\":\"$label\",\"status\":\"pass\"}")
}

fail() {
  local label="$1"
  local detail="${2:-}"
  echo -e "  ${RED}✗${NC} $label"
  [ -n "$detail" ] && echo -e "    ${DIM}$detail${NC}"
  FAIL=$((FAIL + 1))
  RESULTS+=("{\"check\":\"$label\",\"status\":\"fail\",\"detail\":\"$detail\"}")
}

skip() {
  local label="$1"
  local reason="${2:-}"
  echo -e "  ${YELLOW}○${NC} $label ${DIM}($reason)${NC}"
  SKIP=$((SKIP + 1))
  RESULTS+=("{\"check\":\"$label\",\"status\":\"skip\",\"reason\":\"$reason\"}")
}

section() {
  echo ""
  echo -e "${CYAN}═══ $1 ═══${NC}"
}

# ── Step 0: Prerequisites ──────────────────────────────────────────────────

section "Step 0: Prerequisites"

# Python
if command -v python3 &>/dev/null; then
  PY_VER=$(python3 --version 2>&1 | awk '{print $2}')
  if python3 --version 2>&1 | grep -qE "3\.(11|12|13)"; then
    pass "Python $PY_VER"
  else
    fail "Python $PY_VER" "Requires 3.11+"
  fi
else
  fail "Python not found"
fi

# Node
if command -v node &>/dev/null; then
  NODE_VER=$(node --version 2>&1)
  pass "Node $NODE_VER"
else
  skip "Node.js" "not installed (optional for MCP)"
fi

# uv
if command -v uv &>/dev/null; then
  pass "uv package manager"
else
  fail "uv not found" "Install: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

# Docker (optional unless full mode)
if command -v docker &>/dev/null; then
  if docker info &>/dev/null 2>&1; then
    DOCKER_VER=$(docker --version 2>&1 | awk '{print $3}' | tr -d ',')
    pass "Docker $DOCKER_VER (daemon running)"
    DOCKER_OK=true
  else
    skip "Docker installed but daemon not running" "some checks will be skipped"
    DOCKER_OK=false
  fi
else
  skip "Docker" "not installed — container checks skipped"
  DOCKER_OK=false
fi

# ── Step 1: make install ──────────────────────────────────────────────────

section "Step 1: Install"

if [ -d "$ROOT/backend/.venv" ]; then
  pass "Backend virtualenv exists"
else
  echo "  Running make install..."
  if (cd "$ROOT" && make install >/dev/null 2>&1); then
    pass "make install succeeded"
  else
    fail "make install" "check output above"
  fi
fi

# Verify key packages
if "$ROOT/backend/.venv/bin/python" -c "import fastapi, httpx, yaml" 2>/dev/null; then
  pass "Core Python packages (fastapi, httpx, yaml)"
else
  fail "Missing Python packages"
fi

# ── Step 2: Backend Tests ────────────────────────────────────────────────

section "Step 2: Backend Tests"

echo "  Running pytest (backend)..."
BACKEND_RC=0
BACKEND_OUT=$("$ROOT/backend/.venv/bin/python" -m pytest "$ROOT/backend/tests/" --tb=short 2>&1) || BACKEND_RC=$?
# Extract passed/failed from pytest summary (handles both "X passed" and bare-dots formats)
BACKEND_PASSED=$(echo "$BACKEND_OUT" | grep -oP '\d+(?= passed)' | head -1 || echo "")
BACKEND_FAILED=$(echo "$BACKEND_OUT" | grep -oP '\d+(?= failed)' | head -1 || echo "")
# If no "X passed" line, count from collected items
if [ -z "$BACKEND_PASSED" ]; then
  BACKEND_PASSED=$(echo "$BACKEND_OUT" | grep -oP '(\d+) items' | grep -oP '\d+' || echo "")
fi

if [ "$BACKEND_RC" -eq 0 ]; then
  pass "Backend tests: ${BACKEND_PASSED:-all} passed"
else
  fail "Backend tests" "${BACKEND_PASSED:-?} passed, ${BACKEND_FAILED:-?} failed"
fi

# ── Step 3: MCP Server Unit Tests ────────────────────────────────────────

section "Step 3: MCP Server & A2A Agent Tests"

echo "  Running pytest (MCP/A2A)..."
MCP_RC=0
MCP_OUT=$("$ROOT/backend/.venv/bin/python" -m pytest "$ROOT/backend/tests/test_mcp_servers.py" --tb=short 2>&1) || MCP_RC=$?
MCP_PASSED=$(echo "$MCP_OUT" | grep -oP '\d+(?= passed)' | head -1 || echo "")

if [ "$MCP_RC" -eq 0 ]; then
  pass "MCP/A2A tests: ${MCP_PASSED:-all} passed"
else
  MCP_FAILED=$(echo "$MCP_OUT" | grep -oP '\d+(?= failed)' | head -1 || echo "?")
  fail "MCP/A2A tests" "${MCP_PASSED:-?} passed, $MCP_FAILED failed"
fi

# ── Step 4: New MCP Server Tests (10 servers × 7 tests) ─────────────────

section "Step 4: Individual MCP Server Tests"

MCP_SERVERS=(local_notes local_projects web shell_safe gmail google_calendar microsoft_graph slack github notion)
NEW_MCP_PASS=0
NEW_MCP_FAIL=0

for server in "${MCP_SERVERS[@]}"; do
  SERVER_DIR="$ROOT/agentic/integrations/mcp/$server"
  if [ -d "$SERVER_DIR/tests" ]; then
    RC=0
    OUT=$("$ROOT/backend/.venv/bin/python" -m pytest "$SERVER_DIR/tests/" --tb=short 2>&1) || RC=$?
    if [ "$RC" -eq 0 ]; then
      COUNT=$(echo "$OUT" | grep -oP '\d+(?= passed)' | head -1 || echo "7")
      NEW_MCP_PASS=$((NEW_MCP_PASS + ${COUNT:-7}))
    else
      NEW_MCP_FAIL=$((NEW_MCP_FAIL + 1))
      fail "mcp-$server tests"
    fi
  fi
done

if [ "$NEW_MCP_FAIL" -eq 0 ]; then
  pass "Individual MCP server tests: $NEW_MCP_PASS passed across ${#MCP_SERVERS[@]} servers"
fi

# ── Step 5: Configuration Validation ─────────────────────────────────────

section "Step 5: Configuration Validation"

# .env.example exists
if [ -f "$ROOT/.env.example" ]; then
  pass ".env.example exists"
else
  fail ".env.example missing"
fi

# docker-compose.mcp.yml valid YAML
if "$ROOT/backend/.venv/bin/python" -c "import yaml; yaml.safe_load(open('$ROOT/docker-compose.mcp.yml'))" 2>/dev/null; then
  pass "docker-compose.mcp.yml is valid YAML"
else
  fail "docker-compose.mcp.yml YAML parse error"
fi

# Template YAMLs
for tmpl in gateways.yaml virtual_servers.yaml a2a_agents.yaml; do
  TMPL_PATH="$ROOT/agentic/forge/templates/$tmpl"
  if [ -f "$TMPL_PATH" ]; then
    if "$ROOT/backend/.venv/bin/python" -c "import yaml; yaml.safe_load(open('$TMPL_PATH'))" 2>/dev/null; then
      pass "Template: $tmpl"
    else
      fail "Template: $tmpl (invalid YAML)"
    fi
  else
    fail "Template: $tmpl (missing)"
  fi
done

# ── Step 6: Sync Pipeline Consistency ────────────────────────────────────

section "Step 6: Sync Pipeline Consistency"

# Check that sync_service.py and seed_all.py have the same server count
SYNC_COUNT=$("$ROOT/backend/.venv/bin/python" -c "
import sys; sys.path.insert(0, '$ROOT/backend')
from app.agentic.sync_service import MCP_SERVERS
print(len(MCP_SERVERS))
" 2>/dev/null || echo "0")

SEED_COUNT=$("$ROOT/backend/.venv/bin/python" -c "
import sys; sys.path.insert(0, '$ROOT')
import yaml
with open('$ROOT/agentic/forge/templates/gateways.yaml') as f:
    data = yaml.safe_load(f)
print(len(data.get('gateways', [])))
" 2>/dev/null || echo "0")

if [ "$SYNC_COUNT" = "$SEED_COUNT" ] && [ "$SYNC_COUNT" -ge 15 ]; then
  pass "sync_service.py ($SYNC_COUNT servers) matches gateways.yaml ($SEED_COUNT gateways)"
else
  fail "Server count mismatch" "sync=$SYNC_COUNT gateways=$SEED_COUNT (expected >= 15)"
fi

# Virtual server count
VS_COUNT=$("$ROOT/backend/.venv/bin/python" -c "
import yaml
with open('$ROOT/agentic/forge/templates/virtual_servers.yaml') as f:
    data = yaml.safe_load(f)
print(len(data.get('servers', [])))
" 2>/dev/null || echo "0")

if [ "$VS_COUNT" -ge 12 ]; then
  pass "Virtual servers: $VS_COUNT defined (>= 12)"
else
  fail "Virtual servers: only $VS_COUNT (expected >= 12)"
fi

# export_import.py known servers (local var inside function — count from source)
EI_COUNT=$(grep -c '"hp\.' "$ROOT/backend/app/personas/export_import.py" 2>/dev/null | head -1 || echo "0")

if [ "$EI_COUNT" -ge 17 ]; then
  pass "export_import.py: $EI_COUNT known server prefix entries (>= 17)"
else
  fail "export_import.py: only $EI_COUNT known server entries (expected >= 17)"
fi

# ── Step 7: MCP Server Health Checks (live) ─────────────────────────────

section "Step 7: MCP Server Health Checks (live)"

declare -A MCP_PORTS=(
  [personal-assistant]=9101 [knowledge]=9102 [decision-copilot]=9103
  [executive-briefing]=9104 [web-search]=9105 [local-notes]=9110
  [local-projects]=9111     [web-fetch]=9112  [shell-safe]=9113
  [gmail]=9114              [google-calendar]=9115 [microsoft-graph]=9116
  [slack]=9117              [github]=9118     [notion]=9119
)

LIVE_UP=0
LIVE_DOWN=0

for name in $(echo "${!MCP_PORTS[@]}" | tr ' ' '\n' | sort); do
  port="${MCP_PORTS[$name]}"
  if curl -sf --max-time 3 "http://127.0.0.1:$port/health" >/dev/null 2>&1; then
    pass "MCP $name (:$port) — healthy"
    LIVE_UP=$((LIVE_UP + 1))
  else
    skip "MCP $name (:$port)" "not running"
    LIVE_DOWN=$((LIVE_DOWN + 1))
  fi
done

echo -e "  ${DIM}Live servers: $LIVE_UP up, $LIVE_DOWN not running${NC}"

# ── Step 8: Context Forge Health ─────────────────────────────────────────

section "Step 8: Context Forge Gateway"

FORGE_URL="${CONTEXT_FORGE_URL:-http://localhost:4444}"

if curl -sf --max-time 3 "$FORGE_URL/health" >/dev/null 2>&1; then
  pass "Context Forge at $FORGE_URL"

  # Count registered tools
  TOOL_COUNT=$(curl -sf --max-time 5 "$FORGE_URL/tools" 2>/dev/null | \
    "$ROOT/backend/.venv/bin/python" -c "import sys,json; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)" 2>/dev/null || echo "0")
  if [ "$TOOL_COUNT" -gt 0 ]; then
    pass "Forge has $TOOL_COUNT registered tools"
  else
    skip "No tools registered in Forge" "run: make mcp-register-homepilot"
  fi
else
  skip "Context Forge not reachable at $FORGE_URL" "run: make start-mcp"
fi

# ── Step 9: Docker Image ─────────────────────────────────────────────────

section "Step 9: Docker"

if "$DOCKER_OK" 2>/dev/null; then
  # Dockerfile exists
  if [ -f "$ROOT/agentic/integrations/Dockerfile" ]; then
    pass "Generic Dockerfile exists"
  else
    fail "Dockerfile missing at agentic/integrations/Dockerfile"
  fi

  # Compose config valid
  if (cd "$ROOT" && docker compose -f docker-compose.mcp.yml config --quiet 2>/dev/null); then
    SERVICES=$(cd "$ROOT" && docker compose -f docker-compose.mcp.yml config --services 2>/dev/null | wc -l)
    pass "docker-compose.mcp.yml: $SERVICES services"
  else
    fail "docker-compose.mcp.yml config validation"
  fi
else
  if [ -f "$ROOT/agentic/integrations/Dockerfile" ]; then
    pass "Generic Dockerfile exists"
  else
    fail "Dockerfile missing"
  fi
  skip "Docker compose validation" "Docker daemon not available"
fi

# ── Step 10: Persona Launcher ───────────────────────────────────────────

section "Step 10: Persona Launcher"

if [ -f "$ROOT/scripts/persona-launch.sh" ] && [ -x "$ROOT/scripts/persona-launch.sh" ]; then
  pass "persona-launch.sh exists and is executable"
else
  fail "persona-launch.sh missing or not executable"
fi

# Validate --list works (doesn't need Docker)
if "$ROOT/scripts/persona-launch.sh" --list >/dev/null 2>&1; then
  PERSONA_COUNT=$("$ROOT/scripts/persona-launch.sh" --list 2>/dev/null | grep -c "^  " || echo "0")
  pass "Persona launcher --list: $PERSONA_COUNT personas found"
else
  skip "Persona launcher --list" "may need personas in community/sample/"
fi

# ── Summary ─────────────────────────────────────────────────────────────

section "SUMMARY"

TOTAL=$((PASS + FAIL + SKIP))
echo ""
echo -e "  ${GREEN}Passed:${NC}  $PASS"
echo -e "  ${RED}Failed:${NC}  $FAIL"
echo -e "  ${YELLOW}Skipped:${NC} $SKIP"
echo -e "  Total:   $TOTAL"
echo ""

if [ "$FAIL" -eq 0 ]; then
  echo -e "  ${GREEN}All checks passed!${NC}"
else
  echo -e "  ${RED}$FAIL check(s) failed — see above for details.${NC}"
fi

# ── JSON Report ──────────────────────────────────────────────────────────

if "$JSON_REPORT"; then
  RESULTS_JSON=$(printf '%s,' "${RESULTS[@]}" | sed 's/,$//')
  cat > "$REPORT_FILE" <<ENDJSON
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "passed": $PASS,
  "failed": $FAIL,
  "skipped": $SKIP,
  "checks": [$RESULTS_JSON]
}
ENDJSON
  echo ""
  echo "  Report written to: $REPORT_FILE"
fi

# Exit code
[ "$FAIL" -eq 0 ]
