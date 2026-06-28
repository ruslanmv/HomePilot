# HomePilot Mobile (`apps/mobile`)

Expo / React Native client (Wave B · Batch 7). A thin, mobile-native UI over the
shared **`@homepilot/*`** packages — the *same* api-client, compute-client,
types, auth, and design tokens the web app uses. No forked product logic.

> **Status: minimal foundation.** Three tabs (Home / Imagine / Account) that
> prove end-to-end consumption of the shared packages on device. It's additive —
> nothing in `frontend/`, `backend/`, `desktop/`, or the deploy pipeline is
> touched, and it does **not** join the npm workspace.

## What it demonstrates

- **Single source of truth:** `src/lib/client.ts` builds `@homepilot/api-client`
  + `@homepilot/compute-client` with the same `X-API-Key` auth as the web app.
- **Ports & adapters:** `src/lib/storage.ts` implements the `@homepilot/auth`
  `TokenStorage` port with `expo-secure-store` (Keychain/Keystore).
- **Shared design tokens:** screens style from `@homepilot/ui`.
- **Real flows:** Home shows `getComputeStatus()`; Imagine runs
  `createImageJob()` + polls `getJobStatus()`; Account stores the backend URL +
  API key securely.

## How the shared packages resolve (no workspace change)

Same alias strategy as the web frontend — `@homepilot/*` → `../../packages/*/src`
via **`babel.config.js`** (module-resolver) for the bundle and
**`metro.config.js`** (`watchFolders`) so Metro transpiles the package sources.
`tsconfig.json` mirrors it with `paths` for the editor. Nothing is published or
linked through `node_modules`.

## Run

```bash
cd apps/mobile
npm install              # or: npx expo install   (pins native versions)
npx expo start           # press i / a, or scan in Expo Go
npm run typecheck        # tsc --noEmit
```

Set the **backend URL** (and optional API key) on the Account tab — on device
there is no `window.location`, so the host is configured, not inferred. It
defaults to `http://localhost:8000` (`src/lib/client.ts`).

## Production notes (slot in later, no rework)

- **Navigation:** ✅ `@react-navigation/bottom-tabs` is wired in `App.tsx`
  (dark theme from `@homepilot/ui` tokens; a `withSafeTop` wrapper handles the
  top inset so the screens stay untouched). Labels-only for now — add
  `@expo/vector-icons` + `tabBarIcon` for production.
- **Job progress:** replace the Imagine poll loop with
  `computeClient.subscribeToJobEvents(...)` + a `react-native-sse` transport
  adapter (the `EventTransport` port already exists in `@homepilot/compute-client`).
- **Pairing/push/deep-links:** `@homepilot/auth` already exposes
  `startPairing()`; add `expo-notifications` and the `homepilot://` scheme
  (already set in `app.json`).
- **Release:** ✅ Android APK is built by CI and attached to each GitHub Release
  — `.github/workflows/mobile.yml` (Expo prebuild → Gradle `assembleRelease`).
  See **[`../../MOBILE.md`](../../MOBILE.md)** for the build/sign/install guide
  and `docs/MOBILE_RELEASE_PLAN.md` for the full batched plan. iOS
  (TestFlight/App Store) is a later batch.

## Build a release APK

```bash
cd apps/mobile
npm ci
node scripts/set-version.mjs 1.0.0 1      # version + versionCode
node scripts/generate-icon.mjs            # branded icons (also auto in CI)
npx expo prebuild --platform android --no-install
cd android && ./gradlew assembleRelease   # → app/build/outputs/apk/release/app-release.apk
```

Without `ANDROID_KEYSTORE_*` Gradle props the APK is debug-signed (testing
only); provide them (CI does, from secrets) for a release-signed build. The
`withAndroidReleaseSigning` config plugin wires the signing config in
automatically during prebuild.

Full design: `../../docs/design/MONOREPO_AND_WAVE_B.md` §7.1.
