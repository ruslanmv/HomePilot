# MeetingSense — changelog

What changed, when, and why — one entry per batch of
[`design/MEETINGSENSE_BATCHES.md`](design/MEETINGSENSE_BATCHES.md).

> **Written late, and worth saying so.** §0 of the batch plan asks each batch to finish with a
> changelog entry. HomePilot has no repository-wide changelog and never has, so nine batches
> closed without one rather than inventing a repo convention mid-feature. This file is the
> backfill, reconstructed from the commits; entries from MS9 onward are written as the batch
> lands. The rule now has a file to point at.
>
> The reconstruction is honest about its limits: each entry below is what the commit and the
> tests say, not what anybody remembers.

Every batch ships behind flags that default to off. With `MEETINGSENSE_ENABLED` unset, none of
this is reachable and no table is created.

---

## W4 — Brain

### MS14 — a self-sufficient summary, and deleting a meeting · `f537783`

- The summary message carries the recap, decisions, actions with owners and citations, open
  questions and a slide timeline, with thumbnails in `media.images` capped at 8. The chat path
  passes six messages, so this one *is* the meeting as far as a persona is concerned.
- **Per D4 nothing is enqueued.** Two tests hold it: one patches the jobs functions and asserts
  none fired, one greps the module for the word.
- `retention.py` + `DELETE /v1/meetingsense/{id}`: rows and owned files, reporting counts.
  **Retention does not modify deletion** — whatever was kept is removed.
- `session.stop()` forces the last notes window, or the final minute of every meeting is
  missing from its summary.
- **Two weak tests found by mutation:** a symlink does not separate `is_relative_to` from a
  string prefix check (a sibling directory named like the root does), and an empty list never
  reaches a section whose items all render blank.

### MS12 — rolling notes and the recap · `1e90e18`

- `notes_engine.py` + `prompts.py`. Trigger is a floor, not a schedule: 60 s **or** 400 words,
  and nothing pending is never due.
- **Deltas, not rewrites.** The merge happens server-side and never deletes; resolving marks a
  question so the card can strike it through.
- **D9 tier 2 is one signature:** `recap_messages()` takes the previous recap as a string, not
  a meeting id, so it cannot reach the transcript. The 120-word cap is enforced in code, not
  requested in the prompt.
- A citation the transcript cannot support is dropped while the observation is kept.
- **Found an MS6 bug:** `to_markdown` read `notes["json"]` while `store.get_notes()` returns
  the parsed object under `notes["notes"]`, so the Markdown export had been silently omitting
  its notes section. The MS6 test hand-built a shape the store never produces and passed over
  it.

---

## W2 — Reach

### MS8 — through OllaBridge · `27b6e15`, ollabridge `48520da`

- `/v1/meetingsense/status` gains **`remote_ok`** (`enabled AND ready AND flags.remote`) — one
  boolean rather than two flags for a client to combine, because the flags do not imply each
  other and a client guessing would offer a control the server refuses.
- With `MEETINGSENSE_REMOTE` off, avatar-session meeting frames are refused **per frame**, not
  only at start. The local WebSocket is untouched by the flag.
- In `ruslanmv/ollabridge`: the proxy's "it is a pipe" claim is asserted **in bytes** — up,
  down, a whole meeting in order, and over the cloud `sig`/`ev` relay — plus a test forbidding
  meeting vocabulary anywhere in the proxy. `/health` advertises `meetings`.
- **A test that could not fail:** the first audio fixture happened to be byte-identical to
  `json.dumps` output, so a mutant that re-serialised every relayed frame passed the whole
  suite. The fixtures now carry spacing `json.dumps` cannot reproduce.

### MS7 — the avatar-session transport · `75d7294`, 3D-Avatar-Chatbot `303b722`

- `meeting_start`, `meeting_audio`, `meeting_stop` and server `meeting` added to the avatar
  protocol's type sets. **`PROTOCOL_VERSION` stays 1** — §6.9's silent-ignore rule is what
  makes that safe, and a bump would have broken the avatar, voice and panels too.
- New `meetingsense/avatar_bridge.py`: a `Transport` over the handler's outbox, and a bridge
  that reuses MS2's core, MS3's `audio.py` and MS3's own `_handle_audio`. The two transports
  cannot answer differently because there is only one thing answering.
- The handler *queues* meeting frames rather than answering them: `handle()` is synchronous by
  design, and a meeting transcribes audio.
- **Cross-repo:** `backend/tests/fixtures/protocol/` is byte-identical to the copy in
  `ruslanmv/3D-Avatar-Chatbot`, held by `CHECKSUMS.txt`. Adding four frames turned that repo's
  contract test red until the same files landed there — the mechanism working, not an obstacle.
- **A parity test that failed for the right reason:** the two transports differed by one
  millisecond of `elapsed`. Fixed by injecting the clock, not by scrubbing the field.

---

## Carried work

### MS1-a — real timings from a remote endpoint · `97fc3e4`

- `OpenAICompatSTTProvider.transcribe_segments` asks for `response_format=verbose_json`;
  `supports_segments` is now true for that provider. Every install with `STT_BASE_URL` set had
  been producing `t1: None` on every segment.
- **A second call site, not a modified one.** `transcribe()` still sends the default format —
  changing it would alter a return value the voice call shares.
- `verbose_json` is documented, not guaranteed: every degraded shape falls back to one honest
  span rather than raising. **A segment the server did not time is skipped, never given
  `t0: 0`** — these get cited in notes.

---

## W1 — Recorder (local)

### MS6 — the live card, the pill, consent and export · `657f592`

