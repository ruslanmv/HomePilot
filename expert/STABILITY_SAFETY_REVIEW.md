# Expert Module — Stability & Safety Review

_Date updated: 2026-04-23_

## Snapshot

Expert has a solid foundation, but enterprise stability/safety is still in-progress.

### Already in place
- local-first architecture
- deterministic backend mode resolution
- provider timeout + local fallback metadata
- multi-step think/heavy pipelines
- baseline tests for policy/fallback behavior

### Still required for full production safety
- retry/circuit-breaker/backpressure controls
- centralized observability with SLO alerting
- production MCP tool hardening and sandbox controls
- memory governance completeness (TTL/deletion/isolation)
- safety policy enforcement for tool I/O and prompt injection resilience

---

## Priority hardening list

### P0
1. Reliability controls (retry budget + circuit breaker).
2. Structured tracing and dashboards across route -> pipeline -> tool -> provider.
3. Tool allowlist + sandbox limits + output trust labels.
4. Memory lifecycle controls and privacy guardrails.
5. Safety gates for high-risk requests.

### P1
1. Cost-aware traffic shaping for heavy mode.
2. Provenance/citation enforcement in research-like responses.
3. Canary automation and rollback drill runbooks.

---

## Safety principle

> Never trade safety for speed: if uncertain, degrade to safer/local path with explicit notice.
