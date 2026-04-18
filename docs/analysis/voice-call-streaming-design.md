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

Section 3 ends here. Next commit: § 4 backend design.
