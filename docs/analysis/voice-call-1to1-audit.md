# Voice-call 1-to-1 audit — "can we speak with the AI like a person?"

**Status:** audit / action plan. Not design.

**Question from the product owner:** *"The AI on the phone must feel
like we're talking to a human, not an AI. Are we there yet? If not,
what's the gap?"*

Short answer: **the plumbing is right; two bugs were hiding it from
production, one config gate has to be flipped, and one architectural
change (token streaming) is the remaining deal-breaker for the
"human feel." Everything else is within reach of the current
design.**

---

## 1. What the user sees today

The symptom the owner screenshotted:

```
POST /v1/voice-call/sessions → 404 Not Found  (×4)
```

Tap 📞 → overlay opens → `useCallSession` POSTs → backend returns 404
→ `status = "unavailable"` → the overlay falls back to the regular
chat REST path. Under that fallback:

- the persona never speaks first (no WS → no `call.state live` →
  the `openings.py` greeting hook never fires)
- no backchannels, no filler, no phase machine
- every turn takes the standard chat latency (1–3 s)

**Root cause:** `VOICE_CALL_ENABLED=false` server-side. The router
only mounts when that flag is true (`main.py:170`). Fix is one env
var; added to `.env.example` with full context in this commit.

## 2. Two silent bugs that were compounding the problem

Even once the flag is flipped, two bugs would have kept the
greeting from firing. Both fixed in this commit.

### 2.1 Ledger slice was returning a scalar

`voice_call/ws.py` was doing:

```python
new_openers = (list(forbidden) + [tpl.id])[-max(1, cfg.opener_ledger_window)]
#                                         ^^^^^^^ index, not slice
```

That reads as "the element at position -N", not "the last N
elements." So `recent_openers` was being written as a single string
like `"sa_hello"` instead of a list. Downstream reads then go
through `list(stored_value or [])` which turns the string into
`['s','a','_','h','e','l','l','o']`. Anti-repetition silently
ceased to work.

Fix: `[-window:]` (real slice).

### 2.2 Column name mismatch

`ws.py` wrote `recent_openings=new_openers`. The schema column
(defined in `persona_call/store.py`) is **`recent_openers`**
(different word). `update_state` silently swallowed the mismatch in
production because the whole hook is wrapped in a broad `try /
except` — so the greeting _and_ the ledger write were failing
together, invisibly, whenever the flags were on.

Fix: rename the kwarg to match the column.

Both bugs are now covered by a new test
(`test_openings_ledger_rolls_across_calls_without_repeat`) that
simulates 11 consecutive greetings and asserts no duplicate inside
any sliding window of size `opener_ledger_window`.

## 3. Current end-to-end latency path (with flags on)

```
user stops talking
       │
       │ (150–400 ms STT finalization, in-browser, useVoiceController)
       ▼
transcript.final  ─────▶  /v1/voice-call/ws/{sid}
                                   │
                                   │  (5 ms persona_call.directive.compose)
                                   ▼
                         POST /v1/chat/completions  (non-streaming)
                                   │
                                   │  600 ms → latency.FillerScheduler
                                   │           emits "hmm…" to client
                                   │          (Stivers 700 ms trouble cap)
                                   │
                                   │  (500–2000 ms full LLM turn)
                                   ▼
assistant.filler  ─ WS ─▶  client plays "hmm…"
transcript.final  ─ WS ─▶  client feeds text to TTS
                                   │
                                   │  (200–500 ms TTS synth + first audio)
                                   ▼
                              user hears persona
```

Round-trip: **1.5 – 3.0 s per turn**. The filler covers the worst
case from "you stopped speaking" to "you hear something back," but
the persona's actual reply lands with a ~1.5 s floor.

For reference, the canonical human-conversation latency from
Stivers et al. (2009) is ~200 ms modal, ~700 ms trouble threshold.
We fire a filler under 600 ms; the full reply still arrives after
the trouble threshold.

## 4. Call-centre AI industry baseline

What production voice AI systems do today that beats ours:

| Pattern | Industry | HomePilot today |
|---|---|---|
| Streaming LLM tokens | ElevenLabs Conversational, OpenAI Realtime, Retell AI | ❌ non-streaming chat |
| Streaming TTS (synth per token chunk) | ElevenLabs, Cartesia, Rime | ❌ browser TTS plays the whole string |
| Streaming STT partials | Deepgram, AssemblyAI, OpenAI Whisper Streaming | ⚠️ browser STT emits partials but we only consume `final` |
| Server-side barge-in (user interrupts TTS) | All above | ❌ user speech during TTS is dropped |
| Turn-detection on silence + semantics | Retell, Pipecat | ⚠️ silence-only (no semantic end-of-turn detection) |
| Persona-aware greeting on pickup | Retell (agent script), Cognigy | ✅ `openings.py` |
| Backchannels during user speech | Soul Machines, Sonantic | ✅ `backchannel.py` (gated behind WS) |
| Filler under LLM wait | Pipecat, Retell | ✅ `latency.py` |
| Anti-repetition ledger | (few — this is a niche best-practice) | ✅ `repeat.py` |
| Phase machine (opening/topic/closing) | Rare (Retell scripts are linear) | ✅ `state.py` |
| Persona voice facets | Sesame AI, ElevenLabs | ✅ `facets.py` |

