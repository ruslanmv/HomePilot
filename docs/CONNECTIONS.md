# HomePilot Connections: How Agents and MCP Servers Connect

This document explains step by step how HomePilot registers AI tools and agents
with MCP Context Forge, how authentication works, and how to add new connections.

---

## Overview

HomePilot uses a central registry called **MCP Context Forge** to keep track of
all available tools and agents. Think of it as a phone book: every tool and agent
registers itself there, and the HomePilot wizard reads that phone book to show
you what is available when you create a new project.

```
MCP Servers (tools)  -->  Context Forge (registry)  -->  HomePilot Wizard (UI)
A2A Agents           -->  Context Forge (registry)  -->  HomePilot Wizard (UI)
```

---

## Key Concepts

| Term | What It Is |
|------|-----------|
| **MCP Server** | A small service that provides one or more tools (e.g., web search, document Q&A) |
| **Tool** | A single action an MCP server can perform (e.g., "search the web", "fetch a URL") |
| **A2A Agent** | An autonomous agent that can be called by other agents (Agent-to-Agent protocol) |
| **Context Forge** | The central gateway/registry where all tools and agents are registered |
| **Virtual Server** | A named bundle of tools grouped together for convenience |
| **Gateway** | A reference to an MCP server endpoint (for admin visibility) |

---

## Authentication Mechanism

Context Forge uses **JWT (JSON Web Token)** authentication for all API endpoints.
Basic username/password authentication is **not accepted** for API calls.

### How Authentication Works (Step by Step)

1. **Login**: Send a POST request to `/auth/login` with email and password
2. **Receive Token**: Forge returns a JWT `access_token` (valid for ~7 days)
3. **Use Token**: Include the token in all subsequent requests as `Authorization: Bearer <token>`

### Default Credentials

| Setting | Default Value |
|---------|--------------|
| Email | `admin@example.com` |
| Password | `changeme` |
| Forge URL | `http://localhost:4444` |

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `MCPGATEWAY_URL` | Forge gateway URL | `http://localhost:4444` |
| `BASIC_AUTH_USER` | Admin username (used to derive email: `{user}@example.com`) | `admin` |
| `BASIC_AUTH_PASSWORD` | Admin password | `changeme` |
| `CONTEXT_FORGE_URL` | Forge URL for HomePilot backend | `http://localhost:4444` |
| `CONTEXT_FORGE_AUTH_USER` | Auth user for HomePilot backend | `admin` |
| `CONTEXT_FORGE_AUTH_PASS` | Auth password for HomePilot backend | `changeme` |
| `CONTEXT_FORGE_TOKEN` | Pre-configured JWT token (optional, skips auto-login) | (empty) |

### Auto-Login

HomePilot automatically acquires a JWT token when it first connects to Forge.
No manual token management is needed. The sequence is:

1. HomePilot backend starts and creates a `ContextForgeClient`
2. On the first API call (e.g., listing tools), the client calls `_ensure_token()`
3. `_ensure_token()` sends `POST /auth/login` with the configured credentials
4. The returned JWT is cached on the client instance for all future requests
5. If Forge is not reachable, the client gracefully falls back (no crash)

---

## How Tools Are Registered

### Step 1: MCP Server Starts

Each MCP server is a standalone FastAPI application running on its own port:

| Server | Port | Tools Provided |
|--------|------|---------------|
| Personal Assistant | 9101 | search, plan_day |
| Knowledge | 9102 | search_workspace, get_document, answer_with_sources, summarize_project |
| Decision Copilot | 9103 | options, risk_assessment, recommend_next, plan_next_steps |
| Executive Briefing | 9104 | daily, weekly, what_changed_since, digest |
| Web Search | 9105 | web.search, web.fetch |

### Step 2: Tool Discovery

The seed script queries each server's `/rpc` endpoint using JSON-RPC:

