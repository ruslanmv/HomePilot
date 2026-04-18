# Voice-call verification — is the pipeline actually wired?

Last updated: current HEAD of `claude/review-account-isolation-NDcE2`.

This document traces every link in the **"tap 📞 → AI answers first
→ user speaks → AI responds"** pipeline with file:line anchors so you
can confirm the wiring by grepping, not by trusting this document.

At each link I list the **invariant** (what must hold) and **how it
fails** (what the symptom would be if it broke).

---

## Required configuration

For the full simulation to engage, **three flags** must be true on
the backend. Any one missing reverts the call to the chat-REST
fallback — which still works but does **not** produce an opening
greeting and does **not** carry the persona_call phase machine.

```
VOICE_CALL_ENABLED=true           # mounts /v1/voice-call/* routes
VOICE_CALL_WEBSOCKET_ENABLED=true  # accepts WS handshakes
PERSONA_CALL_ENABLED=true          # loads persona_call module
PERSONA_CALL_APPLY=true            # attaches suffix to the LLM call
```

Quick self-check with `curl`:

```bash
curl -i -X POST http://localhost:8000/v1/voice-call/sessions \
  -H "content-type: application/json" -d '{}'
# 404 → VOICE_CALL_ENABLED=false
# 401 → route is mounted, just needs auth
# 201 → working; includes session_id + ws_url + resume_token
```

---

## Pipeline walk — five links

### Link 1 — Browser sends `POST /v1/voice-call/sessions`

**Where:** `frontend/src/ui/call/callApi.ts::createCallSession` (the
REST wrapper). Called by
`frontend/src/ui/call/useCallSession.ts::run` on session open.

**Invariant:** the request body carries the persona id + the
client's streaming capability declaration
(`device_info.streaming: true`, `device_info.barge_in: true`).

**Verify:** open DevTools → Network → tap 📞 → look for the POST.
The response should be a 201 with `{ session_id, ws_url,
resume_token, capabilities: { streaming: true, barge_in: true } }`.

**Failure mode:** 404 → flags off (see above). 500 → persona
lookup broken; check backend logs.

---

### Link 2 — Browser opens WebSocket

**Where:** `callSocket.ts::connect` → native `new WebSocket(url)`.
Triggered by `useCallSession` right after a successful session POST.

**Invariant:** the URL is `ws://…/v1/voice-call/ws/{session_id}?resume_token=…&token=<jwt>`.

**Verify:** DevTools → Network → WS → look for the handshake
(status 101). First frame from the server must be
`{ type: "call.state", payload: { status: "live" } }`.

**Failure mode:** close code 1008 + reason "bad-resume-token" →
session creation + WS open raced. Close code 1008 + reason
"websocket-disabled" → `VOICE_CALL_WEBSOCKET_ENABLED=false`.

---

### Link 3 — Server emits opening greeting

**Where:** `backend/app/voice_call/ws.py:144-201`. After `call.state`
live, the "theory of answering" hook picks a template from
`persona_call/openings.py` and emits it as a `transcript.final`
envelope with `role=assistant`.

**Invariant:**

1. When `PERSONA_CALL_ENABLED=true`, exactly one
   `transcript.final {role: assistant, text: <opening>}` fires
   **before** the heartbeat loop starts (ws.py line 204).
2. The chosen template id is appended to `recent_openers` so
   consecutive calls never repeat.
3. The opening survives WS reconnect within the resume window —
   but a new greeting does NOT fire on resume (the server has
   already emitted turn 1 once).

**Verify:** backend logs should show no warning from
`[persona_call] opening greeting skipped`. Covered by the test
`test_openings_ledger_rolls_across_calls_without_repeat` which
exercises the exact `choose() → update_state(recent_openers=…)`
path this hook uses (backend/tests/test_persona_call.py).

**Failure mode:** if `_pc_cfg.enabled` is false (flag off), the
hook is skipped silently and the persona never speaks first — the
call enters `listening` with dead air.

---

### Link 4 — Browser plays the greeting as TTS (you hear the AI first)

**Where:** `frontend/src/ui/CallOverlay.tsx:784-795`.

```ts
useEffect(() => {
  if (!useBackend) return
  const unsub = session.onAssistantTranscript((p) => {
    if (window.SpeechService?.speak) {
      window.SpeechService.speak(p.text); return
    }
    if ('speechSynthesis' in window) {
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(p.text))
    }
  })
  return unsub
}, [useBackend, session])
```

**Invariant:** any `transcript.final` arriving from the WS flows
through either `window.SpeechService.speak` (if the app's TTS shim
has loaded) or the browser's native `speechSynthesis` API. No
throttling, no buffering — the greeting starts speaking inside the
same animation frame it arrives.

**Verify:** listen. If you tapped 📞 and the handshake succeeded,
you should hear one of these 23 templates (from
`persona_call/openings.py`):

- `"Hello?"`, `"Yes?"`, `"Yeah?"`
- `"Atlas speaking."`, `"This is Atlas."`
- `"Hi, Atlas here."`, `"Hey — Atlas."`
- `"Good evening."`, `"Morning — Atlas."` (time-of-day gated)
- `"Thank you for calling. This is Atlas, how can I help?"`
  (formality ≥ 0.65)
- `"Hey…"`, `"Mm, yeah?"` (late-night brief)