We're ahead of the industry on the conversational-structure layer
(phase machine, ledger, openings bank). We're behind on the
**audio pipeline**: streaming LLM + streaming TTS.

## 5. What the remaining gap actually costs

The "feels like AI, not a person" signal is dominated by two
measurable things:

1. **First-audio latency from end-of-user-turn.** Humans on the
   phone start a reply within ~200 ms. We start a reply within ~1.5 s
   (filler masks this but doesn't solve it).
2. **No barge-in.** If the user tries to interrupt, the persona
   keeps speaking until the TTS finishes. Humans stop instantly.

Both are fixed by the same architectural change: **token-streaming
LLM → streaming TTS → VAD-driven interrupt of in-flight audio.**

## 6. The ordered plan (actionable, not aspirational)

### Phase 0 — now (this commit)

- Fix the two ledger bugs (done).
- Document VOICE_CALL / PERSONA_CALL flags in `.env.example` (done).
- Add ledger regression test (done).

### Phase 1 — enable the WS path (config, not code)

Set in backend env:

```
VOICE_CALL_ENABLED=true
VOICE_CALL_WEBSOCKET_ENABLED=true
PERSONA_CALL_ENABLED=true
PERSONA_CALL_APPLY=true
```

Restart. The 404 goes away, the frontend `useCallSession` flips
from 'unavailable' to 'live', the persona greets on pickup, the
phase machine + ledger + backchannels + filler all run.

**This alone takes us from "silent AI" to "AI that picks up the
phone and answers naturally within the first turn." The per-turn
latency is still 1.5–3 s.**

### Phase 2 — streaming chat endpoint

Add a streaming variant of `voice_call/turn.py` that:

- calls the chat endpoint with `stream=true`
- emits an `assistant.transcript.partial` WS event per token chunk
- the client feeds each chunk to a streaming TTS (Cartesia /
  ElevenLabs / Piper-WASM's streaming mode)
- a `done=true` marker closes the turn

Expected delta: first-audio latency drops from ~1.5 s to ~250 ms.
This is the single biggest "feels human" improvement we can make.

### Phase 3 — server-side barge-in

In the WS loop, if `transcript.partial` arrives from the client
while the server is mid-reply, the server:

- stops emitting further assistant chunks
- sends `assistant.cancel` so the client kills in-flight TTS
- treats the interrupt as the next user turn

Expected delta: the persona stops speaking the instant the user
starts. This is the other half of the "feels human" signal.

### Phase 4 — semantic turn-taking

Replace pure silence-based end-of-turn detection with a small
classifier on the partials:

- "um I was just thinking, so…"  → trailing hedge, DON'T end turn
- "I was just thinking about it." → clean sentence, DO end turn

This is what production voice AI vendors call "turn detection" and
it's the last 10% — brings the perceived latency from "good" to
"unnervingly good."

## 7. Verification checklist for the owner

Once Phase 1 is flipped on:

1. Open chat, click 📞. The network tab should show
   `POST /v1/voice-call/sessions → 201` (not 404).
2. The WebSocket to `/v1/voice-call/ws/{session_id}` should open.
3. Within ~500 ms of "live" state, you should see an inbound
   `transcript.final` with `role=assistant` — the persona's
   opening line (one of the 23 templates in `openings.py`).
4. The card-end waveform should animate based on real mic level
   while you're speaking, and on the synthesised envelope while
   the persona is speaking.
5. Ending the call should send `call.control end` and you should
   see the `CallMemoryCard` appear inline in the chat with a
   factual "Voice session completed · 7:36 PM".

If any of those fails, the commit that introduced it is easy to
bisect — each one has a named module and a test.

## 8. What the simulation is still *not*

- **Not a replacement for a real voice-native API** like OpenAI
  Realtime or ElevenLabs Conversational. Phase 2+3 closes most of
  the gap but those vendors have years of head start on audio
  quality specifically.
- **Not a substitute for streaming TTS.** Browser Web Speech is
  OK; Piper-WASM is better; Cartesia / ElevenLabs streaming is best.
- **Not a turn-detector.** Phase 4 is a separate ML model we don't
  have in-tree yet.

Nothing in the current code blocks those additions. Every phase
above is a strict superset of what's already shipped.
