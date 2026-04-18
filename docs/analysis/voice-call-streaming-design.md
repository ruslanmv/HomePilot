# Voice-call streaming + barge-in — design notes

**Status:** design document. No code changes ship with this doc; the
file only defines the additive mechanism for Phase 2 + Phase 3 of
[`docs/analysis/voice-call-1to1-audit.md`](./voice-call-1to1-audit.md).

**Companion to:**
- [`docs/PHONE.md`](../PHONE.md) — user-facing "theory of answering"
- [`docs/analysis/voice-call-human-simulation-design.md`](./voice-call-human-simulation-design.md) — persona_call architecture
- [`docs/analysis/voice-call-1to1-audit.md`](./voice-call-1to1-audit.md) — the gap analysis this doc closes

**Scope:** the two architectural changes that make the call feel
human rather than AI:

- **Phase 2** — stream LLM tokens end-to-end: server streams chat
  completion chunks → emits partial envelopes on the existing WS →
  client feeds a streaming TTS surface so the persona's voice
  starts inside ~250 ms of the first token, not after the full
  reply arrives.
- **Phase 3** — server-side barge-in: client VAD detects user
  speech-start while the persona is speaking → sends a barge-in
  signal → server cancels the in-flight turn → client stops TTS
  mid-utterance. Round-trip under 200 ms.

**Non-goals:**
- Replacing the current non-streaming chat endpoint.
- Changing the persona prompt, the opening template bank, the
  phase machine, or any persona_call module.
- Moving off browser TTS. The design is TTS-provider-agnostic; a
  streaming TTS plugin is a separate choice, noted in § 5.3 but
  not decided here.
- New authentication, new session model, new DB tables. Every
  change below lives as an optional field on an existing envelope
  or a new envelope type that unaware clients safely ignore.

## 1. Goals (measurable)

Every number below is observable from the browser console or a WS
tcpdump. None require an A/B study.

1. **First-audio latency**: ≤ 600 ms from the client's
   `transcript.final` send to the first TTS audio hitting the
   speaker, P50. Matches Stivers 2009 modal human response latency
   (~200 ms) plus a realistic network + TTS first-chunk budget.
   Current: ~1500 ms P50.
2. **Barge-in cutoff**: ≤ 200 ms from user speech-start to TTS
   audio silent on the speaker, P95. Current: infinite (user can't
   interrupt).
3. **Turn-end detection**: unchanged from today — VAD silence
   window in `useVoiceController`. Semantic endpointing is
   explicitly out of scope (Phase 4 in the audit).
4. **Behavioural compatibility**: with the streaming flag OFF,
   every byte on the wire and every DOM node rendered is identical
   to the current (non-streaming) path. Regression is regression
   by construction, not by review.

## 2. Design constraints (hard)

1. **Additive only.** New envelope types, new optional fields, new
   module files. No rename of any existing field. No deletion of
   any existing envelope. No change to the REST session endpoint.
2. **Flag-gated.** One new flag,
   `VOICE_CALL_STREAMING_ENABLED`, defaults false. Off = current
   behaviour, byte-identical. On = new path engaged for clients
   that advertise support.
