# HomePilot — Verification Guide

How to verify that HomePilot's agentic layer (MCP servers, A2A agents,
Context Forge integration) is working end-to-end.

## Quick Start

```bash
# One command — runs all checks
./scripts/verify_end_to_end.sh

# CI-safe (skips Docker/Forge live checks)
./scripts/verify_end_to_end.sh --quick

# Machine-readable JSON report
./scripts/verify_end_to_end.sh --report
```

## What Gets Verified

| Step | Check | Requires |
|------|-------|----------|
| 0 | Prerequisites (Python 3.11+, uv, Node, Docker) | — |
| 1 | `make install` completes | uv |
| 2 | Backend tests (366 tests) | Python venv |
| 3 | MCP/A2A unit tests (164 tests) | Python venv |
| 4 | Individual MCP server tests (70 tests, 10 servers) | Python venv |
| 5 | Configuration validation (YAML templates, .env.example) | — |
| 6 | Sync pipeline consistency (server counts match) | Python venv |
| 7 | MCP server health checks (15 servers, ports 9101–9119) | Servers running |
| 8 | Context Forge gateway health + tool count | Forge running |
| 9 | Docker image & compose validation | Docker daemon |
| 10 | Persona launcher validation | persona-launch.sh |

## Architecture Overview

```
                    ┌────────────────────────┐
                    │    HomePilot Backend    │
                    │    (FastAPI :8000)      │
                    └────────┬───────────────┘
                             │ POST /v1/agentic/*
                             ▼
                    ┌────────────────────────┐
                    │   Context Forge        │
                    │   Gateway (:4444)      │
                    └────────┬───────────────┘
                             │ JSON-RPC 2.0
                ┌────────────┼────────────────┐
                ▼            ▼                ▼
         ┌──────────┐ ┌──────────┐    ┌──────────┐
         │Core MCP  │ │Local MCP │    │Comms MCP │
         │:9101-9105│ │:9110-9113│    │:9114-9117│
         └──────────┘ └──────────┘    └──────────┘
```

## MCP Server Inventory

| Server | Port | Profile | Tool Prefix |
|--------|------|---------|-------------|
| personal-assistant | 9101 | core | `hp.personal.*` |
| knowledge | 9102 | core | `hp.search_*`, `hp.get_*` |
| decision-copilot | 9103 | core | `hp.decision.*` |
| executive-briefing | 9104 | core | `hp.brief.*` |
| web-search | 9105 | core | `hp.web.*` |
| local-notes | 9110 | local | `hp.notes.*`, `hp.local_notes.*` |
| local-projects | 9111 | local | `hp.projects.*`, `hp.local_projects.*` |
| web-fetch | 9112 | local | `hp.web_fetch.*` |
| shell-safe | 9113 | local | `hp.shell.*` |
| gmail | 9114 | comms | `hp.gmail.*` |
| google-calendar | 9115 | comms | `hp.gcal.*` |
| microsoft-graph | 9116 | comms | `hp.graph.*`, `hp.microsoft_graph.*` |
| slack | 9117 | comms | `hp.slack.*` |
| github | 9118 | dev | `hp.github.*` |
| notion | 9119 | dev | `hp.notion.*` |

### A2A Agents

| Agent | Port | Profile |
|-------|------|---------|
| everyday-assistant | 9201 | agents |
| chief-of-staff | 9202 | agents |

## Step-by-Step Manual Verification

### 1. Install and test

```bash
make install
make test                    # 366 backend + 164 MCP/A2A
make test-mcp-new-servers    # 70 tests (10 servers × 7 each)
```

### 2. Start Context Forge

```bash
make start-mcp               # starts gateway on :4444
```

### 3. Start MCP servers

```bash
# All servers
docker compose -f docker-compose.mcp.yml --profile all up -d

# Or by profile
docker compose -f docker-compose.mcp.yml --profile core up -d
docker compose -f docker-compose.mcp.yml --profile local up -d
docker compose -f docker-compose.mcp.yml --profile comms up -d
docker compose -f docker-compose.mcp.yml --profile dev up -d
docker compose -f docker-compose.mcp.yml --profile agents up -d

# Or persona-driven
./scripts/persona-launch.sh diana
```

### 4. Register tools in Forge

```bash
make mcp-register-homepilot
# or
python agentic/forge/seed/seed_all.py
```

### 5. Verify registration

```bash
# List registered tools
make mcp-list-tools

# List gateways
make mcp-list-gateways

# Check via API
curl -s http://localhost:4444/tools | python3 -m json.tool | head -20
```

### 6. Health check all servers

```bash
for port in 9101 9102 9103 9104 9105 9110 9111 9112 9113 9114 9115 9116 9117 9118 9119; do
  status=$(curl -sf --max-time 3 http://127.0.0.1:$port/health && echo "UP" || echo "DOWN")
  echo "  :$port  $status"
done
```

### 7. Invoke a tool through Forge

```bash
# Direct invocation (example: personal assistant greeting)
curl -s -X POST http://localhost:4444/tools/{tool_id}/invoke \
  -H "Content-Type: application/json" \
  -d '{"input": {"query": "Hello"}}'
```

## Production Readiness Checklist

- [ ] All 600 tests pass (`make test` + `make test-mcp-new-servers`)
- [ ] `.env` file created from `.env.example` with production values
- [ ] `WRITE_ENABLED=false` and `DRY_RUN=true` for all servers (default)
- [ ] API secrets set: `GITHUB_TOKEN`, `SLACK_BOT_TOKEN`, `NOTION_TOKEN`, etc.
- [ ] `CORS_ORIGINS` restricted to production domains
- [ ] `API_KEY` set for backend authentication
- [ ] `AUTH_REQUIRED=true` for Forge admin UI
- [ ] Context Forge JWT credentials changed from defaults
- [ ] Docker images built: `docker compose -f docker-compose.mcp.yml build mcp-base`
- [ ] Health checks pass for all required servers
- [ ] Tools registered in Forge
- [ ] Persona `.hpersona` packages tested with `persona-launch.sh --check`
- [ ] Logs and monitoring configured
- [ ] Network policies restrict MCP server access to internal only

## Environment Variables

See `.env.example` for the complete list. Key categories:

- **Write-gating**: `WRITE_ENABLED`, `DRY_RUN`, `*_WRITE_ENABLED` — all default to safe (disabled)
- **API credentials**: `GITHUB_TOKEN`, `SLACK_BOT_TOKEN`, `NOTION_TOKEN`, `MS_GRAPH_*`, `TAVILY_API_KEY`
- **Forge auth**: `CONTEXT_FORGE_AUTH_USER`, `CONTEXT_FORGE_AUTH_PASS`, `CONTEXT_FORGE_TOKEN`
- **Timeouts**: `HEALTH_TIMEOUT`, `STARTUP_TIMEOUT`, `SHELL_EXEC_TIMEOUT`

## Troubleshooting

**Tests fail with import errors**: Run `make install` to ensure all dependencies are installed.

**MCP server not reachable**: Check if the port is already in use (`lsof -i :9101`).
The persona launcher's health-check-first design will detect this automatically.

**Forge returns 401**: JWT token expired. Set `CONTEXT_FORGE_TOKEN` or ensure
`CONTEXT_FORGE_AUTH_USER`/`CONTEXT_FORGE_AUTH_PASS` are correct.

**Docker compose fails**: Ensure Docker daemon is running. Build the base image first:
`docker compose -f docker-compose.mcp.yml build mcp-base`
