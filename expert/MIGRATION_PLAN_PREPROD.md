# Expert Module Migration Plan (Additive, Non-Destructive)

This plan is for **preprod deployment first**, keeping all changes additive so existing functionality continues to run unchanged.

## Principles

1. **Additive only**: no endpoint removals, no schema-breaking changes, no hard cutovers.
2. **Feature-flagged rollout**: new paths are opt-in until validated.
3. **Fast rollback**: disable flags to revert to current stable behavior.
4. **Observe before scale**: metrics first, traffic later.

---

## Scope (this folder only)

- `expert/frontend/src/expert/*` and related Expert docs in `expert/`.
- No destructive changes to existing backend routes.

---

## Phase 0 — Baseline Snapshot (Preprod)

### Deliverables
- Capture current behavior and latency/error baseline for `/v1/expert/chat` and `/v1/expert/stream`.
- Record baseline provider availability and mode usage.

### Exit criteria
- Baseline report stored in preprod runbook.
- Alert thresholds defined (error rate, latency, timeout).

---

## Phase 1 — Additive Wiring (Disabled by Default)

### Deliverables
- Deploy new frontend Expert core artifacts with flags OFF.
- Add configuration support for local/remote provider vars.
- Add no-op/simulated tool registry in preprod.

### Flags
- `EXPERT_V2_ROUTER_ENABLED=false`
- `EXPERT_TOOLS_ENABLED=false`
- `EXPERT_MEMORY_ENABLED=false`
- `EXPERT_EVALS_ENABLED=false`

### Exit criteria
- Build/deploy passes with no runtime impact.
- Existing Expert UX and backend contract unchanged.
- Unit tests for tool/memory/eval/reliability/routing core pass in CI.

---

## Phase 2 — Shadow Mode (No User-Visible Behavior Change)

### Deliverables
- Run new routing logic in parallel (shadow) and log decisions.
- Compare shadow decisions vs current route outcomes.
- Collect reliability snapshots and eval records in preprod only.

### Flags
- `EXPERT_V2_ROUTER_ENABLED=false`
- `EXPERT_V2_SHADOW_MODE=true`
- `EXPERT_EVALS_ENABLED=true`

### Exit criteria
- Shadow mismatch rate understood and documented.
- No regression in latency/error in primary path.

---

## Phase 3 — Controlled Enablement (Internal Traffic)

### Deliverables
- Enable v2 router for internal/test users only.
- Enable memory recall/append for session-scoped flows.
- Enable tool loop with strict budget and simulated backends.

### Flags
- `EXPERT_V2_ROUTER_ENABLED=true`
- `EXPERT_TOOLS_ENABLED=true`
- `EXPERT_MEMORY_ENABLED=true`
- `EXPERT_TOOL_BUDGET_DEFAULT=3`
- `EXPERT_REMOTE_ALLOWED=false` (local-first lock)

### Exit criteria
- Internal success metrics stable for 3+ days.
- No incident-level failures.

---

## Phase 4 — Remote Acceleration in Preprod (Opt-In)

### Deliverables
- Configure one remote vLLM/OpenAI-compatible endpoint.
- Keep local-first routing; allow remote only for expert/heavy paths.
- Enforce monthly budget guardrail and remote health checks.

### Flags
- `EXPERT_REMOTE_ALLOWED=true`
- `EXPERT_MONTHLY_GPU_BUDGET_LIMIT=<value>`
- `EXPERT_REMOTE_FAILBACK_TO_LOCAL=true`

### Exit criteria
- Remote path improves quality/latency for target tasks.
- Budget usage and failback behavior verified.

---

## Phase 5 — MCP Tool Integrations (Incremental)

### Deliverables
- Replace simulated tools one-by-one with real MCP-backed handlers:
  1. `retrieval`
  2. `web_search`
  3. `code_exec`
  4. `model_compare`
- Keep per-tool kill-switches.

### Flags
- `EXPERT_TOOL_RETRIEVAL_LIVE=true|false`
- `EXPERT_TOOL_WEB_SEARCH_LIVE=true|false`
- `EXPERT_TOOL_CODE_EXEC_LIVE=true|false`
- `EXPERT_TOOL_MODEL_COMPARE_LIVE=true|false`

### Exit criteria
- Each tool validated independently with fallback path.
- No cross-tool cascading failures.

---

## Phase 6 — Preprod Readiness Gate

### Mandatory checks
- Reliability:
  - Error rate within SLA target.
  - Timeout rate stable.
- Quality:
  - Eval score trend non-degrading.
- Cost:
  - Remote budget stays within policy.
- Safety:
  - Tool calls auditable and rate-limited.

### Exit criteria
- Signed preprod readiness checklist.
- Production cutover plan approved.

---

## Rollback Strategy (Non-Destructive)

At any point, rollback is done by flags only:

1. Set `EXPERT_V2_ROUTER_ENABLED=false`
2. Set `EXPERT_TOOLS_ENABLED=false`
3. Set `EXPERT_MEMORY_ENABLED=false`
4. Set `EXPERT_REMOTE_ALLOWED=false`

This returns behavior to current stable path without reverting deployed artifacts.

---

## Production Migration (After Preprod Signoff)

- Start with 1-5% traffic canary.
- Increase by stage with automated halt on error/latency thresholds.
- Keep local-only fallback available at all times.
- Do not remove legacy path until two full release cycles pass with stable metrics.
