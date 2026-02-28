# MCP Context Forge -- Architecture & Startup Guide

**How HomePilot connects Personas and Agents to tools, MCP servers, and A2A agents through the Context Forge gateway.**

---

## What Is MCP Context Forge?

MCP Context Forge is the **central gateway** that connects HomePilot's AI Personas to tools and services. It implements the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) -- an open standard for exposing tools to AI assistants.

Think of it as a **switchboard**: Personas don't call tools directly. Instead, they ask the gateway "what tools are available?", the gateway returns a catalog, and the Persona invokes tools through the gateway.

```
Persona  -->  Backend  -->  Context Forge Gateway (:4444)  -->  MCP Servers  -->  Tools
                                      |
                            +-------- | --------+
                            |         |         |
                       MCP Servers  A2A Agents  Virtual Servers
                      (9101-9120)  (9201-9202)  (curated bundles)
```

---

## Port Map

| Port | Service | Type |
| :--- | :--- | :--- |
| **4444** | Context Forge Gateway | Gateway (REST + Admin UI) |
| 9101 | Personal Assistant | MCP Server |
| 9102 | Knowledge | MCP Server |
| 9103 | Decision Copilot | MCP Server |
| 9104 | Executive Briefing | MCP Server |
| 9105 | Web Search | MCP Server |
| 9110 | Local Notes | MCP Server |
| 9111 | Local Projects | MCP Server |
| 9112 | Web Fetch | MCP Server |
| 9113 | Shell Safe | MCP Server |
| 9114 | Gmail | MCP Server |
| 9115 | Google Calendar | MCP Server |
| 9116 | Microsoft Graph | MCP Server |
| 9117 | Slack | MCP Server |
| 9118 | GitHub | MCP Server |
| 9119 | Notion | MCP Server |
| 9120 | Inventory | MCP Server |
| 9201 | Everyday Assistant | A2A Agent |
| 9202 | Chief of Staff | A2A Agent |

---

## How `make start` Launches Everything

When you run `make start` with `AGENTIC=1` (the default), the startup follows a **three-phase boot sequence** inside a single bash process that tracks all PIDs for clean shutdown on Ctrl+C.

### Phase 1 -- Gateway Boot

**Script:** `scripts/mcp-start.sh --with-servers`

1. **Detects installation mode:**
   - **Repo mode:** the cloned `mcp-context-forge/` directory has a `.venv`
   - **Pip mode:** the `mcpgateway` command is on PATH (installed via `pip install mcp-contextforge-gateway`)

2. **Starts the MCP Gateway** as a background uvicorn process:

   ```
   HOST=0.0.0.0
   BASIC_AUTH_USER=admin
   BASIC_AUTH_PASSWORD=changeme
   AUTH_REQUIRED=false
   MCPGATEWAY_UI_ENABLED=true
   MCPGATEWAY_ADMIN_API_ENABLED=true

   uvicorn mcpgateway.main:app --host 127.0.0.1 --port 4444
   ```

3. **Waits up to 30 seconds** for `GET http://localhost:4444/health` to succeed before proceeding.

4. With `--with-servers`, also starts any bundled upstream demo servers (csv_pandas, plotly, python_sandbox) from the cloned Context Forge repo on ports 9100+. These are the upstream project's example servers, separate from HomePilot's own.

### Phase 2 -- Agentic Servers Boot + Forge Seeding

**Script:** `scripts/agentic-start.sh`

#### Step 2a: Start HomePilot's MCP Servers + A2A Agents

All servers are launched via the backend's Python venv:

```bash
PYTHONPATH="$ROOT" backend/.venv/bin/python -m uvicorn \
    agentic.integrations.mcp.<server>:app \
    --host 127.0.0.1 --port <port>
```

Six MCP servers start on ports 9101--9105 and 9120. Two A2A agents start on ports 9201--9202. The script polls all 8 `/health` endpoints for up to 10 seconds until all respond.

