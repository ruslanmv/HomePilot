# HomePilot Mobile — Upgrade Batches (voice-first, premium, simple)

**Goal:** turn the thin mobile companion into *"Grok's voice companion, but on your own
private GPU."* Deliver the 7 must-haves (`MOBILE_MUSTHAVES` review) **without** making the
client complex.

**Three rules (carried from the rest of this repo):**
1. **Smart backend, thin client.** The hard logic (voice orchestration, STT/TTS,
   persona selection, routing) moves to the **backend + shared `@homepilot/*`
   packages**. The mobile app stays a shell: capture mic → stream → play audio →
   render state. This is the opposite of porting the browser-only voice controller
   into React Native.
2. **Reuse what already works.** We extend existing endpoints, the TTS registry,
   the persona system, the pairing flow, and the compute-mode router — we do not
   rebuild them.
3. **Additive & non-destructive.** Every batch is a new endpoint / new screen /
   new package behind a flag. Nothing existing (web voice mode, desktop stack,
   single-user installs) is changed or removed.

---

## Implementation status (all shipped on `claude/practical-ritchie-cb2eu5`)

✅ **MB0** pairing/auth fix · ✅ **MB1** chat · ✅ **MB2** voice backend ·
✅ **MB2.5** STT + **MB3/3a** voice screen + mic · ✅ **MB4** persona picker ·
✅ **MB5** premium neural voice · ✅ **MB6** cloud-GPU burst ·
✅ **MB7** single sign-in · ✅ **MB8** push notifications · ✅ **MB9** polish (tab
icons, notification handler, `eas.json`).

