# Expert Module (Local-First Orchestration)

This folder contains the **Expert module** for HomePilot, designed as a local-first AI orchestration system with optional remote GPU escalation.

## Goals

- Run reliably with **no dependency on external paid APIs**.
- Keep local inference as the default path (privacy, cost control, offline readiness).
- Support optional remote acceleration (vLLM/OpenAI-compatible endpoint) for harder tasks.
- Provide building blocks for tool use, memory, evals, and reliability feedback loops.

---

## Current Architecture

```txt
UI (Expert.tsx)
  -> expertApi.ts
  -> Backend /v1/expert/*

Frontend Expert Core (src/expert)
  -> ExpertRouter
      -> Policies (mode + complexity + reliability)
      -> Providers (Local, Remote)
      -> Tool Registry (budgeted)
      -> Memory Store (session recall/append)
      -> Eval Recorder (per-run scoring)
      -> Reliability Tracker (success/latency snapshots)
```

### Frontend core (`expert/frontend/src/expert`)

- `router.ts`
  - Main orchestration entrypoint for local/remote execution.
  - Supports `single-pass`, `expert-thinking`, and `heavy-multi-pass` strategies.
  - Applies memory recall + tool loop context + eval and reliability recording.
- `policies.ts`
  - Routing decisions by mode (`auto|fast|expert|heavy|beta`), complexity, budget, provider health, and reliability stats.
- `providers/local.ts`
  - Local provider adapter (Ollama/OpenAI-compatible API).
- `providers/remote.ts`
  - Optional remote provider adapter (vLLM/OpenAI-compatible API).
- `tools/*`
  - Tool contracts + registry + built-in simulated tools (`web_search`, `retrieval`, `code_exec`, `model_compare`).
- `memory/store.ts`
  - `MemoryStore` abstraction and in-memory implementation.
- `evals/harness.ts`
  - `EvalRecorder` abstraction and in-memory baseline scorer.
- `reliability/metrics.ts`
  - Provider-level success and latency snapshot tracking.

### Backend core (`expert/backend/app/expert`)

- Existing backend endpoints remain stable:
  - `GET /v1/expert/info`
  - `POST /v1/expert/chat`
  - `POST /v1/expert/stream`
  - `POST /v1/expert/route`
  - `POST /v1/expert/ollabridge/chat/completions` (OllaBridge/OpenAI-compatible adapter)
  - `POST /v1/expert/persona/draft` (generate persona draft payload for HomePilot)
  - `GET /v1/expert/readiness` (environment/config readiness report for prod gating)

No destructive backend behavior changes are required for this documentation update.

Additional production scaffolding modules are available under `expert/backend/app/expert/`:
- `mcp_tools.py` (real MCP HTTP tool adapters with call budgets)
- `persistent_memory.py` (sqlite memory with basic PII redaction)
- `safety_policy.py` (prompt safety guardrail decisions)
- `observability.py` (SLO monitor snapshotting)
- `eval_bench.py` (eval scoring + regression gate helpers)

---

## Environment Variables

### Local inference

- `VITE_LOCAL_LLM_URL` (default `http://localhost:11434/v1`)
- `VITE_LOCAL_LLM_MODEL` (default `llama3.1:8b`)

### Remote inference (optional)

- `VITE_REMOTE_LLM_URL` (empty disables remote path)
- `VITE_REMOTE_LLM_API_KEY` (optional)
- `VITE_REMOTE_LLM_MODEL` (default `Qwen/QwQ-32B`)

---

## Operational Model

- **Default:** Local provider
- **Escalation:** Remote provider when policy allows (mode + complexity + budget + reliability)
- **Fallback:** Local when remote unavailable or blocked by policy
- **Additive path:** New services can be introduced without replacing current endpoints

---

## What is “production-ready” here?

The module is designed to become production-ready in stages:

1. Stable local-only baseline
2. Optional remote GPU acceleration
3. Real MCP integrations for tool calls
4. Durable memory persistence
5. Eval-driven routing improvements

See `expert/MIGRATION_PLAN_PREPROD.md` for the full additive rollout sequence.

---

## Test Status (Backend Python Expert)

Backend Python unit coverage for this Expert module now exists at:

- `expert/backend/tests/test_expert_module.py`

Covered checks:

- Complexity scoring + provider selection behavior (`app.expert.router`)
- Message assembly (`build_messages`)
- Think pipeline step outputs (`app.expert.thinking`)
- Heavy pipeline correction behavior (`app.expert.heavy`)

---

## Gap Coverage Matrix

This module now includes minimum viable coverage for the previously identified critical gaps:

1. **Tool layer**  
   Covered by `tools/types.ts`, `tools/registry.ts`, and `tools/builtin.ts`, plus tool loop integration in `router.ts`.
2. **Memory layer**  
   Covered by `memory/store.ts` and session recall/append integration in `router.ts` via `sessionId`.
3. **Eval/reliability layer**  
   Covered by `evals/harness.ts` and `reliability/metrics.ts`, with policy input integration in `policies.ts`.
4. **Adaptive routing improvements**  
   Covered by `policies.ts` reliability-aware decisions and `router.ts` feedback recording.

These are **foundational** layers (not full enterprise implementations) and are intentionally designed so each piece can be replaced by production services without destructive changes.


See also `expert/STABILITY_SAFETY_REVIEW.md` for a full hardening review and production safety checklist.

See `expert/RESEARCHER_FEASIBILITY.md` for a dedicated Researcher-agent feasibility and rollout guide.

See `expert/INSTITUTE_SCALABLE_BACKEND_BLUEPRINT.md` for the long-range institute backend architecture plan.

See `expert/SPACE_AUTONOMY_EVOLUTION_ROADMAP.md` for the long-term autonomous space-AI and controlled self-evolution roadmap.

See `expert/PRODUCTION_READINESS_SUMMARY.md` for the current production-parity status and required next steps.

See `expert/MCP_SERVERS_PRODUCTION_LIST.md` for the prioritized MCP servers/tools required for production.