#### Step 2b: Seed Context Forge

Once all servers are healthy, the script runs `agentic/forge/seed/seed_all.py`. This is the critical wiring step that registers everything with the gateway:

```
seed_all.py
  |
  |-- 1. Acquire JWT token
  |     POST /auth/login { email: "admin@example.com", password: "changeme" }
  |     --> Returns access_token (all subsequent calls use Bearer JWT)
  |
  |-- 2. Discover tools from each MCP server
  |     POST http://127.0.0.1:{port}/rpc
  |     { "jsonrpc": "2.0", "method": "tools/list" }
  |     --> Returns list of tool definitions (name, description, inputSchema)
  |
  |-- 3. Register each tool with Forge
  |     POST /tools
  |     { "tool": { "name": "hp.personal.search", "integration_type": "REST",
  |                  "url": "http://127.0.0.1:9101/rpc", ... } }
  |
  |-- 4. Register A2A agents
  |     POST /a2a  (from agentic/forge/templates/a2a_agents.yaml)
  |
  |-- 5. Register gateways for admin UI visibility
  |     POST /gateways  (from agentic/forge/templates/gateways.yaml)
  |
  |-- 6. Create virtual servers (curated tool bundles)
  |     POST /servers  (from agentic/forge/templates/virtual_servers.yaml)
```

The seed script is **idempotent** -- it skips items that already exist (matched by name). On re-run it only updates tool associations for virtual servers.

### Phase 3 -- Final Health Check

After both scripts return, the Makefile verifies everything:

```
Context Forge:  curl http://localhost:4444/health      --> healthy / not responding
MCP Servers:    curl http://127.0.0.1:{9101..9120}/health  --> X/6 healthy
A2A Agents:     curl http://127.0.0.1:{9201,9202}/health   --> X/2 healthy
```

---

## Authentication

Context Forge uses **JWT Bearer tokens** for its API. Basic auth is only used for the admin UI login page.

The authentication flow:

1. The seed script (and the backend client) call `POST /auth/login` with:
   ```json
   { "email": "admin@example.com", "password": "changeme" }
   ```
2. Forge returns an `access_token` (JWT).
3. All subsequent API calls include `Authorization: Bearer <token>`.

The backend's `ContextForgeClient` (`backend/app/agentic/client.py`) handles this automatically -- if no token is configured, it auto-acquires one on the first API call.

---

## MCP Server Architecture

Every HomePilot MCP server follows the same pattern. They are thin FastAPI apps built on a common framework at `agentic/integrations/mcp/_common/server.py`.

### Endpoints

Each server exposes exactly two endpoints:

| Method | Path | Purpose |
| :--- | :--- | :--- |
| GET | `/health` | Returns `{ "ok": true, "name": "...", "ts": "..." }` |
| POST | `/rpc` | JSON-RPC 2.0: `tools/list` and `tools/call` |

### Tool Naming Convention

All HomePilot tools use the `hp.` prefix namespace:

```
hp.personal.search          (Personal Assistant)
hp.personal.plan_day        (Personal Assistant)
hp.search_workspace         (Knowledge)
hp.decision.analyze_options (Decision Copilot)
hp.brief.daily              (Executive Briefing)
hp.web.search               (Web Search)
hp.notes.create             (Local Notes)
hp.gmail.search             (Gmail)
hp.github.list_repos        (GitHub)
...
```

This naming convention is what enables **virtual servers** to bundle tools by prefix.

### Creating a New MCP Server

To add a new MCP server:

1. Create a module under `agentic/integrations/mcp/`:

   ```python
   from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

   TOOLS = [
       ToolDef(
           name="hp.myservice.do_thing",
           description="Does the thing",
           input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
           handler=my_async_handler,
       ),
   ]

   app = create_mcp_app(server_name="homepilot-myservice", tools=TOOLS)
   ```

2. Add a port assignment and `start_server` call in `scripts/agentic-start.sh`.

