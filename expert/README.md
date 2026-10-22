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
| `fast` | single-pass + tool loop | lowest latency, local-first; the model may search or read as it answers |
| `think` / `expert` | expert-thinking | analyze → plan → solve (the solve step has the tool loop) |
| `heavy` | heavy-multi-pass | research (with tools) → reason → synthesize → validate; escalates to the strongest model on the connection |
| `deep` (Deep research) | deep-agent job | plan → one sub-agent per item with tools → cited report; offered only with a high-end model |
| `auto` | policy-resolved | deterministic selection by complexity/health/budget |

### What every turn gets (the ChatGPT-shaped turn)

- **Conversation history** as role-tagged turns in every pipeline step, within a window
  (`EXPERT_HISTORY_MAX_TURNS` 12 / `EXPERT_HISTORY_MAX_CHARS` 16000). Older turns are not
  dropped: `compaction.py` summarizes them into a running note once per overflow, cached per
  session (`EXPERT_COMPACTION_ENABLED`, `EXPERT_COMPACTION_MAX_TOKENS`).
- **Tools in the loop** (`tools.py`, `tool_loop.py`): HomePilot's own MCP servers — web search,
  page fetch, workspace and notes search — discovered over JSON-RPC and offered in OpenAI
  function-calling shape. Up to `EXPERT_TOOL_MAX_ROUNDS` (4) rounds, then a forced answer;
  web results come back numbered so the answer cites `[n]` and the UI links them; once results
  exist, a citation note joins that round's system prompt (small models follow it, the one-line
  mention in the tools note alone was not enough). Models that reject `tools` are remembered
  (`EXPERT_CAPABILITY_NEGATIVE_TTL_S`, 1 h; a success for a month) and answer without them — in
  the research modes HomePilot then runs the web search itself and hands over the results.
  `EXPERT_TOOL_SERVERS` lists the
  `/rpc` URLs (Context Forge's `/rpc` can be added), `EXPERT_TOOL_ALLOWLIST` the native names.
  The chat's "Search the web" switch sends `feature_hints.webSearch = "force"`: the search
  runs first, before the model is asked.
- **Streaming** (`POST /v1/expert/stream`): `meta`, `step` (with `role: work|answer`),
  `step_end`, `tool` (start/end), `sources`, `reset`, `notice`, `verdict`, `final_answer`,
  `done`, plain `data:` tokens. A `: keep-alive` comment goes out after `EXPERT_SSE_HEARTBEAT_S`
  (10 s) of silence, so a long first model call never looks like a dead connection; the
  pipeline runs as its own task and is cancelled the moment the reader disconnects. The sync
  `POST /v1/expert/chat` returns `tool_trace`, `sources`, `verdict` and `model_escalated`
  alongside the answer.
- **Show reasoning** (chat settings, on by default): Expert and Heavy stream each stage's
  reasoning into the work card as it is written, the way ChatGPT and Claude show their
  thinking; off, the card names the stages and keeps each output one click away. Deep
  research shows its plan and items either way.
- **Queue and usage meter** (`providers.py`): requests beyond the in-flight limit wait in a
  priority queue per endpoint — a person's turn ahead of Deep research's background calls. A
  rate limit is waited out for up to `EXPERT_PROVIDER_WAIT_S` (90 s) in a chat turn and
  `EXPERT_PROVIDER_BACKGROUND_WAIT_S` (300 s) in a job, and the chat shows "The model provider
  is busy; retrying in N s…" (a `wait` stream event) instead of a silent pause. The meter learns
  each endpoint's limit: on a 429 the cap becomes the successes of the last
  `EXPERT_PROVIDER_WINDOW_S` (60 s), a token bucket then spreads requests at that rate, and the
  cap grows by one after three quiet windows. `GET /v1/expert/usage` shows queue, cap and counts.
- **Adaptive pacing, retries, degradation** (`providers.py`, `heavy.py`, `deep.py`): one
  OpenAI-compatible endpoint gets at most `EXPERT_PROVIDER_MAX_INFLIGHT` (2) requests at a time
  (a semaphore per base URL) and a gap between request starts. The gap starts at
  `EXPERT_PROVIDER_MIN_INTERVAL_S` (1 s), doubles on every rate limit up to
  `EXPERT_PROVIDER_MAX_INTERVAL_S` (15 s) — every caller to that endpoint waits out the
  cooldown — and shrinks back 15 % per success. A 429, a body saying "rate limit", or a
  502/503/504 is retried `EXPERT_PROVIDER_RETRIES` (4) times with exponential backoff and
  jitter (about 2, 4, 8, 16 s; `Retry-After` is a floor), always before the first token. A stage
  that still fails is skipped and named: Heavy answers from its reasoning or unvalidated, Deep
  research marks the item and goes on, a failed writer returns the findings. Deep research on a
  greeting answers in one call.
- **Operator instructions**: `system_prompt` reaches think and heavy too (added to each
  agent's role prompt). Heavy returns the validator's **verdict** (`validated` / `corrected` /
  `reviewed`); a correction replaces the answer, in the stream as well.
- **One model**: the model chosen in the chat is the one every mode uses, Deep research
  included. Escalation is off by default; with `EXPERT_HEAVY_ESCALATE=1`, Heavy runs on the
  strongest model of the same connection when it is a clear step up (`capability.py`), and
  says so in a notice.

### Effort, projects, verdicts (Phase 1)

- **Adaptive effort** (`policies.effort_for`): the mode is a ceiling, the request decides.
  A greeting is one generation in every mode; Expert writes a visible analysis and answers
  from it (two calls), and adds a plan only from complexity
  `EXPERT_THINK_PLAN_MIN_COMPLEXITY` (4); Heavy runs its research agent only from
  `EXPERT_HEAVY_RESEARCH_MIN_COMPLEXITY` (5) or when a web search was asked for — otherwise
  the reasoner has the tools itself. Per-mode profiles: `EXPERT_{FAST,THINK,HEAVY}_{TEMPERATURE,
  MAX_TOKENS,TOOL_ROUNDS}`. Responses and the stream's `meta` carry `effort` (level and why).
- **Project context**: the request's `project` (id, name, instructions, document_count) folds the
  instructions into every step's system prompt and, inside HomePilot, exposes the project's
  documents as the `project_search` tool (the backend's own retrieval), searched first when the
  project has documents. The trace shows "Using project X".
- **Structured verdict**: the validator answers JSON (`verdict`, `issues`, `corrected_answer`,
  `method`, `limitations`); the older prose shape still parses. A correction without text, or a
  "validated" with a high-severity issue, becomes `needs_review`. The stream's `verdict` event
  and `/chat`'s `verdict_detail` carry the detail.
- **Durable facts** (`state_store.py`, `<DATA_DIR>/expert_state.sqlite` or `EXPERT_STATE_DB`):
  which models reject the tools field (learned, or measured by `POST /v1/expert/capabilities`
  with `probe: true` — one tiny tool call and one JSON instruction, kept `EXPERT_CAPABILITY_TTL_S`),
  and every Deep research job with its numbered events, so `GET /deep/{id}/events?after=<seq>`
  (or `Last-Event-ID`) resumes without duplicates and a finished report survives a restart.
- **Evaluation against the real stack**: `backend/.venv/bin/python scripts/eval-expert.py
  --backend http://127.0.0.1:8002 [--provider openai_compat --base-url … --model … --api-key-env …]`
  runs the roadmap's ten scenarios (greeting, follow-up context, coding, tools, sources,
  Heavy validation, Deep research resume, cancellation, compaction) and prints a table;
  `--json report.json` keeps the details. It needs a model, so it is not part of CI.

### Capabilities and Deep research

`POST /v1/expert/capabilities` measures the connection: Ollama's `/api/tags` (parameter
counts) or a gateway's `/models` (names such as `gemma4-31b`, `gpt-oss-120b`, `claude`,
`gemini`, `glm-5`, `kimi`). Tiers: `high` (frontier family or ≥ `EXPERT_DEEP_MIN_PARAMS_B`
= 20B), `medium` (≥ 7B), `low`. Deep research is offered when the **selected** model is `high`
(`EXPERT_DEEP_RESEARCH=auto`; `always` / `off` override) and runs on it. A model that cannot
call tools is still fine: HomePilot runs the searches and hands it the results. The gate
re-reads the connection on request and `probe: true` measures the model itself. See also
`docs/Deep-Research.md`.

`POST /v1/expert/deep` starts a background job (`deep.py`): the planner writes 2–5
sub-questions, a sub-agent researches each with the tool loop (`EXPERT_DEEP_ROUNDS_PER_ITEM`),
a writer produces the cited report, all within `EXPERT_DEEP_TIME_BUDGET_S` (300 s). Follow it
at `GET /v1/expert/deep/{job_id}/events` (SSE, replays from the start), snapshot at
`GET /v1/expert/deep/{job_id}`, cancel with `DELETE`. No extra dependency: the harness is the
same tool loop plus a plan, a shared source book and a time budget.

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
