# MCP Shared Community Servers — Best Practices

A practical guide to creating, sharing, and integrating MCP servers with HomePilot personas using the community shared bundle system.

---

## How It Works

The shared bundle system lets anyone create a **persona + MCP server** package that can be distributed via Git and installed into any HomePilot instance. Each bundle is self-contained — it carries the persona definition, the MCP server code, and the Context Forge integration files needed to register everything automatically.

### Architecture at a Glance

```
community/shared/
├── bundles/                          # All bundles live here (local + cloned)
│   └── <bundle_id>/
│       ├── bundle_manifest.json      # Bundle metadata + MCP config
│       ├── persona/                  # Standard .hpersona v2 structure
│       │   ├── manifest.json
│       │   ├── blueprint/            # persona_agent.json, appearance, agentic
│       │   ├── dependencies/         # mcp_servers.json, tools.json, etc.
│       │   ├── assets/
│       │   └── preview/card.json
│       ├── mcp_server/               # Dedicated MCP server code (if applicable)
│       │   ├── __init__.py
│       │   ├── app.py                # FastAPI app via create_mcp_app()
│       │   └── server_def.json
│       └── forge/                    # Context Forge YAML entries
│           ├── server_catalog_entry.yaml
│           ├── gateway_entry.yaml
│           └── virtual_server_entry.yaml
├── registry/
│   ├── shared_registry.json          # Master registry of all bundles
│   └── port_map.json                 # Port allocation tracker (9200-9999)
├── scripts/
│   ├── generate_bundle.py            # Scaffold new bundles
│   └── install_bundle.py             # Install bundles into HomePilot
├── _schema/                          # JSON Schema for validation
└── _templates/                       # Boilerplate for scaffolding
```

### Port Ranges

| Range       | Purpose                      |
|-------------|------------------------------|
| 9101–9105   | Core servers (always running)|
| 9110–9120   | Optional built-in servers    |
| **9200–9999** | **Community servers** (800 slots) |

---

## MCP Server Modes

Every bundle declares one of three modes in `bundle_manifest.json`:

### 1. Dedicated (`"mode": "dedicated"`)

The bundle ships its own MCP server on a unique port. Best for specialized tools only one persona needs.

```json
"mcp_server": {
  "mode": "dedicated",
  "server_id": "hp-community-greeter",
  "port": 9200,
  "module": "agentic.integrations.mcp.community_greeter_server:app",
  "tools_provided": ["hp.community.greeter.greet", "hp.community.greeter.farewell"]
}
```

### 2. Shared (`"mode": "shared"`)

Multiple personas reference the same existing MCP server by ID. Best for common utilities used by many personas.

```json
"mcp_server": {
  "mode": "shared",
  "server_id": "hp-community-greeter",
  "tools_provided": ["hp.community.greeter.greet"]
}
```

### 3. None (`"mode": "none"`)

The persona uses only built-in HomePilot capabilities — no custom MCP tools.

---

## Creating a New Bundle

### Step 1: Scaffold with the Generator

```bash
python community/shared/scripts/generate_bundle.py \
  --id weather_forecast \
  --name "Cirrus" \
  --role "Weather Forecaster" \
  --class-id assistant \
  --author "Your Name" \
  --tools "forecast,radar,alerts"
```

This creates the full directory structure at `community/shared/bundles/weather_forecast/` with:
- A port auto-allocated from the 9200–9999 range
- A scaffolded `mcp_server/app.py` from the template
- All persona files pre-filled with sensible defaults
- Forge integration YAML entries ready to append

Options:
- `--class-id` — one of: `assistant`, `secretary`, `companion`, `creative`, `specialist`
- `--shared-server hp-community-greeter` — share an existing server instead of creating a new one
- `--git-url` — the GitHub repo URL where the bundle will be published
- `--tags` — comma-separated tags for discoverability

### Step 2: Implement Your MCP Server

Edit `mcp_server/app.py`. The template uses HomePilot's standard `create_mcp_app()` factory:

```python
from agentic.integrations.mcp._common.server import ToolDef, create_mcp_app

async def hp_forecast(location: str, days: int = 3):
    """Your tool logic here."""
    return {"content": [{"type": "json", "json": {"forecast": "sunny", "location": location}}]}

TOOLS = [
    ToolDef(
        name="hp.community.weather_forecast.forecast",
        description="Get weather forecast for a location.",
        input_schema={
            "type": "object",
            "properties": {
                "location": {"type": "string", "description": "City or coordinates"},
                "days": {"type": "integer", "description": "Number of days", "default": 3},
            },
            "required": ["location"],
        },
        handler=lambda args: hp_forecast(**args),
    ),
]

app = create_mcp_app(server_name="homepilot-community-weather-forecast", tools=TOOLS)
```

The resulting server exposes:
- `GET /health` — returns `{"ok": true}`
- `POST /rpc` — JSON-RPC 2.0 (`tools/list`, `tools/call`)

### Step 3: Customize the Persona

Edit `persona/blueprint/persona_agent.json` to set the system prompt, tone, and allowed tools:

```json
{
  "id": "weather_forecast",
  "label": "Cirrus",
  "role": "Weather Forecaster",
  "system_prompt": "You are Cirrus, a weather forecasting specialist...",
  "response_style": {"tone": "Friendly, data-driven"},
  "allowed_tools": ["community_forecast", "community_radar", "community_alerts"]
}
```

### Step 4: Install Locally

```bash
python community/shared/scripts/install_bundle.py weather_forecast
```