3. Add a gateway entry in `agentic/forge/templates/gateways.yaml`.

4. Add the server to the `MCP_SERVERS` list in `agentic/forge/seed/seed_all.py`.

5. (Optional) Add it to a virtual server in `agentic/forge/templates/virtual_servers.yaml`.

---

## A2A Agent Architecture

A2A (Agent-to-Agent) agents are higher-level orchestrators that can use MCP tools. They follow a similar framework at `agentic/integrations/a2a/_common/server.py`.

| Agent | Port | Role |
| :--- | :--- | :--- |
| **Everyday Assistant** | 9201 | Friendly helper that summarizes and plans. Read-only + advisory. |
| **Chief of Staff** | 9202 | Orchestrates: gather facts, structure options, produce briefings. Always asks before acting. |

Both agents are registered with Forge via `agentic/forge/templates/a2a_agents.yaml`:

```yaml
agents:
  - name: "everyday-assistant"
    agent_type: "jsonrpc"
    endpoint_url: "http://localhost:9201/rpc"
    description: "Friendly helper that summarizes and plans. Read-only + advisory."

  - name: "chief-of-staff"
    agent_type: "jsonrpc"
    endpoint_url: "http://localhost:9202/rpc"
    description: "Orchestrates: gather facts, structure options, produce briefing."
```

---

## Virtual Servers (Curated Tool Bundles)

Virtual servers are **allow-lists of tools grouped by prefix**. They let Personas access a curated subset of all available tools rather than everything.

Defined in `agentic/forge/templates/virtual_servers.yaml`:

| Virtual Server | Include Prefixes | Purpose |
| :--- | :--- | :--- |
| `hp-home-default` | `hp.personal.` | Home defaults: personal assistant tools only |
| `hp-default-readonly` | `hp.*` (exclude `hp.action.`) | Pro defaults: all tools, read-only/advisory |
| `hp-decision-room` | `hp.search_`, `hp.get_`, `hp.answer_`, `hp.summarize_`, `hp.decision.` | Knowledge + Decision tools |
| `hp-exec-briefing` | `hp.brief.` | Executive briefing tools only |
| `hp-web-research` | `hp.web.` | Web search + fetch |
| `hp-local-tools` | `hp.notes.`, `hp.projects.`, `hp.web_fetch.`, `hp.shell.` | Local file tools |
| `hp-notes-only` | `hp.notes.`, `hp.local_notes.` | Notes only |
| `hp-projects-only` | `hp.projects.`, `hp.local_projects.` | Projects only |
| `hp-comms-all` | `hp.gmail.`, `hp.gcal.`, `hp.graph.`, `hp.slack.` | All communication tools |
| `hp-email` | `hp.gmail.`, `hp.graph.mail.` | Email tools |
| `hp-calendar` | `hp.gcal.`, `hp.graph.calendar.` | Calendar tools |
| `hp-dev-tools` | `hp.github.`, `hp.notion.`, `hp.shell.`, `hp.projects.` | Developer tools |

The seed script matches tool names against these prefixes using `_tool_ids_by_prefix()` and registers the resulting tool ID lists with Forge.

---

## How the Backend Connects

The backend exposes the agentic layer through `backend/app/agentic/`:

### Client (`client.py`)

`ContextForgeClient` is the single point of contact with the gateway:

```python
client = ContextForgeClient(
    base_url="http://localhost:4444",    # CONTEXT_FORGE_URL
    auth_user="admin",                   # CONTEXT_FORGE_AUTH_USER
    auth_pass="changeme",               # CONTEXT_FORGE_AUTH_PASS
)

# Methods:
await client.list_tools()       # GET /tools
await client.list_agents()      # GET /a2a
await client.list_gateways()    # GET /gateways
await client.list_servers()     # GET /servers
await client.register_tool()    # POST /tools
await client.invoke_tool()      # POST /rpc (or /tools/{id}/invoke)
```

