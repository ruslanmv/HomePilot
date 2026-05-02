# Expert Mode Review (Frontend + Backend)

**Date:** 2026-04-23
**Status:** Updated to reflect current backend routing metadata, timeout, and fallback instrumentation.

---

## Executive summary

Expert mode in this repository is a **real orchestration layer**, not a cosmetic UI toggle.

It already implements:

- multi-pass reasoning
- provider routing (local vs remote)
- tool hooks
- memory hooks
- evaluation hooks

However, the system currently operates with **dual orchestration layers**:

1. `expert/frontend/src/expert/*` → client-side orchestration
2. `expert/backend/app/expert/*` → service-side orchestration

This creates a **split-brain architecture**, which is the main blocker for production readiness.

---

## Verified behavior

### 1) Frontend expert router is behaviorally real

The frontend router performs:

- mode selection logic (`fast`, `expert`, `heavy`, `auto`, `beta`)
- complexity scoring (heuristics)
- attachment-aware routing
- provider health evaluation
- budget gating

It outputs:

- provider: `local` vs `remote`
- strategy:
  - `single-pass`
  - `expert-thinking`
  - `heavy-multi-pass`

---

### 2) Frontend strategies are materially different

| Mode   | Execution                      |
|--------|--------------------------------|
| Fast   | single-pass                    |
| Expert | analyze → answer               |
| Heavy  | draft → critique → synthesize  |

This is **true orchestration**, not just model switching.

---

### 3) Frontend includes tool + memory + eval hooks

Frontend currently performs:

- tool planning (keyword-based)
- tool execution loops
- session memory recall/write
- evaluation logging
- reliability scoring

⚠️ These are **policy-level responsibilities**, which should not live in frontend.

---

### 4) Backend expert service is also fully capable

Backend already implements:

- routing logic
- provider abstraction
- multi-pass pipelines
- readiness checks
- memory modules
- eval infrastructure

👉 Meaning: backend already has everything needed to be the **single source of truth**.

---

## Strengths

### 1. Real mode semantics

Modes are not fake — they map to real pipelines.

### 2. Hybrid provider model

- local-first
- remote GPU optional
- fallback capability

### 3. Multi-pass reasoning exists

Heavy and Expert already behave like advanced reasoning systems.

### 4. Observability foundation exists

Eval hooks and metrics exist (needs centralization).

### 5. Tool + memory integration exists

Even if immature, the architecture direction is correct.

---

## Gaps and risks

### 1. Split-brain orchestration ❌ (critical)

Frontend and backend both decide:

- routing
- provider
- strategy
- tools
- memory

This creates divergence risk, debugging complexity, and inconsistent behavior.

### 2. Policy logic in frontend ❌

Frontend currently owns:

- provider health decisions
- tool planning
- memory behavior
- eval logging

👉 This is unsafe for production.

### 3. Drift risk between FE and BE ❌

Over time, logic diverges and behavior becomes unpredictable.

### 4. Tool planner is heuristic ⚠️

- keyword-based
- limited context awareness
- no hard planner guarantees

Acceptable for MVP, not for production autonomy.

### 5. Memory system incomplete ⚠️

Missing:

- strict boundaries (session vs persistent)
- summarization policy
- PII safety policy enforcement
- retention rules

### 6. Integration ambiguity ⚠️

Expert still feels partly parallel instead of fully unified with:

- main chat entrypoint
- session model
- telemetry stack

---

## Recommended production direction

### Core principle

> **Backend becomes the ONLY expert brain**

Frontend becomes:

- UI
- transport
- renderer

---

## Target architecture

```txt
Frontend UI
  ↓
Expert API
  ↓
Backend Expert Router (single authority)
  ↓
Policy Engine
  ↓
Provider Layer (local / remote / burst)
  ↓
Thinking Pipelines
  ↓
Tools + Memory
  ↓
Evals + Telemetry
  ↓
Response
```

---

## Migration plan (execution-ready)

### Phase 1 — Contract unification (P0)

**Goal:** One authoritative API contract.

**Actions**

```ts
type ExpertRequest = {
  mode: "fast" | "expert" | "heavy" | "auto" | "beta";
  messages: Message[];
  sessionId?: string;
  attachments?: boolean;
};
```

```ts
type ExpertResponse = {
  text: string;
  provider: "local" | "remote";
  strategy: string;
  toolsUsed?: string[];
  memoryUsed?: boolean;
  latencyMs?: number;
  fallback?: boolean;
};
```

**Outcome:** FE/BE share one canonical contract.

---

### Phase 2 — Backend authority (P0)

**Goal:** Remove duplication.

**Move to backend**

- routing logic
- complexity scoring
- provider selection
- tool planning
- memory logic
- eval logging

**Outcome:** backend is single source of truth.

---

### Phase 3 — Frontend simplification (P0)

**Goal:** Thin deterministic frontend.

**Remove**

- routing logic
- provider selection
- memory writes
- eval writes
- tool planning

**Keep**

- mode selector
- request builder
- streaming UI
- debug/trace viewer (optional)

**Outcome:** stable frontend presentation layer.

---

### Phase 4 — Provider hardening (P0)

**Add**

- timeout per request
- retry policy
- health check endpoint
- circuit breaker
- budget enforcement

**Guarantee**

- no hanging requests
- deterministic fallback

---

### Phase 5 — Thinking pipelines stabilization (P1)

- Fast: one pass, strict latency cap
- Expert: analysis → answer
- Heavy: draft → critique → synthesize

**Add**

- token limits
- step limits
- cancellation support

---

### Phase 6 — Memory system (P1)

Split memory:

- Session memory: recent turns + rolling summary
- Persistent memory: preferences + pinned facts

**Add**

- PII redaction
- TTL policy
- summarization policy

---

### Phase 7 — Tool system (P1)

**Add**

- max tool loop count
- timeout per tool
- allowlist
- audit log

**Move**

- all tool planning to backend

---

### Phase 8 — Observability (P0)

Log for every request:

- mode
- provider
- strategy
- latency
- fallback
- tools used
- memory used
- errors

Required metrics:

- latency p50/p95
- failure rate
- fallback rate
- local vs remote ratio

---

## Definition of Expert Mode (target production semantics)

### Fast

- single-pass
- local-first
- low latency

### Expert

- analysis-first reasoning
- adaptive provider

### Heavy

- multi-pass reasoning
- highest accuracy
- remote-preferred

### Auto

- complexity + health + budget routing

### Beta

- isolated experimental path

---

## Production readiness checklist

### Must pass before release

#### Architecture

- [ ] backend is single brain
- [ ] frontend is thin client

#### Reliability

- [x] timeout enforced
- [x] fallback guaranteed
- [ ] retry/circuit breaker fully implemented

#### Observability

- [x] response carries strategy/fallback/latency/notices
- [ ] centralized per-request telemetry pipeline complete

#### UX honesty

- [ ] UI reflects backend-selected provider + strategy + fallback notice

#### Testing

- [x] routing mode resolution tested
- [x] fallback metadata tested
- [ ] provider failure matrix + e2e parity suite completed

---

## Final conclusion

### Already strong

- ✔ Real expert orchestration
- ✔ Multi-pass reasoning
- ✔ Hybrid provider model
- ✔ Tool + memory foundation

### Must change next

- ❗ Remove dual orchestration
- ❗ Move all decision logic to backend
- ❗ Harden providers beyond timeout/fallback (retry/circuit breaker/budget gates)
- ❗ Simplify frontend to API client + UX only

### Final verdict

> The system is **architecturally strong but not yet fully production-safe**.

With this migration plan and current backend hardening progress, it can become a robust local-first expert system with optional remote scaling.
