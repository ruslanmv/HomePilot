# Community Shared Bundles — Design Document

## Architecture Overview

```
community/shared/
├── _schema/                          # JSON Schema definitions
│   ├── bundle_manifest.schema.json   # Validates bundle_manifest.json
│   └── mcp_server.schema.json        # Validates server_def.json
├── _templates/                       # Scaffolding templates
│   ├── mcp_server/app.py.tmpl        # MCP server boilerplate
│   └── persona_bundle/               # Bundle manifest template
├── bundles/                          # All shared bundles live here
│   └── hello_world_greeter/          # Example bundle
│       ├── bundle_manifest.json      # Bundle metadata + MCP config
│       ├── persona/                  # Standard .hpersona v2 structure
│       │   ├── manifest.json
│       │   ├── blueprint/
│       │   │   ├── persona_agent.json
│       │   │   ├── persona_appearance.json
│       │   │   └── agentic.json
│       │   ├── dependencies/
│       │   │   ├── mcp_servers.json
│       │   │   ├── tools.json
│       │   │   ├── a2a_agents.json
│       │   │   ├── models.json
│       │   │   └── suite.json
│       │   ├── assets/
│       │   └── preview/
│       │       └── card.json
│       ├── mcp_server/               # Dedicated MCP server code
│       │   ├── __init__.py
│       │   ├── app.py                # FastAPI app (create_mcp_app)
│       │   └── server_def.json       # Server metadata
│       └── forge/                    # Context Forge integration
│           ├── server_catalog_entry.yaml
│           ├── gateway_entry.yaml
│           └── virtual_server_entry.yaml
├── registry/
│   ├── shared_registry.json          # Master registry of all bundles
│   └── port_map.json                 # Port allocation tracker
└── scripts/
    ├── generate_bundle.py            # Scaffold new bundles
    └── install_bundle.py             # Install bundles into HomePilot
```

## MCP Server Modes

### 1. Dedicated (1 persona = 1 server)
Each persona ships its own MCP server on a unique port (9200-9999).
Best for: specialized tools that only one persona needs.

### 2. Shared (N personas = 1 server)
Multiple personas reference the same MCP server by ID.
Best for: common utilities (e.g., hp-community-greeter shared by 10 greeting personas).

### 3. None
Persona has no MCP tools — uses only built-in HomePilot capabilities.

## Context Forge Compatibility

Every community MCP server is fully compatible with Context Forge:

1. **Tool Discovery**: `POST /rpc` with `tools/list` returns all ToolDef objects
2. **Tool Invocation**: `POST /rpc` with `tools/call` invokes by name
3. **Health Check**: `GET /health` returns `{"ok": true}`
4. **Registration**: `server_manager.install()` → discover → register in Forge
5. **Virtual Servers**: Prefix-matched via `hp.community.<slug>.*`

## Naming Conventions

| Component | Pattern | Example |
|-----------|---------|---------|
| Bundle ID | `snake_case` | `hello_world_greeter` |
| Server ID | `hp-community-<kebab>` | `hp-community-greeter` |
| Tool FQN | `hp.community.<slug>.<action>` | `hp.community.greeter.greet` |
| Personality Tool | `community_<action>` | `community_greet` |
| Entry Point | `community_<slug>_server.py` | `community_greeter_server.py` |

## Scalability

- **Port Range**: 9200-9999 = 800 dedicated servers
- **Shared Servers**: Unlimited personas per server
- **Registry**: JSON-based, merge-friendly, auto-allocated ports
- **Generator**: `generate_bundle.py` scaffolds in seconds
- **No Core Modifications**: All changes are additive (append-only to YAML configs)

## Installation Flow

```
generate_bundle.py → scaffold files
install_bundle.py  → copy to MCP dir + append YAML configs + build .hpersona
server_manager.install() → start uvicorn → discover tools → register in Forge
POST /persona/import → import .hpersona into HomePilot project
```