### Backend API Routes

| Method | Endpoint | Purpose |
| :--- | :--- | :--- |
| GET | `/v1/agentic/status` | Feature flag + gateway health |
| GET | `/v1/agentic/admin` | Admin UI URL redirect |
| GET | `/v1/agentic/capabilities` | Dynamic capability list from Forge |
| GET | `/v1/agentic/catalog` | Full catalog (tools, agents, servers, gateways) |
| POST | `/v1/agentic/invoke` | Execute a capability |
| POST | `/v1/agentic/sync` | Trigger catalog refresh |
| POST | `/v1/agentic/register/tool` | Register a custom tool |
| POST | `/v1/agentic/register/agent` | Register a custom A2A agent |
| POST | `/v1/agentic/register/gateway` | Register a gateway |
| POST | `/v1/agentic/register/server` | Register a virtual server |
| GET | `/v1/agentic/registry/servers` | Browse Forge MCP Registry (81+ public servers) |
| POST | `/v1/agentic/registry/{id}/register` | Install a server from the Forge catalog |
| POST | `/v1/agentic/registry/{id}/unregister` | Remove an installed server |

The `/v1/agentic/catalog` endpoint is what the frontend's **Tools tab** consumes -- it aggregates tools, A2A agents, servers, and gateways into a single JSON response.

The `/v1/agentic/registry/*` endpoints proxy the Forge admin MCP Registry so the frontend **Discover** sub-tab can browse and install public MCP servers without opening the Forge admin UI. Supports query params: `category`, `auth_type`, `provider`, `search`, `limit`, `offset`.

---

## Discover MCP Servers (Setup Wizard)

<p align="center">
  <img src="../assets/blog/discover-mcp-servers.svg" alt="Discover MCP Servers — browse 81+ servers, install with one click, manage from the UI" width="900" /><br>
  <em>The Discover tab: browse a catalog of 81 verified MCP servers, install with one click, and manage everything from the UI.</em>
</p>

The **Discover** tab lets you browse, install, and remove 81+ public MCP servers directly from the HomePilot UI -- no command line needed.

### What it does

- **Browse a catalog** of 81 verified MCP servers organized by category (Productivity, Software Development, Communication, AI, etc.)
- **One-click install** for servers that need no credentials (marked "Open")
- **Guided setup** for servers that require an API key or OAuth login
- **One-click uninstall** to cleanly remove any installed server (your external account is never affected)
- **Editable server URL** in the details drawer, so you can fix or customize endpoints after installation

### How to use it

1. Open the **MCP Servers** tab in your project
2. Click the **Discover** sub-tab
3. Browse or search for a server (e.g., "GitHub", "Slack", "Asana")
4. Click **Install** -- the Setup Wizard walks you through any required configuration
5. To remove a server, click the installed server card and choose **Uninstall**

### Auth types explained

| Type | What you need | Examples |
| :--- | :--- | :--- |
| **Open** | Nothing -- just click Install | DeepWiki, Cloudflare Docs, Semgrep |
| **API Key** | Paste your API key from the service's dashboard | Stripe, HubSpot, GitHub |
| **OAuth2.1** | Click Install, then complete the login flow on the service's website | Asana, Linear, Notion, Slack |

### MatrixHub (optional secondary catalog)

You can enable an additional catalog source called **MatrixHub** in Settings:

1. Go to **Settings** (gear icon)
2. Scroll to **MatrixHub Catalog** at the bottom
3. Toggle **Enable MatrixHub** on
4. Enter the MatrixHub URL (e.g., `http://localhost:8080`)
5. A new **MatrixHub** tab appears in the Discover view

MatrixHub is disabled by default. When enabled, it adds a second tab alongside the main Forge catalog.

---

## Configuration Reference

