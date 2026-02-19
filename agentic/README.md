# HomePilot Agentic Suite

This folder is **additive-only** and intentionally isolated from the core
HomePilot runtime. It provides a production-oriented **reference
implementation** for integrating:

* **MCP servers** (tools — email, calendar, GitHub, Slack, etc.)
* **A2A agents** (agent-to-agent — orchestrators, specialists)
* **MCP Context Forge** (registry, governance, virtual servers)

## Architecture overview

```
agentic/
├── suite/           # Profile definitions (home, pro, addons)
├── forge/           # Context Forge templates + seed scripts
│   ├── templates/   #   gateways.yaml, virtual_servers.yaml, a2a_agents.yaml
│   └── seed/        #   seed_all.py, seed_lib.py
├── integrations/    # MCP server + A2A agent implementations
│   ├── mcp/         #   15 MCP servers (personal, knowledge, gmail, etc.)
│   └── a2a/         #   2 A2A agents (everyday-assistant, chief-of-staff)
├── ops/             # Docker Compose + Dockerfiles
│   └── compose/     #   docker-compose.yml, dockerfiles/
└── specs/           # Positioning, wizard flows
    ├── launch/      #   positioning.md, why-homepilot.md
    └── wizard/      #   home-flow.md, pro-flow.md
```

## What ships by default

See `suite/`:

| File | Profile | Description |
|------|---------|-------------|
| `default_home.yaml` | Home | Personal assistant tools + Everyday Assistant agent |
| `default_pro.yaml` | Pro | Read-only suite + Decision Room + Chief of Staff agent |
| `optional_addons.yaml` | — | Calendar, Email, Jira, Slack (opt-in) |

## Port allocation

| Range | Service | Examples |
|-------|---------|----------|
| 9101–9105 | Core MCP servers | Personal Assistant, Knowledge, Decision, Briefing, Web Search |
| 9110–9113 | Local MCP servers | Notes, Projects, Web Fetch, Shell Safe |
| 9114–9117 | Communication MCP | Gmail, Google Calendar, Microsoft Graph, Slack |
| 9118–9119 | Dev & Knowledge MCP | GitHub, Notion |
| 9201–9202 | A2A agents | Everyday Assistant, Chief of Staff |
| 4444 | MCP Context Forge | Governance + registry |

## Bundled personas

Each MCP server maps to a pre-built persona in `community/sample/`:

| Persona | Role | MCP Server | Port |
|---------|------|-----------|------|
| Nora Whitfield | Memory Keeper | mcp-local-notes | 9110 |
| Felix Navarro | Project Navigator | mcp-local-projects | 9111 |
| Maya Chen | Web Researcher | mcp-web | 9112 |
| Soren Lindqvist | Automation Operator | mcp-shell-safe | 9113 |
| Priya Sharma | Email Manager | mcp-gmail | 9114 |
| Luca Moretti | Calendar Strategist | mcp-google-calendar | 9115 |
| Diana Brooks | Office Navigator | mcp-microsoft-graph | 9116 |
| Kai Tanaka | Comms Specialist | mcp-slack | 9117 |
| Raven Okafor | Dev Workflow Assistant | mcp-github | 9118 |
| Elena Voss | Knowledge Curator | mcp-notion | 9119 |
| Atlas | Research Assistant | (core) | 9101 |
| Scarlett | Executive Secretary | (core) | 9102 |

## Quick start (dev)

1. Start Context Forge (separately)
2. Start the sample MCP + A2A services:

```bash
cd agentic/ops/compose
docker compose up -d
```

3. Seed Context Forge:

```bash
python agentic/forge/seed/seed_all.py
```

4. Open HomePilot and create an **Agent** project.

> The wizard loads `suite/*.yaml` via the HomePilot backend and lets you pick
> a **Tool Bundle** (Virtual Server) + optional A2A agents.

## Installing personas

### From the Community Gallery (recommended)

1. Open HomePilot → **Shared with me** tab
2. Browse the gallery — all 12 bundled personas are available
3. Click **Install** on any persona → 3-step wizard handles the rest

### From a `.hpersona` file

1. Open HomePilot → **My Projects** → **Import**
2. Drag in the `.hpersona` file (from `community/sample/` or a download)
3. Follow the install wizard

### CLI (advanced)

```bash
# Validate a package
python community/scripts/process_submission.py validate community/sample/nora.hpersona

# Extract preview + metadata
python community/scripts/process_submission.py extract community/sample/nora.hpersona /tmp/out
```

## Publishing workflows

Two complementary GitHub Actions workflows manage the persona gallery:

### `persona-seed.yml` — Bundled personas (auto-sync)

Handles the 12 personas that ship with HomePilot. Triggers:
- **On every GitHub Release** — gallery is always current
- **On push to `master`/`main`** when `community/sample/` changes
- **Manual dispatch** from the Actions tab

Flow: scan `community/sample/*.hpersona` → validate → upload to R2 →
rebuild `registry.json` (preserving third-party entries) → purge cache.

### `persona-publish.yml` — Third-party submissions

For external developers contributing their own personas:
1. Create a GitHub Issue using the **Persona Submission** template
2. Attach the `.hpersona` ZIP
3. A maintainer adds the `persona-approved` label
4. The workflow validates, uploads to R2, creates a GitHub Release, and closes the issue

### Data source priority

The backend (`backend/app/community.py`) serves personas with three fallbacks:

1. **Cloudflare Worker** (production) — edge-cached, global, no rate limits
2. **R2 direct** (development) — raw bucket access, rate-limited
3. **Local samples** (always-on) — `community/sample/` served from disk

If the Cloudflare Worker is unreachable, the gallery still works with local files.

## Required GitHub secrets

| Secret | Purpose |
|--------|---------|
| `R2_ACCESS_KEY_ID` | R2 API token Access Key ID |
| `R2_SECRET_ACCESS_KEY` | R2 API token Secret Access Key |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |
| `R2_BUCKET_NAME` | R2 bucket name (e.g. `homepilot`) |
| `CLOUDFLARE_API_TOKEN` | (optional) Cache purge token |
