# Expert Module Migration Plan (Preprod → Enterprise Production)

This plan is additive and aligned with the current repository state.

---

## Goals

1. Make backend the single authoritative orchestration layer.
2. Keep local-first operation as default.
3. Preserve deterministic fallback to local.
4. Introduce enterprise-grade observability and safety gates.

---

## Phase 0 — Baseline and inventory

- Capture latency/error/fallback baselines for `/v1/expert/chat` and `/v1/expert/stream`.
- Document frontend/backend behavior overlap (split-brain inventory).
- Confirm current strategy metadata fields in response contracts.

**Exit criteria:** baseline report + migration risk log.

---

## Phase 1 — API contract stabilization

- Freeze canonical request/response contract at backend boundary.
- Ensure mode semantics and strategy labels are identical in docs and API.
- Version or feature-flag contract changes as needed.

**Exit criteria:** stable API schema consumed by frontend.

---

## Phase 2 — Backend authority hardening

- Keep routing and mode policy exclusively backend-owned.
- Ensure timeouts/fallback notices are emitted for all applicable paths.
- Expand reliability policy with retry/circuit-breaker roadmap.

**Exit criteria:** backend decisions are authoritative and observable.

---

## Phase 3 — Frontend simplification

- Remove frontend policy/routing ownership.
- Keep frontend focused on mode selection, rendering, and truthful runtime status display.
- Show backend-selected provider/strategy/fallback notices in UI.

**Exit criteria:** frontend acts as thin client.

---

## Phase 4 — MCP and memory productionization

- Replace simulated tool paths with MCP-backed services according to priority list.
- Harden memory lifecycle (retention, privacy, deletion controls).
- Add audit trail for tool/memory operations.

**Exit criteria:** tool and memory subsystems are enterprise-safe.

---

## Phase 5 — Observability, evals, release gates

- Centralize metrics, traces, structured events.
- Add automated eval gates and regression thresholds.
- Introduce canary + rollback policy.

**Exit criteria:** measurable SLO-backed production launch criteria met.

---

## Recommended sequencing timeline

- Week 1: Phases 0-1
- Week 2: Phase 2
- Week 3: Phase 3
- Week 4: Phase 4
- Week 5+: Phase 5 + controlled rollout