### Makefile Variables

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `AGENTIC` | `1` | Set to `0` to disable MCP/A2A entirely |
| `MCP_DIR` | `mcp-context-forge` | Clone directory for the gateway repo |
| `MCP_REPO` | `https://github.com/ruslanmv/mcp-context-forge.git` | Source repository |
| `MCP_GATEWAY_PORT` | `4444` | Gateway listen port |
| `MCP_GATEWAY_HOST` | `127.0.0.1` | Gateway bind address |

### Environment Variables

| Variable | Default | Used By |
| :--- | :--- | :--- |
| `AGENTIC_ENABLED` | `true` | Backend -- feature flag |
| `CONTEXT_FORGE_URL` | `http://localhost:4444` | Backend client |
| `CONTEXT_FORGE_ADMIN_URL` | `http://localhost:4444/admin` | Admin UI link |
| `CONTEXT_FORGE_AUTH_USER` | `admin` | Backend client JWT login |
| `CONTEXT_FORGE_AUTH_PASS` | `changeme` | Backend client JWT login |
| `MCPGATEWAY_URL` | `http://localhost:4444` | Seed script |
| `BASIC_AUTH_USER` | `admin` | Gateway + seed script |
| `BASIC_AUTH_PASSWORD` | `changeme` | Gateway + seed script |
| `AUTH_REQUIRED` | `false` | Gateway (disables login prompt) |
| `MCPGATEWAY_UI_ENABLED` | `true` | Gateway admin UI |
| `MCPGATEWAY_ADMIN_API_ENABLED` | `true` | Gateway admin API |
| `SECURE_COOKIES` | `false` | Gateway (disable secure cookies for local HTTP) |

### Gateway `.env` File

The file `mcp-context-forge/.env` is created automatically by `make install`. If you need to recreate it manually (or the gateway shows a login / "Password Change Required" screen), run `make clean-mcp` or create `mcp-context-forge/.env` with:

```env
# HomePilot MCP Context Forge defaults
HOST=0.0.0.0

# ── Authentication ───────────────────────────────────────────────────────
# Disable login prompt (DEV ONLY). Set true for production.
AUTH_REQUIRED=false
SECURE_COOKIES=false

# ── Default Credentials (used when AUTH_REQUIRED=true) ───────────────────
#   Admin UI login:   Email: admin@example.com  /  Password: changeme
#   HTTP Basic Auth:  Username: admin  /  Password: changeme
BASIC_AUTH_USER=admin
BASIC_AUTH_PASSWORD=changeme
JWT_SECRET_KEY=my-test-key
AUTH_ENCRYPTION_SECRET=my-test-salt
PLATFORM_ADMIN_EMAIL=admin@example.com
PLATFORM_ADMIN_PASSWORD=changeme
DEFAULT_USER_PASSWORD=changeme

# ── Password Policy (relaxed for local dev) ──────────────────────────────
# Disable the forced "change your password" screen on first login
PASSWORD_CHANGE_ENFORCEMENT_ENABLED=false
ADMIN_REQUIRE_PASSWORD_CHANGE_ON_BOOTSTRAP=false
DETECT_DEFAULT_PASSWORD_ON_LOGIN=false
REQUIRE_PASSWORD_CHANGE_FOR_DEFAULT_PASSWORD=false
PASSWORD_POLICY_ENABLED=false
PASSWORD_MAX_AGE_DAYS=36500
PASSWORD_REQUIRE_UPPERCASE=false
PASSWORD_REQUIRE_LOWERCASE=false
PASSWORD_REQUIRE_SPECIAL=false
PASSWORD_REQUIRE_NUMBERS=false
PASSWORD_MIN_LENGTH=4

# ── Admin UI & API ───────────────────────────────────────────────────────
MCPGATEWAY_UI_ENABLED=true
MCPGATEWAY_ADMIN_API_ENABLED=true
```

> **Note:** `SECURE_COOKIES=false` is needed when running the gateway over plain HTTP (localhost). Without it, the browser will reject session cookies because they are marked `Secure` by default, which requires HTTPS. Set this to `true` in production behind a TLS reverse proxy.

