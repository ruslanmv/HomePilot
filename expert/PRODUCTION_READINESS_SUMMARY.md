# Expert Module — Production Readiness Summary

_Date updated: 2026-04-23_

## Current verdict

**Strong architecture direction, partial production readiness.**

- Architecture readiness: **medium-high**
- Production readiness: **medium**
- Frontier parity readiness: **low-medium**

---

## What is implemented now (aligned with code)

1. Deterministic mode resolution (`auto -> fast/think/heavy`) in backend policy layer.
2. Backend strategy metadata in responses (`strategy_used`).
3. Provider timeout (`EXPERT_PROVIDER_TIMEOUT_S`) and deterministic local fallback.
4. Fallback metadata surfaced (`fallback_applied`, `notices`).
5. Latency metadata surfaced (`latency_ms`).
6. Think/heavy pipelines propagate fallback/notices across multi-step execution.
7. MCP server catalog and tool mapping definitions are present in backend catalog modules.
8. Unit tests cover policy mode resolution and fallback metadata extraction.

---

## What remains before enterprise production

### P0 (must-have)

1. Frontend simplification to thin client (remove duplicate orchestration ownership).
2. Real MCP tool backends in production paths (beyond simulated/basic flows).
3. Persistent memory governance: TTL, deletion APIs, tenant isolation, auditable lifecycle.
4. Safety policy enforcement and prompt/tool injection hardening at runtime boundaries.
5. Centralized observability pipelines (metrics/traces/events with SLO alerts).
6. Circuit breaker + retry/backpressure reliability controls.

### P1 (important)

1. Cost-aware dynamic routing feedback loops.
2. Citation/provenance enforcement for research outputs.
3. Load/performance/canary testing and rollback automation.
4. Full UI honesty indicators for selected provider/strategy/fallback.

---

## Deployability statement

- ✅ **Safe for preprod and controlled pilots** with guardrails.
- ⚠️ **Not yet full enterprise production parity** until P0 items are completed and validated under sustained traffic.
