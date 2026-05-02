# Expert Module Audit (HomePilot)

## Short answer first

**The Expert module is beyond “UI-only” and already includes routing + multi-step reasoning pipelines, but it is not yet a fully competitive frontier AI architecture because tool use, durable memory, and eval-driven reliability are still missing.**

---

## What is already implemented well

### 1) Orchestration exists (not just a mode selector)
- Query complexity scoring (`score_complexity`) is implemented.
- Provider routing (`select_provider`) picks local/groq/grok/gemini/etc. with availability checks and fallbacks.
- Auto thinking mode maps complexity to `fast` / `think` / `heavy`.

**Verdict:** The orchestration layer is real and functional.

### 2) Reasoning layer exists
- `think` pipeline runs analyze → plan → solve (+ optional critique).
- `heavy` pipeline runs researcher → reasoner → synthesizer → validator.
- Streaming endpoints expose per-step events for live UI progression.

**Verdict:** The system already has multi-step reasoning architecture.

### 3) Product/UI integration is strong
- UI supports provider selector, thinking mode selector, step panels, and streamed status.
- SSE stream metadata and step events are wired end-to-end.

**Verdict:** UX + backend orchestration are tightly integrated.

---

## Critical gaps vs Claude/GPT/Gemini-level systems

### 1) Tool layer is missing
There is no native integrated tool execution loop in the Expert pipelines (e.g., search, retrieval, code execution, API tools called during reasoning).

**Impact:** Reduced grounding and actionability; higher hallucination risk.

### 2) Memory layer is missing
The module accepts short-term `history` in requests, but no persistent long-term user/task memory store is evident in this module.

**Impact:** Weak personalization and continuity across sessions.

### 3) Evals/reliability framework is missing
No built-in eval harness, quality scoring, regression benchmark, or policy-based fallback tuning was found in the Expert module itself.

**Impact:** Hard to prove quality improvements and maintain reliability at scale.

### 4) Router sophistication is heuristic
Routing uses keyword/length heuristics rather than learned policy + cost/latency/quality optimization.

**Impact:** Good baseline, but brittle on edge cases.

---

## Reality check on current maturity

- **UI/Product maturity:** High.
- **Orchestration maturity:** Medium-High.
- **Reasoning maturity:** Medium-High.
- **Tooling maturity:** Low.
- **Memory maturity:** Low.
- **Eval/reliability maturity:** Low.

**Overall:** This is no longer a “UI-only prototype”; it is an **advanced orchestration prototype** that needs tooling + memory + evals to become truly competitive.

---

## Priority roadmap (practical)

1. **Tool substrate first (critical)**
   - Add standardized tool interfaces (web search, retrieval, code execution, API calls).
   - Make think/heavy pipelines tool-aware with explicit call budgets.

2. **Persistent memory (critical)**
   - Session summary memory + user profile memory + task memory with retrieval rules.

3. **Eval harness (critical)**
   - Add task suite, golden answers, and automated quality/cost/latency tracking.

4. **Adaptive routing v2 (important)**
   - Replace pure heuristics with policy scoring using historical performance.

5. **Reliability hardening (important)**
   - Structured retries, circuit breakers, degraded-mode responses, and observability.

---

## Final verdict

HomePilot Expert is **architecturally promising and already ahead of many single-LLM apps**, but to compete with top-tier systems it must evolve from “multi-step prompting + provider routing” into a full **tool-augmented, memory-backed, eval-governed intelligence platform**.

---

## Implementation update (local-first upgrade)

A new local-first Expert frontend orchestration module now adds foundational building blocks for the previously identified gaps:

- **Tool substrate:** Registry + built-in tool contracts (`web_search`, `retrieval`, `code_exec`, `model_compare`) with explicit tool budgets and execution summaries.
- **Memory substrate:** Session-scoped memory store abstraction (`MemoryStore`) with in-memory implementation for conversation recall/append.
- **Eval substrate:** Basic eval recorder abstraction (`EvalRecorder`) with in-memory scoring history to enable future benchmark automation.
- **Reliability substrate:** Provider success/latency tracking and adaptive routing hints wired into policy decisions.

These upgrades do not yet represent full production grounding/evals, but they convert the architecture from “missing core layers” to **minimal viable layers that can be wired to MCP servers and real storage/eval backends**.
