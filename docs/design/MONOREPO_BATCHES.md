# Monorepo + Wave B — implementation batches (lean tracker)

Companion to `MONOREPO_AND_WAVE_B.md`. Small, additive, independently-shippable
batches — deliberately not all at once. Each leaves every existing app green.

| # | Batch | Scope | Status |
|---|---|---|---|
| **M0** | Workspace | root `package.json` workspaces + `turbo.json` + `tsconfig.base.json` (npm workspaces; no PM change) | ✅ done |
| **M1** | Foundation packages | `@homepilot/{types, api-client, compute-client, ui}` — lean, real skeletons | ✅ done |
| **M1b** | Remaining packages | `@homepilot/{config, auth, core}` — lean, typechecked | ✅ done |
| **M2-infra** | Build-time package aliases | frontend resolves `@homepilot/*` → `../packages/*/src` via tsconfig `paths` + vite `resolve.alias`; deploy Dockerfiles `COPY packages/`; **no** npm-dep / lockfile / `npm ci` change. First type-only extraction landed. See `M2_STRANGLER_GUIDE.md` | ✅ implemented — pending pipeline verification |
| **M2-extract** | Strangler extraction | types re-export ✅; `api.ts` exports shared `http`/`computeClient` (first runtime import) ✅ + additive `authHeader` on api-client; axios `api` kept; remaining = migrate axios call sites per domain | 🔄 in progress (verify a build) |
| **B7** | `apps/mobile` | Expo/RN consuming `@homepilot/*` via babel-alias + Metro watchFolders (no workspace change); tabs Home/Imagine/Devices/Account; Imagine streams progress via SSE (`react-native-sse` EventTransport); compute-client now camelCases responses (snake API ⇄ camel types). SSOT usage typechecks. | 🔄 foundation (run `npm install && expo start` to verify) |
| **B8** | Family/org sharing | cloud `SupplierPolicy` (migration `0005`) + `/v1/devices*` policy API + tier-2 routing behind `SHARING_TIERS_ENABLED` (8 tests, ollabridge-cloud); mobile Devices tab wired to `listUserDevices`/`get`/`setDevicePolicy`. Node `hello.node.sharing` ingestion still ⬜. | ✅ cloud + mobile (flag-gated) |
| **M4** | Optional relocate | `git mv frontend apps/web`, `git mv desktop apps/desktop` (mechanical, history-preserving) | ⬜ |

## Decisions taken (for this additive bootstrap)

- **Package manager: npm workspaces.** The repo already uses npm; this avoids a
  destructive pnpm conversion of `frontend/`. pnpm + Turborepo remains the
  documented future upgrade (`MONOREPO_AND_WAVE_B.md` §4) — switching later is a
  lockfile change, not a code change.
- **Internal packages export TypeScript source** (`main`/`exports` → `src/index.ts`),
  the Turborepo "internal packages" pattern — no per-package build step in dev;
  the consuming bundler (Vite/Metro) transpiles.
- **Scope discipline:** only the four foundation packages are stood up now.
  `frontend/`/`desktop/` are **not** touched and **not** yet workspace members —
  they join in M2 when extraction begins.

## Activate the workspace (when ready)

```bash
npm install           # at repo root — links @homepilot/* and installs turbo/tsc
npm run typecheck     # turbo runs typecheck across packages
```

Existing apps are unaffected: `cd frontend && npm install && npm run build`
still works exactly as before.
