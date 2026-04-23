# Frontend TS/JS Cleanup Plan

Remove the 305 stale `.js`/`.jsx` mirrors under `frontend/src/`. The TS/TSX tree
is the live source (`index.html` loads `main.tsx`; the JS tree has zero
importers except `main.jsx` which Vite does not load).

## Baseline

- Source files: **611** (306 TS/TSX + 305 JS/JSX)
- Duplicate basename pairs: **305**
- JS bytes to recover: **~3 MiB**
- Groups where JS has more importers than TS: **0** (safe — TS is canonical everywhere)
- Audit tool: `python tools/frontend_audit.py`

## Staging (one PR per bullet, small → large)

Keep every PR focused on one folder so review and rollback stay cheap.

- [ ] **PR 1 — `test/`** (1 pair) — warm-up, minimal risk
- [ ] **PR 2 — `agentic/`** (3 pairs)
- [ ] **PR 3 — `expert/`** (1 pair)
- [ ] **PR 4 — `ui/lib/`** (3 pairs)
- [ ] **PR 5 — `ui/sessions/`** (4 pairs)
- [ ] **PR 6 — `ui/enhance/`** (6 pairs)
- [ ] **PR 7 — `ui/call/`** (8 pairs)
- [ ] **PR 8 — `ui/tools/`** (9 pairs)
- [ ] **PR 9 — `ui/tts/`** (10 pairs)
- [ ] **PR 10 — `ui/voice/`** (14 pairs)
- [ ] **PR 11 — `ui/edit/`** (16 pairs)
- [ ] **PR 12 — `ui/components/`** (18 pairs)
- [ ] **PR 13 — `ui/mcp/`** (21 pairs)
- [ ] **PR 14 — `ui/phone/`** (21 pairs)
- [ ] **PR 15 — `ui/teams/`** (25 pairs)
- [ ] **PR 16 — `ui/interactive/`** (26 pairs)
- [ ] **PR 17 — `ui/studio/`** (31 pairs)
- [ ] **PR 18 — `ui/avatar/`** (40 pairs)
- [ ] **PR 19 — `ui/` leaf files** (~30 pairs including `App.jsx`, `main.jsx`, `CallOverlay.jsx`, etc.)
- [ ] **PR 20 — tsconfig hardening + CI guard** (final, prevents regressions)

## Per-PR checklist

For each folder PR above:

1. `python tools/frontend_audit.py imports <one .jsx in folder>` — confirm 0 importers on the JS side.
2. `git rm frontend/src/<folder>/*.jsx frontend/src/<folder>/*.js` (only duplicates — keep any JS that has no TS twin).
3. `make test-frontend` — TypeScript check + Vitest must pass.
4. `make build` — Vite production build must succeed.
5. `python tools/frontend_audit.py inventory | head -5` — duplicate count should drop by the folder's pair count.
6. Commit message: `cleanup(frontend): remove stale .jsx mirrors in <folder>/`

## Final PR (tsconfig hardening + CI guard)

Prevents the duplicates from ever coming back.

1. Add `"noEmit": true` to `frontend/tsconfig.json`:
   ```json
   {
     "compilerOptions": {
       "target": "ES2021",
       "lib": ["dom", "es2021"],
       "jsx": "preserve",
       "module": "esnext",
       "moduleResolution": "bundler",
       "strict": true,
       "skipLibCheck": true,
       "noEmit": true
     }
   }
   ```
   Vite still does the real build; `tsc -b` now only type-checks.

2. Add CI step (GitHub Actions, your existing workflow, or a pre-commit hook):
   ```bash
   python tools/frontend_audit.py ci
   ```
   Exits 1 if any TS/JS duplicate is re-introduced.

3. Add contributor guideline to the repo's `CONTRIBUTING.md` or equivalent:
   > No `.js`/`.jsx` files under `frontend/src/` for modules that are
   > authored in TS/TSX. Vite builds from `.tsx` directly; committed
   > compiled mirrors are not allowed.

## Verification after all PRs merge

- `python tools/frontend_audit.py ci` → exits 0
- `python tools/frontend_audit.py inventory` → "No duplicates. ✓"
- `make test-frontend` → all 124 tests pass
- `make build` → produces `dist/` with no working-tree changes afterward

## Out of scope for this cleanup

- **Expert feature rollout** — runs on its own lane (`make start-expert` → canary → prod). Do not mix with frontend hygiene PRs.
- **CSS / Tailwind pruning** — separate concern.
- **Bundle size reduction** (code-splitting, `manualChunks`) — performance follow-up, not hygiene.
