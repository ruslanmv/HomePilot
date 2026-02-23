# HomePilot MCP Server: Inventory

Read-only inventory service that exposes project/persona assets (photos,
outfits, documents) to agents via the MCP JSON-RPC protocol.

## Tools

| Tool | Purpose |
|------|---------|
| `hp.inventory.list_categories` | List Outfits / Photos / Documents with counts and tag breakdowns |
| `hp.inventory.search` | Search items by query text, type, tags; supports `return_count_only` |
| `hp.inventory.get` | Get full metadata for a single item by server-issued ID |
| `hp.inventory.resolve_media` | Resolve an asset ID to a safe `/files/...` URL |

## How It Works

The server reads directly from the existing HomePilot legacy storage:

```
UPLOAD_DIR/
  projects_metadata.json       <-- persona_appearance metadata
  homepilot.db                 <-- file_assets table (documents)
  projects/<id>/persona/appearance/*  <-- committed images
```

It builds an in-memory inventory on each request (stateless) and returns
only server-issued IDs. Agents must call `resolve_media` to get a URL,
which prevents hallucinated asset references from rendering.

## Scope Object

Every tool requires a `scope` parameter:

```json
{
  "kind": "persona",
  "project_id": "<uuid>",
  "persona_id": "persona:<uuid>"
}
```

- `kind`: `"persona"` or `"project"`
- `project_id`: UUID of the HomePilot project (required)
- `persona_id`: Required when `kind=persona`

## Sensitivity Gating

All tools accept `sensitivity_max` (`safe` | `sensitive` | `explicit`).
Items above the ceiling are silently filtered out.

Default: `safe` (configurable via `INVENTORY_DEFAULT_SENSITIVITY_MAX`).

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `UPLOAD_DIR` | auto-detect | Path to HomePilot uploads root |
| `BACKEND_BASE_URL` | `http://localhost:8000` | Used to build `/files/...` URLs |
| `INVENTORY_DEFAULT_SENSITIVITY_MAX` | `safe` | Default sensitivity ceiling |
| `INVENTORY_ALLOW_PROJECT_IDS` | (empty) | Optional allowlist of project UUIDs |

## Running

```bash
# Local development
export UPLOAD_DIR=backend/data/uploads
uvicorn agentic.integrations.mcp.inventory_server:app --port 9120

# Docker
docker compose -f docker-compose.mcp.yml up inventory
```

## Health Check

```bash
curl http://localhost:9120/health
```

## Example: Agent Workflow

```
1. Agent calls hp.inventory.search(scope, query="lingerie", types=["outfit"])
   -> Returns: [{id: "outfit_abc123...", label: "Lingerie", ...}]

2. Agent calls hp.inventory.get(scope, id="outfit_abc123...")
   -> Returns: {item: {asset_ids: ["img_def456..."], ...}}

3. Agent calls hp.inventory.resolve_media(scope, asset_id="img_def456...")
   -> Returns: {url: "http://localhost:8000/files/projects/.../outfit_lingerie.png"}

4. Backend returns structured media.images[] with the resolved URL
   -> Frontend renders the image (no hallucinated URLs possible)
```

## Safety

- Never exposes absolute disk paths
- Rejects unknown/hallucinated IDs with `ITEM_NOT_FOUND`
- Enforces sensitivity gating on every tool call
- Read-only: no write tools (add later behind `inventory:write` capability)
- Path traversal prevention (`..` segments rejected)
