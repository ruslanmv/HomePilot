# HomePilot Monorepo (`apps/` + `packages/`) & Wave B Design

**Status:** design-only · additive · non-destructive
**Supersedes:** the top-level `mobile/` design scaffold (relocated to `apps/mobile/`).
**Companion to:** `../../ollabridge-cloud/docs/MULTIMODAL_UPGRADE_BATCHES.md`
(master plan) and `jobs-protocol.md` (the Wave A relay/job contract).

This redesigns Wave B (Batches 7–8) around the industry-standard structure for a
multi-platform product: **one repository, shared packages as the single source of
truth for logic/types/clients, and separate app folders per platform.** The goal
is that a fix or feature written once propagates to web, desktop, and mobile
automatically — no duplication, no manual sync, no version drift.

---

## 0. Principle (and the "why")

> **Separate app folders. Shared packages. Platform-specific UX. One source of
> truth for everything that isn't UI.**

- **Not full unification** — mobile genuinely differs from desktop/web in
  navigation, gestures, permissions, storage, push, app-store builds,
  camera/gallery, and performance. Forcing one UI makes either the desktop app
  too thin or the mobile app too heavy.
- **Not full duplication** — copying the API client, auth, compute/job logic,
  types, and design tokens into three apps guarantees drift and triples
  maintenance.

This follows the same guidance the ecosystem documents: Expo recommends
monorepos when multiple apps share code as a single source of truth; React
Native provides `.ios`/`.android`/`.native` file extensions precisely so logic is
shared and only the platform edges differ; Electron exists to wrap one web
codebase as a desktop app.

---

## 1. Target structure

```text
HomePilot/
├── apps/
│   ├── web/         # (future home of frontend/) HomePilot Cloud web app — Vite/React
│   ├── desktop/     # (future home of desktop/)  Electron shell wrapping apps/web
│   └── mobile/      # NEW — Expo / React Native (Batch 7)
│
├── packages/                 # ← the single source of truth
│   ├── types/         @homepilot/types          # shared TS DTOs
│   ├── config/        @homepilot/config         # env, constants, feature flags
│   ├── api-client/    @homepilot/api-client     # HTTP to HomePilot backend + OllaBridge Cloud
│   ├── auth/          @homepilot/auth           # login, sessions, token storage (port), pairing
│   ├── compute-client/@homepilot/compute-client # jobs, progress, devices, policy, credits
│   ├── core/          @homepilot/core           # personas, generation builders, validation, analytics
│   └── ui/            @homepilot/ui             # design tokens (+ optional shared primitives)
│
├── frontend/        # ← UNCHANGED today; becomes apps/web in Phase M4 (optional, mechanical)
├── desktop/         # ← UNCHANGED today; becomes apps/desktop in Phase M4 (optional, mechanical)
├── backend/         # ← UNCHANGED (Python; not part of the JS workspace)
├── pnpm-workspace.yaml   # NEW (Phase M0)
├── turbo.json            # NEW (Phase M0)
└── package.json          # extended with workspace config (keeps existing devDeps)
```

During migration the workspace lists **both** the legacy paths (`frontend`,
`desktop`) and the new ones (`apps/*`, `packages/*`), so nothing has to move for
the architecture to start paying off (see §7).

---

## 2. The packages — your single source of truth

Each package is an internal, versionless (`workspace:*`) library consumed by the
apps. This table is the contract; implementations are Wave-B work, not designed
here line-by-line.

