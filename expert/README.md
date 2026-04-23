# 🌐 Expert Module — Enterprise Local-First AI for HomePilot

> Build your own sovereign AI platform (ChatGPT/Claude/Gemini/Grok-style experience) on local infrastructure first, with optional rented GPU burst when policy allows.

---

## 🚀 Vision

The Expert subsystem is designed for organizations that want:

- 🔒 **Data sovereignty** (keep prompts/inference local by default)
- 💸 **Cost control** (remote GPU is optional, policy-gated)
- 🧠 **High-quality reasoning** (fast / think / heavy pipelines)
- 🛡️ **Reliability** (timeouts, deterministic fallback, observability)
- 🏢 **Enterprise readiness** (memory, tools, safety, evals, readiness gates)

---

## 🧭 Core operating principle

1. **Local-first inference is default**
2. **Remote/rented GPU is escalation path, not baseline**
3. **Backend is single source of truth** for routing and execution decisions
4. **Fallback to local must exist** whenever remote fails/unavailable

---

## 🏗️ Architecture (high-level)

```txt
┌──────────────────────────────────────────────────────────────────┐
│                        Frontend (UI)                            │
│ mode selector • streaming renderer • notices • trace panel      │
└──────────────────────────────┬───────────────────────────────────┘
                               │ API request
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│           Backend Expert Router (authoritative brain)           │
│ mode resolution • policy • provider choice • strategy selection │
└───────────────┬───────────────────────────────┬──────────────────┘
                │                               │
                ▼                               ▼
      ┌───────────────────────┐        ┌──────────────────────────┐
      │ Thinking Pipelines    │        │ Runtime Services         │
      │ fast / think / heavy  │        │ tools • memory • evals   │
      └────────────┬──────────┘        │ safety • observability   │
                   │                   └──────────────┬───────────┘
                   └──────────────────────┬────────────┘
                                          ▼
                             ┌──────────────────────────┐
                             │ Provider Abstraction     │
                             │ local / remote / burst   │
                             └─────────────┬────────────┘
                                           │
                              ┌────────────┴────────────┐
                              ▼                         ▼
                    Local GPU/CPU (Ollama)     Remote / Rented GPU
```

---

## ⚙️ Modes and strategies

| Mode | Strategy | Typical intent |
|---|---|---|
| `fast` | single-pass | lowest latency, local-first |
| `think` / `expert` | expert-thinking | analysis + planning + answer |
| `heavy` | heavy-multi-pass | strongest reasoning path for hard tasks |
| `auto` | policy-resolved | deterministic selection by complexity/health/budget |
| `beta` | experimental branch | controlled experiments, never silent replacement |

---

## 🔌 MCP servers and tools (what Expert uses)

Expert is designed to be **tool-augmented** through MCP. There are two layers:

### 1) Tool intents currently used by Expert orchestration
- `web_search`
- `retrieval`
- `code_exec`
- `model_compare`

### 2) MCP server mapping (production target)

```txt
web_search    -> mcp-web-search
retrieval     -> mcp-doc-retrieval
code_exec     -> mcp-code-sandbox
model_compare -> mcp-eval-runner (and cost awareness via mcp-cost-router)
```

### Priority MCP server stack

- **P0** (must-have):
  - `mcp-web-search`
  - `mcp-doc-retrieval`
  - `mcp-code-sandbox`
  - `mcp-citation-provenance`
  - `mcp-memory-store`
- **P1**:
  - `mcp-safety-policy`
  - `mcp-eval-runner`
  - `mcp-observability`
- **P2**:
  - `mcp-cost-router`
  - `mcp-job-orchestrator`

For the full server API expectations and priority rationale, see [`MCP_SERVERS_PRODUCTION_LIST.md`](./MCP_SERVERS_PRODUCTION_LIST.md).

---

## 🪜 End-to-end lifecycle (step-by-step)

