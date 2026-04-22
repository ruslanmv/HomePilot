# MCP Servers / Tools to Build Next for Expert Production

## Short answer

For production Expert, you should prioritize **10 MCP servers** in this order:

1. `mcp-web-search` (grounded web retrieval)
2. `mcp-doc-retrieval` (private knowledge/RAG)
3. `mcp-code-sandbox` (safe execution)
4. `mcp-citation-provenance` (claim→source tracing)
5. `mcp-memory-store` (durable session/user/task memory)
6. `mcp-safety-policy` (policy checks + moderation)
7. `mcp-eval-runner` (benchmark/eval automation)
8. `mcp-observability` (metrics/traces/log export)
9. `mcp-cost-router` (budget-aware routing policy)
10. `mcp-job-orchestrator` (long-running simulation/research jobs)

---

## P0: Build first (must-have)

## 1) `mcp-web-search`
**Purpose:** Real-time grounded answers, citation candidates.  
**Why:** Replaces simulated `web_search` tool and reduces hallucination.

### Required APIs
- `search(query, top_k, recency_days)`
- `fetch(url)`
- `extract(content)`

## 2) `mcp-doc-retrieval`
**Purpose:** Internal/private knowledge retrieval.  
**Why:** Enables reliable enterprise and institute workflows.

### Required APIs
- `index(document_id, text, metadata)`
- `query(text, top_k, filters)`
- `delete(document_id)`

## 3) `mcp-code-sandbox`
**Purpose:** Safe code execution/calculation.  
**Why:** Needed for engineering/science tasks and verification.

### Required APIs
- `run(language, code, timeout_s, memory_mb)`
- `status(run_id)`
- `result(run_id)`

### Safety minimum
- no network by default
- CPU/memory/time caps
- isolated filesystem

## 4) `mcp-citation-provenance`
**Purpose:** Track claim lineage and enforce citation integrity.  
**Why:** Critical for research-grade trust.

### Required APIs
- `attach_claim(claim_text, source_refs)`
- `verify_citations(response_text)`
- `get_lineage(response_id)`

## 5) `mcp-memory-store`
**Purpose:** Durable memory backend with privacy controls.  
**Why:** Replace in-memory store for production continuity.

### Required APIs
- `append(session_id, role, content)`
- `recall(session_id, limit)`
- `profile_upsert(user_id, key, value)`
- `forget(user_id|session_id)`

### Privacy minimum
- PII redaction hooks
- TTL policy per memory class
- tenant/user isolation

---

## P1: Build second (important)

## 6) `mcp-safety-policy`
**Purpose:** Policy checks for unsafe/harmful requests and outputs.

### Required APIs
- `check_input(text, profile)`
- `check_output(text, profile)`
- `risk_score(context)`

## 7) `mcp-eval-runner`
**Purpose:** Continuous quality/safety/cost regression testing.

### Required APIs
- `run_suite(suite_id, model_profile)`
- `report(run_id)`
- `regression_gate(run_id, baseline_id)`

## 8) `mcp-observability`
**Purpose:** Central metrics/traces/logs for SLO monitoring.

### Required APIs
- `emit_metric(name, value, tags)`
- `emit_trace(trace_id, spans)`
- `emit_event(event_type, payload)`

---

## P2: Build third (scale)

## 9) `mcp-cost-router`
**Purpose:** Budget-aware adaptive routing.

### Required APIs
- `recommend_route(query_meta, budget_state)`
- `record_cost(provider, tokens, latency_ms, success)`
- `monthly_budget_status(org_id)`

## 10) `mcp-job-orchestrator`
**Purpose:** Queue and manage long-running workloads (simulations/research).

### Required APIs
- `submit(job_type, payload, priority)`
- `status(job_id)`
- `cancel(job_id)`
- `result(job_id)`

---

## Mapping to current Expert tools

Current tool names can map directly:

- `web_search` -> `mcp-web-search`
- `retrieval` -> `mcp-doc-retrieval`
- `code_exec` -> `mcp-code-sandbox`
- `model_compare` -> `mcp-eval-runner` + `mcp-cost-router`

---

## Minimal production set (if you must choose only 5)

1. `mcp-web-search`
2. `mcp-doc-retrieval`
3. `mcp-memory-store`
4. `mcp-safety-policy`
5. `mcp-observability`

With these five, Expert becomes meaningfully production-capable.