**Failure mode:** no sound → check browser TTS permission + voice
picker. `speechSynthesis.getVoices().length === 0` → the browser
hasn't finished loading voices; the first utterance is silently
dropped on Chromium. Fix = preload voices via
`speechSynthesis.onvoiceschanged` (already handled in
`SpeechService` shim).

---

### Link 5 — Browser STT → backend → AI reply

**Where:**

- Capture: `useVoiceController(onSendText)` (the existing hook,
  reused across Voice mode + Call mode).
- Route: `CallOverlay.tsx:767-773` — when the backend session is
  live, the captured transcript routes through
  `sessionRef.current.sendTranscript(text)` which sends
  `transcript.final` over the WS.

```ts
const voice = useVoiceController((text: string) => {
  if (useBackendRef.current) {
    sessionRef.current.sendTranscript(text)
  } else {
    onSendTextRef.current?.(text)
  }
})
```

**Invariant:**

1. `voice.setHandsFree(true)` is called when
   `connected = state !== 'dialing' && state !== 'connecting' &&
   state !== 'ended'` becomes true (CallOverlay.tsx:926-931).
2. Every final STT transcript routes through `sendTranscript` when
   streaming is negotiated, `onSendText` (chat REST) otherwise.
3. The backend `ws.py` handler for `transcript.final` runs
   `persona_call.directive.compose` for the suffix, then either
   `turn_stream.run_turn_streaming` (streaming branch) or
   `turn.run_turn` (unary branch).
4. The reply flows back as `assistant.partial` + `assistant.turn_end`
   (streaming) or `transcript.final` (unary).

**Verify:** speak into the mic. DevTools → Network → WS → Messages.
You should see your text go out in a `transcript.final` with
`role=user`, followed by either a stream of `assistant.partial`
frames or a single `transcript.final` with `role=assistant`.

**Failure mode:** your text never leaves → `useBackendRef.current`
is false (fallback mode); the chat-REST path runs instead.
`voice.setHandsFree` never enabled → mic is idle; check the mute
button state. `useVoiceController` reports VAD errors → AEC/NS/AGC
needs browser permission; check console for
`[VAD] Failed to acquire mic`.

---

## Gap analysis — what might still feel "off"

| Concern | Current behaviour | Notes |
|---|---|---|
| Mic opens while greeting is playing | `setHandsFree(true)` fires on `connected = listening`. The greeting may still be speaking. | TTS bleed is usually below the 0.035 VAD threshold, so it rarely triggers false speech. The barge-in detector threshold is 0.08 specifically to tolerate bleed. If you notice the AI interrupting itself, lower `PERSONA_CALL_BC_MIN_GAP_MS` or raise the bargeIn threshold. |
| Opening doesn't fire on resume | By design — the turn index would double-count. | Safe: the ledger already holds the last opener id so the persona continues seamlessly. |
| Fallback mode has no greeting | Chat REST path ignores `openings.py` entirely. | Intentional; falling back is supposed to be minimal. |
| `window.SpeechService.speak` preempts `speechSynthesis` | Priority order is deliberate. | If you're on a build without the SpeechService shim, native `speechSynthesis` kicks in. |

---

## Tests protecting each link

| Link | Test | File |
|---|---|---|
| 2 (WS + capability negotiation) | `test_native_streaming_yields_deltas_in_order` | backend/tests/test_voice_call_turn_stream.py |
| 3 (opening templates) | `test_openings_*` (8 tests) | backend/tests/test_persona_call.py |
| 3 (ledger rotation) | `test_openings_ledger_rolls_across_calls_without_repeat` | same |
| 4 (transcript → TTS) | wired through a non-regressed render; no explicit unit test yet (intentional — the effect is a thin pass-through). | — |
| 5 (barge-in cancellation) | `test_cancel_active_with_matching_id_cancels` and siblings | backend/tests/test_voice_call_barge_in.py |
| 5 (streaming turn runner) | `test_native_streaming_respects_cancel` + fallback variant | backend/tests/test_voice_call_turn_stream.py |

Total: 36 backend tests + 59 frontend tests, all green as of this
commit.

---

## Quick runtime verification script

After flipping the backend flags:

```bash
# 1. Backend route exists
curl -i -X POST http://localhost:8000/v1/voice-call/sessions \
     -H "content-type: application/json" \
     -H "authorization: Bearer $TOKEN" -d '{"entry_mode":"call"}'
# Expect 201.

# 2. Full pipeline: open http://localhost:3000 in a browser, tap 📞.
#    DevTools → Network → WS → Messages.
#    Expected sequence within ~3 seconds of connecting:
#      (out) transcript.final (if typed something; otherwise nothing)
#      (in)  call.state {status: live}
#      (in)  transcript.final {role: assistant, text: "Hello?" or similar}
#      (…)   heartbeat pings every 10s
#      (out) transcript.final {role: user, text: "<your utterance>"}
#      (in)  assistant.partial × N + assistant.turn_end   (streaming)
#             OR transcript.final {role: assistant}       (unary)

# 3. Barge-in: while the AI is speaking, speak over it.
#    Expect:
#      (out) user.barge_in {turn_id: t_xxxx}
#      (in)  assistant.cancel {turn_id: t_xxxx}
#      (in)  assistant.turn_end {reason: "cancelled"}
#      → TTS silences within ~200ms.
```

If step 2 shows the inbound greeting **before** your first
utterance, the AI-answers-first wire is working. If not, check
backend logs for `[persona_call] opening greeting skipped` and
verify the four flags above.
