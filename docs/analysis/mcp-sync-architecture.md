# MCP Sync Architecture: HomePilot <-> MCP Context Forge

## Executive Summary

HomePilot integrates with MCP Context Forge through a multi-layered sync architecture
that discovers local MCP server tools, registers them in Forge's centralized registry,
and organizes them into virtual servers. The frontend then reads from a cached catalog
API that aggregates tools, A2A agents, gateways, and virtual servers into a single
unified view.

---

## 1. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                        HomePilot Frontend (React)                    │
│                                                                      │
│  ┌──────────────┐   ┌───────────────┐   ┌───────────────────────┐   │
│  │  ToolsTab    │   │ McpServersTab │   │ AgentSettingsPanel    │   │
│  │  (tools+a2a) │   │ (gateways+    │   │ (per-project config)  │   │
│  │              │   │  vservers)    │   │                       │   │
│  └──────┬───────┘   └──────┬────────┘   └───────────┬───────────┘   │
│         │                  │                        │               │
│         └─────────┬────────┘────────────────────────┘               │
│                   │                                                  │
│         ┌────────┴──────────┐                                       │
│         │ useAgenticCatalog │  ← Single HTTP call for all data      │
│         │ (React hook)      │                                       │
│         └────────┬──────────┘                                       │
│                  │  GET /v1/agentic/catalog                         │
│                  │  POST /v1/agentic/sync    (Sync All button)      │
└──────────────────┼───────────────────────────────────────────────────┘
                   │