```
POST http://127.0.0.1:{port}/rpc
{"jsonrpc": "2.0", "id": "discover", "method": "tools/list"}
```

Each server responds with its tool definitions (name, description, input schema).

### Step 3: Tool Registration in Forge

Each discovered tool is registered with Forge via:

```
POST http://localhost:4444/tools
Authorization: Bearer <jwt_token>

{
  "tool": {
    "name": "hp.web.search",
    "description": "Search the web",
    "inputSchema": { ... },
    "integration_type": "REST",
    "request_type": "POST",
    "url": "http://127.0.0.1:9105/rpc",
    "tags": ["homepilot"]
  }
}
```

**Important**: Tools must use `integration_type: "REST"` for direct registration.
The `"MCP"` type is reserved for tools auto-discovered via SSE gateways.

### Step 4: Verification

After registration, the HomePilot catalog endpoint returns all tools:

```
GET http://localhost:8000/v1/agentic/catalog
```

Returns 16 tools and 2 agents that the wizard can display.

---

## How A2A Agents Are Registered

### Step 1: Agent Definition

Agents are defined in `agentic/forge/templates/a2a_agents.yaml`:

```yaml
agents:
  - name: hp-planning-agent
    description: "Assists with day planning and scheduling"
    endpoint_url: "http://127.0.0.1:9201/.well-known/agent.json"
  - name: hp-research-agent
    description: "Searches knowledge bases for information"
    endpoint_url: "http://127.0.0.1:9202/.well-known/agent.json"
```

### Step 2: Registration

Each agent is registered with Forge:

```
POST http://localhost:4444/a2a
Authorization: Bearer <jwt_token>

{
  "agent": {
    "name": "hp-planning-agent",
    "description": "...",
    "endpoint_url": "http://127.0.0.1:9201/.well-known/agent.json"
  },
  "visibility": "public"
}
```

---

## Adding a New MCP Server to HomePilot

### Step 1: Create the Server

Create a new Python file in `agentic/integrations/mcp/`:

```
agentic/integrations/mcp/my_new_server.py
```

Use `create_mcp_app()` from the common server module to create the FastAPI app.
Register your tools using the `@app.tool()` decorator.

### Step 2: Choose a Port

Pick an unused port (e.g., 9106). Add it to:

- `scripts/agentic-start.sh` (startup command)
- `Makefile` (healthcheck and kill targets)
- `agentic/ops/compose/docker-compose.yml` (Docker service)

### Step 3: Add to Templates

Add your server to `agentic/forge/templates/gateways.yaml`:

```yaml
- name: my-new-server
  url: "http://localhost:9106/rpc"
  transport: "SSE"
  description: "My new server description"
```

### Step 4: Add to Seed Script

Add your server to the `MCP_SERVERS` list in `agentic/forge/seed/seed_all.py`:

```python
MCP_SERVERS = [
    ...existing servers...,
    ("my-new-server", 9106, "My new MCP server"),
]
```

### Step 5: Run the Seed Script

```bash
python agentic/forge/seed/seed_all.py
```

The script will:
1. Log in to Forge (JWT)
2. Discover tools from your new server
3. Register them in Forge
4. Skip any tools that already exist (idempotent)

### Step 6: Verify

Check the catalog endpoint:

```bash
curl http://localhost:8000/v1/agentic/catalog -H "x-api-key: test"
```

Your new tools should appear in the tools list.

---

## Adding a New A2A Agent

### Step 1: Create the Agent

Create an agent service that implements the A2A protocol
(exposes `/.well-known/agent.json`).

### Step 2: Add to Templates

Add to `agentic/forge/templates/a2a_agents.yaml`:

```yaml
- name: my-new-agent
  description: "What this agent does"
  endpoint_url: "http://127.0.0.1:9203/.well-known/agent.json"
```

### Step 3: Run the Seed Script

```bash
python agentic/forge/seed/seed_all.py
```

---

## Network Architecture

