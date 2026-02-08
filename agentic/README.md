# HomePilot Agentic Suite (Additive)

This folder is **additive-only** and intentionally isolated from the core
HomePilot runtime.

It provides a production-oriented **reference implementation** for integrating:

* **MCP servers** (tools)
* **A2A agents** (agent-to-agent)
* **MCP Context Forge** (registry, governance, virtual servers)

## What ships by default

See `suite/`:

* `default_home.yaml` – defaults for personal/home usage
* `default_pro.yaml` – defaults for professional/enterprise usage
* `optional_addons.yaml` – optional installs for later

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

> The wizard will load `suite/*.yaml` via the HomePilot backend and let you pick
> a **Tool Bundle** (Virtual Server) + optional A2A agents.
