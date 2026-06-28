# `packages/` — the single source of truth

> **Status: design-only.** This folder documents the shared-package catalog; the
> packages are not implemented yet. Standing them up is additive (Phase M1) and
> breaks nothing. Full design: **[`../docs/design/MONOREPO_AND_WAVE_B.md`](../docs/design/MONOREPO_AND_WAVE_B.md)**.

Every app in `../apps/*` (and the legacy `../frontend`, `../desktop`) consumes
these internal packages via the workspace protocol (`"@homepilot/x": "workspace:*"`),
so there is **no version drift** — a change here propagates to web, desktop, and
mobile on their next build.

## Catalog

| Package | Owns | Representative exports |
|---|---|---|
| `@homepilot/types` | Shared DTOs | `Persona`, `Job`, `JobEvent`, `Artifact`, `ComputeStatus`, `Device`, `SupplierPolicy`, `CreditsWallet` |
| `@homepilot/config` | Env, constants, client feature flags | `getBaseUrl()`, `flags.sharingTiers`, `flags.computeModeDefault` |
| `@homepilot/api-client` | Base HTTP (auth header, retries, errors, transport port) | `createClient({ baseUrl, tokenProvider, fetchImpl })` |
| `@homepilot/auth` | Login, sessions, **device pairing**, token-storage **port** | `signIn`, `signOut`, `useSession`, `startPairing`, `TokenStorage` |
| `@homepilot/compute-client` | **Jobs, progress, devices, policy, credits** | `createImageJob`, `createVideoJob`, `editImage`, `getJobStatus`, `subscribeToJobEvents`, `getComputeStatus`, `listUserDevices`, `getDevicePolicy`, `setDevicePolicy`, `getWallet` |
| `@homepilot/core` | Domain/product logic | personas, generation-request builders, zod validation, analytics events |
| `@homepilot/ui` | Design **tokens** (+ optional primitives) | `tokens` (color/spacing/type/motion) |

## Golden rules

1. **No platform APIs in packages.** Declare a port (interface); each app injects
   the adapter (`TokenStorage`, `fetchImpl`, `EventTransport`, `Notifier`). This
   keeps shared code pure, testable, and identical across platforms.
2. **Types flow down, never up.** Apps import `@homepilot/types`; packages never
   import from apps.
3. **`compute-client` is the Wave A/B heart.** Job creation, progress handling,
   the compute-status pill data, and Batch 8's device/policy logic live here once
   and are shared by all apps.
