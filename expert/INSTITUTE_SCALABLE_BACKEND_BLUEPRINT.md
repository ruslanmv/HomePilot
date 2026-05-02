# Institute-Scale Expert Backend Blueprint

This document describes how the current Expert stack can evolve from enterprise local-first deployment to institute-scale scientific/research workloads.

---

## Alignment to current stack

Current implementation already supports the foundation:

- backend orchestration (`routes`, `router`, `policies`, `thinking`, `heavy`)
- local-first provider strategy with optional remote escalation
- memory/tool/eval modules ready for productionization

Institute scale requires extending these primitives, not replacing them.

---

## Target architecture

```txt
API Gateway
  -> Identity/AuthZ/Audit
  -> Expert Orchestrator
      -> Domain routers
      -> Planner + tool graph executor
      -> Model gateway (local + rented GPU + HPC)
      -> Safety/policy engine
      -> Memory + provenance
      -> Eval + reliability + cost controller
```

---

## Priority build sequence

1. Domain routers and risk classes
2. Deterministic tool graph execution
3. Model gateway capacity orchestration
4. Provenance-first evidence store
5. Safety and policy enforcement layers
6. Continuous eval and cost governance

---

## Domain expansion examples

- medicine and biomedical workflows
- chemistry/simulation workflows
- physics reasoning/simulation workflows
- engineering design and automation workflows

All should inherit the same local-first + policy-gated remote model.
