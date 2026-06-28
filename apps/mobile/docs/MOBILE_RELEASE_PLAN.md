# HomePilot Mobile — Build & Release Plan (Android + iOS)

**Goal:** ship installable mobile clients of HomePilot the same way the desktop
app ships — built by GitHub Actions, attached to a **GitHub Release**, and
offered as a one‑click **thumbnail/card on `getting-started.html`** that always
points at the latest version.

**Principles (same as the rest of this repo):** additive, non‑destructive,
*reuse what already works*. We mirror the existing `desktop.yml` workflow and
the existing release‑aware JS on the getting‑started page rather than inventing
a parallel system.

> **Status (v1 decision: Android only).**
> - ✅ **M0** build foundation — `apps/mobile/package-lock.json`, branded
>   `scripts/generate-icon.mjs` (icon + adaptive icon), `scripts/set-version.mjs`,
>   `app.json` icon/splash/plugin wiring, npm scripts.
> - ✅ **M0** signing — `plugins/withAndroidReleaseSigning.js` (release signing
>   from CI secrets, debug fallback).
> - ✅ **M1** Android CI — `.github/workflows/mobile.yml` builds the APK and
>   attaches it to the Release.
> - ✅ **M3** page thumbnail — Android download card + iPhone "coming soon" card
>   on `docs/getting-started.html` (live `.apk` link + size, mobile OS detection).
> - ⏳ **M2** iOS — deferred by decision; the iOS card reads "coming soon".
>   Revisit with the phased path below (sideload IPA → TestFlight/App Store).
> - ⏳ **M4** remaining — `MOBILE.md` shipped; store presence (M5) later.

---

## 0. The one honest constraint you must decide up front: Android ≠ iOS

A free, "download the file and tap to install" experience **exists on Android**
and **does not exist on stock iOS**. This is an Apple policy limit, not a build
limit, and it shapes the whole plan.

| | Android | iOS |
|---|---|---|
| Distributable file | `.apk` | `.ipa` |
| Install from a website link? | ✅ Yes — enable "install unknown apps", tap the APK | ❌ No — stock iOS refuses unsigned/unknown `.ipa` |
| Cost to publish for free | **$0** (self‑signed keystore) | **$99/yr** Apple Developer for the *good* path |
| Truly‑free path | GitHub Release APK (this plan, Batch M1) | Sideload via **AltStore/Sideloadly** using the user's *own* Apple ID — app expires every **7 days**, max 3 apps/device |
| Recommended real path | APK now + Google Play later (optional, $25 once) | **TestFlight** public link (free for testers, needs the $99 account) → App Store |

**What this means for the page:** the Android card is a normal "Download `.apk`"
button. The iOS card cannot be — it links to either a short **sideload guide**
(free, no account) or a **TestFlight join link** (once we pay for the account).
We design both and switch the iOS card with one variable.

> **Open decision (see end of doc): which iOS path do we commit to for v1?**
> The rest of the plan is built so Android ships independently of that answer.

---

## 1. What we're mirroring (so this is reuse, not new infra)

- **`.github/workflows/desktop.yml`** — already: triggers on `release: published`
  *and* `workflow_dispatch`; derives the version from the tag / input /
  `package.json`; matrix‑builds; uploads artifacts; attaches them to the
  Release (or creates one on manual dispatch). The mobile workflow copies this
  shape verbatim, so **one published Release ends up holding desktop installers
  *and* the mobile APK/IPA together.**
- **`docs/getting-started.html`** — already fetches
  `api.github.com/repos/ruslanmv/HomePilot/releases/latest`, maps assets by file
  extension (`.exe/.dmg/.AppImage/.deb`), fills in real download URLs + sizes,
  detects the OS and highlights "Your system". We just add `.apk`/`.ipa` to that
  same map and add Android/iOS detection — **no new fetch, no rewrite.**

---

## 2. Current state of `apps/mobile` (facts this plan is grounded in)

- **Expo SDK 51, managed workflow** — there is no committed `android/` or `ios/`
  directory, so CI must run `npx expo prebuild` to generate the native projects.
- `app.json`: `name: HomePilot`, `slug: homepilot`, `version: 0.1.0`,
  `ios.bundleIdentifier` / `android.package` = `com.ruslanmv.homepilot`.