```txt
[1] User selects mode + sends prompt
      ↓
[2] Backend resolves mode -> concrete strategy
      ↓
[3] Policy evaluates complexity + health + budget + availability
      ↓
[4] Provider selected (local-first, remote only if justified)
      ↓
[5] Pipeline executes (fast / think / heavy)
      ↓
[6] Optional tools + memory operations under strict limits
      ↓
[7] Response returns with metadata:
      strategy_used, fallback_applied, notices, latency_ms
      ↓
[8] Telemetry + eval logs emitted
```

---

## 🧱 Deployment tiers

- **Tier 0 — Local only:** fully sovereign, offline-capable baseline
- **Tier 1 — Local + guarded remote burst:** recommended enterprise hybrid
- **Tier 2 — Hybrid scale:** local clusters + rented pools + SLO/budget governance

---

## 📚 Complete documentation index (all Expert `.md` files)

> Every Markdown file in `expert/` is listed here for complete onboarding and discoverability.

1. 📘 [`README.md`](./README.md) — Master overview, principles, and navigation.
2. 🗺️ [`DOCUMENTATION_GUIDE.md`](./DOCUMENTATION_GUIDE.md) — Role-based reading paths for humans and AI agents.
3. 🏢 [`ENTERPRISE_LOCAL_ARCHITECTURE.md`](./ENTERPRISE_LOCAL_ARCHITECTURE.md) — Enterprise architecture, operations, and governance blueprint.
4. 🔍 [`EXPERT_MODE_REVIEW.md`](./EXPERT_MODE_REVIEW.md) — Production gap analysis and migration phases.
5. ✅ [`PRODUCTION_READINESS_SUMMARY.md`](./PRODUCTION_READINESS_SUMMARY.md) — Current readiness snapshot and gates.
6. 🛣️ [`MIGRATION_PLAN_PREPROD.md`](./MIGRATION_PLAN_PREPROD.md) — Step-by-step preproduction migration plan.
7. 🔐 [`STABILITY_SAFETY_REVIEW.md`](./STABILITY_SAFETY_REVIEW.md) — Safety and stability hardening review.
8. 🔧 [`MCP_SERVERS_PRODUCTION_LIST.md`](./MCP_SERVERS_PRODUCTION_LIST.md) — MCP server priorities and required APIs.
9. 🧪 [`RESEARCHER_FEASIBILITY.md`](./RESEARCHER_FEASIBILITY.md) — Researcher-agent feasibility and rollout notes.
10. 🏛️ [`INSTITUTE_SCALABLE_BACKEND_BLUEPRINT.md`](./INSTITUTE_SCALABLE_BACKEND_BLUEPRINT.md) — Scalable backend blueprint for institute-level usage.
11. 🌌 [`SPACE_AUTONOMY_EVOLUTION_ROADMAP.md`](./SPACE_AUTONOMY_EVOLUTION_ROADMAP.md) — Long-range autonomy evolution roadmap.
12. 🩹 [`INTEGRATION_PATCH.md`](./INTEGRATION_PATCH.md) — Integration patch notes and guidance.

---

## 🧪 Quick verification commands

```bash
PYTHONPATH=/workspace/HomePilot/expert/backend \
pytest -q expert/backend/tests/test_expert_module.py \
          expert/backend/tests/test_expert_ollabridge_routes.py \
          expert/backend/tests/test_expert_policies.py
```

### 🔬 Preprod sandbox (safe, isolated ports)

Use these targets to validate Expert in preprod **without touching current prod ports**:

```bash
make start-preprod
# Backend:  http://localhost:18000
# Frontend: http://localhost:13000
# ComfyUI:  http://localhost:18188
```

In another terminal:

```bash
make test-preprod-expert
```

This verifies `/v1/expert/info` and `/v1/expert/chat` response contracts including strategy/fallback metadata.

---

## 🏁 Enterprise statement

HomePilot Expert is built to deliver a world-class assistant experience with **local sovereignty first**, **truthful operational behavior**, and **controlled remote scaling**.

**Short product stance:**

> Local-first, expert when needed, heavy only when justified, remote only when policy allows.
