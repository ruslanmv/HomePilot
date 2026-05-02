# Expert Documentation Guide (Human + AI Agent Onboarding)

This guide is the canonical navigation map for all Expert documentation and is aligned to the current repository layout.

---

## Alignment snapshot (2026-04-23)

- ✅ Expert has both frontend and backend layers in repo.
- ✅ Backend contains production-target orchestration modules (`routes`, `router`, `policies`, `thinking`, `heavy`, providers, readiness).
- ⚠️ Frontend still contains orchestration artifacts and should converge toward thin-client behavior over migration phases.

---

## 1) Role-based reading order

### Product / Leadership
1. [`README.md`](./README.md)
2. [`EXPERT_MODE_REVIEW.md`](./EXPERT_MODE_REVIEW.md)
3. [`PRODUCTION_READINESS_SUMMARY.md`](./PRODUCTION_READINESS_SUMMARY.md)

### Backend Engineers
1. [`README.md`](./README.md)
2. [`ENTERPRISE_LOCAL_ARCHITECTURE.md`](./ENTERPRISE_LOCAL_ARCHITECTURE.md)
3. [`MIGRATION_PLAN_PREPROD.md`](./MIGRATION_PLAN_PREPROD.md)
4. `expert/backend/app/expert/*.py`

### Frontend Engineers
1. [`README.md`](./README.md)
2. [`EXPERT_MODE_REVIEW.md`](./EXPERT_MODE_REVIEW.md)
3. [`ENTERPRISE_LOCAL_ARCHITECTURE.md`](./ENTERPRISE_LOCAL_ARCHITECTURE.md)
4. `expert/frontend/src/expert/*`

### DevOps / SRE
1. [`ENTERPRISE_LOCAL_ARCHITECTURE.md`](./ENTERPRISE_LOCAL_ARCHITECTURE.md)
2. [`PRODUCTION_READINESS_SUMMARY.md`](./PRODUCTION_READINESS_SUMMARY.md)
3. [`MCP_SERVERS_PRODUCTION_LIST.md`](./MCP_SERVERS_PRODUCTION_LIST.md)
4. `expert/backend/app/expert/readiness.py`

### AI Coding Agents
1. [`README.md`](./README.md)
2. [`EXPERT_MODE_REVIEW.md`](./EXPERT_MODE_REVIEW.md)
3. [`ENTERPRISE_LOCAL_ARCHITECTURE.md`](./ENTERPRISE_LOCAL_ARCHITECTURE.md)
4. then modify code

---

## 2) Canonical truths

1. Local-first is the default operating mode.
2. Backend must be the authoritative decision layer.
3. Frontend should evolve toward thin client + UX renderer.
4. Mode labels must match actual runtime behavior.
5. Fallback to local must be deterministic and observable.

---

## 3) Complete Expert document catalog

All markdown files under `expert/`:

1. [`README.md`](./README.md)
2. [`DOCUMENTATION_GUIDE.md`](./DOCUMENTATION_GUIDE.md)
3. [`ENTERPRISE_LOCAL_ARCHITECTURE.md`](./ENTERPRISE_LOCAL_ARCHITECTURE.md)
4. [`EXPERT_MODE_REVIEW.md`](./EXPERT_MODE_REVIEW.md)
5. [`PRODUCTION_READINESS_SUMMARY.md`](./PRODUCTION_READINESS_SUMMARY.md)
6. [`MIGRATION_PLAN_PREPROD.md`](./MIGRATION_PLAN_PREPROD.md)
7. [`STABILITY_SAFETY_REVIEW.md`](./STABILITY_SAFETY_REVIEW.md)
8. [`MCP_SERVERS_PRODUCTION_LIST.md`](./MCP_SERVERS_PRODUCTION_LIST.md)
9. [`RESEARCHER_FEASIBILITY.md`](./RESEARCHER_FEASIBILITY.md)
10. [`INSTITUTE_SCALABLE_BACKEND_BLUEPRINT.md`](./INSTITUTE_SCALABLE_BACKEND_BLUEPRINT.md)
11. [`SPACE_AUTONOMY_EVOLUTION_ROADMAP.md`](./SPACE_AUTONOMY_EVOLUTION_ROADMAP.md)
12. [`INTEGRATION_PATCH.md`](./INTEGRATION_PATCH.md)

---

## 4) 60-minute technical onboarding path

- 10 min: `README.md`
- 10 min: `EXPERT_MODE_REVIEW.md`
- 10 min: `PRODUCTION_READINESS_SUMMARY.md`
- 15 min: `ENTERPRISE_LOCAL_ARCHITECTURE.md`
- 15 min: `MIGRATION_PLAN_PREPROD.md`

---

## 5) Documentation maintenance rules

When implementation changes:

- Update `README.md` first.
- Update readiness and migration docs second.
- Update long-term roadmap docs only when strategy changes.
- Keep links and mode terminology consistent (`fast`, `think/expert`, `heavy`, `auto`, `beta`).