This performs five additive (non-destructive) steps:
1. Creates a thin entry point at `agentic/integrations/mcp/community_weather_forecast_server.py`
2. Appends to `server_catalog.yaml`
3. Appends to `gateways.yaml`
4. Appends to `virtual_servers.yaml`
5. Builds the `.hpersona` zip package

Then restart HomePilot or call `server_manager.install('hp-community-weather-forecast')`.

---

## Sharing a Bundle via Git

### Publishing

1. Create a GitHub repository for your bundle
2. The repo root should mirror the bundle directory structure:

```
your-repo/
├── bundle_manifest.json        # Must be at repo root
├── persona/
├── mcp_server/
└── forge/
```

3. Set the `git` field in `bundle_manifest.json`:

```json
"mcp_server": {
  "git": "https://github.com/yourname/hp-bundle-weather",
  "ref": "main"
}
```

4. Push to GitHub. That's it — your bundle is now installable by anyone.

### Installing from Git

Anyone with a HomePilot instance can install your bundle in one command:

```bash
python community/shared/scripts/install_bundle.py \
  --from-git https://github.com/yourname/hp-bundle-weather
```

What happens:
1. Shallow-clones the repo into `community/shared/bundles/<bundle_id>/`
2. Strips the `.git` directory (only source files are kept)
3. Reads `bundle_manifest.json` to get the `bundle_id`
4. Registers the port in `port_map.json`
5. Runs the full install flow (entry point, YAML append, .hpersona build)

To pin a specific version:

```bash
python community/shared/scripts/install_bundle.py \
  --from-git https://github.com/yourname/hp-bundle-weather \
  --ref v1.2.0
```

---

## Naming Conventions

Follow these patterns to keep the ecosystem consistent:

| Component         | Pattern                           | Example                                |
|-------------------|-----------------------------------|----------------------------------------|
| Bundle ID         | `snake_case`                      | `weather_forecast`                     |
| Server ID         | `hp-community-<kebab>`            | `hp-community-weather-forecast`        |
| Tool FQN          | `hp.community.<slug>.<action>`    | `hp.community.weather_forecast.radar`  |
| Personality Tool  | `community_<action>`              | `community_forecast`                   |
| Entry Point       | `community_<slug>_server.py`      | `community_weather_forecast_server.py` |

---

## Best Practices

### Bundle Design

- **One responsibility per bundle.** A weather bundle should do weather, not also manage calendars.
- **Keep tools focused.** 3–8 tools per server is the sweet spot. If you need more, consider splitting into multiple bundles.
- **Use shared mode** when multiple personas need the same tools. Don't duplicate servers.
- **Include a `card.json`** with a clear description, tags, and role — this powers the community browse UI.

### MCP Server Code

- **Always use `create_mcp_app()`** from `_common/server.py`. This guarantees compatibility with Context Forge, server_manager, and the health check protocol.
- **Return MCP-formatted responses**: `{"content": [{"type": "json", "json": {...}}]}`.
- **Keep handlers async.** All tool handlers should be `async def` — the server runs on uvicorn.
- **Validate inputs** at the boundary. Use `input_schema` to define required fields and types — Forge will enforce them before your handler runs.
- **No hardcoded ports.** The port is set in `bundle_manifest.json` and auto-allocated by the generator. Your `app.py` should never hardcode a port number.

### Persona Integration

- **Match `allowed_tools`** in `persona_agent.json` to the personality tool names (e.g., `community_forecast`), not the FQN.
- **Keep `mcp_servers.json` in sync** with `bundle_manifest.json`. Both should reference the same `server_id` and `tools_provided`.
- **Set `requires_config`** in the compatibility section if your server needs environment variables (e.g., API keys). This lets the installer warn users upfront.

### Distribution

- **Version your bundles** using semver in `bundle_version`. Consumers can pin with `--ref v1.0.0`.
- **Keep `bundle_manifest.json` at repo root.** The install script expects it there.
- **One repo = one bundle.** Subdirectory repos are not supported yet.
- **Test locally before publishing.** Run `install_bundle.py` with `--dry-run` first:

```bash
python community/shared/scripts/install_bundle.py weather_forecast --dry-run
```

### Uninstalling

```bash
python community/shared/scripts/install_bundle.py --uninstall weather_forecast
```

This removes the entry point and `.hpersona` file. YAML entries in `server_catalog.yaml`, `gateways.yaml`, and `virtual_servers.yaml` must be removed manually (noted in the output).

---

## Quick Reference

```bash
# List all installed bundles
python community/shared/scripts/install_bundle.py --list

# Scaffold a new bundle
python community/shared/scripts/generate_bundle.py \
  --id my_bundle --name "Agent" --role "Helper" --tools "do_thing,check_thing"

# Install a local bundle
python community/shared/scripts/install_bundle.py my_bundle

# Install from GitHub
python community/shared/scripts/install_bundle.py \
  --from-git https://github.com/user/hp-bundle-name

# Dry run (preview without changes)
python community/shared/scripts/install_bundle.py my_bundle --dry-run

# Uninstall
python community/shared/scripts/install_bundle.py --uninstall my_bundle
```

---

## End-to-End Flow

```
generate_bundle.py       →  Scaffold bundle files + allocate port
  ↓
Edit mcp_server/app.py   →  Implement tool handlers
Edit persona_agent.json  →  Customize system prompt and tools
  ↓
install_bundle.py        →  Entry point + YAML config + .hpersona
  ↓
server_manager.install() →  Start uvicorn → health check → tool discovery
  ↓
POST /persona/import     →  Import .hpersona into HomePilot
  ↓
Context Forge            →  Tools registered, virtual server prefix matched
  ↓
Persona is live          →  Users can interact with persona + MCP tools
```
