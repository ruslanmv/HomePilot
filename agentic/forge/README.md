# Context Forge assets

This folder contains:

* `templates/` – declarative YAML templates (gateways, virtual servers, agents)
* `seed/` – scripts that register these templates into a running MCP Context Forge
* `examples/` – curl scripts and demo flows

All seed scripts are safe to re-run (idempotent best-effort).

## Prereqs

* MCP Context Forge running (default: http://localhost:4444)
* Basic auth configured (default: admin / changeme)