- Shared `@homepilot/*` packages resolve via **babel `module-resolver` aliases →
  `../../packages/*/src`** plus **Metro `watchFolders`**. This already works in
  dev, and the native release build bundles JS through the same Metro/babel
  config, so the shared packages are included automatically. CI just needs the
  full monorepo checked out (it is) and the app's own `node_modules`.
- **Gaps that block a *real* binary (handled in Batch M0):**
  - No `apps/mobile/package-lock.json` → `npm ci` can't run yet.
  - No app **icon/splash** in `app.json` → prebuild would use ugly Expo
    placeholders.
  - No `versionCode` (Android) / `buildNumber` (iOS) mapping from the release tag.

---

## 3. Batches

Each batch is small, additive, and independently shippable. Android (M0–M1) is
the free deliverable and does not depend on the iOS decision.

### Batch M0 — Build foundation *(prereqs; no CI yet)*
1. **Commit a mobile lockfile**: run `npm install` in `apps/mobile` and commit
   `apps/mobile/package-lock.json` so CI is reproducible (`npm ci`).
2. **App identity assets**: add `apps/mobile/assets/icon.png` (1024×1024),
   `adaptive-icon.png` (foreground), and `splash.png`; wire them in `app.json`
   (`expo.icon`, `expo.android.adaptiveIcon`, `expo.splash`). Derive from the
   existing brand mark (the house‑logo SVG already in the site nav) so mobile
   matches desktop/web.
3. **Version plumbing**: a tiny `scripts/set-version.mjs` that takes a semver and
   writes `expo.version`, derives an integer `expo.android.versionCode` and
   `expo.ios.buildNumber` (e.g. from the tag), mirroring `desktop.yml`'s
   "Derive version → inject into package.json" steps.
4. **npm scripts** in `apps/mobile/package.json`: `prebuild`, `build:android`
   (gradle `assembleRelease`), `build:ios` (xcodebuild archive + unsigned
   export), so CI just calls scripts (same ergonomics as desktop `build:win`
   etc.).

*Deliverable:* the app builds locally to an installable APK. Nothing in CI yet,
nothing user‑facing changed.

### Batch M1 — Android APK → GitHub Releases *(the free win)*
New job in `.github/workflows/mobile.yml` (full draft in §4), `runs-on:
ubuntu-latest`:
`checkout → setup‑node(22)+java(17) → derive version → npm ci (apps/mobile) →
set version → expo prebuild --platform android → sign with keystore → gradlew
assembleRelease → rename to HomePilot-<version>-android.apk → upload artifact +
attach to the Release`.

- **Signing**: keystore stored as `ANDROID_KEYSTORE_BASE64` (+ password/alias
  secrets). If the secret is absent (forks/dev), fall back to a generated
  debug keystore so the APK is still installable for testing, and label it
  clearly. A *stable* release keystore must be kept for the life of the app
  (changing it breaks in‑place updates).
- **Output name**: `HomePilot-<version>-android.apk` so the page's asset matcher
  finds it by `.apk`.

*Deliverable:* every published Release carries a sideloadable Android APK.

### Batch M2 — iOS `.ipa` *(phased; pick a phase in the Open Decision)*