| Package | Owns | Representative public surface | Consumed by |
|---|---|---|---|
| `@homepilot/types` | All shared DTOs | `Persona`, `Job`, `JobEvent`, `Artifact`, `ComputeStatus`, `Device`, `SupplierPolicy`, `CreditsWallet` | every package + app |
| `@homepilot/config` | Env, constants, **client feature flags**, base URLs, build profiles | `getBaseUrl()`, `flags.sharingTiers`, `flags.computeModeDefault` | api-client, apps |
| `@homepilot/api-client` | Base HTTP: auth header, retries, error normalization, transport | `createClient({ baseUrl, tokenProvider, fetchImpl })` | compute-client, core, apps |
| `@homepilot/auth` | Login, session refresh, **device pairing** (`/device/start`→`/poll`), token storage **port** | `signIn()`, `signOut()`, `useSession()`, `startPairing()`, `TokenStorage` (interface) | apps (inject platform storage) |
| `@homepilot/compute-client` | **The heart of Wave A/B reuse** | `createImageJob()`, `createVideoJob()`, `editImage()`, `getJobStatus()`, `subscribeToJobEvents()`, `getComputeStatus()`, `listUserDevices()`, `getDevicePolicy()`, `setDevicePolicy()`, `getWallet()` | every app |
| `@homepilot/core` | Domain/product logic | personas, generation-request builders, validation schemas (zod), analytics event taxonomy | every app |
| `@homepilot/ui` | **Design tokens** (color/spacing/typography/motion) + optional cross-platform primitives | `tokens`, (optional) `Button`, `Card` | every app |

**Why `compute-client` matters most:** Wave A's job API and Batch 8's
device/policy logic live here *once*. Web, desktop, and mobile all call
`createImageJob()` / `getDevicePolicy()` — so "share my GPU with family",
job-progress handling, and the compute-status pill behave identically and are
fixed in one place.

---

## 3. Shared vs. platform-specific

The discipline that keeps logic shared and apps thin: **shared packages never
import a platform API directly** — they declare a port (interface) and each app
injects the adapter at its boundary (ports-&-adapters / dependency injection).

| Shared (in `packages/*`) | Platform-specific (in `apps/*`) |
|---|---|
| Auth + session logic | Sign-in screen layout, biometric prompt |
| API + compute/job clients | Loading/skeleton UI, gestures |
| Device pairing flow | Camera/QR scan, deep-link handling |
| Compute-status logic | The status **pill** component |
| Job creation + **progress events** | Progress UI (toast vs. inline) |
| Credits wallet logic | Paywall / store screens |
| Personas data model + builders | Persona cards, studio panels |
| Generation request/result types | Media grid vs. mobile media tiles |
| Validation schemas | Form widgets, keyboard handling |
| Feature flags, analytics events | Navigation (sidebar vs. bottom tabs) |
| Design **tokens** | Native components, window/tray, push |

**Ports that each app adapts** (declared in packages, implemented per app):

| Port (package) | web (`apps/web`) | desktop (`apps/desktop`) | mobile (`apps/mobile`) |
|---|---|---|---|
| `TokenStorage` (`auth`) | `localStorage` | Electron `safeStorage` | `expo-secure-store` (Keychain/Keystore) |
| `fetchImpl` (`api-client`) | `fetch` | `fetch` | `fetch` (RN) |
| `EventTransport` (`compute-client`) | `EventSource` (SSE) | `EventSource` | `react-native-sse` or polling |
| `Notifier` | Web Notifications | Electron notifications | APNs/FCM via Expo Notifications |

This is the technique that makes "the same logic everywhere" actually hold:
shared code is pure and testable; native concerns stay at the edges.

---

## 4. Tooling — pnpm + Turborepo + TS project references

Recommended, and aligned with Expo's monorepo guidance:

- **pnpm workspaces** — strict, efficient, first-class Expo/Metro support
  (symlinked workspace packages resolve cleanly). The existing `frontend` npm
  lockfile imports via `pnpm import` (mechanical; no app-code change).
- **Turborepo** — task graph + local/remote caching (`build`, `lint`, `test`,
  `typecheck`) across apps and packages; one `turbo run build` builds the world
  with caching.
- **TypeScript project references** — fast incremental builds, enforce package
  boundaries.
- **Changesets** — only if/when a package is published externally; internally
  apps consume `workspace:*` (always the in-repo version).
- **Expo + Metro note** — `apps/mobile/metro.config.js` adds `watchFolders` for
  the repo root and enables `nodeModulesPaths`/`disableHierarchicalLookup` per
  Expo's documented monorepo setup so RN resolves the shared packages.

Blueprint (created in Phase M0, shown here for precision — not yet committed):

```yaml
# pnpm-workspace.yaml
packages:
  - "apps/*"
  - "packages/*"
  - "frontend"   # legacy path, kept until Phase M4
  - "desktop"    # legacy path, kept until Phase M4
```

