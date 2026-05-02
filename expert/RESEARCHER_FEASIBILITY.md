# Researcher Agent Feasibility (Expert Stack)

## Verdict

**Yes — feasible now as v1, scalable to enterprise with MCP + safety hardening.**

---

## Alignment to current infrastructure

Current backend/frontend stack already provides:

- mode-based orchestration (`fast`, `think`, `heavy`, `auto`)
- provider routing with local-first behavior
- fallback metadata and latency reporting
- tool intent layer that can map to MCP servers
- memory and eval scaffolding

This is enough for a practical researcher assistant in preprod.

---

## v1 researcher flow

1. Plan research questions.
2. Execute retrieval/web tool calls with bounded budgets.
3. Synthesize findings into structured output.
4. Run critique/validation pass.
5. Persist session context for follow-up.

---

## What is required for production researcher quality

### P0
- Real MCP retrieval/search integrations
- citation/provenance validation
- persistent memory governance
- safety policy for tool outputs and prompt injection resistance
- eval gates for factuality/citation quality

### P1
- contradiction detection across sources
- confidence scoring by section
- report templates by audience (engineering/executive/research)
