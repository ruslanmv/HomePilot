# Expert Module — Stability & Safety Review

## Short answer

The current Expert module is a strong **foundational orchestration prototype** with local-first design and initial tests, but it is **not yet production-stable or safety-complete**. It still needs hardening in security, reliability controls, observability, persistence, and evaluation rigor.

---

## 1) What is already good

- Local-first architecture with optional remote escalation.
- Basic routing + multi-step strategies.
- Tool/memory/eval/reliability abstractions exist.
- Unit tests exist for frontend core and backend Python expert pipelines.

These are the correct primitives.

---

## 2) What is still missing for stable operation

## A. Reliability hardening (P0)

1. **Retry/circuit-breaker policy**
   - Per-provider retry budget (e.g., 1-2 retries max).
   - Circuit breaker with cool-down when remote failure rate spikes.

2. **Timeout classes**
   - Distinct timeouts for fast/expert/heavy modes.
   - Global request budget + per-step sub-budgets.

3. **Idempotent fallback behavior**
   - Explicit failover order and reason codes.
   - Deterministic fallback telemetry fields.

4. **Backpressure/rate-limit handling**
   - Queue depth limits and overload responses.
   - Adaptive sampling for heavy mode during load.

## B. Observability (P0)

1. **Structured tracing**
   - Correlation ID through router → tools → provider calls.
   - Per-step timing and token/cost counters.

2. **Operational dashboards**
   - Success/error/timeout rates by mode and provider.
   - Latency percentiles (p50/p95/p99), fallback rate, tool failure rate.

3. **Audit logs**
   - Tool invocations logged with redaction.
   - Decision reasons captured for postmortems.

## C. Persistence and memory safety (P0)

1. **Durable memory backend**
   - Replace in-memory store with persistent storage (sqlite/postgres + retention policy).

2. **Data lifecycle controls**
   - TTL per memory type, deletion APIs, and per-user isolation.

3. **PII policy**
   - Redact or hash sensitive entities before memory write.

## D. Tool security (P0)

1. **Tool allowlist + capability scopes**
   - Per-tool permission model by mode/user role.

2. **Sandboxing for code execution**
   - Hard CPU/memory/time/file/network boundaries.

3. **Output sanitization**
   - Guard against prompt injection from tool outputs.
   - Provenance tags and trust levels on retrieved content.

---

## 3) What is still missing for safety/compliance

## A. Model safety controls (P1)

- Input/output moderation layers.
- Policy-driven refusal and safe-completion templates.
- High-risk topic escalation workflow.

## B. Access controls (P1)

- API authentication for tool endpoints.
- Tenant/user scoping for memory and eval logs.
- Signed config changes and audit trail.

## C. Secrets management (P1)

- Move API keys to managed secret store.
- Key rotation and scoped credentials.

---

## 4) What is still missing for evaluation quality

## A. Real eval dataset + regression suite (P0)

- Curated benchmark sets by mode (fast/expert/heavy).
- Golden answers + rubric scoring.
- Mandatory CI gate on eval regression.

## B. Safety evals (P0)

- Prompt injection scenarios.
- Tool abuse/escape scenarios.
- Hallucination and citation-faithfulness checks.

## C. Cost-performance evals (P1)

- Latency/cost/quality Pareto tracking.
- Auto policy tuning from historical outcomes.

---

## 5) What is still missing for development velocity

## A. Test expansion (P0)

- Integration tests for end-to-end `/v1/expert/chat` and `/v1/expert/stream` behavior.
- Failure-mode tests (provider down, timeout, bad tool payload).
- Property tests for router decisions under boundary inputs.

## B. Contract tests (P1)

- OpenAI-compatible provider contract tests for local/remote adapters.
- Tool contract tests (input schema, output schema, error schema).

## C. Release engineering (P1)

- Feature flag matrix tests.
- Canary + automated rollback triggers.

---

## 6) Minimal "production-ready" acceptance checklist

A release should not go live unless all are true:

1. Reliability SLOs met for 7 consecutive days in preprod.
2. Critical safety tests pass (prompt injection/tool abuse).
3. Persistent memory + deletion/retention controls enabled.
4. Observability dashboards and alerting configured.
5. CI includes unit + integration + eval regression gates.
6. Rollback-by-flags tested and documented.

---

## 7) Practical next implementation order

1. Durable memory + PII redaction.
2. Tool security model + code sandbox.
3. End-to-end integration tests + failure-mode tests.
4. Structured telemetry + dashboards + alerting.
5. Eval benchmark suite + CI regression gates.
6. Reliability controls (circuit breakers, adaptive backpressure).

---

## Final verdict

You now have the right architecture skeleton. To become truly stable and safe, prioritize **security + persistence + observability + evaluation gates** before adding more model complexity.
