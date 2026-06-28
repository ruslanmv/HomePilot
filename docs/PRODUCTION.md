# HomePilot — Production Readiness (mobile + voice + cloud burst)

This is the operator guide for taking the **mobile / voice / premium** stack
(batches MB0–MB9) to production. It is deliberately additive: every feature here
is **flag-gated and default-off or default-free**, so a stock backend keeps
serving chat and Imagine exactly as it does today until you opt in.

Companion docs:
- [`MOBILE.md`](../MOBILE.md) — install + build the mobile app.
- [`DEPLOYMENT.md`](../DEPLOYMENT.md) — the core Docker/compose stack.
- [`apps/mobile/docs/MOBILE_UPGRADE_BATCHES.md`](../apps/mobile/docs/MOBILE_UPGRADE_BATCHES.md)
  — the MB0–MB9 feature batches and their non-destructiveness guarantees.
- OllaBridge Cloud control plane:
  `ollabridge-cloud/docs/FREEMIUM_PRODUCTION_READINESS.md`.

---

## 1. What is production-ready today

| Capability | State | How it's enabled |
|---|---|---|
| **OllaBridge Cloud** (control plane) | ✅ live | Hugging Face Space **`ruslanmv/ollabridge`** → `https://ruslanmv-ollabridge.hf.space` (verified RUNNING). |
| **Mobile Android APK** | ✅ CI-built | `.github/workflows/mobile.yml` → APK attached to each GitHub Release (verified installable: aapt badging + apksigner). |
| **Mobile sign-in** (MB7) | ✅ | `POST /v1/auth/login` (cloud) → JWT in `expo-secure-store`. |
| **Streaming chat** (MB1) | ✅ | `POST /v1/chat/completions` — no new route. |
| **Voice session** (MB2) | ⚙️ flag | `VOICE_BACKEND_ENABLED=true` → `WS /v1/voice/session`. |
| **Free voice** (Piper TTS + local Whisper STT) | ⚙️ config | `PIPER_VOICE_MODEL`, `WHISPER_MODEL` (§2). |
| **Premium neural voice** (MB5) | ⚙️ flag | `PREMIUM_VOICE_ENABLED=true` + `TTS_*`/`STT_*` (§3). |
| **Cloud-GPU burst** (MB6) | ⚙️ flag | `HOMEPILOT_COMPUTE_MODE=auto` (+ optional premium gate, §4). |
| **Push notifications** (MB8) | ✅ | Expo push; `POST /v1/push/register` (cloud), best-effort. |

"⚙️ flag" = shipped and tested, off by default. Turning a flag on never changes
any other path.

---

## 2. Enable voice (free, on your own GPU)

Voice runs **server-side**: the client streams mic audio over a WebSocket and
plays audio back; the backend does STT → LLM → TTS with barge-in. This is why
voice quality is a server swap, not a client change.

```bash
# 1) Turn the voice route on (otherwise WS /v1/voice/session rejects connections)
VOICE_BACKEND_ENABLED=true

# 2) Free local TTS — Piper (the engine HomePilot already uses for story/persona
#    speech). Active only when a voice model is present; else voice is text-only.
PIPER_BINARY=piper                 # on PATH (default: "piper")
PIPER_VOICE_MODEL=/models/en_US-amy-medium.onnx

# 3) Free local STT — faster-whisper. Active only when WHISPER_MODEL is set AND
#    the faster-whisper package is installed.
WHISPER_MODEL=base                 # base | small | medium
```

With (1) only, voice works **text-in / voice-out off** (the client can still send
typed turns and receive replies). Add (2) for spoken replies, (3) for spoken
input. Everything is local — nothing leaves the user's GPU.

---

## 3. Enable premium neural voice (entitlement seam)

Premium is a **quality** upgrade, never a gate on the core. When
`PREMIUM_VOICE_ENABLED=true` **and** a neural TTS endpoint is configured,
entitled sessions use low-latency neural STT/TTS; everyone else stays on free
Piper/Whisper. Both speak the OpenAI-compatible `/audio/*` shape, so the provider
can be OpenAI, Groq, a local whisper.cpp server, or any compatible gateway.

```bash
PREMIUM_VOICE_ENABLED=true

# Neural TTS (POST {TTS_BASE_URL}/audio/speech)
TTS_BASE_URL=https://api.openai.com/v1   # required to enable neural TTS
TTS_API_KEY=sk-...                       # optional for keyless gateways
TTS_MODEL=tts-1                          # default: tts-1
TTS_VOICE=alloy                          # default: alloy

# Cloud STT (POST {STT_BASE_URL}/audio/transcriptions)
STT_BASE_URL=https://api.openai.com/v1   # required to enable cloud STT
STT_API_KEY=sk-...
STT_MODEL=whisper-1                      # default: whisper-1
```

> The mobile client shows a single **"Premium voice"** toggle and never changes
> its audio pipeline — proving the thin-client thesis. The global
> `PREMIUM_VOICE_ENABLED` flag is the seam a **per-user** entitlement check
> replaces once billing exists; it is never wired to *remove* free voice.

Selection logic lives in `backend/app/voice/providers.py`
(`get_tts_provider(premium=…)` / `get_stt_provider()`): neural when entitled +
configured, else Piper/Whisper, else silent text-only — it degrades safely.