**M2a — Free, no Apple account (sideload IPA).** Add an `ios` job on
`runs-on: macos-latest` (free on public repos): `expo prebuild --platform ios →
pod install → xcodebuild archive CODE_SIGNING_ALLOWED=NO → wrap the `.app` in an
unsigned `Payload/…ipa`` → attach `HomePilot-<version>-ios.ipa` to the Release.`
The page's iOS card links to a **sideload guide** (AltStore/Sideloadly). Honest
caveat shown to users: free Apple‑ID sideloads expire after 7 days.

**M2b — TestFlight / App Store ($99/yr, recommended for real users).** When the
Apple Developer account exists, add an export step that signs with an **App
Store Connect API key** (`APPSTORE_KEY_ID/ISSUER_ID/P8` secrets) and runs
`eas submit` *or* `xcrun altool`/`fastlane pilot` to push the build to
TestFlight. The page's iOS card becomes a **"Join the TestFlight beta"** link.
No 7‑day expiry; standard 90‑day TestFlight build cycle.

*These are mutually compatible:* we can ship M2a now and add M2b later without
touching Android or the page structure (just the iOS card's target URL).

### Batch M3 — getting‑started page: the mobile thumbnail
Add a **"Also on mobile"** row beneath the desktop platform grid with two cards
(Android, iOS), styled with the existing `.platform-card` classes (full
HTML/JS draft in §5):
- Extend the existing asset matcher to also map `.apk` → Android card and
  `.ipa` → iOS card (URL + size), reusing the same `fetch` already on the page.
- Extend `detectOS()` to recognize `android` / `ios` user agents; when a visitor
  is *on a phone*, promote the matching mobile card to the primary button and
  mark it "Your system".
- iOS card target = sideload guide (M2a) or TestFlight link (M2b) — a single
  `IOS_INSTALL_URL` constant.

*Deliverable:* exactly what was asked — a single new thumbnail on
`getting-started.html` that downloads the latest Android (and offers the latest
iOS) client.

### Batch M4 — Release orchestration + docs
- Because `mobile.yml` and `desktop.yml` both trigger on `release: published`,
  the existing release process is unchanged: tag `vX.Y.Z` → publish Release →
  **both** workflows attach their assets to it. Document this in a top‑level
  `MOBILE.md` (mirroring `DESKTOP.md`) covering build, signing, and install.
- Add a `mobile` row to the README download table and the release‑notes template.
- Update `apps/mobile/README.md` with the local build commands from M0.

### Batch M5 — Store presence *(optional, later)*
Google Play internal‑testing track (one‑time $25) and Apple App Store listing.
Pure addition; the GitHub‑Release APK/sideload path keeps working for users who
prefer it.

---

## 4. Draft workflow — `.github/workflows/mobile.yml` (Android job shown in full)

```yaml
name: "📱 Build Mobile Apps"

on:
  release:
    types: [published]
  workflow_dispatch:
    inputs:
      version:
        description: "Version (e.g. 1.0.0). Empty = app.json version."
        required: false
      create_release:
        description: "Create a GitHub Release with the built apps"
        type: boolean
        default: true

permissions:
  contents: write

concurrency:
  group: mobile-build
  cancel-in-progress: true