```jsonc
// turbo.json
{ "pipeline": {
    "build": { "dependsOn": ["^build"], "outputs": ["dist/**", "build/**"] },
    "lint": {}, "typecheck": {}, "test": {} } }
```

> **Fallback if you want zero package-manager change:** npm workspaces (npm ≥7)
> also work with Turborepo and keep `frontend` on npm — but pnpm is the better
> long-term fit for Expo. Recommendation: pnpm.

---

## 5. "Upgrade once, propagate everywhere"

Because every app depends on packages via the **workspace protocol**
(`"@homepilot/compute-client": "workspace:*"`), there is **no version drift**:

```text
Fix a job-polling bug in packages/compute-client
  → apps/web picks it up on next build
  → apps/desktop (wraps apps/web) picks it up automatically
  → apps/mobile picks it up on next build
One change. Three apps updated. No copy, no version bump, no sync PR.
```

This is exactly the requirement ("desktop upgrades become automatic/trivial when
mobile upgrades"): shared behavior lives in one package, and desktop — which
wraps the web build — inherits it for free. Turborepo's task graph rebuilds only
what changed and its dependents, so the propagation is also fast.

---

## 6. Non-destructive migration plan (the critical part)

The existing `frontend/` and `desktop/` must never break. Migration is a
**strangler** pattern — stand up the structure, extract logic incrementally,
relocate folders last (and only if desired).

| Phase | Action | Risk / reversibility |
|---|---|---|
| **M0 — Workspace, change nothing** | Add `pnpm-workspace.yaml`, `turbo.json`, extend root `package.json`; register `frontend`, `desktop` as members. Their build commands are unchanged. | Zero — purely additive; delete the 2 files to revert. |
| **M1 — Empty packages** | Create `packages/{types,config,api-client,auth,compute-client,core,ui}` with `package.json` + `tsconfig` + stub `index.ts`. No app depends on them yet. | Zero — nothing imports them. |
| **M2 — Extract logic incrementally** | Move one module at a time from `frontend/src` into a package; update `frontend` imports to `@homepilot/*` (or re-export from the old path). Each is a tiny PR; web app stays green. Order: types → config → api-client → compute-client → auth → core → ui-tokens. | Low — per-module, independently testable/revertible. |
| **M3 — Build `apps/mobile`** | Expo app consumes `@homepilot/*` from day one (Batch 7). | Additive — new app. |
| **M4 — (Optional, later) relocate** | `git mv frontend apps/web`, `git mv desktop apps/desktop`; update workspace globs + CI paths. History-preserving, mechanical, isolated to one PR. | Low — pure move; can stay at legacy paths indefinitely if preferred. |

**Key point:** the architecture and the "single source of truth" benefit are
fully realized by **M2** — the physical folder relocation (M4) is cosmetic and
optional. You get shared packages without moving the existing apps.

---

## 7. Wave B in this structure

### 7.1 Batch 7 — `apps/mobile` (Expo / React Native + TS)

Mobile is a thin UI over `packages/*`. It reuses **all** logic and **none** of
the desktop layout.

```text
apps/mobile/
├── app.config.ts · eas.json · metro.config.js · package.json · tsconfig.json
├── src/
│   ├── navigation/         # React Navigation — bottom tabs + stacks
│   ├── screens/            # Chat | Imagine | Gallery | Devices | Account
│   │   ├── ChatScreen.tsx · ImagineScreen.tsx · GalleryScreen.tsx
│   │   ├── DevicesScreen.tsx        # Batch 8 (uses compute-client device APIs)
│   │   └── AccountScreen.tsx
│   ├── components/         # ComputeStatusPill, MediaTile, PromptBar (RN)
│   ├── adapters/           # SecureStore token storage, SSE transport, notifier
│   └── theme/              # consumes @homepilot/ui tokens
└── assets/
```

- **Bottom tabs** (consumer UX): `Chat | Imagine | Gallery | Devices | Account`
  — deliberately *not* the desktop sidebar/multi-panel layout.
- **Logic** = `@homepilot/{auth,api-client,compute-client,core,types,config}`.
- **Native concerns** (adapters/app-level): `expo-secure-store` for tokens
  (Keychain/Keystore), Expo Notifications (APNs/FCM), deep links
  (`homepilot://`) for pairing-code hand-off, `expo-image-picker`/camera for
  edit/img2img, safe-area + gesture handling.
- **Build/release:** EAS Build (dev/preview/production) + EAS Submit; closed
  beta via TestFlight + Play Internal Testing.

### 7.2 Batch 8 — share to family/org devices

**Client logic lives once in `@homepilot/compute-client`** (`listUserDevices`,
`getDevicePolicy`, `setDevicePolicy`, `subscribeToJobEvents`) and is consumed by
a `DevicesScreen` on mobile and a device dashboard panel on web/desktop — same
logic, platform-specific screens. This is the monorepo paying off directly:
Batch 8's "share my GPU" behavior is implemented and tested in one package.

The **backend/cloud/node** side of Batch 8 is unchanged from the prior design
and is independent of this frontend restructure:
- **Cloud:** new `SupplierPolicy` table (migration `0005`), `hello.node.sharing`
  ingestion, `/v1/devices*` policy/history routes, router **tiers 2–3** as new
  candidate sources over Batch 5 — all behind `SHARING_TIERS_ENABLED` (default
  off). "Family/org" reuses the existing `Org`/`OrgMembership` (no new
  primitive).
- **Node:** `sharing_policy.py` + dashboard "Cloud" tab toggles + Pause Sharing.

Non-destructive: default policy (`allow_my_account` only) ≡ Wave A; with the flag
off, routing is byte-for-byte Batch 5.

---

## 8. Desktop strategy

Keep the working Electron app — **don't rewrite it.** `apps/desktop` wraps the
`apps/web` build and adds native features (tray, notifications, local-file
access, local OllaBridge discovery, Docker management it already does). It
consumes the same `packages/*`, so it inherits every shared-logic upgrade
automatically (§5). Tauri is a lighter alternative noted for the future, but
there's no reason to migrate a functioning Electron shell now.

---

## 9. Apple / Android enterprise best-practices checklist

- **Platform UX:** iOS HIG + Android Material affordances; `.ios.tsx`/`.android.tsx`
  where they diverge; safe areas, native gestures, large-title/back behavior.
- **Security:** tokens in Keychain/Keystore via `expo-secure-store`; never in
  AsyncStorage; certificate-aware HTTP via the shared client.
- **Notifications:** Expo Notifications → APNs/FCM; job-complete pushes from the
  `Notifier` port.
- **Releases:** EAS Build + Submit; semantic app versioning; **OTA via EAS Update
  only for JS-safe changes**, native changes go through the stores.
- **Accessibility & i18n:** RN a11y props + a shared i18n catalog in `core`.
- **Quality gates:** Turborepo `typecheck`/`lint`/`test` on every PR; package
  boundaries enforced by TS project references.

---

## 10. Sequencing & first PRs

1. **M0 (additive):** `pnpm-workspace.yaml` + `turbo.json` + root `package.json`
   workspace globs; `frontend`/`desktop` build unchanged. One PR, no behavior
   change.
2. **M1:** scaffold the seven `packages/*` (stubs). One PR.
3. **M2 (the value):** extract `types` → `config` → `api-client` →
   `compute-client` first (these unblock both Batch 7 and Batch 8). Small PRs.
4. **Batch 7:** `apps/mobile` on the packages → closed beta.
5. **Batch 8:** add device/policy methods to `compute-client` + the cloud/node
   pieces (flag-gated) + a `DevicesScreen` (mobile) and panel (web).
6. **M4 (optional):** relocate `frontend`→`apps/web`, `desktop`→`apps/desktop`.

## 11. Open decisions (confirm before building)

1. **Package manager:** pnpm (recommended, best Expo fit) vs. npm workspaces
   (zero PM change). 
2. **Monorepo runner:** Turborepo (recommended, lightweight) vs. Nx (heavier,
   more codegen/enforcement).
3. **Relocate now or later:** move `frontend`/`desktop` into `apps/` up front
   (one mechanical PR) vs. leave them at legacy paths and relocate post-M2
   (recommended — maximizes non-destructiveness).
4. **`@homepilot/ui` scope:** tokens-only (safest cross-platform) vs. a shared
   component layer (e.g. Tamagui) for true write-once primitives.
