# MCP Servers / Tools for Expert Production

_Date updated: 2026-04-23_

## Alignment note

This priority list aligns with current backend catalog definitions under:
- `expert/backend/app/expert/mcp_catalog.py`
- `expert/backend/app/expert/mcp_tools.py`

Current tool intent mapping in Expert:

- `web_search` -> `mcp-web-search`
- `retrieval` -> `mcp-doc-retrieval`
- `code_exec` -> `mcp-code-sandbox`
- `model_compare` -> `mcp-eval-runner` (+ optional `mcp-cost-router`)

---

## Priority order

1. `mcp-web-search` (grounded web retrieval)
2. `mcp-doc-retrieval` (private knowledge/RAG)
3. `mcp-code-sandbox` (safe execution)
4. `mcp-citation-provenance` (claim/source tracing)
5. `mcp-memory-store` (durable memory)
6. `mcp-safety-policy` (policy checks)
7. `mcp-eval-runner` (evaluation automation)
8. `mcp-observability` (metrics/traces/events)
9. `mcp-cost-router` (budget routing)
10. `mcp-job-orchestrator` (long jobs)

---

## Minimal enterprise set (first 5)

1. `mcp-web-search`
2. `mcp-doc-retrieval`
3. `mcp-memory-store`
4. `mcp-safety-policy`
5. `mcp-observability`

This set provides practical production value while preserving local-first behavior.
