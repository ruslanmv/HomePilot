# Expert Integration Patch Guide (Current State)

_Date updated: 2026-04-23_

## Important

This file replaces older one-time patch notes.
The Expert module is now integrated as an ongoing subsystem, not a temporary patch.

---

## Current backend integration points

- Expert routes are provided under `/v1/expert/*`.
- Primary files:
  - `expert/backend/app/expert/routes.py`
  - `expert/backend/app/expert/router.py`
  - `expert/backend/app/expert/policies.py`

Integration expectation:

1. Include expert router in backend app startup.
2. Keep environment configuration for local/remote providers.
3. Keep readiness endpoint enabled for operational checks.

---

## Current frontend integration points

- Expert UI entry point: `expert/frontend/src/ui/Expert.tsx`
- Frontend should call backend Expert API contract.
- Product direction: thin client UX with backend-authoritative routing decisions.

---

## Migration caution

If older branch instructions reference manual sidebar wiring or one-off patches, treat them as **historical** and validate against current app layout before applying.

---

## Verification checklist

- [ ] Backend includes `/v1/expert/info` and `/v1/expert/chat` routes.
- [ ] Frontend Expert view can reach backend endpoints.
- [ ] Response metadata (`strategy_used`, `fallback_applied`, `latency_ms`) is visible in client debug logs.