> **Forgot password?** Run `make clean-mcp` — it wipes the database and reinstalls with defaults.

### Forge Internal Settings (Advanced)

The Context Forge gateway has additional settings that HomePilot does **not** set directly. They live inside the `mcpgateway` package's Pydantic config and use safe defaults for local development. You only need to change them in production.

**How the defaults align with HomePilot:**

```
HomePilot sets             Forge expects internally       Must match?
─────────────────────────  ───────────────────────────    ──────────
BASIC_AUTH_USER=admin  →   PLATFORM_ADMIN_EMAIL           Yes (admin → admin@example.com)
BASIC_AUTH_PASSWORD    →   PLATFORM_ADMIN_PASSWORD         Yes (both "changeme")
(not set)              →   JWT_SECRET_KEY                  No (Forge-internal only)
(not set)              →   AUTH_ENCRYPTION_SECRET          No (Forge-internal only)
```

The seed script and backend client construct the login email as `{BASIC_AUTH_USER}@example.com`, which must match Forge's `PLATFORM_ADMIN_EMAIL`. The password must match `PLATFORM_ADMIN_PASSWORD`. As long as you don't change one side without the other, the defaults work.

> **Production checklist:**
> 1. Set `JWT_SECRET_KEY` to a strong random value (`openssl rand -hex 32`)
> 2. Set `AUTH_ENCRYPTION_SECRET` to a different strong random value
> 3. Change `BASIC_AUTH_PASSWORD` / `PLATFORM_ADMIN_PASSWORD` to a real password
> 4. Set `AUTH_REQUIRED=true` and `SECURE_COOKIES=true` (behind TLS)
> 5. Update `CONTEXT_FORGE_AUTH_PASS` in the HomePilot backend to match
> 6. Re-enable password policy: `PASSWORD_POLICY_ENABLED=true`, `PASSWORD_CHANGE_ENFORCEMENT_ENABLED=true`

---

## File Structure

```
HomePilot/
  Makefile                                   # start, install-mcp, start-mcp targets
  scripts/
    mcp-setup.sh                             # Clones + installs Context Forge
    mcp-start.sh                             # Starts the gateway process
    agentic-start.sh                         # Starts MCP servers + A2A agents + seeds
  mcp-context-forge/                         # Cloned gateway repo (created by make install)
    .venv/                                   # Gateway Python venv
    .env                                     # Gateway env config
  agentic/
    forge/
      seed/
        seed_all.py                          # Registers tools/agents/servers with Forge
        seed_lib.py                          # Shared seed utilities
      templates/
        gateways.yaml                        # Gateway definitions (16 entries)
        a2a_agents.yaml                      # A2A agent definitions (2 entries)
        virtual_servers.yaml                 # Virtual server bundles (12 entries)
    integrations/
      mcp/
        _common/
          server.py                          # Shared MCP server framework
        personal_assistant_server.py         # :9101
        knowledge_server.py                  # :9102
        decision_copilot_server.py           # :9103
        executive_briefing_server.py         # :9104
        web_search_server.py                 # :9105
        inventory_server.py                  # :9120
        ...                                  # + local, comms, dev servers
      a2a/
        _common/
          server.py                          # Shared A2A agent framework
        everyday_assistant_agent.py          # :9201
        chief_of_staff_agent.py              # :9202
  backend/
    app/
      agentic/
        client.py                            # ContextForgeClient (HTTP client)
        routes.py                            # /v1/agentic/* API endpoints
        catalog_types.py                     # Pydantic models for catalog
        sync_service.py                      # Catalog sync + TTL cache
        ttl_cache.py                         # Generic TTL cache
```

---

## Make Targets

