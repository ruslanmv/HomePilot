# MCP Context Forge - Registration & Discovery Analysis

Analysis of [mcp-context-forge](https://github.com/ruslanmv/mcp-context-forge) from branch `claude/create-project-presentation-AR7dh`, based on the `demo.sh` script and the underlying codebase.

---

## Architecture Overview

MCP Context Forge is a centralized **gateway and registry** for AI tool ecosystems built on the Model Context Protocol (MCP). It sits between AI clients (Claude, GPT, Copilot, custom agents) and backend MCP servers, providing:

- **Tool Registry** - Central catalog of executable functions
- **Gateway Layer** - Federation of external MCP servers
- **Auth & RBAC** - Role-based access control
- **Metrics & Logging** - Observability built-in

```
AI Clients (Claude, GPT, etc.)
        │
        │  MCP Protocol (JSON-RPC 2.0 over SSE/WebSocket/HTTP)
        ▼
┌──────────────────────────────┐
│     MCP CONTEXT FORGE        │
│  Registry │ Gateway │ Auth   │
└──────────────┬───────────────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
 MCP Server  REST API   Legacy
 (Native)   (Virtual)   System
```

**Server URL**: `http://localhost:4444` (default)
**Auth**: Basic auth (`admin:changeme` by default)

---

## 1. How to Register Tools

Tools are individual executable functions that AI clients can discover and invoke. Each tool requires:

| Field | Description |
|-------|-------------|
| `name` | Unique identifier |
| `description` | Human-readable explanation (helps AI choose the right tool) |
| `inputSchema` | JSON Schema defining required parameters |

### Register a tool via REST API

**Endpoint**: `POST /tools`

```bash
curl -X POST "http://localhost:4444/tools" \
  -u admin:changeme \
  -H "Content-Type: application/json" \
  -d '{
    "tool": {
      "name": "search_database",
      "description": "Search the enterprise database for records matching a query",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "Search query"
          },
          "limit": {
            "type": "integer",
            "description": "Maximum results",
            "default": 10
          }
        },
        "required": ["query"]
      }
    }
  }'
```

The response returns the tool with an auto-generated `id` and `enabled: true` by default.

### Advanced inputSchema features

Tools support full JSON Schema, including:

- **Arrays**: `"type": "array", "items": {"type": "string"}` (e.g., list of email recipients)
- **Enums**: `"enum": ["low", "normal", "high"]` to restrict allowed values
- **Nested objects**: `"type": "object"` for complex data inputs

### Tool governance (enable/disable)

Disable a tool instantly (hides it from all AI clients):

```bash
curl -X POST "http://localhost:4444/tools/{tool_id}/state?activate=false" \
  -u admin:changeme
```

Re-enable:

```bash
curl -X POST "http://localhost:4444/tools/{tool_id}/state?activate=true" \
  -u admin:changeme
```

---

## 2. How to Register MCP Servers (Gateways)

MCP Context Forge can federate entire external MCP servers by registering them as **gateways**. After registration, Context Forge aggregates their tools into the unified catalog.

### Register a gateway

**Endpoint**: `POST /gateways`

```bash
curl -X POST "http://localhost:4444/gateways" \
  -u admin:changeme \
  -H "Content-Type: application/json" \
  -d '{
    "gateway": {
      "name": "regional-us-east",
      "url": "http://mcp-server-us-east:4445/sse",
      "transport": "sse",
      "description": "US East regional MCP server"
    }
  }'
```

### Refresh a gateway (pull its tools)

After registration, refresh to import the gateway's tools:

```bash
curl -X POST "http://localhost:4444/gateways/{gateway_id}/refresh" \
  -u admin:changeme
```

### Create virtual servers (composed tool sets)

Virtual servers let you cherry-pick tools from multiple gateways into custom collections for different use cases (e.g., `finance-tools`, `hr-tools`, `public-tools`).

**Endpoint**: `POST /servers`

```bash
curl -X POST "http://localhost:4444/servers" \
  -u admin:changeme \
  -H "Content-Type: application/json" \
  -d '{
    "server": {
      "name": "finance-analysis",
      "description": "Financial analysis tools for analysts",
      "tool_ids": ["tool_id_1", "tool_id_2", "tool_id_3"]
    }
  }'
```

Each virtual server gets its own SSE endpoint:

```
http://localhost:4444/servers/{server_id}/sse
```

---

## 3. How to Register Agents (A2A - Agent-to-Agent)

MCP Context Forge supports **A2A (Agent-to-Agent)** registration for LangChain-based or custom agents.

**Endpoint**: `POST /a2a`

Agents support:
- Visibility levels: `public`, `team`, `private`
- Team assignment and owner tracking
- Auth encoding/headers
- Tag-based classification

**Listing agents**: `GET /a2a`

The bundled agent runtime at `agent_runtimes/langchain_agent/` provides a LangChain agent implementation supporting OpenAI, Azure, Bedrock, Ollama, and Anthropic as LLM backends.

---

## 4. How to List Available Servers Ready to Use

### List all registered tools

```bash
curl -s "http://localhost:4444/tools" -u admin:changeme | jq '.[] | {name, description, enabled}'
```

Only **enabled** tools are returned by default. To include disabled tools:

```bash
curl -s "http://localhost:4444/tools?include_inactive=true" -u admin:changeme
```

### List all gateways

```bash
curl -s "http://localhost:4444/gateways" -u admin:changeme
```

### List all virtual servers

```bash
curl -s "http://localhost:4444/servers" -u admin:changeme
```

### List tools for a specific server

```bash
curl -s "http://localhost:4444/servers/{server_id}/tools" -u admin:changeme
```

### List A2A agents

```bash
curl -s "http://localhost:4444/a2a" -u admin:changeme
```

### Pagination

All listing endpoints support **cursor-based pagination**:

```bash
curl -s "http://localhost:4444/tools?cursor=CURSOR_TOKEN&limit=20&include_pagination=true" \
  -u admin:changeme
```

### Filtering

All listing endpoints support filtering by:
- `tags` - Tag-based filtering
- `team_id` - Team-based scoping
- `visibility` - `private`, `team`, or `public`
- `include_inactive` - Include disabled items

---

## 5. Pre-built MCP Server Catalog (100+ servers)

The file `mcp-catalog.yml` contains a curated catalog of **100+ public MCP servers** ready to be registered as gateways. Categories include:

| Category | Examples |
|----------|----------|
| Project Management | Asana, Linear, Notion, monday.com |
| Software Development | GitHub, Atlassian, Buildkite, Sentry, Vercel, Neon |
| Payments | Stripe, PayPal, Plaid, Square |
| CRM | HubSpot, Close, Intercom |
| Document Management | Box, Egnyte, Cloudinary |
| Design & Content | Canva, InVideo |
| CMS | Webflow, Wix |
| RAG-as-a-Service | OneContext, Needle, DeepWiki, CustomGPT |
| Web Scraping | Simplescraper, Apify |
| Automation | Zapier |
| Documentation | Cloudflare Docs, Astro Docs |
| Blockchain | OpenZeppelin (Solidity, Cairo, Stellar, Stylus) |
| And more... | Security, Analytics, Communication, etc. |

Each catalog entry includes:
```yaml
- id: github
  name: "GitHub"
  category: "Software Development"
  url: "https://api.githubcopilot.com/mcp"
  auth_type: "OAuth2.1"
  provider: "GitHub"
  description: "Version control and collaborative software development"
  requires_api_key: false
  tags: ["development", "git", "version-control"]
```

---

## 6. Bundled MCP Servers (22 built-in)

The project ships with 22 Python MCP servers in `mcp-servers/python/`:

| Server | Purpose |
|--------|---------|
| `chunker_server` | Document chunking |
| `code_splitter_server` | Code parsing |
| `csv_pandas_chat_server` | CSV data analysis |
| `data_analysis_server` | Comprehensive data analysis |
| `docx_server` | Word document processing |
| `graphviz_server` | Graph visualization |
| `latex_server` | LaTeX compilation |
| `libreoffice_server` | Office document conversion |
| `mcp-rss-search` | RSS feed searching |
| `mcp_eval_server` | Model evaluation |
| `mermaid_server` | Diagram generation |
| `plotly_server` | Interactive plotting |
| `pm_mcp_server` | Project management |
| `pptx_server` | PowerPoint processing |
| `python_sandbox_server` | Sandboxed Python execution |
| `qr_code_server` | QR code generation |
| `synthetic_data_server` | Synthetic data generation |
| `url_to_markdown_server` | URL content extraction |
| `xlsx_server` | Excel file processing |

---

## 7. CLI Entry Points

| Command | Purpose |
|---------|---------|
| `mcpgateway` | Start the gateway server (default: `localhost:4444`) |
| `mcpplugins` | Plugin management (bootstrap, install, package) |
| `cforge` | Build, deploy, and manage gateway infrastructure |

---

## 8. HomePilot Wizard Integration

The Agentic Creator wizard exposes a **Sync HomePilot** button (`POST /v1/agentic/sync`) that bulk-discovers tools from running MCP servers and registers them in Forge in one click.
The `ForgeInventory` helper (`backend/app/agentic/list_forge_inventory.py`) and `sync_service.py` power both the CLI (`make mcp-inventory`) and the wizard sync flow.

## 9. Admin UI & API Docs

- **Admin UI**: `http://localhost:4444/admin` - Web-based management dashboard
- **API Docs (Swagger)**: `http://localhost:4444/docs` - Full OpenAPI documentation
- **Health Check**: `http://localhost:4444/health`

---

## Quick Start Summary

```bash
# 1. Start the server
make dev

# 2. Register a tool
curl -X POST "http://localhost:4444/tools" \
  -u admin:changeme \
  -H "Content-Type: application/json" \
  -d '{"tool": {"name": "my_tool", "description": "Does something", "inputSchema": {"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"]}}}'

# 3. Register a gateway (external MCP server)
curl -X POST "http://localhost:4444/gateways" \
  -u admin:changeme \
  -H "Content-Type: application/json" \
  -d '{"gateway": {"name": "my-gateway", "url": "http://remote-server:8080/sse", "transport": "sse"}}'

# 4. List all available tools
curl -s "http://localhost:4444/tools" -u admin:changeme | jq '.[] | {name, description}'

# 5. List all gateways
curl -s "http://localhost:4444/gateways" -u admin:changeme

# 6. List all servers
curl -s "http://localhost:4444/servers" -u admin:changeme

# 7. Bulk-sync HomePilot MCP servers, tools, agents, and virtual servers
curl -X POST "http://localhost:4444/v1/agentic/sync" -H "x-api-key: YOUR_KEY"

# 8. Run the interactive demo
bash demo.sh
```