┌──────────────────┼───────────────────────────────────────────────────┐
│                  │     HomePilot Backend (FastAPI)                    │
│                  │                                                    │
│         ┌────────┴──────────────┐                                    │
│         │  /v1/agentic/* router │                                    │
│         │  (routes.py)          │                                    │
│         └───┬────────┬──────────┘                                    │
│             │        │                                               │
│   ┌─────────┘        └──────────────┐                                │
│   │                                 │                                │
│   │  GET /catalog                   │  POST /sync                    │
│   │  ┌────────────────────┐         │  ┌──────────────────────┐      │
│   │  │AgenticCatalogService│        │  │  sync_service.py     │      │
│   │  │ (TTL=15s cache)    │         │  │  sync_homepilot()    │      │
│   │  └────────┬───────────┘         │  └──────────┬───────────┘      │
│   │           │                     │             │                  │
│   │  ┌────────┴──────────┐          │  1. Discover tools from        │
│   │  │ ContextForgeClient│          │     local MCP servers          │
│   │  │ + ForgeHttp       │          │  2. Register tools in Forge    │
│   │  └────────┬──────────┘          │  3. Register A2A agents        │
│   │           │                     │  4. Create/update vservers     │
│   │           │                     │             │                  │
└───┼───────────┼─────────────────────┼─────────────┼──────────────────┘
    │           │   REST/JWT Auth     │             │
    │           └─────────┬───────────┘─────────────┘
    │                     │
┌───┼─────────────────────┼────────────────────────────────────────────┐
│   │                     │    MCP Context Forge (Gateway)             │
│   │              ┌──────┴──────┐                                     │
│   │              │  REST API   │                                     │
│   │              │  /tools     │   /gateways   /servers   /a2a       │
│   │              └──────┬──────┘                                     │
│   │                     │                                            │
│   │              ┌──────┴──────┐                                     │
│   │              │ PostgreSQL  │  tools, gateways, servers,          │
│   │              │ Database    │  a2a_agents, server_tool_assoc      │
│   │              └─────────────┘                                     │
└───┼──────────────────────────────────────────────────────────────────┘
    │
┌───┼──────────────────────────────────────────────────────────────────┐
│   │            Local MCP Servers (ports 9101-9120)                    │
│   │                                                                  │
│   ├── hp-personal-assistant  :9101  (core)                           │
│   ├── hp-knowledge           :9102  (core)                           │
│   ├── hp-decision-copilot    :9103  (core)                           │
│   ├── hp-executive-briefing  :9104  (core)                           │
│   ├── hp-web-search          :9105  (core)                           │
│   ├── hp-local-notes         :9110  (local)                          │
│   ├── hp-local-projects      :9111  (local)                          │
│   ├── hp-web-fetch           :9112  (local)                          │
│   ├── hp-shell-safe          :9113  (local)                          │
│   ├── hp-gmail               :9114  (communication)                  │
│   ├── hp-google-calendar     :9115  (communication)                  │
│   ├── hp-microsoft-graph     :9116  (communication)                  │
│   ├── hp-slack               :9117  (communication)                  │
│   ├── hp-github              :9118  (dev)                            │
│   ├── hp-notion              :9119  (dev)                            │
│   └── hp-inventory           :9120  (inventory)                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. Sync Flow (POST /v1/agentic/sync)

The "Sync All" button in the MCP Servers tab triggers `POST /v1/agentic/sync`.
This is the primary mechanism for populating MCP Context Forge with HomePilot's
tools and agents.

### 2.1 Step-by-Step Flow

**File:** `backend/app/agentic/sync_service.py` → `sync_homepilot()`

```
┌─────────────────────────────────────────────────────┐
│  Step 0: Health Check + Authentication               │
│                                                      │
│  1. Wait for Forge /health (up to 10s)               │
│  2. Acquire JWT via POST /auth/login                 │
│     - Retries 3x with 2s backoff                    │
│     - Falls back to basic auth if JWT fails          │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│  Step 1: Pre-fetch Existing Items                    │
│                                                      │
│  GET /tools    → existing_tools   {name: id}         │
│  GET /a2a      → existing_agents  {name: id}         │
│  GET /servers  → existing_servers {name: id}         │
│                                                      │
│  (Used for idempotent skip-if-exists logic)          │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│  Step 2: Discover + Register Tools                   │
│                                                      │
│  For each of 16 MCP servers (ports 9101-9120):       │
│    1. POST http://{host}:{port}/rpc                  │
│       body: { method: "tools/list" }                 │
│    2. For each discovered tool:                      │
│       - Skip if name already in existing_tools       │
│       - POST /tools with tool definition:            │
│         { name, description, inputSchema,            │
│           integration_type: "REST",                  │
│           url: "http://{host}:{port}/rpc",           │
│           tags: ["homepilot"] }                      │
│    3. Build tool_id_map: {tool_name → forge_uuid}    │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│  Step 3: Register A2A Agents                         │
│                                                      │
│  Source: agentic/forge/templates/a2a_agents.yaml     │
│                                                      │
│  Agents:                                             │
│    - everyday-assistant  → localhost:9201/rpc         │
│    - chief-of-staff      → localhost:9202/rpc         │
│                                                      │
│  POST /a2a for each (skip if exists)                 │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│  Step 4: Register Gateways (best-effort)             │
│                                                      │
│  Source: agentic/forge/templates/gateways.yaml       │
│                                                      │
│  16 gateways matching each MCP server                │
│  POST /gateways for each (may 503 on Community Ed.)  │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│  Step 5: Create/Update Virtual Servers               │
│                                                      │
│  Source: agentic/forge/templates/virtual_servers.yaml │
│                                                      │
│  12 virtual servers (curated tool bundles):           │
│    hp-home-default, hp-default-readonly,             │
│    hp-decision-room, hp-exec-briefing,               │
│    hp-web-research, hp-local-tools,                  │
│    hp-notes-only, hp-projects-only,                  │
│    hp-comms-all, hp-email, hp-calendar,              │
│    hp-dev-tools                                      │
│                                                      │
│  Each defines include/exclude_tool_prefixes:         │
│    e.g. hp-dev-tools includes:                       │
│      hp.github.*, hp.notion.*, hp.shell.*,           │
│      hp.projects.*, hp.local_projects.*              │
│                                                      │
│  Tool assignment: _tool_ids_by_prefix() matches      │
│    tool names from tool_id_map against prefixes      │
│    to produce a list of Forge tool UUIDs             │
│                                                      │
│  Upsert logic:                                       │
│    - Exists? → PUT /servers/{id} (update tools)      │
│    - New?    → POST /servers (create)                │
│    - Fallback → DELETE + recreate                    │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│  Step 6: Post-Sync                                   │
│                                                      │
│  1. Invalidate catalog cache (_catalog_service)      │
│  2. Fetch fresh catalog via get_cached()             │
│  3. Return { sync: summary, catalog: refreshed }     │
└─────────────────────────────────────────────────────┘
```

### 2.2 Idempotency

The sync is designed to be **idempotent**:
- Tools are looked up by name; if already registered, they're skipped
- A2A agents are looked up by name; skipped if present
- Virtual servers are upserted: existing ones get tool associations updated
- HTTP 409 (conflict) responses are silently accepted

---

## 3. Catalog Read Flow (GET /v1/agentic/catalog)

The frontend's primary data source. Called by `useAgenticCatalog` hook on mount
and after sync.

### 3.1 Data Flow

**File:** `backend/app/agentic/catalog_service.py` → `AgenticCatalogService`

```
Frontend                 Backend                      Forge
────────                 ───────                      ─────

useAgenticCatalog()
  │
  ├─→ GET /v1/agentic/catalog
  │        │
  │        ├─→ TTLCache check (15s)
  │        │   ├─→ HIT → return cached AgenticCatalog
  │        │   └─→ MISS → build()
  │        │
  │        ├─→ ForgeHttp.health()        → GET /health
  │        ├─→ ContextForgeClient        → GET /tools
  │        │     .list_tools()
  │        ├─→ ContextForgeClient        → GET /a2a
  │        │     .list_agents()
  │        ├─→ ForgeHttp                 → GET /servers
  │        │     .list_servers_best_effort()    (or /admin/servers)
  │        ├─→ ForgeHttp                 → GET /gateways
  │        │     .list_gateways_best_effort()   (or /admin/gateways)
  │        │
  │        ├─→ Normalize: tools name→UUID resolution
  │        ├─→ Build capability_sources heuristic map
  │        ├─→ Assemble AgenticCatalog
  │        └─→ Cache and return
  │
  ├─→ Splits into derived hooks:
  │     useInstalledServers (gateways + virtual servers)
  │     useToolsInventory   (tools + A2A agents)
  │
  └─→ UI renders
```

### 3.2 AgenticCatalog Schema

```typescript
type AgenticCatalog = {
  source: string              // "forge"
  last_updated: string        // ISO timestamp
  forge: ForgeStatus          // { base_url, healthy, error? }
  servers: CatalogServer[]    // Virtual servers with tool_ids[]
  tools: CatalogTool[]        // { id, name, description, enabled }
  a2a_agents: CatalogA2AAgent[] // { id, name, description, enabled, endpoint_url }
  gateways: CatalogGateway[]  // { id, name, enabled, url, transport }
  capability_sources: Record<string, string[]>  // capability → tool_ids
}
```

---

## 4. Authentication Flow

```
HomePilot Backend → MCP Context Forge
─────────────────────────────────────

1. ContextForgeClient._ensure_token()
   ├── If token exists → use Bearer JWT
   ├── If no token + retry interval passed:
   │   └── POST /auth/login { email, password }
   │       └── Store JWT for subsequent calls
   └── If JWT fails → fallback to BasicAuth

2. sync_service._acquire_jwt()
   ├── POST /auth/login with retries (3x, 2s backoff)
   ├── Tolerates HTTP 500 during Forge startup
   └── Falls back to BasicAuth if all retries fail

3. ForgeHttp._ensure_token()
   ├── Same JWT auto-acquisition
   └── 60s retry interval to prevent hammering
```

Environment variables controlling auth:
- `CONTEXT_FORGE_URL` (default: `http://localhost:4444`)
- `CONTEXT_FORGE_TOKEN` (pre-configured bearer token)
- `CONTEXT_FORGE_AUTH_USER` (default: `admin`)
- `CONTEXT_FORGE_AUTH_PASS` (default: `changeme`)

---

## 5. MCP Context Forge Internal Architecture

### 5.1 Database Schema (Key Tables)

**File:** `mcpgateway/db.py`

| Table | Key Fields | Description |
|-------|-----------|-------------|
| `tools` | id (UUID), original_name, url, description, integration_type, input_schema, enabled | Registered MCP tools |
| `gateways` | id, name, url, transport, enabled, reachable | Federated MCP servers |
| `servers` | id, name, description, enabled | Virtual servers (tool bundles) |
| `server_tool_association` | server_id, tool_id | M:N join between servers and tools |
| `a2a_agents` | id, name, description, endpoint_url, enabled | A2A protocol agents |

### 5.2 Gateway Tool Discovery

**File:** `mcpgateway/services/gateway_service.py` → `_refresh_gateway_tools_resources_prompts()`

When Forge's health check runs or a manual refresh is triggered:

1. Opens MCP session to gateway URL (SSE or StreamableHTTP)
2. Calls MCP `tools/list`, `resources/list`, `prompts/list`
3. Diffs against DB: adds new, removes stale, updates changed
4. Links tools to gateway via `server_tool_association`

This is the Forge-internal mechanism. HomePilot uses a **direct discovery** approach
instead (querying each MCP server's `/rpc` endpoint directly).

### 5.3 Forge REST API Endpoints Used by HomePilot

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/health` | GET | Health check before sync |
| `/auth/login` | POST | JWT token acquisition |
| `/tools` | GET | List all registered tools |
| `/tools` | POST | Register a new tool |
| `/a2a` | GET | List all A2A agents |
| `/a2a` | POST | Register a new A2A agent |
| `/gateways` | GET | List all gateways |
| `/gateways` | POST | Register a new gateway |
| `/gateways/{id}/tools/refresh` | POST | Trigger tool discovery |
| `/servers` | GET | List virtual servers |
| `/servers` | POST | Create virtual server |
| `/servers/{id}` | PUT | Update server tool associations |
| `/servers/{id}/tools` | GET | List tools for a server |
| `/admin/mcp-registry/servers` | GET | Browse public MCP catalog |
| `/admin/mcp-registry/{id}/register` | POST | Install from public catalog |

---

## 6. Virtual Server Tool Bundling

Virtual servers are the key organizational abstraction. They create **curated
tool collections** (allow-lists) that projects can reference.

### 6.1 Template Definition

**File:** `agentic/forge/templates/virtual_servers.yaml`

```yaml
- name: "hp-dev-tools"
  description: "Developer tools: GitHub, Notion, shell, projects"
  include_tool_prefixes:
    - "hp.github."
    - "hp.notion."
    - "hp.shell."
    - "hp.projects."
    - "hp.local_projects."
```

### 6.2 Tool Resolution

**File:** `backend/app/agentic/sync_service.py` → `_tool_ids_by_prefix()`

```python
# tool_id_map = {"hp.github.list_repos": "uuid-1", "hp.notion.search": "uuid-2", ...}
# include = ["hp.github.", "hp.notion."]
# Result: ["uuid-1", "uuid-2"]
```

Each virtual server's tools are resolved at sync time by matching tool names
against prefix patterns, then storing the resulting UUIDs in Forge's
`server_tool_association` table.

### 6.3 Virtual Servers Defined

| Name | Description | Tool Prefixes |
|------|-------------|---------------|
| hp-home-default | Personal Assistant (safe, read-only) | hp.personal.* |
| hp-default-readonly | Knowledge + Decision + Briefing | hp.* (excl. hp.action.*) |
| hp-decision-room | Knowledge + Decision | hp.search_*, hp.get_*, hp.answer_*, hp.summarize_*, hp.decision.* |
| hp-exec-briefing | Executive briefing only | hp.brief.* |
| hp-web-research | Web search + fetch | hp.web.* |
| hp-local-tools | Notes, projects, web fetch, shell | hp.notes.*, hp.projects.*, hp.web_fetch.*, hp.shell.* |
| hp-notes-only | Local notes only | hp.notes.*, hp.local_notes.* |
| hp-projects-only | Local projects only | hp.projects.*, hp.local_projects.* |
| hp-comms-all | All communication | hp.gmail.*, hp.gcal.*, hp.graph.*, hp.slack.* |
| hp-email | Email tools | hp.gmail.*, hp.graph.mail.* |
| hp-calendar | Calendar tools | hp.gcal.*, hp.graph.calendar.* |
| hp-dev-tools | Developer tools | hp.github.*, hp.notion.*, hp.shell.*, hp.projects.* |

---

## 7. Frontend Data Flow

### 7.1 Hook Architecture

```
useAgenticCatalog (single fetch)
  │
  ├── useInstalledServers (MCP Servers tab)
  │     ├── Maps gateways → InstalledServer[]
  │     ├── Maps servers → InstalledServer[]
  │     └── Provides: servers, counts, forgeHealthy
  │
  └── useToolsInventory (Tools tab)
        ├── Maps tools → CapabilityItem { kind: 'tool' }
        ├── Maps a2a_agents → CapabilityItem { kind: 'a2a_agent' }
        └── Provides: items, counts, search, filters
```

### 7.2 UI Components

**MCP Servers Tab** (`frontend/src/ui/mcp/McpServersTab.tsx`):
- Shows installed gateways and virtual servers as cards
- "Sync All" button → `POST /v1/agentic/sync`
- "Refresh" button → re-fetches catalog
- "Add Server" → manual gateway registration
- Discover sub-tab → browse Forge's MCP registry

**Tools Tab** (`frontend/src/ui/tools/ToolsTab.tsx`):
- Shows all tools + A2A agents in a unified grid
- Filters: type (tool/a2a), status (active/inactive)
- Shows Forge Online/Offline status badge
- Counts: Total, Tools, A2A, Active, Inactive

**InstalledServerCard** (`frontend/src/ui/mcp/InstalledServerCard.tsx`):
- Gateway cards: green icon + "Gateway" badge
- Virtual server cards: purple icon + "Virtual Server" badge
- Shows tool count or "No skills yet — run Sync All" if empty

---

## 8. Sync Result Response

When `POST /v1/agentic/sync` completes, it returns:

```json
{
  "sync": {
    "ok": true,
    "mcp_tool_host": "127.0.0.1",
    "mcp_servers_reachable": 5,
    "mcp_servers_total": 16,
    "mcp_servers_unreachable": ["hp-slack:9117", ...],
    "tools_registered": 12,
    "tools_skipped": 3,
    "tools_total_in_forge": 15,
    "agents_registered": 2,
    "agents_skipped": 0,
    "gateways_registered": 5,
    "virtual_servers_created": 12,
    "virtual_servers_updated": 0,
    "virtual_servers_unchanged": 0,
    "log": ["hp-personal-assistant: 4 tools discovered", ...],
    "errors": []
  },
  "catalog": { ... refreshed AgenticCatalog ... }
}
```

---

## 9. Discover Tab (Phase 9)

The Discover sub-tab in MCP Servers allows browsing Forge's public MCP registry
(81+ community servers across 38 categories) and installing them as gateways.

**Flow:**
1. `GET /v1/agentic/registry/servers` → Proxies to Forge's `/admin/mcp-registry/servers`
2. User clicks "Install" on a registry entry
3. `POST /v1/agentic/registry/{server_id}/register` → Proxies to Forge
4. Forge creates gateway, triggers tool discovery
5. Catalog cache invalidated, server appears in Installed tab

---

## 10. Key Design Decisions

1. **Direct discovery over SSE auto-discovery**: HomePilot queries each MCP server's
   `/rpc` endpoint directly via JSON-RPC `tools/list`, rather than relying on Forge's
   SSE-based gateway discovery. This avoids network topology issues when Forge and
   MCP servers run on different hosts.

2. **Prefix-based virtual servers**: Tools are organized by naming convention
   (`hp.github.*`, `hp.notes.*`) rather than explicit tool IDs. This makes the
   system self-organizing as new tools are added.

3. **TTL-cached catalog**: The `AgenticCatalogService` caches the full catalog for
   15 seconds, reducing load on Forge while keeping the UI reasonably fresh.

4. **JWT-first auth with basic fallback**: Handles Forge startup races where
   `/auth/login` may return HTTP 500 transiently.

5. **Idempotent sync**: Safe to run repeatedly. Tools/agents are deduplicated by
   name, virtual servers are upserted.

6. **Single-fetch UI pattern**: `useAgenticCatalog` makes one HTTP call; derived
   hooks (`useInstalledServers`, `useToolsInventory`) are purely in-memory transforms.

---

## 11. File Reference

### HomePilot Backend
| File | Purpose |
|------|---------|
| `backend/app/agentic/routes.py` | FastAPI router: /v1/agentic/* endpoints |
| `backend/app/agentic/sync_service.py` | Bulk sync: discover tools + register in Forge |
| `backend/app/agentic/catalog_service.py` | TTL-cached catalog builder |
| `backend/app/agentic/client.py` | ContextForgeClient: thin HTTP wrapper |
| `backend/app/agentic/forge_http.py` | ForgeHttp: extended HTTP wrapper for servers/gateways |
| `backend/app/agentic/types.py` | Pydantic models for API contract |

### HomePilot Frontend
| File | Purpose |
|------|---------|
| `frontend/src/agentic/useAgenticCatalog.ts` | Core hook: fetches catalog |
| `frontend/src/agentic/types.ts` | TypeScript types mirroring backend |
| `frontend/src/ui/mcp/McpServersTab.tsx` | MCP Servers tab with Sync All |
| `frontend/src/ui/mcp/useInstalledServers.ts` | Hook: servers view from catalog |
| `frontend/src/ui/tools/ToolsTab.tsx` | Tools + A2A unified view |
| `frontend/src/ui/tools/useToolsInventory.ts` | Hook: tools view from catalog |
| `frontend/src/ui/mcp/InstalledServerCard.tsx` | Server card component |

### YAML Templates
| File | Purpose |
|------|---------|
| `agentic/forge/templates/a2a_agents.yaml` | A2A agent definitions |
| `agentic/forge/templates/gateways.yaml` | Gateway (MCP server) definitions |
| `agentic/forge/templates/virtual_servers.yaml` | Virtual server tool bundles |

### MCP Context Forge (Gateway)
| File | Purpose |
|------|---------|
| `mcpgateway/services/gateway_service.py` | Gateway federation + tool refresh |
| `mcpgateway/services/tool_service.py` | Tool management + invocation |
| `mcpgateway/admin.py` | Admin UI REST endpoints |
| `mcpgateway/db.py` | SQLAlchemy ORM: Tool, Gateway, Server, A2AAgent |
| `mcpgateway/config.py` | Settings incl. gateway_auto_refresh_interval |
