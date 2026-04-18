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

Section 2 ends here. Next commit: § 3 envelope contracts.