| Target | Purpose |
| :--- | :--- |
| `make start` | Start everything (backend + frontend + ComfyUI + MCP + A2A) |
| `make start-no-agentic` | Start without MCP gateway or agentic features |
| `make start-agentic-servers` | Start only MCP servers + A2A agents (standalone) |
| `make start-mcp` | Start only the MCP Gateway (port 4444) |
| `make start-inventory` | Start only the Inventory MCP server (port 9120) |
| `make install-mcp` | Install/update MCP Context Forge |
| `make verify-mcp` | Verify MCP installation status |
| `make mcp-status` | Show gateway health + registered tools |
| `make mcp-start-full` | Start gateway + servers + LangChain agent |
| `make mcp-inventory` | List all Forge inventory (tools, agents, gateways, servers) |
| `make mcp-register-homepilot` | Register HomePilot default tools |
| `make mcp-list-tools` | List registered tools |
| `make mcp-list-gateways` | List registered gateways |
| `make mcp-list-agents` | List registered A2A agents |
| `make stop` | Stop all services (includes MCP processes) |
| `make stop-mcp` | Stop only MCP gateway + servers |
| `make clean-mcp` | Wipe + reinstall MCP from scratch (resets password/database) |

---

## Startup Sequence Diagram

```
make start (AGENTIC=1)
  |
  |-- Backend (:8000)       uvicorn app.main:app
  |-- Edit-Session (:8010)  uvicorn app.main:app
  |-- Frontend (:3000)      npm run dev
  |-- ComfyUI (:8188)       python main.py
  |
  |-- [Phase 1] scripts/mcp-start.sh --with-servers
  |     |
  |     |-- Start Gateway (:4444)
  |     |     uvicorn mcpgateway.main:app
  |     |     ENV: AUTH_REQUIRED=false, MCPGATEWAY_UI_ENABLED=true
  |     |
  |     |-- Wait for /health (up to 30s)
  |     |
  |     +-- (optional) Start upstream demo servers (:9100+)
  |
  |-- [Phase 2] scripts/agentic-start.sh
  |     |
  |     |-- Start 6 MCP servers (:9101-9105, :9120)
  |     |-- Start 2 A2A agents (:9201-9202)
  |     |-- Wait for all 8 /health endpoints (up to 10s)
  |     |
  |     +-- Seed Forge (agentic/forge/seed/seed_all.py)
  |           |-- JWT login --> POST /auth/login
  |           |-- Discover tools --> POST /rpc (tools/list) per server
  |           |-- Register tools --> POST /tools (per tool)
  |           |-- Register A2A agents --> POST /a2a
  |           |-- Register gateways --> POST /gateways
  |           +-- Create virtual servers --> POST /servers
  |
  +-- [Phase 3] Health verification
        |-- Forge /health
        |-- MCP servers /health (X/6)
        +-- A2A agents /health (X/2)
```

---

## Troubleshooting

### Gateway not starting

```bash
# Check if port 4444 is in use
lsof -i :4444

# Start gateway manually with verbose logging
cd mcp-context-forge
.venv/bin/python -m uvicorn mcpgateway.main:app --host 127.0.0.1 --port 4444 --log-level debug
```

### MCP servers not healthy

```bash
# Check individual server health
curl http://127.0.0.1:9101/health

# Test tool discovery
curl -X POST http://127.0.0.1:9101/rpc \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":"test","method":"tools/list"}'
```

### Seed script failing

```bash
# Run seed manually with verbose output
MCPGATEWAY_URL=http://localhost:4444 \
  BASIC_AUTH_USER=admin \
  BASIC_AUTH_PASSWORD=changeme \
  python agentic/forge/seed/seed_all.py
```

### Backend can't reach Forge

```bash
# Check the backend's agentic status
curl http://localhost:8000/v1/agentic/status | python3 -m json.tool

# Check the full catalog
curl http://localhost:8000/v1/agentic/catalog | python3 -m json.tool
```

### Disabling agentic features

```bash
# Start without MCP at all
make start-no-agentic

# Or set the flag directly
make start AGENTIC=0
```
