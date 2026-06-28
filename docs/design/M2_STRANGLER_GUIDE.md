# M2 — Strangler extraction (frontend → packages)

Goal: make `frontend/` consume the `@homepilot/*` packages as the single source
of truth, **without breaking the running web app or its deploys**, one module
per PR.

## The constraint that shaped the approach

The deployed frontend is built **standalone** (`container/Dockerfile`,
`hf/builder/Dockerfile`, `deploy/huggingface-space/Dockerfile`, and the
`Makefile` all build `frontend/` in isolation). Making `frontend/package.json`
depend on `@homepilot/*` workspace packages would make `npm ci/install` fail in
those builds. So instead of npm workspace linking, M2-infra consumes the shared
packages as **build-time source aliases**.

## M2-infra — chosen approach: path aliases (✅ implemented)

The packages export TypeScript source. The frontend resolves `@homepilot/*` to
`../packages/*/src` at build time — **no npm dependency, no root lockfile, no
change to `npm ci`/`npm install`**, so standalone installs are untouched.

What landed:

| File | Change |
|---|---|
| `frontend/tsconfig.json` | added `"paths": { "@homepilot/*": ["../packages/*/src"] }` (no `baseUrl` — moduleResolution `bundler` resolves paths relative to the tsconfig) |
| `frontend/vite.config.ts` | added `resolve.alias` `@homepilot/* → ../packages/*/src` for runtime imports |
| `container/Dockerfile`, `hf/builder/Dockerfile`, `deploy/huggingface-space/Dockerfile` | one line each: `COPY packages/ /packages/` (WORKDIR is `/build`, so `../packages` = `/packages`). `npm ci`/`install` unchanged. |
| `frontend/src/shared/types.ts` | first extraction — a **type-only** re-export of `@homepilot/types` (erased at build; proves resolution) |

Why this is non-destructive:
- `frontend/package.json` is **unchanged** → `cd frontend && npm ci/install`
  still works exactly as before.
- The `Makefile` frontend targets need **no change** — on a dev host the
  packages are the sibling `../packages`, so `cd frontend && npm run build` /
  `npx tsc --noEmit` resolve them directly.
- The Docker change is additive (copy `packages/`); the install step is
  untouched.
- The first extraction is type-only, so runtime output is identical.

### ✅ Verify before merging (needs the real pipeline — can't run Docker here)

1. `cd frontend && npx tsc --noEmit` (host) — should pass with `../packages`
   present.
2. `cd frontend && npm run build` (host) — `dist/` builds as before.
3. A container build, e.g. `docker build -f container/Dockerfile -t homepilot .`
   — the frontend stage should build with `COPY packages/ /packages/`.
4. Confirm the rendered app is unchanged (the type-only re-export adds nothing
   at runtime).

### Known caveat — dev-only `frontend/Dockerfile`

`frontend/Dockerfile` (the `npm run dev` container) builds with context
`frontend/`, so it can't see `../packages`. It's unaffected today (the type-only
re-export is erased, and `vite dev` doesn't run `tsc`). When a later slice adds a
**runtime** `@homepilot/*` import, either mount `../packages` into that dev
container or build it from the repo root. Host dev (`make dev`) is unaffected.

## M2-extract — per-module PRs (now unblocked)

Strangler pattern: replace internals, keep the public surface identical, so call
sites don't change.

1. **Types first (done for the first slice).** Re-export shared DTOs from
   `frontend/src/shared/types.ts`; migrate `import { Job } from "../types"`
   call sites to it incrementally.
2. **Base client (✅ done — first runtime import).** `frontend/src/ui/api.ts`
   now constructs and exports the shared clients alongside the legacy axios
   instance:
   - `api` (axios) is **left untouched** — its 16 call sites rely on axios
     response semantics, so swapping it would be destructive. Its call sites are
     strangled onto `http` one PR at a time.
   - new `http = createClient({ baseUrl: getDefaultBackendUrl(), tokenProvider,
     authHeader: (k) => ({ "X-API-Key": k }) })` and
     `computeClient = createComputeClient(http)` — same base URL + `X-API-Key`
     auth, fetch-based, shared across platforms.
   - `@homepilot/api-client` gained an additive, backward-compatible
     `authHeader` option (default still `Authorization: Bearer`) so HomePilot's
     `X-API-Key` scheme works without changing the Bearer default.

   This is the **first runtime import**, so the dev-container caveat above is now
   live and a build should be verified.
3. **Migrate axios call sites → `http` / `computeClient`.** Per domain, replace
   `api.get('/x').then(r => r.data)` with `await http.get('/x')` (the shared
   client returns parsed JSON directly). Small, independently revertible PRs.
4. **Compute/devices.** New screens + Wave A's job API call `computeClient`
   directly (net-new; nothing to strangle).

## Status

- M2-infra: ✅ implemented (path aliases + Docker copy + first type-only
  extraction) — pending pipeline verification (checklist above).
- M2-extract: 🔄 in progress — types re-export (slice 1) and the base-client
  runtime import (slice 2) landed; remaining work is migrating axios call sites
  onto `http` per domain. **Verify a frontend build** now that there's a runtime
  `@homepilot/*` import (`cd frontend && npm run build`, and a container build).