- `frontend/src/ui/meetingsense/`: `meetingState.ts`, `MeetingCard.tsx`, `RecordingPill.tsx`,
  `ConsentSheet.tsx`, `useMeetingSense.ts`. Backend `export.py`, `finalize.py`,
  `GET /v1/meetingsense/{id}` and `/export?fmt=md|srt|json`.
- **Stop keeps recording.** Pressing it starts a ten-second undo countdown and only then sends
  `stop` — the seconds spent deciding are usually seconds somebody else was still talking.
- Segments keyed by `id` so a resume replay is invisible; a provisional line is the same
  element as the segment replacing it; new lines scroll into view only when the reader is
  already at the bottom.
- Export handles `t1: None`, which is *every* segment on a remote-STT install.
- **A finding that shrank the work:** HomePilot has no `conversations` table — History labels a
  conversation with its last message's content. So D5's auto-title needed no schema change; the
  meeting message is that last message and the title leads it.

### MS4-a — reconnect, level meter, backpressure · `63dffcd`

- Reconnect on 1-2-4-8 s backoff capped at 15 s, sending `resume` with the **highest** `seq`
  seen. `ms:reconnecting` / `ms:resumed`.
- `levels` (RMS per channel, polled) and backpressure shedding by **how much speech a chunk
  carries** rather than by age, reporting `behind_ms`.
- **Three test defects, all mine:** shed tests that put the near-silent chunk first (so
  dropping by age gave the same answer), a "gives up" test that never asserted the pill stops
  saying *reconnecting*, and leaked `addEventListener`s that counted each event once per prior
  test.

### MS3-a — resume on reconnect · `ada9408`

- A dropped socket **suspends** for `MEETINGSENSE_RESUME_GRACE_S` (default 120) instead of
  ending. `0` reproduces the old behaviour exactly, and a test pins that.
- Store gains `ms_meetings.suspended_at` and `ms_segments.seq`, added by `ALTER` when missing —
  without it a database created by MS2 would fail mid-meeting on its first resume.
- **A deliberate deviation from D10:** the server *does* replay. "The client already has it" is
  false for exactly the frames in flight when the socket died.
- **A test that could not fail:** `pytest.approx` on a Unix timestamp has a relative tolerance
  of roughly ±1700 s. Now on an injected clock.

### MS5 — the entry point · `1ee3227`

- The ScreenSense button gains a popover when MeetingSense is enabled, and is untouched when it
  is not — asserted as `outerHTML` byte-identical before and after.
- Every disabled control names its cause and its fix, with a stable id per state; a test greps
  the module for generic "unavailable" prose. axe-core over the healthy *and* degraded trees.
- **"Ask once" needed care:** ScreenSense's own click handler is still on that button, so one
  click would have both asked a question and opened the popover. Suppressed in the capture
  phase and re-fired by the popover's own button.

### MS4 — the audio capture addon · `6ee54ab`

- Mirrored addon pair, own `getDisplayMedia`/`getUserMedia`, separate gain nodes into a channel
  merger (**ch0 = call, ch1 = mic**, never summed), AudioWorklet → 16 kHz PCM16 20 ms frames,
  energy VAD with a 350 ms close over a 1 s floor and an 8 s hard cut.
- **Only the hard cut carries the 200 ms overlap.** The first draft carried it from every close
  and measured 140 ms: one ring buffer was doing two jobs, and the silence that closed an
  utterance displaced the frames the overlap was made of.
- **Outside the batch's scope:** `vitest.config.ts` had been excluding **17 test files and 124
  tests** — every `.test.js` and `.test.jsx`, the whole phone/call primitives suite included.
  They had never run in CI. The glob was widened; all 124 pass unchanged.

### MS3 — the local WebSocket transport · `15b2b24`

- `WS /v1/meetingsense/session` plus `audio.py`. Refuses flag-off the way the voice route does
  (accept, say why, close 1008) so a client can tell "disabled" from "server down".
- PCM16 gets a RIFF header server-side: headerless PCM named `.wav` has 44 bytes of speech read
  as a header, producing a garbled transcript rather than an error.
- A stereo frame is two transcriptions, one assembler each.
- **Two tests that hung instead of failing.** A test waiting on a frame the server never sends
  blocks forever; a CI timeout is a worse diagnosis than a red assertion. The helper now
  provokes a `pong` end-marker.

### MS2 — store, assembler, transport-agnostic core · `82c8ff4`

- `store.py`, `transcript.py`, `session.py`. **`session.py` never imports FastAPI** — it knows
  about a `Transport`, which is `send` and `close` and nothing else.
- The assembler trims the **head of the later** span, never the tail of the earlier one: text
  already sent must not change. The comparison window is over *emitted* words.
- **Mutation testing found real redundancy:** deleting the `dedupe()` call changed nothing,
  because `push()` hand-rolled the same rule. Now one implementation.

---

## W0 — Foundation

### MS1 — the STT capability layer · `3b8e1a8`

- The one sanctioned exception to additive-only, spent. `WHISPER_DEVICE`/`WHISPER_COMPUTE`, the
  **resolved** device read back off the loaded model, `transcribe_segments()` concrete on the
  ABC, and a provider cache keyed on config.
- **A claim of mine that was wrong:** faster-whisper does *not* default to CPU — `device`
  defaults to `"auto"`. The real problem is that `auto` falls back to CPU *silently*, which is
  why the resolved device is reported.
- Carried out: **MS1-a** (real remote timings) and **MS1-b** (measure the real-time factor).

### MS0 — skeleton and flags · `6ad44e7`

- `backend/app/meetingsense/{__init__,config,routes}.py`, the master flag and six sub-flags
  (none implied by the master), and `GET /v1/meetingsense/status` — always mounted, always 200,
  never leaking the STT endpoint.
- Probes run through a wrapper that turns any escape into a reported unknown: a status endpoint
  that 500s because an optional package moved has failed at its one job.