---

## 4. Cloud-GPU burst ("works when your PC is off")

In `HOMEPILOT_COMPUTE_MODE=auto`, when the user's local GPU is offline HomePilot
can burst a job to a paired GPU via OllaBridge Cloud. **The local GPU is never
gated.** By default the burst works for everyone (today's behaviour); make it
premium-only with two flags.

```bash
HOMEPILOT_COMPUTE_MODE=auto                       # local | ollabridge_cloud | auto
OLLABRIDGE_CLOUD_URL=https://ruslanmv-ollabridge.hf.space
OLLABRIDGE_CLOUD_TOKEN=                            # Bearer JWT / ob_ API key

# Make the burst premium-only (both default false → everyone can burst):
COMPUTE_BURST_REQUIRES_PREMIUM=true               # require entitlement to burst
PREMIUM_COMPUTE_ENABLED=true                       # the global entitlement
```

Gating logic: `backend/app/compute/__init__.py` — `_burst_allowed()` is
`(not COMPUTE_BURST_REQUIRES_PREMIUM) or PREMIUM_COMPUTE_ENABLED`; `resolve_mode`
only falls back to cloud in `auto` when the burst is allowed; `compute_status`
surfaces `premium` / `burst` / `burst_gated` to the client status pill. Covered
by `backend/tests/test_compute_burst.py`.

---

## 5. The control plane (OllaBridge Cloud on Hugging Face)

The cloud is **live** at `https://ruslanmv-ollabridge.hf.space` (Space
`ruslanmv/ollabridge`). Mobile and backend default to this URL
(`apps/mobile/src/lib/client.ts` `DEFAULT_CLOUD_URL`, `backend/app/config.py`
`OLLABRIDGE_CLOUD_URL`), so a fresh install needs only a sign-in.

**Production secrets (action required for a hardened deploy).** The Space image
ships **publicly-known default** `TOKEN_PEPPER` / `JWT_SECRET` — long enough to
pass the boot guard, but not secret. For a real deployment set strong values as
**HF Space secrets** (Settings → *Variables and secrets*):

```bash
TOKEN_PEPPER=$(openssl rand -hex 32)
JWT_SECRET=$(openssl rand -hex 32)
```

> ⚠️ Rotating these **invalidates existing JWTs and device pairings** — users
> re-sign-in / re-pair once. Do it during a maintenance window, not silently on a
> Space that already has live users. Full guidance and the boot guard
> (`core/preflight.assert_production_ready`) are in the cloud's
> `docs/FREEMIUM_PRODUCTION_READINESS.md`.

Fair-use, rate-limiting, Postgres, observability, and the GDPR/legal posture for
the control plane are all documented there — this guide covers only the
HomePilot-side enablement.

---

## 6. Mobile release pipeline

| Path | Use |
|---|---|
| **CI APK** | `.github/workflows/mobile.yml` builds + attaches `HomePilot-<version>-android.apk` to each Release (debug-signed fallback; release-signed when the `ANDROID_KEYSTORE_*` secrets are set — see [`MOBILE.md`](../MOBILE.md#signing)). |
| **EAS** | `apps/mobile/eas.json`: `development` (dev client), `preview` (internal **APK**), `production` (store **AAB**, `autoIncrement`). |
| **Local** | `expo prebuild` → `gradlew assembleRelease` (see [`MOBILE.md`](../MOBILE.md#build-locally)). |

iOS is intentionally deferred (no sideload-from-file on stock iOS; needs
TestFlight / a paid Apple Developer account). The workflow and `eas.json` are
structured so adding the iOS lane is additive.

---

## 7. Go-live checklist

**Backend (per deployment that wants voice/premium):**
- [ ] `VOICE_BACKEND_ENABLED=true` if you want voice at all.
- [ ] `PIPER_VOICE_MODEL` set (spoken replies) and/or `WHISPER_MODEL` set +
      `faster-whisper` installed (spoken input) for free voice.
- [ ] For premium: `PREMIUM_VOICE_ENABLED=true` + reachable `TTS_BASE_URL`
      (and `STT_BASE_URL`); verify a synth/transcribe round-trip.
- [ ] Decide burst policy: leave open (default) or set
      `COMPUTE_BURST_REQUIRES_PREMIUM=true` + entitlement.

**Cloud (the shared HF Space):**
- [ ] Strong `TOKEN_PEPPER` / `JWT_SECRET` set as HF Space secrets (§5).
- [ ] Fair-use knobs reviewed (cloud readiness doc §6).
- [ ] `GET /health` and `GET /ready` green.

**Mobile:**
- [ ] `ANDROID_KEYSTORE_*` repo secrets set for a **release-signed** APK
      (keep the keystore for the life of the app).
- [ ] Cut a Release → confirm the APK artifact installs on a device.
- [ ] Sign in, send a chat, hold-to-talk on Voice — end-to-end smoke test.

**Verification bar already met on `claude/practical-ritchie-cb2eu5`:** backend
`pytest` (voice, compute-burst, cloud auth, push) green; mobile `tsc --noEmit`
green; APK build verified on a real CI runner; cloud Space verified RUNNING.
