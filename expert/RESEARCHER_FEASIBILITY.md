# Can we build a "Researcher" with this technology?

## Short answer

**Yes — absolutely.**

With the current Expert architecture (router + tool substrate + memory + eval + reliability), you can build a practical Researcher agent. It will be a **v1 researcher** immediately, and it can evolve toward a high-quality production researcher once you replace simulated tools with real MCP-backed services and add stronger safety/eval gates.

---

## Why this stack is sufficient

A Researcher agent needs these capabilities:

1. Query planning
2. Multi-source retrieval/search
3. Evidence synthesis
4. Citation/provenance tracking
5. Iterative refinement
6. Long-session memory

Your current module already has foundational parts for this:

- Router for fast/expert/heavy execution paths
- Tool contracts + execution budget mechanism
- Session memory interface
- Reliability and eval hooks

So the architecture is compatible with a Researcher product.

---

## What a v1 Researcher can do now

You can implement a first working version with:

1. **Plan step**
   - Prompt the model to create a research plan with sub-questions.

2. **Tool execution step**
   - Use tool registry calls (`web_search`, `retrieval`) for each sub-question.

3. **Synthesis step**
   - Merge findings into a structured answer with assumptions and confidence notes.

4. **Review step**
   - Run a critique/check pass for contradictions or missing evidence.

5. **Memory step**
   - Persist session-level research context and follow-up questions.

This gives useful research behavior without requiring a full multi-agent framework.

---

## What is still required for a strong production Researcher

## P0 (must-have)

1. Replace simulated tools with real integrations
   - MCP web/search, local docs retrieval, optional code sandbox.

2. Add citations/provenance
   - Every claim should map to source IDs/URLs/chunks.

3. Safety hardening
   - Prompt-injection defenses and tool output sanitization.

4. Durable memory
   - Persistent memory backend + retention + deletion controls.

5. Evaluation gates
   - Research-quality benchmark with factuality/citation checks.

## P1 (important)

1. Confidence scoring by section
2. Contradiction detection across sources
3. Cost/latency optimization policies
4. Research report templates (brief, deep-dive, executive)

---

## Recommended implementation pattern

Use a single Researcher workflow with explicit phases:

```txt
Question
 -> Plan
 -> Gather (tools)
 -> Synthesize
 -> Validate
 -> Deliver (with citations)
```

And map these phases to existing Expert modes:

- `fast`: quick answer + minimal retrieval
- `expert`: plan + gather + synthesize
- `heavy`: deeper gather + validation + contradiction checks

---

## Risks to handle early

1. Hallucinated citations
2. Prompt injection from web content
3. Source quality variance
4. Cost spikes during heavy research loops
5. Overconfidence in low-evidence outputs

Each should have explicit guardrails and tests before production.

---

## Final verdict

**Yes, it is fully possible to create a Researcher with this technology.**

Your architecture is already in the right direction; the next milestone is not redesign, but **wiring real tools + citations + safety + eval quality gates**.