jobs:
  android:
    name: Build Android APK
    runs-on: ubuntu-latest
    outputs:
      version: ${{ steps.version.outputs.version }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "22" }
      - uses: actions/setup-java@v4
        with: { distribution: "temurin", java-version: "17" }

      - name: Derive version           # same logic as desktop.yml
        id: version
        shell: bash
        run: |
          if [ "${{ github.event_name }}" = "release" ]; then RAW="${GITHUB_REF#refs/tags/}";
          elif [ -n "${{ github.event.inputs.version }}" ]; then RAW="${{ github.event.inputs.version }}";
          else RAW=""; fi
          if [ -n "$RAW" ]; then SEMVER="${RAW#v}";
          else SEMVER=$(node -p "require('./apps/mobile/app.json').expo.version"); fi
          echo "version=$SEMVER" >> "$GITHUB_OUTPUT"

      - name: Install deps
        working-directory: apps/mobile
        run: npm ci

      - name: Set version + versionCode
        run: node apps/mobile/scripts/set-version.mjs "${{ steps.version.outputs.version }}" "${{ github.run_number }}"

      - name: Expo prebuild (Android)
        working-directory: apps/mobile
        run: npx expo prebuild --platform android --no-install

      - name: Sign config (keystore from secret, else debug fallback)
        working-directory: apps/mobile/android
        env:
          KS: ${{ secrets.ANDROID_KEYSTORE_BASE64 }}
        run: |
          if [ -n "$KS" ]; then echo "$KS" | base64 -d > app/release.keystore; fi

      - name: Build release APK
        working-directory: apps/mobile/android
        env:
          ORG_GRADLE_PROJECT_HP_STORE_PASSWORD: ${{ secrets.ANDROID_KEYSTORE_PASSWORD }}
          ORG_GRADLE_PROJECT_HP_KEY_ALIAS: ${{ secrets.ANDROID_KEY_ALIAS }}
          ORG_GRADLE_PROJECT_HP_KEY_PASSWORD: ${{ secrets.ANDROID_KEY_PASSWORD }}
        run: ./gradlew assembleRelease --no-daemon

      - name: Rename APK
        run: |
          mkdir -p out
          cp apps/mobile/android/app/build/outputs/apk/release/app-release.apk \
             out/HomePilot-${{ steps.version.outputs.version }}-android.apk

      - uses: actions/upload-artifact@v4
        with: { name: HomePilot-android, path: out/*.apk, retention-days: 90 }

      - name: Attach to release
        if: github.event_name == 'release'
        uses: softprops/action-gh-release@v2
        with: { files: out/*.apk }

  # ios:  (Batch M2 — runs-on: macos-latest; unsigned IPA for M2a or
  #        App-Store-Connect-signed + TestFlight submit for M2b)
```

(The `ios` job and the `workflow_dispatch`→create‑release branch follow the same
patterns already present in `desktop.yml`.)

---

## 5. Draft page change — mobile card on `getting-started.html`

**Markup** (drop in after the existing `.platform-grid`, reusing existing CSS):

```html
<h3 class="mobile-heading">Also on <span class="gradient-text">mobile</span></h3>
<div class="platform-grid mobile-grid">
  <a href="https://github.com/ruslanmv/HomePilot/releases/latest"
     class="platform-card" id="card-android" aria-label="Download for Android">
    <div class="platform-icon">🤖</div>
    <div class="platform-name">Android</div>
    <div class="platform-format">.apk · sideload</div>
    <span class="platform-size" id="size-android"></span>
  </a>
  <a href="IOS_INSTALL_URL" class="platform-card" id="card-ios"
     aria-label="Get HomePilot for iPhone">
    <div class="platform-icon">🍏</div>
    <div class="platform-name">iPhone / iPad</div>
    <div class="platform-format" id="ios-format">TestFlight / sideload</div>
    <span class="platform-size" id="size-ios"></span>
  </a>
</div>
```

**JS** (add to the existing `assets.forEach` matcher + `detectOS`):

```js
// in the asset map:
else if (n.endsWith('.apk')) map.android = a;
else if (n.endsWith('.ipa')) map.ios = a;
// after building the map:
setCard('card-android', 'size-android', map.android);   // APK → direct download
if (map.ios) setCard('card-ios', 'size-ios', map.ios);  // only if we ship an IPA
// detectOS(): add
if (/Android/i.test(ua)) return 'android';
if (/iPhone|iPad|iPod/i.test(ua)) return 'ios';
```

The iOS card's `href` (`IOS_INSTALL_URL`) is the single switch between the M2a
sideload guide and the M2b TestFlight link.

---

## 6. Secrets required (set in repo → Settings → Secrets)

| Secret | For | Needed when |
|---|---|---|
| `ANDROID_KEYSTORE_BASE64` | base64 of the release `.jks` | M1 release builds |
| `ANDROID_KEYSTORE_PASSWORD` / `ANDROID_KEY_ALIAS` / `ANDROID_KEY_PASSWORD` | keystore creds | M1 release builds |
| `APPSTORE_KEY_ID` / `APPSTORE_ISSUER_ID` / `APPSTORE_API_KEY_P8` | App Store Connect API key | **M2b only** (TestFlight/App Store) |

Android is the only thing needed for the free launch. No secret at all still
produces a (debug‑signed) testable APK.

---

## 7. Versioning & tagging
- Keep the existing `vX.Y.Z` tag → published Release flow. Both desktop and
  mobile workflows derive the version from the tag, so assets stay in lockstep.
- `versionCode` (Android) / `buildNumber` (iOS) come from the CI run number (or
  a monotonic derivation of the semver) so each upload is strictly increasing —
  a store requirement and good hygiene for sideloads.

## 8. Non‑destructiveness / risk notes
- New files only: `mobile.yml`, `apps/mobile/scripts/*`, `apps/mobile/assets/*`,
  a lockfile, and *additive* markup on `getting-started.html`. No existing
  workflow, route, or page section is modified destructively.
- If the mobile workflow is never given signing secrets, it still succeeds with
  a testable artifact; it never blocks the desktop release.
- iOS honesty is built‑in: we never imply a one‑tap iPhone install that Apple
  doesn't allow.

---

## 9. Open decision — iOS path for v1

This is the only fork that needs your call, because it costs money and changes
what the iOS card does:

- **A. Free now, paid later (recommended):** ship Android APK + an unsigned iOS
  `.ipa` with a sideload guide now ($0); add TestFlight when ready ($99/yr).
- **B. Pay now for the good iOS UX:** set up the Apple Developer account and go
  straight to TestFlight public links (no 7‑day expiry), skipping the sideload
  IPA.
- **C. Android only for v1:** ship the APK now; the iOS card says "coming soon"
  and links to a notify/star CTA. Add iOS later.

Android (Batches M0–M1) and the page thumbnail (M3) proceed identically in all
three; only Batch M2 + the iOS card target differ.