```
                    ┌─────────────────────────┐
                    │   HomePilot Frontend     │
                    │   (React, port 3000)     │
                    └──────────┬──────────────┘
                               │ HTTP
                    ┌──────────▼──────────────┐
                    │   HomePilot Backend      │
                    │   (FastAPI, port 8000)   │
                    │                          │
                    │  /v1/agentic/catalog ────┼──── reads tools/agents
                    │  /v1/agentic/invoke  ────┼──── executes tools
                    └──────────┬──────────────┘
                               │ JWT Bearer Auth
                    ┌──────────▼──────────────┐
                    │   MCP Context Forge      │
                    │   (Gateway, port 4444)   │
                    │                          │
                    │  /auth/login ────────────┼──── returns JWT token
                    │  /tools     ────────────┼──── tool registry
                    │  /a2a       ────────────┼──── agent registry
                    │  /gateways  ────────────┼──── gateway catalog
                    │  /servers   ────────────┼──── virtual servers
                    └─────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                   │
     ┌──────▼──────┐   ┌──────▼──────┐    ┌──────▼──────┐
     │ MCP Server  │   │ MCP Server  │    │ MCP Server  │
     │ port 9101   │   │ port 9102   │    │ port 9105   │
     │ (Personal)  │   │ (Knowledge) │    │ (Web Search)│
     └─────────────┘   └─────────────┘    └─────────────┘
```

---

## Ports Reference

| Service | Port | Protocol |
|---------|------|----------|
| HomePilot Frontend | 3000 | HTTP |
| HomePilot Backend | 8000 | HTTP REST |
| Context Forge Gateway | 4444 | HTTP REST + JWT |
| MCP Personal Assistant | 9101 | HTTP JSON-RPC |
| MCP Knowledge | 9102 | HTTP JSON-RPC |
| MCP Decision Copilot | 9103 | HTTP JSON-RPC |
| MCP Executive Briefing | 9104 | HTTP JSON-RPC |
| MCP Web Search | 9105 | HTTP JSON-RPC |
| A2A Planning Agent | 9201 | A2A Protocol |
| A2A Research Agent | 9202 | A2A Protocol |

---

## Troubleshooting

### "Authorization token required"
The Forge API requires JWT Bearer tokens. If you see this error:
1. Ensure Forge is running: `curl http://localhost:4444/health`
2. Check credentials: default is `admin@example.com` / `changeme`
3. HomePilot auto-acquires JWT tokens — no manual setup needed

### "0 tools, 0 agents" in Wizard
1. Check Forge is running on port 4444
2. Run the seed script: `python agentic/forge/seed/seed_all.py`
3. Check MCP servers are running on ports 9101-9105
4. Check the catalog endpoint: `curl http://localhost:8000/v1/agentic/catalog -H "x-api-key: test"`

### "list_tools failed: All connection attempts failed"
Context Forge is not running. Start it with:
```bash
BASIC_AUTH_USER=admin BASIC_AUTH_PASSWORD=changeme \
  mcpgateway mcpgateway.main:app --host 127.0.0.1 --port 4444
```

### MCP Server Not Responding
Check individual server health:
```bash
curl http://127.0.0.1:9105/health
```

### Integration Type Error
When registering tools manually, use `"integration_type": "REST"`.
The `"MCP"` type is reserved for gateway auto-discovery and cannot be set manually.

---

## Quick Start

```bash
# 1. Start everything
make start

# 2. Verify all servers are healthy
for port in 9101 9102 9103 9104 9105; do
  echo "Port $port: $(curl -sf http://127.0.0.1:$port/health)"
done

# 3. Check Forge
curl http://localhost:4444/health

# 4. Run seed script to register tools
python agentic/forge/seed/seed_all.py

# 5. Verify catalog
curl http://localhost:8000/v1/agentic/catalog -H "x-api-key: test" | python3 -m json.tool
```
