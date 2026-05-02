# Enterprise Local Architecture — Expert Mode

This document is the technical blueprint for running Expert as an enterprise-grade, local-first AI platform with optional rented GPU capacity.

_Alignment checked against current frontend/backend structure: 2026-04-23._

---

## 1) Design objectives

### Primary objectives

1. **Sovereignty:** keep sensitive data and inference local whenever possible.
2. **Reliability:** always return a response via deterministic fallback.
3. **Cost control:** treat rented GPU as controlled burst capacity, not default.
4. **Quality scaling:** route harder tasks to stronger pipelines/providers when justified.
5. **Operational clarity:** emit enough metadata for auditing and UX honesty.

### Non-goals

- Blindly maximizing model size/cost on every request.
- Hiding fallback/provider behavior from users/operators.

---

## 2) Reference runtime architecture

```txt
                             ┌─────────────────────┐
                             │     End User        │
                             └──────────┬──────────┘
                                        │
                                        ▼
                         ┌──────────────────────────────┐
                         │  Frontend Chat / Expert UI   │
                         │  (mode selector + renderer)  │
                         └──────────────┬───────────────┘
                                        │ HTTPS
                                        ▼
               ┌────────────────────────────────────────────────┐
               │      Backend Expert API (FastAPI routes)      │
               │ /v1/expert/chat, /stream, /route, /readiness  │
               └───────────────────┬────────────────────────────┘
                                   │
                     ┌─────────────┴─────────────┐
                     ▼                           ▼
        ┌───────────────────────────┐   ┌──────────────────────────┐
        │ Policy + Mode Resolution  │   │  Runtime Services        │
        │ complexity, budget, health│   │  memory/tools/evals/safe │
        └──────────────┬────────────┘   └──────────────┬───────────┘
                       │                               │
                       └──────────────┬────────────────┘
                                      ▼
                         ┌────────────────────────┐
                         │ Provider Abstraction   │
                         │ local / remote / burst │
                         └──────────┬─────────────┘
                                    │
             ┌──────────────────────┴──────────────────────┐
             ▼                                             ▼
┌──────────────────────────────┐              ┌──────────────────────────────┐
│ Local Inference Infrastructure│             │ Remote Burst Infrastructure   │
│ Ollama + local GPU/CPU        │             │ rented GPU / managed endpoint │
└──────────────────────────────┘              └──────────────────────────────┘
```

---

## 3) Request execution flow (step-by-step)

### Step 1 — Request ingress
Frontend sends:
- mode
- messages
- session id (optional)
- attachment indicator
- feature hints (optional)

### Step 2 — Mode resolution
Backend resolves requested mode into concrete strategy:
- `fast` → `single-pass`
- `think/expert` → `expert-thinking`
- `heavy` → `heavy-multi-pass`
- `auto` → deterministic selection by complexity thresholds

### Step 3 — Provider decision
Policy evaluates:
- provider health/readiness
- complexity
- budget constraints
- availability

Then selects provider path (local first, remote if justified).

### Step 4 — Pipeline execution
Chosen strategy runs:
- fast: one pass
- think: analysis/plan/solve
- heavy: multi-agent/multi-pass chain

### Step 5 — Tools and memory
If enabled by policy:
- tool loop runs under strict budgets
- session/persistent memory read/write rules applied

### Step 6 — Fallback management
If provider fails or times out:
- local fallback is attempted
- fallback metadata is captured

### Step 7 — Response envelope
Return final text + operational metadata:
- strategy used
- fallback applied
- notices
- latency

### Step 8 — Observability and eval logging
Emit events for dashboards, audits, and regression checks.

---

## 4) Deployment modes

### Mode A — Fully local (baseline)

```txt
Frontend → Backend Expert → Local Provider only
```

Use when:
- strict data residency is required
- no internet is allowed
- cost must be near zero incremental

### Mode B — Local + remote burst (recommended hybrid)

```txt
Frontend → Backend Expert → Local by default
                              └→ Remote burst only on policy-approved tasks
```

Use when:
- enterprise wants local sovereignty plus optional heavy acceleration
- complex workloads need occasional stronger hardware

### Mode C — Local cluster + GPU rental pools (scale)

```txt
Frontend → API Gateway → Expert Router → Local cluster or rented pool
```

Use when:
- multi-team demand
- SLO-driven capacity planning
- formal budget governance

---

## 5) Provider and fallback policy (enterprise stance)

1. **Always verify health before remote preference.**
2. **Timeouts are mandatory for each provider call.**
3. **Fallback to local must be deterministic.**
4. **Fallback events must be visible in response metadata and logs.**
5. **Budget ceilings must prevent runaway remote spend.**

---

## 6) Memory architecture

```txt
                 ┌─────────────────────────────┐
                 │ Conversation Turn           │
                 └──────────────┬──────────────┘
                                │
                                ▼
                 ┌─────────────────────────────┐
                 │ Session Memory              │
                 │ short window + summaries    │
                 └──────────────┬──────────────┘
                                │
                                ▼
                 ┌─────────────────────────────┐
                 │ Persistent Memory           │
                 │ preferences/pinned facts    │
                 └──────────────┬──────────────┘
                                │
                                ▼
                 ┌─────────────────────────────┐
                 │ Redaction + TTL + Audit     │
                 └─────────────────────────────┘
```

Rules:
- Separate session context from long-term memory.
- Apply PII redaction before persistence.
- Enforce retention TTL and compaction policies.

---

## 7) Tooling architecture

Tools should be backend-owned and policy-gated:

- allowlist execution only
- timeout per tool
- max loop count
- per-call audit logs

This avoids uncontrolled autonomous behavior while enabling real augmentation.

---

## 8) Observability model

Minimum per-request record:

- request id
- mode + strategy
- provider requested/used
- fallback flag
- latency
- error class
- tools used
- memory used

Key aggregate metrics:
- p50/p95 latency by mode
- provider failure rate
- fallback rate
- local vs remote traffic split
- heavy mode success ratio

---

## 9) Security and governance checklist

1. Data classification for prompts/responses.
2. Secret management for provider keys.
3. Access control for admin/eval endpoints.
4. Audit trail retention policy.
5. Incident runbook for provider outages and degraded mode.

---

## 10) Migration sequence (practical)

```txt
Phase 1: Contract unification
Phase 2: Backend authority
Phase 3: Frontend simplification
Phase 4: Provider hardening
Phase 5: Tools/memory stabilization
Phase 6: SLO + telemetry gates
```

This order minimizes regression risk while moving quickly toward production.

---

## 11) Enterprise final position

**Recommended product stance:**

> Local-first, expert when needed, heavy only when justified, remote only when policy allows.

This gives the organization a sovereign AI capability comparable in user experience to major platforms, while preserving control over privacy, cost, and reliability.
