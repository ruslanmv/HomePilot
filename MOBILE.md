# HomePilot Mobile

Native mobile client for **Android** (and **iOS**, coming soon).
An [Expo](https://expo.dev) / React Native app (`apps/mobile`) that talks to your
HomePilot backend and runs generations against your own GPU — the same shared
`@homepilot/*` logic the web and desktop apps use.

The desktop counterpart is documented in [`DESKTOP.md`](DESKTOP.md).

---

## Download

Pre-built apps are attached to each [GitHub Release](https://github.com/ruslanmv/HomePilot/releases),
and the latest is one tap away on the
[Getting Started page](https://ruslanmv.github.io/HomePilot/getting-started.html).

| Platform | File | Install |
|----------|------|---------|
| **Android** | `HomePilot-x.x.x-android.apk` | Enable **Install unknown apps** for your browser, then open the APK |
| **iPhone / iPad** | — | **Coming soon** (via TestFlight / App Store) |

> **Why no iPhone file yet?** Unlike Android, Apple does not allow installing an
> app from a downloaded file on a stock iPhone — iOS distribution requires
> TestFlight or the App Store (a paid Apple Developer account). It's planned as a
> follow-up; see [`apps/mobile/docs/MOBILE_RELEASE_PLAN.md`](apps/mobile/docs/MOBILE_RELEASE_PLAN.md).

---

## First run

1. Install and open the app.
2. On the **Account** tab, **sign in** with your OllaBridge Cloud email +
   password. The app exchanges them for a token (`POST /v1/auth/login`) and
   stores it in the device keychain (`expo-secure-store`) — no manual URL
   needed for a default install. The backend URL / access-token fields are still
   there under **Advanced** as a fallback (on a phone there's no
   `window.location`, so the host can be configured rather than inferred).
3. Talk on the **Voice** tab (hold to speak), chat on **Chat**, and run
   image jobs from **Imagine** — generations run on the GPU your account routes
   to (your own paired PC by default).

The tabs are **Voice · Chat · Home · Imagine · Devices · Account**. Voice and
the neural "premium voice" upgrade are server-side features — see
[Voice & premium](#voice--premium) below.

---

## Voice & premium

Voice is a **backend** feature: the app opens a WebSocket, streams mic audio,
and plays audio back, while the server does STT → LLM → TTS (with barge-in).
That keeps the client thin and means voice **quality is a server-side swap, not
a client change**:

- **Free** — local Piper TTS + local Whisper STT (your own GPU, fully private).
- **Premium** — low-latency neural STT/TTS via an OpenAI-compatible endpoint,
  selected by entitlement. The mobile app shows a single "Premium voice" toggle;
  the audio pipeline is identical.

Both require backend flags described in
[`docs/PRODUCTION.md`](docs/PRODUCTION.md) and [`.env.example`](.env.example)
(`VOICE_BACKEND_ENABLED`, the `STT_*` / `TTS_*` knobs, `PREMIUM_VOICE_ENABLED`).
They are **default-off**: a stock backend serves chat and Imagine exactly as
before until you opt in.

---

## How releases are built

`.github/workflows/mobile.yml` mirrors the desktop pipeline: it triggers on a
published Release (or manual `workflow_dispatch`), and because both workflows
listen for `release: published`, **one tag → one Release** carrying the desktop
installers *and* the Android APK.

Pipeline (Android): `npm ci` → `set-version` → `generate-icon` →
`expo prebuild` → Gradle `assembleRelease` → rename to
`HomePilot-<version>-android.apk` → attach to the Release.

### Cut a release

- **Tag + Release:** publish a GitHub Release `vX.Y.Z` → the workflow builds and
  attaches the APK automatically.
- **Manual:** run the *Build Mobile Apps* workflow (Actions tab) with a version;
  it creates the Release with the APK.

### Signing

For a **release-signed** APK, set these repo secrets (the CI step decodes the
keystore and passes it to Gradle via the `withAndroidReleaseSigning` config
plugin):

| Secret | Value |
|--------|-------|
| `ANDROID_KEYSTORE_BASE64` | `base64 -w0 release.keystore` |
| `ANDROID_KEYSTORE_PASSWORD` | keystore password |
| `ANDROID_KEY_ALIAS` | key alias |
| `ANDROID_KEY_PASSWORD` | key password |

Generate a keystore once and keep it for the life of the app (changing it breaks
in-place updates):

```bash
keytool -genkeypair -v -keystore release.keystore -alias homepilot \
  -keyalg RSA -keysize 2048 -validity 10000
```

Without these secrets the workflow still succeeds but produces a **debug-signed**
APK (fine for testing, not for the Play Store).

---

## Build locally

```bash
cd apps/mobile
npm ci
node scripts/set-version.mjs 1.0.0 1
node scripts/generate-icon.mjs
npx expo prebuild --platform android --no-install
cd android && ./gradlew assembleRelease
# → apps/mobile/android/app/build/outputs/apk/release/app-release.apk
```

Requires Node 22 + JDK 17 + the Android SDK. For day-to-day development use
`npx expo start` (see [`apps/mobile/README.md`](apps/mobile/README.md)).

---

## Roadmap

- ✅ Android APK on every Release + Getting Started download card.
- ✅ Streaming chat, one-tap voice, persona picker (MB1–MB4).
- ✅ Email/password sign-in + push notifications (MB7–MB8).
- ✅ Tab icons + `eas.json` (development / preview-APK / production-AAB) (MB9).
- ✅ Premium-voice and cloud-GPU-burst entitlement seams (MB5–MB6, server-side).
- ⏳ iOS: unsigned IPA for sideloading, then TestFlight → App Store.
- ⏳ QR/code pairing onboarding (token sign-in ships today; the device-scoped
  `pair-simple` QR flow is the next onboarding step).
- ⏳ EAS over-the-air beta channel wired to the `preview` profile.

Full plans:
[`apps/mobile/docs/MOBILE_RELEASE_PLAN.md`](apps/mobile/docs/MOBILE_RELEASE_PLAN.md)
(build/ship) and
[`apps/mobile/docs/MOBILE_UPGRADE_BATCHES.md`](apps/mobile/docs/MOBILE_UPGRADE_BATCHES.md)
(MB0–MB9 feature batches). Production rollout:
[`docs/PRODUCTION.md`](docs/PRODUCTION.md).