3. **Capability-negotiated, not forced.** The client declares
   support via the existing `device_info` field on session create;
   the server advertises support via the existing `capabilities`
   field in the session response. Mismatches degrade gracefully
   (server streams to non-streaming clients by buffering; clients
   degrade to non-streaming when the server doesn't advertise it).
4. **Persona-preserving.** The per-turn system suffix from
   persona_call is still attached exactly once, at the head of the
   turn, before the first token streams. No change to the
   composer.
5. **Unary-semantics preserved.** `assistant.turn_end` closes every
   streamed turn the same way a single `transcript.final` closes
   a non-streamed one. Downstream code that treats a turn as a
   single message doesn't need to know streaming happened.
6. **Cancellation is cooperative.** Barge-in is a two-party
   handshake: client declares, server acks with
   `assistant.cancel`, client stops TTS. No unilateral teardown
   on either side. Orphan state is surfaced as an observable
   error rather than silently swallowed.

## 3. Envelope contracts (additive)

Every change below lands inside the existing WS envelope shape:

```
{ "type": "<event>", "seq": <int>, "ts": <ms>, "payload": { ... } }
```

No new transport, no new path. Only new `type` values and new
optional fields on existing payloads. A client that doesn't know
these types continues to work — the default branch in
`callSocket.ts::dispatch` already logs-and-drops unknown `type`s.

### 3.1 Capability negotiation (session create)

`POST /v1/voice-call/sessions` — adds two optional fields, both
namespaced under existing objects.

- **Request** (new optional field on `device_info`):
  ```json
  { "device_info": { "streaming": true, "barge_in": true, … } }
  ```
  Declares which pieces of the new protocol the client can honour.
  A client that omits this is treated as non-streaming (current
  behaviour).

- **Response** (new optional field on `capabilities`):
  ```json
  { "capabilities": { "streaming": true, "barge_in": true } }
  ```
  Advertises what the *server* can do. The effective mode is
  `min(client.streaming, server.streaming)` — both must agree, or
  the turn runs in unary mode.

Degrade paths:
- Server supports streaming, client does not → server buffers
  partials into a single `transcript.final` (current behaviour).
- Client supports streaming, server does not → client treats
  incoming `transcript.final` as the complete turn (current
  behaviour).
- Neither supports → current behaviour, no change.

### 3.2 Server → client — new envelope types

**`assistant.partial`** — one or more token chunks of an
in-flight assistant turn. May fire many times per turn; the text
is cumulative by *chunk*, not by *message* (see § 4.2 for why
cumulative-per-chunk is simpler to reason about than
cumulative-per-message). Clients concatenate `payload.delta`.

```json
{
  "type": "assistant.partial",
  "seq": 42,
  "ts": 1730000000123,
  "payload": {
    "turn_id": "t_8c1f…",
    "delta": " and then ",
    "index": 3
  }
}
```

- `turn_id`: stable per assistant turn. The client uses this to
  reconcile partials against the turn they belong to (so a late
  partial arriving after a cancel doesn't corrupt the next turn).
- `delta`: the *new* text only. Never the full reply.
- `index`: monotonic per turn, starting at 0. Useful for replay
  ordering if a proxy ever reorders frames.

**`assistant.turn_end`** — signals the in-flight turn is complete.
Equivalent to the final boundary of a streamed reply. Fires exactly
once per `turn_id` that streamed (never fires for unary turns —
those still use `transcript.final`).

```json
{
  "type": "assistant.turn_end",
  "seq": 50,
  "ts": 1730000000999,
  "payload": {
    "turn_id": "t_8c1f…",
    "reason": "complete",
    "full_text": "… concatenated reply …"
  }
}
```

- `reason`: `"complete"` (normal), `"cancelled"` (barge-in won),
  `"error"` (upstream LLM fault). Mirrors the audit doc's
  cooperative-cancel semantics.
- `full_text`: the server's authoritative reconstruction of the
  concatenated deltas. Optional but recommended — saves the
  client from buffering if it only cares about the final.

**`assistant.cancel`** — the server acknowledges a barge-in and
confirms it has stopped emitting partials. The client stops TTS
playback on receipt. The same `turn_id` will still receive exactly
one `assistant.turn_end` with `reason: "cancelled"` immediately
after so turn bookkeeping closes cleanly.

```json
{
  "type": "assistant.cancel",
  "seq": 51,
  "ts": 1730000001050,
  "payload": { "turn_id": "t_8c1f…", "cause": "user_barge_in" }
}
```

### 3.3 Client → server — new envelope types

**`transcript.partial`** — interim STT output while the user is
still speaking. Only sent when the client advertised
`device_info.streaming=true`; used by the server to drive
semantic endpointing in a future phase and, critically, to detect
barge-in *before* final silence (§ 4.3).

```json
{
  "type": "transcript.partial",
  "ts": 1730000001200,
  "payload": { "text": "hold on I want", "stable_prefix_len": 8 }
}
```

- `stable_prefix_len`: characters of `text` that the STT engine
  has already committed (won't rewrite). Optional; present when
  the STT engine exposes it (most streaming engines do).

**`user.barge_in`** — explicit interrupt. The client emits this
the instant its VAD trips above threshold while a turn is
in-flight (state === `speaking`). Cheaper than waiting for
`transcript.partial` because it fires on first audio, not first
decoded word.

```json
{
  "type": "user.barge_in",
  "ts": 1730000001100,
  "payload": { "turn_id": "t_8c1f…" }
}
```

The `turn_id` disambiguates against races: if the client fires a
barge-in for turn A but by the time it reaches the server turn B
has already started, the server compares IDs and ignores the
stale signal.

### 3.4 Unchanged envelopes

These keep their current wire format 100%:

- `call.state` — unchanged.
- `transcript.final` (server → client) — still sent for every
  turn that runs in unary mode (flag off, or capability mismatch).
- `call.control` — unchanged.
- `ui.state` — unchanged.
- `assistant.backchannel`, `assistant.filler`, `safety.notice` —
  unchanged (all persona_call events remain orthogonal to the
  streaming path).

## 4. Backend design

Two new files + one additive change to `voice_call/ws.py`. Every
existing module stays as-is.

```
backend/app/voice_call/
├── config.py          (existing — one new flag added)
├── turn.py            (existing — unchanged)
├── turn_stream.py     NEW — async-generator streaming runner
├── barge_in.py        NEW — per-session cancellation registry
├── ws.py              (existing — one new branch in the turn loop)
├── router.py          (existing — unchanged)
└── service.py, store.py, policy.py, models.py (all unchanged)
```

### 4.1 `turn_stream.py` — streaming turn runner

Pure async generator. Drops into the same call-site shape as
`turn.run_turn`, but yields chunks instead of returning a string.

```python
async def run_turn_streaming(
    *,
    user_text: str,
    model: str,
    auth_bearer: str | None,
    additional_system: str | None,
    cancel_token: "BargeInToken",
) -> AsyncIterator[str]:
    """Yield token chunks from the chat endpoint.

    Exits early (without exception) when ``cancel_token`` is tripped
    by a barge-in. The caller is responsible for emitting the final
    ``assistant.turn_end`` envelope regardless of exit reason.
    """
```

Implementation notes:

- Uses the existing chat endpoint's streaming mode (Ollama
  `stream: true`, OpenAI `stream: true`). The provider abstraction
  already lives in `turn.py::_call_chat`; `turn_stream.py` reuses
  it via an `iter_sse` helper factored out of the same file.
- `cancel_token.is_cancelled()` is polled between chunks. If true,
  the generator breaks cleanly — no exception, no backend retry
  storm.
- The persona_call suffix is attached exactly once, as the first
  element of the messages list, before the first yield. This
  matches the current non-streaming behaviour so the persona's
  first-turn framing is identical byte-for-byte.
- Shadow mode (`PERSONA_CALL_APPLY=false`) still suppresses the
  suffix; streaming is orthogonal to whether the suffix is used.
- Zero changes to `turn.py`. The non-streaming path stays for
  callers that don't opt in.

### 4.2 Why cumulative-per-chunk (delta-only) wire format

Each `assistant.partial` carries only the *new* text
(`payload.delta`), not the growing full reply. The alternatives:

| Wire format | Pros | Cons |
|---|---|---|
| Delta only (chosen) | Minimum bytes; client concatenates freely; works even if the client only buffers the last N chunks for animation | Ordering matters — we track it via `index` |
| Cumulative full-text per chunk | Self-correcting if frames are dropped | 3× bandwidth on a 200-token reply; forces the client to diff to animate |
| Both | Bullet-proof | Over-engineered for a WS that already has seq ordering |

Delta only wins because `callSocket.ts` already guarantees
monotonic seq; stacking chunks in order is effectively free. The
`index` field is a defence-in-depth check, not a load-bearing one.

### 4.3 `barge_in.py` — per-session cancellation registry

One small module; no DB. A process-local dict keyed by session
id, each entry a `BargeInToken` with an `asyncio.Event`.

```python
class BargeInToken:
    def __init__(self, turn_id: str) -> None:
        self.turn_id = turn_id
        self._ev = asyncio.Event()
    def cancel(self) -> None: self._ev.set()
    def is_cancelled(self) -> bool: return self._ev.is_set()

def new_token(session_id: str, turn_id: str) -> BargeInToken: ...
def cancel_active(session_id: str, turn_id: str) -> bool: ...
def clear(session_id: str) -> None: ...
```

- `cancel_active` refuses to cancel if the incoming `turn_id`
  doesn't match the currently-active turn. Stale barge-ins from
  a previous turn are no-ops. This is the server half of the
  race guard described in § 3.3.
- Lives in memory only. A WS drop clears the session's tokens
  via `clear`; a subsequent resume starts a fresh turn, fresh
  token.
- Tested in isolation — the module has no HTTP, no DB, no
  asyncio transport. Pure state machine + `asyncio.Event`.

### 4.4 `ws.py` — one new branch in the turn loop

On receipt of a `transcript.final`, the existing handler runs
`turn.run_turn` and emits one `transcript.final` (assistant). The
streaming branch:

```text
on transcript.final (user):
    if streaming_effective:
        turn_id = uuid()
        token = barge_in.new_token(sid, turn_id)
        async for delta in turn_stream.run_turn_streaming(
                user_text=..., additional_system=suffix,
                cancel_token=token, ...):
            if token.is_cancelled():          # user barged in
                break
            await _send("assistant.partial", {turn_id, delta, index})
        reason = "cancelled" if token.is_cancelled() else "complete"
        await _send("assistant.turn_end",
                    {turn_id, reason, full_text=...})
    else:
        # current non-streaming path — untouched.
        reply = await turn.run_turn(...)
        await _send("transcript.final", {"role": "assistant", "text": reply})
```

On receipt of `user.barge_in`:

```text
cancelled = barge_in.cancel_active(sid, payload.turn_id)
if cancelled:
    await _send("assistant.cancel",
                {turn_id: payload.turn_id, cause: "user_barge_in"})
# else: stale signal (the turn is already over). Silent drop.
```

The `assistant.cancel` is emitted **immediately** on receipt of
the barge-in, *before* the streaming generator notices the cancel
event on its next poll. This cuts ~50–100 ms off the perceived
barge-in latency — the client stops TTS on the cancel envelope,
even if the last partial arrives moments later.

`transcript.partial` (user) is accepted but currently only used to
drive the barge-in detector as a backup signal:

```text
on transcript.partial (user):
    if state == 'speaking' and turn_id_active:
        # late-signal backup for clients whose VAD misses
        # speech-start but STT picks up the first word
        barge_in.cancel_active(sid, turn_id_active)
```

Primary barge-in trigger is the explicit `user.barge_in`;
`transcript.partial` is secondary defence.

### 4.5 What stays untouched

- `voice_call/turn.py` — not edited. Parallel path.
- `persona_call/*` — not edited. The composer, openings, ledger,
  phase machine, backchannels, filler, closings all run exactly
  as today. The suffix is attached in both paths.
- REST session create — schema gains one optional server-side
  field (`capabilities.streaming`) that defaults false. Old
  clients that never read `capabilities` stay on the unary path.
- Database schema — no migration. `barge_in.py` is process-local.

## 5. Frontend design

Three additive changes under `frontend/src/ui/call/` and one
barge-in tap inside `CallOverlay.tsx`. No existing files are
destructively rewritten.

```
frontend/src/ui/call/
├── callApi.ts          (existing — one field added to the request)
├── callSocket.ts       (existing — four new event types + 2 send methods)
├── useCallSession.ts   (existing — new subscribe helpers)
├── streamTts.ts        NEW — pluggable streaming TTS surface
└── bargeIn.ts          NEW — VAD-driven speech-start detector tap
```

### 5.1 `callApi.ts` — advertise client capability

One additive field on the `CreateCallSessionRequest.device_info`
block:

```ts
device_info: {
  tz: string
  platform: string
  streaming?: boolean   // NEW
  barge_in?: boolean    // NEW
}
```

Set both to `true` when the build includes `streamTts.ts` and the
environment has `Web Audio + requestAnimationFrame` (both always
true in supported browsers). Keeping them optional means older
builds keep shipping unchanged requests.

Response parsing adds one optional read:

```ts
handshake.capabilities?.streaming  // server-side opt-in mirror
handshake.capabilities?.barge_in
```

The effective mode `useBackend && streaming` is stashed in a
stable ref on the session handle.

### 5.2 `callSocket.ts` — four new events + 2 new sends

Typed event map extended — no removals:

```ts
interface CallSocketEventMap {
  // existing
  statusChange: CallLifecycleStatus
  callState: CallStatePayload
  assistantTranscript: AssistantTranscriptPayload   // still fires in unary mode
  // NEW — only fire when the session negotiated streaming
  assistantPartial: AssistantPartialPayload
  assistantTurnEnd: AssistantTurnEndPayload
  assistantCancel: AssistantCancelPayload
  // unchanged
  assistantFiller: AssistantFillerPayload
  assistantBackchannel: AssistantBackchannelPayload
  serverError: ServerErrorPayload
  safetyNotice: Record<string, unknown>
  pong: void
  closed: { reason: CallCloseReason; code?: number; detail?: string }
}
```

Two new public methods:

```ts
sendTranscriptPartial(p: { text: string; stable_prefix_len?: number }): void
sendBargeIn(turn_id: string): void
```

Both use the existing `enqueueLine` so the outbound queue and
reconnect semantics apply uniformly. Unknown server types still
fall through to the "forward-compat: no-op" branch.

### 5.3 `streamTts.ts` — pluggable streaming surface

One interface, three implementations (the last two are future
work):

```ts
interface StreamingTts {
  /** Append a text chunk. Implementations decide their own
   *  clause-boundary flushing; callers pass raw deltas. */
  appendDelta(delta: string): void
  /** Signal the turn is complete. Implementations may flush a
   *  residual buffer and schedule the final audio. */
  flush(): void
  /** Stop immediately. Must silence any audio currently playing
   *  or queued within ≤ 50 ms. This is the barge-in path. */
  stop(): void
  /** True while audio is either playing or scheduled-to-play.
   *  Reading is cheap; used by the VAD tap to decide whether a
   *  user-speech-start counts as a barge-in. */
  readonly isSpeaking: boolean
}
```

Implementations:

- **`WebSpeechStreamTts`** (ships first). Buffers deltas until a
  sentence-ender hits (`. ! ? ;` outside quotes). Flushes one
  `SpeechSynthesisUtterance` per sentence. `stop()` calls
  `speechSynthesis.cancel()` — silent within ~20 ms on Chromium.
- **`PiperWasmStreamTts`** (later). Uses the existing
  `SpeechService` shim's streaming mode (Piper WASM emits WAV
  fragments as tokens arrive). Reuses an `<audio>` element for
  seamless concatenation.
- **`RemoteStreamTts`** (later, optional). Pipes deltas to a
  vendor HTTP/2 streaming endpoint (Cartesia / ElevenLabs) and
  plays the returned audio via `AudioContext.decodeAudioData`.

The hook `useCallSession` exposes a `getTts()` factory that
returns whichever implementation `SpeechService` is currently
bound to, defaulting to `WebSpeechStreamTts`. Swap is a one-line
change in that factory, not a `CallOverlay` rewrite.

### 5.4 `bargeIn.ts` — VAD tap on speech-start

The existing `useVoiceController` already exposes `audioLevel`
(0..1, EMA-smoothed) and `state` (`IDLE` / `LISTENING` / …). The
barge-in detector is a thin hook layered on top:

```ts
useBargeInDetector({
  audioLevelRef,            // MutableRefObject<number>
  threshold: 0.08,          // above noise floor; tunable
  minSustainMs: 80,         // guard against a single spike
  enabled: isTtsSpeaking && streamingNegotiated,
  onBargeIn: () => {
    tts.stop()
    session.sendBargeIn(currentTurnId)
  },
})
```

Why detector-local threshold + sustain:

- The VAD inside `useVoiceController` is tuned for end-of-user-
  turn silence detection, which is a different problem than
  start-of-user-turn speech detection during AI playback. Using
  a slightly higher `threshold` here (0.08 vs the VAD's 0.035
  baseline) prevents the persona's own TTS bleed from tripping
  it (Chromium exposes the mic even during TTS, and a fraction
  of the persona's audio returns as low-level input on most
  laptops).
- `minSustainMs` of 80 ms matches the minimum duration of a
  voiced phoneme, so a keyboard clack or a single cough won't
  cut the persona off.

The detector fires only when `enabled` — i.e. the TTS is actually
speaking AND streaming is negotiated. Outside that window it's a
pure no-op.

### 5.5 `CallOverlay.tsx` — three additive wires

All inside `CallOverlayInner`, guarded on `session.streaming`:

1. **Subscribe to partials** — pipe them into the streaming TTS:
   ```ts
   useEffect(() => {
     if (!streaming) return
     return session.onAssistantPartial(p => {
       currentTurnIdRef.current = p.turn_id
       ttsRef.current.appendDelta(p.delta)
     })
   }, [streaming, session])
   ```
2. **Subscribe to turn-end + cancel** — flush or stop the TTS:
   ```ts
   session.onAssistantTurnEnd(p => ttsRef.current.flush())
   session.onAssistantCancel(_ => ttsRef.current.stop())
   ```
3. **Mount the VAD tap** — fires the barge-in:
   ```ts
   useBargeInDetector({
     audioLevelRef: voiceAudioLevelRef,
     enabled: ttsRef.current.isSpeaking && streaming,
     onBargeIn: () => {
       const tid = currentTurnIdRef.current
       ttsRef.current.stop()
       if (tid) session.sendBargeIn(tid)
     },
   })
   ```

The unary path (`streaming === false`) runs exactly today's code.
The existing `onAssistantTranscript` listener stays in place and
still fires — but only when the server didn't stream.

### 5.6 Waveform during streaming

`CallOverlay` already animates the waveform from an `intensityRef`
(see `f90fa4d`). Streaming changes nothing here — the `speaking`
state keeps using the synthesised envelope. A future enhancement
could tap `WebSpeechStreamTts.onBoundary` to modulate the envelope
with real word boundaries, but that's a polish pass, not a
prerequisite.

## 6. Failure modes + graceful degradation

The design assumes the network, the LLM provider, and the
browser's speech subsystems will all misbehave at some point. Each
row below is a specific failure with its handler in-tree.

| Failure | Symptom | Handler |
|---|---|---|
| Network drop during streaming | `WebSocket close` with a transient code | `callSocket.ts` already reconnects within the resume window. The current in-flight turn is treated as cancelled; `assistant.turn_end` with `reason: "error"` is emitted by the server on the resume or on reconnect timeout. Client stops TTS on cancel. |
| LLM upstream fault mid-stream | Server sees an exception inside `turn_stream.run_turn_streaming` | Generator raises → caught in `ws.py` → emit `assistant.turn_end` with `reason: "error"` + a fallback `full_text` ("one sec — connection hiccup."). No half-state. |
| TTS subsystem unavailable | `speechSynthesis` throws, no audio | `WebSpeechStreamTts.stop()` and `appendDelta()` are both no-ops under throw. The turn still writes the transcript into the chat; the user reads instead of hearing. |
| Barge-in fires but the turn is already over | Race: `user.barge_in` arrives after `assistant.turn_end` | Server's `cancel_active` compares `turn_id`; stale IDs are silent drops (§ 4.3). No `assistant.cancel` is sent. |
| Barge-in fires twice | User pauses + resumes within one TTS pass | `BargeInToken.cancel()` is idempotent (`asyncio.Event.set()` is idempotent). First cancel wins; second is a no-op. |
| TTS bleed trips the VAD tap | Persona's own voice causes a false barge-in | `threshold=0.08` + `minSustainMs=80` on the tap. If bleed still trips it, user can hard-mute via the mic button — `sendUiState({muted: true})` also disables the detector via `enabled` gating. |
| Client advertises streaming, server doesn't support | `capabilities.streaming` missing / false | Effective mode is unary; client's streaming code paths never subscribe; old `onAssistantTranscript` path runs identically to today. |
| Server advertises streaming, client doesn't | `device_info.streaming` missing / false | Server buffers deltas and emits a single `transcript.final` at turn end. Zero client change. |
| Partial arrives after a cancel | Late frame for a cancelled `turn_id` | Client tracks `currentTurnIdRef`; any partial whose `turn_id` doesn't match the current one is dropped. Monotonic-seq check already guarantees the frame is in-order, just stale. |
| Ordering corruption (proxy reorders) | `index` goes backwards | Client logs once (via `callSocket.log.warn`) and appends anyway — text order still wins because seq is monotonic. `index` is advisory, not load-bearing (§ 4.2). |
| `assistant.turn_end` never arrives | Hung upstream | Client watchdog: if no partial + no turn_end for `idle_timeout_sec`, treat the turn as ended with the last-seen text. Matches the existing idle-timeout path in `ws.py`. |

## 7. Flag rollout (three stages, gated)

Both flags default **off** — the feature is deletable at any stage
by flipping them back.

### 7.1 Stage 0 — shadow measurement

```
VOICE_CALL_STREAMING_ENABLED=false   (default)
```

No behaviour change. Ship the new modules behind the flag; run
the new backend tests in CI; verify tsc/vitest green on the
frontend. Zero production impact.

### 7.2 Stage 1 — internal dogfood

```
VOICE_CALL_STREAMING_ENABLED=true
PERSONA_CALL_ENABLED=true
PERSONA_CALL_APPLY=true
```

Flipped for a small internal allowlist. Watch:

- `pc_turn_ms_p50` should drop from ~1500 ms to ≤ 600 ms.
- `pc_barge_in_rate` new metric, should be > 0 as soon as anyone
  interrupts.
- Error rate on `turn_end {reason: "error"}` should stay < 1 %.

If any of those regress, flip the flag off. The fallback path is
byte-identical, so the blast radius of a bad rollout is zero.

### 7.3 Stage 2 — public

Default both flags on in the shipped `.env.example`. Keep the
unary path alive for a full release cycle so we have a rollback
lever. Remove it only after a deliberate decision, in its own
commit — not as part of this series.

## 8. Testing plan

Three layers, in the same shape as the existing persona_call test
suite.

### 8.1 Backend unit

- **`barge_in.py`**: token creation, cancel with matching id
  cancels, cancel with mismatched id does nothing,
  double-cancel is idempotent, `clear` on session close tears
  down everything.
- **`turn_stream.py`**: mocked SSE source yielding three chunks
  → generator yields three deltas → matches order. Cancel
  before chunk 2 → generator stops, no further yield. Upstream
  exception → generator raises; caller can emit
  `reason: "error"`.
- **ws handler** branch for `user.barge_in`: active turn's
  token is cancelled, `assistant.cancel` is emitted, stale
  `turn_id` is silent.

### 8.2 Frontend unit (vitest)

- **`callSocket.ts`**: new server events dispatch to the correct
  listener set; delta concatenation across 10 partials produces
  the full string; `sendBargeIn` routes through `enqueueLine`
  with correct envelope shape.
- **`streamTts.ts::WebSpeechStreamTts`**: sentence-boundary
  flushing; `stop()` silences within the frame budget (mock
  `speechSynthesis`).
- **`bargeIn.ts::useBargeInDetector`**: 80 ms sustained above
  threshold fires once; a single spike above threshold does not
  fire; muted state hard-disables.

### 8.3 End-to-end integration (pytest + a fake WS)

- Drive a scripted session through a mocked chat provider that
  yields 5 chunks over 1 s. Assert the server emits 5
  `assistant.partial` frames, 1 `assistant.turn_end` with
  `reason: "complete"`, `full_text` matches concatenation.
- Drive the same session with a `user.barge_in` after chunk 2.
  Assert 2 `assistant.partial`, 1 `assistant.cancel`, 1
  `assistant.turn_end` with `reason: "cancelled"`.
- Negative: stale `turn_id` in a barge-in → no `assistant.cancel`
  emitted; the turn completes normally.

Every test above fails loudly on a spec regression, not on a
rendering regression. The design is defensible by tests, not by
eyeballs.

## 9. What is explicitly NOT in this design

- **Semantic turn detection** (Phase 4 in the audit). End-of-turn
  is still VAD silence. A small classifier on partials is the
  next phase; not here.
- **Server-side audio rendering.** TTS still runs in the browser.
  Moving TTS server-side is a separate decision tied to provider
  choice (Cartesia, ElevenLabs, Piper-CPU) and billing.
- **Streaming STT.** The browser already emits interim transcripts
  via `SpeechRecognition.onresult`, but we only consume `final`.
  Forwarding `interim` as `transcript.partial` is a follow-up
  that only matters for semantic endpointing.
- **A new LLM provider.** The streaming path uses the same chat
  endpoint the unary path uses (`stream: true` switch). Provider
  swap is orthogonal.
- **A new persona, new voice facet, new opening template, new
  backchannel token.** Every persona_call module ships unchanged.
- **A redesign of `CallOverlay`.** The visual surface is a strict
  superset of today's (same waveform, same modal, same controls).
  Only three new `useEffect` blocks + one hook.
- **Any change to the chat REST fallback.** The existing chat path
  — and by extension the Call overlay's unavailable-mode fallback
  — is out of scope. Phase 2 + 3 are additive on top of it.

## 10. Summary (one paragraph)

The call overlay already negotiates a dedicated WS session with
the backend (`useCallSession` + `callSocket`). Phase 2 + 3 ride on
that same session, with one new env flag
(`VOICE_CALL_STREAMING_ENABLED`), one new capability field on the
session handshake, three new server→client event types, two new
client→server event types, two new backend modules (`turn_stream`
+ `barge_in`), two new frontend modules (`streamTts` + `bargeIn`),
and three new `useEffect` blocks in `CallOverlay`. No rename, no
deletion, no schema migration, no persona change, no chat-endpoint
change. When the flag is off every byte on the wire and every DOM
node rendered is identical to today. When the flag is on the
persona starts speaking inside ~600 ms of user turn-end, and stops
inside ~200 ms of user barge-in — the two numbers that turn "AI
on a phone" into "someone on a phone."

