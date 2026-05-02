# Frontend TS/JS Cleanup Plan

Remove the stale `.js`/`.jsx` mirrors under `frontend/src/`. The TS/TSX tree is
the **only canonical source** — Vite now resolves every bare import to the
`.tsx` / `.ts` variant, and `tsc -b` no longer emits `.jsx` / `.js` compile
artifacts.

> **Status**: **Phase 0 — Guard is live** (see below). The remaining 305 stale
> mirrors are orphan files that nothing loads and nothing regenerates. Deleting
> them is pure cleanup (review-noise reduction + ~3 MiB reclaimed).

## Phase 0 — Guard already landed ✅

These three changes together make the **newest TypeScript** the authoritative
source of every import, and stop any new `.jsx` / `.js` mirror from being
created by future builds:

| Change | Commit | What it does |
|---|---|---|
| `frontend/tsconfig.json` adds `"noEmit": true` | `7757e69` | `tsc -b` only type-checks; never writes compiled siblings |
| Delete `frontend/vite.config.js` + `frontend/vitest.config.js` | `b4d39f4` | Vite config-file priority puts `.js` before `.ts`, so the stale compiled configs were shadowing the real ones |
| `vite.config.ts` adds `resolve.extensions: ['.tsx', '.ts', '.mts', '.jsx', '.js', '.mjs', '.json']` | `b4d39f4` | Bare imports (`./ui/App`) now prefer TypeScript — the default Vite order put `.jsx` first and was loading the stale mirror |

**Proof the guard works**: strings that only exist in recent `.tsx` edits on
this branch — `Your personas and legacy chat`, `Thinks harder`, `avif`,
`Expert Pick`, `Persona Live` — all show up exactly once in
`frontend/dist/assets/index-*.js` after `make build`. Before the fixes every
one of these was 0 because Vite was bundling the `.jsx` shadow.

## Baseline (current audit)

- Source files: **614** (309 TS/TSX + 305 JS/JSX)
- Duplicate basename pairs: **305** (all are orphan .jsx / .js mirrors)
- JS bytes to recover: **~3 MiB**
- Groups where JS has more importers than TS: **0** (safe — TS is canonical everywhere)
- Audit tool: `python tools/frontend_audit.py`
- CI gate: `python tools/frontend_audit.py ci` exits **1** today → enable once the staged deletion below completes

## Staging (one PR per bullet, small → large)

Keep every PR focused on one folder so review and rollback stay cheap.

- [ ] **PR 1 — `test/`** (1 pair) — warm-up, minimal risk
- [ ] **PR 2 — `expert/`** (1 pair)
- [ ] **PR 3 — `agentic/`** (3 pairs)
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
- [ ] **PR 19 — `ui/` leaf + small subfolders** (**48 pairs**: 44 `ui/*.jsx` at top level + `ui/agentic/` (1) + `ui/persona/` (2) + `(root)/main.jsx` (1); includes `App.jsx`, `main.jsx`, `CallOverlay.jsx`, `VoiceModeGrok.jsx`, etc.)
- [ ] **PR 20 — enable CI guard + contributor guideline** (after 0 duplicates)

Total pairs to remove across PRs 1–19: **305** (matches audit).

## Per-PR checklist

For each folder PR above:

1. `python tools/frontend_audit.py imports <one .jsx in folder>` — confirm 0 importers on the JS side.
2. `git rm frontend/src/<folder>/*.jsx frontend/src/<folder>/*.js` (only duplicates — keep any JS that has no TS twin).
3. `make test-frontend` — TypeScript check + Vitest must pass.
4. `make build` — Vite production build must succeed.
5. `python tools/frontend_audit.py inventory | head -5` — duplicate count should drop by the folder's pair count.
6. Commit message: `cleanup(frontend): remove stale .jsx mirrors in <folder>/`

## Final PR — enable the CI guard (Phase 0 step 2)

`noEmit` and the vite config are already in. What's left after all 305 mirrors
are gone:

1. Add the CI step (GitHub Actions, your existing workflow, or a pre-commit hook):
   ```bash
   python tools/frontend_audit.py ci
   ```
   Exits 1 if any TS/JS duplicate is re-introduced.

2. Add contributor guideline to the repo's `CONTRIBUTING.md` or equivalent:
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
