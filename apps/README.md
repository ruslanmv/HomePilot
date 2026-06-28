# `apps/` — platform applications

> **Status: design-only.** This folder currently documents the target structure;
> only `apps/mobile/` (design docs) exists so far. Creating it is additive and
> changes nothing in the existing `frontend/`, `desktop/`, or `backend/`.

Each app is a **thin, platform-specific UI**. All product logic, API/compute
clients, auth, types, and design tokens come from `../packages/*` — the single
source of truth. See **[`../docs/design/MONOREPO_AND_WAVE_B.md`](../docs/design/MONOREPO_AND_WAVE_B.md)**
for the full design.

| App | Platform | Source today | Notes |
|---|---|---|---|
| `web/` | Browser | `../frontend/` (until Phase M4) | Vite + React 18 SPA — the canonical UI |
| `desktop/` | Win/macOS/Linux | `../desktop/` (until Phase M4) | Electron shell wrapping the web build |
| `mobile/` | iOS / Android | **here (new)** | Expo / React Native (Wave B · Batch 7) |

**Migration note:** `frontend/` and `desktop/` keep working at their current
paths and are registered as workspace members as-is. They relocate into `apps/`
only in the optional, mechanical Phase M4 (`git mv`, history-preserving) — never
a prerequisite for the shared-packages benefit.

**What belongs in an app (and not in a package):** navigation, screen layouts,
gestures, native storage/permissions/camera, push notifications, window/tray,
and the platform adapters that satisfy the ports declared in `../packages/*`.