Verified: backend pytest (voice, compute-burst, cloud auth, push) + mobile
`tsc`. Premium hooks (#4 voice, #5 burst) are server-side entitlement seams —
the client never changes. Follow-ups noted inline: a user-pairing code (vs the
device-scoped `pair-simple`), real chat-history load/save on mobile, and the
web voice mode adopting the MB2 backend session.

---

## What we reuse (inventory — none of this is rebuilt)

| Already shipped | Reused for |
|---|---|
| `pair-simple` + `/device/enroll` (cloud) — code → `device_token` | Mobile one-tap GPU linking (MB0) |
| `/chat` + OpenAI-compat `/v1/chat/completions` (streaming) | Mobile chat (MB1) |
| `apps/mobile/src/lib/eventTransport.ts` (`react-native-sse`) | Streaming transport (MB1, MB3) |
| `ui/voice/*` (VAD, barge-in, `conversationStrategy`, personalities), `VoiceModeGrok` | Voice **state machine** → shared pkg; visual design reference (MB2, MB3) |
| Piper TTS (`story_mode`, `teams/bridge`) + `ui/tts/core/registry` | Backend TTS provider interface; free voice (MB2, MB5) |
| `backend/app/compute/*` + `HOMEPILOT_COMPUTE_MODE=auto` + tier-2 routing | Cloud-GPU burst (MB6) |
| Cloud `User`/`Org`/`ApiKey` + OAuth + email verify | Unified sign-in (MB7) |
| Per-user profile/memory store (`/v1/user-*`, multi-user aware) | History/memory sync (MB8) |
| `@homepilot/{types,api-client,auth,compute-client,core,ui}` | Single source of truth across web + mobile |
| `apps/mobile` Imagine screen (image jobs) | Kept as-is — secondary feature, no work |

---

## The architectural keystone (MB2): move voice to the backend

Today the web voice mode runs **in the browser** (`useVoiceController` + the Web
Speech API for STT). That can't be lifted to React Native (no Web Speech API) and
duplicating it would make the client complex. Instead:

> **One backend voice session both clients call.** The client opens a WebSocket,
> streams mic audio, and plays audio back. The **server** does VAD → STT → LLM
> (streaming) → TTS, and handles **barge-in** (stop TTS when new speech arrives).
> STT and TTS sit behind provider interfaces, so *free Piper* vs *premium neural*
> is a server swap — **zero client change**.

This makes mobile trivial **and** upgrades web (premium voices, no Web-Speech-API
lock-in) from the same investment — the single-source-of-truth win.

---

## Batches

State key: each batch is small, flag-gated, independently shippable. "Client" =
`apps/mobile`; "Backend" = `HomePilot/backend` (and `packages/*` where shared).

### Foundations

**MB0 — Pairing onboarding (kill the "backend URL" field)** · delivers #3
- **Backend:** none new — reuse `pair-simple`. Render a code + **QR** on the
  desktop/web pairing screen (reuse the existing pairing page).
- **Client:** "Link my PC" screen — `expo-camera` QR scan **or** type `ABCD-1234`
  → `pair-simple` → store cloud URL + `device_token` in `expo-secure-store`.
  Demote the manual URL to "Advanced".
- **Additive:** AccountScreen keeps manual entry as a fallback. Flag: none (pure UI).

**MB1 — Streaming text chat on mobile** · delivers #2 (table stakes — mobile has no chat today)
- **Backend:** reuse streaming `/v1/chat/completions` (persona endpoint). No new route.
- **Shared:** add a tiny `@homepilot/chat` (or extend `api-client`) with the
  request + stream parse — used by web **and** mobile.
- **Client:** a Chat screen using the shared client + existing `eventTransport.ts`.
- **Additive:** new screen + new tab. Nothing else touched.

### The backend brain

**MB2 — Backend voice orchestration service** · enables #1, #4
- **Backend (new, flag `VOICE_BACKEND_ENABLED`):** `WS /v1/voice/session` —
  audio in → VAD → **STTProvider** → LLM (streaming) → **TTSProvider** → audio out;
  server-side barge-in. Define `STTProvider` / `TTSProvider` interfaces; ship the
  **Piper** TTS provider (reuse) + a local/Whisper STT provider as the free default.
- **Shared:** extract the voice **state machine** from `ui/voice/useVoiceController`
  into platform-agnostic `@homepilot/voice` (web keeps its Web-Speech adapter; mobile
  gets an `expo-av` adapter). No duplicated logic.
- **Additive:** brand-new endpoint; **web's existing client-side voice mode is
  untouched** and can opt in later.

### The headline

**MB3 — One-tap voice mode on mobile** · delivers #1
- **Client:** full-screen voice screen (mic button, state visualizer, barge-in)
  using `expo-av` audio + the MB2 WebSocket + `@homepilot/voice`. Visual design
  reuses `VoiceModeGrok` (starfield, glow) rebuilt with `@homepilot/ui` tokens.
- **Sub-batches:** **MB3a** push-to-talk MVP (hold to speak) → **MB3b** hands-free
  VAD + barge-in. Ship 3a first.
- **Additive:** new screen; becomes the default home once stable.

**MB4 — Persona / voice companion picker** · delivers #7
- **Shared:** lift the persona list (`personalities` + persona API) into a shared
  package (single source of truth with web).
- **Client:** a 2×3 picker (reuse `VoiceGrid` layout) to choose persona + voice;
  passed to the MB2 session.
- **Additive:** new screen; default persona if unset.

### Premium (the paywall — quality + convenience, never the core)

**MB5 — Premium neural voice tier** · delivers #4
- **Backend:** add a **cloud neural** `TTSProvider` + `STTProvider` behind the MB2
  interfaces; choose engine by entitlement (`MONETIZATION_ENABLED` + plan). Free =
  Piper + local STT; premium = neural, low-latency.
- **Client:** a single "Premium voice" toggle — **no audio-pipeline change**
  (proves the thin-client thesis).
- **Additive:** new providers; default stays free Piper.

**MB6 — Cloud-GPU burst ("works when your PC is off")** · delivers #5
- **Backend/cloud:** reuse `HOMEPILOT_COMPUTE_MODE=auto` + OllaBridge Cloud tier-2
  routing — when the paired GPU is offline, fall back to a cloud GPU (premium).
- **Client:** a status pill + premium toggle; no routing logic on device.
- **Additive:** behaviour already exists; this exposes + gates it.

### Account & stickiness

**MB7 — Unified single sign-in** · delivers #6 (today there are two logins)
- **Backend:** bridge so one identity — the OllaBridge Cloud account (already has
  OAuth/orgs/`ApiKey`) — is consumed by HomePilot. Keep single-user/API-key mode.
- **Client:** a real sign-in screen (OAuth/email) replacing the API-key field;
  reuse `@homepilot/auth`.
- **Additive:** new auth path; existing paths untouched.

**MB8 — Push notifications + history/memory sync** · supporting must-haves
- **Backend:** a push-token registry + emit events ("PC ready", "image done");
  reuse the per-user memory/profile store for cross-device history.
- **Client:** `expo-notifications` registration; conversations follow the account.
- **Additive:** new table + opt-in.

### Ship

**MB9 — Mobile polish + beta/store pipeline**
- Tab icons (`@expo/vector-icons`), the friendly status pill, replace error copy.
- EAS beta channel + store metadata; reuse the shipped `mobile.yml` (APK) and add
  iOS when the iOS decision lands.
- **Additive:** polish only.

---

## Sequencing & dependencies

```
MB0 (link) ─┬─ MB1 (chat) ───────────────────────────────► ship early wins
            └─ MB2 (voice backend) ─┬─ MB3 (voice screen) ─┬─ MB4 (personas)
                                    │                       └─ MB5 (premium voice)
                                    └─ (web also migrates here later)
MB6 (cloud burst)  ── independent, after MB0
MB7 (sign-in) ── after MB0 ──► MB8 (push + history)
MB9 (polish/ship) ── last
```

Critical path to the "wow": **MB0 → MB2 → MB3a**. Everything else layers on.

## Free vs premium (what each batch unlocks)

| Tier | From |
|---|---|
| **Free** (your GPU, private) | MB0 link · MB1 chat · MB3 voice (Piper) · MB4 personas · keep Imagine |
| **Premium** ($) | MB5 neural voice · MB6 cloud-GPU burst · (later) durable history quotas, priority routing, persona packs |

## Non-destructiveness guarantees

- No existing endpoint, screen, or flag is modified destructively — every batch is
  a **new** route / screen / package / provider, default-off or default-free.
- The **web voice mode keeps working unchanged**; MB2 is an opt-in path it can adopt
  later for premium voices.
- **Single-user / API-key installs keep working**; MB7 adds SSO without removing them.
- Mobile **Imagine** and **Devices** screens are untouched.
- Client complexity stays flat: each feature is *a screen + a transport*, with the
  orchestration living server-side or in shared packages.

---

*Companion to `MOBILE_RELEASE_PLAN.md` (build/ship) and the UX review. Grounded in
`apps/mobile/*`, `frontend/src/ui/{voice,call,tts}`, `backend/app/{compute,auth}`,
the cloud pairing/relay APIs, and the `@homepilot/*` shared packages.*
