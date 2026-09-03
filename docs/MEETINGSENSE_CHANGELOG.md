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

## W6 — Together

### MS19 — the eighth activity · `3b7af51` (avatar) + `PENDING`

- `meeting.js` joins the 👥 launcher. It cannot obtain a stream: no `navigator`, no media
  call, no canvas — asserted by reading its own source. The recorder is handed the grant's
  streams through a new `startWithStreams`, because a recorder that opened its own capture
  inside that page would be a second consent story for the same screen.
- `meeting` is a **compound consent source**: screen then microphone, in that order. A part
  declined, or resolving with no stream, grants nothing.
- **Revoking stops the recorder synchronously**, asserted with no timers at all. If the test
  needed one, the guarantee would be "soon" rather than "now".
- **Two pre-existing tests updated rather than worked around.** `capture.test.js` pinned
  `SOURCES` exactly and B11's docstring says adding a consumer should be a registration —
  MS19 is the first to take that offer. `composition.test.js` caught `meeting.js` publishing a
  global `boot.js` never loaded, which is what it is for.
- **A real bug the tests found:** `stop()` released the grant *after* revoking, so its own
  consent listener still saw a live grant, announced a second stop and counted a deliberate
  stop as a revocation.
- **A harness bug worth recording:** two mutations aimed at `startWithStreams` matched the
  identical guard lines in `start()` instead — `replace(…, 1)` takes the first occurrence —
  and survived, because `start()`'s own guard had no test. Both are covered now, and the
  borrowed path uses distinct local names so an anchor cannot land on the wrong function.

### MS18 — the live context provider · `188ee7a`

- New `live_context.py`, and one optional `conversation_id` argument on
  `build_system_prompt`. Every existing caller omits it and gets a byte-identical prompt;
  `orchestrator.py`'s chat path passes it.
- **D9 tiers 1 and 2 only**, capped at 900 tokens — the same constant MS13 answers under, so
  there is one number rather than two that drift. Trim order: verbatim oldest-first, then the
  notes lists, and the recap never.
- The block tells the persona what it cannot see. Without that, a model asked "what did she
  say?" answers about the last thing in its own window — the chat — and invents a timestamp.
- **Two weak tests found by mutation.** The budget was asserted against
  `live_context.TOKEN_BUDGET`, so raising that constant passed; it is now asserted against
  900. And nothing covered the orchestrator seam, so the wiring could be removed with the
  suite green — now checked by reading the call, which is the right weight for a one-keyword
  claim.
- A separate hazard worth recording: a mutation that replaced the notes-trim body with `pass`
  turned the loop infinite, timed out past the harness's own limit, and was left in the source
  by a restore that never ran. Every subsequent run hung until it was found. Mutations that can
  spin need their own timeout inside the harness, not around it.

---

## Carried work

### MS12-a — the notes engine, actually connected · 3c592f0

- MS12 shipped an engine that was complete, tested, and **constructed by nothing**. `start`
  echoed `notes: true` straight back, `MeetingSession` drove a `notes=` engine correctly, and
  no route ever built one — so for four batches no meeting on any install produced a `notes`
  frame, and every client was told notes were on.
- One `engine_factory(config)` in `notes_engine.py`, wired into both transports. Two call
  sites building one each would be two places for this to happen again.
- **`ready` now reports whether notes are running, not whether they were requested.** That is
  the half of the bug that hid the other half: a server answering with the client's own
  question can be wrong indefinitely without anybody noticing.
- The tests go through a **real socket** and a **real avatar bridge** rather than the session
  core, because MS12's suite tested the engine, MS3's tested the socket, and the gap was
  between them.

---

## W5 — Memory

### MS17 — naming a meeting without asking · `d3facbe`

- New `metadata.py`: the shared window's title (free, from `MediaStreamTrack.label`) and a
  calendar event via MCP, both applied after `ready` as a background task and reported as a
  `meta` frame. Schema 4 adds `attendees` and `link`.
- **A title the user gave always wins**, and **an empty answer is not an answer** — the two
  rules that stop auto-metadata from being worse than nothing. `"Zoom Meeting"` yields no
  title, because writing it in makes every Zoom call in History look identical.
- **Two real bugs the tests found.** Markers matched as substrings read "Cisco Webex Meetings"
  — and any shared document called "Meeting notes" — as a Meet call; they now match on word
  boundaries. And a regex counts `_` as a word character, so "Webex_Meetings" matched nothing
  until underscores were normalised for matching.
- The name is the **longest** surviving part of a window title, not the first: Teams titles a
  call `"<speaker> | <meeting> | Microsoft Teams"`, and the first part is whoever happened to
  be talking when recording started.
- Auto-metadata may write four columns and no others. It is fed by a calendar event and a
  window title, neither of which the user typed, and a path that can set any column is one bad
  MCP answer away from rewriting a meeting's conversation or its retention mode.

### MS16 — binding, resume and branching · `bd16c01`

- `ms_threads` and `ms_artifacts` (schema 3), a new `binding.py`, and three endpoints:
  `GET /conversations/{id}` to bring a card back, `POST /{id}/thread` to branch, and
  `POST /{id}/attach` to push the transcript into a project.
- **The origin thread is recorded when a meeting starts, not when it stops.** A meeting
  interrupted by a server restart should still bring its card back, and nothing on a chat
  message says which meeting produced it.
- **The conversation route is declared above `/{meeting_id}`.** FastAPI matches in declaration
  order; a path parameter first swallows "conversations" as a meeting id and 404s every
  hydration — a bug that looks like a missing feature.
- **The brief is not the summary message.** The summary is written where the reader has just
  been in the meeting; the brief opens a conversation whose reader may be a week late, so it
  leads with what is still open and ends by saying the transcript is searchable.
- **Attach goes through `process_and_add_file`**, the function the project upload button
  calls, which is why it needs no new job type — asserted, because "we reuse X" is the kind of
  claim that quietly stops being true.
- **A hole found by mutation, twice over:** a section whose items all render blank still
  printed its heading. MS14's note sections had the identical bug and its guard was copied
  without its test.

### MS15 — embeddings and cross-meeting retrieval · `bd16c01`

- New `retrieval.py`. On stop a meeting is embedded — after `final`, so nobody waits on it —
  into a Chroma namespace of its own, and `ms_search(query, meeting_id?, k)` returns rows
  carrying their own `<title> · hh:mm:ss` citation.
- `vectordb.py` gained a `namespace` parameter whose default produces the byte-identical
  collection name it always produced, and `collection_name()` is now the single place that
  name is built — two copies of a naming rule is how a delete stops matching its create.
- **One collection filtered by `meeting_id`, not one per meeting**, which is a deliberate
  deviation from the batch row: both queries a per-meeting collection would serve are the
  global one with and without a filter, the delete runs filtered either way, and the second
  copy would double every index for no capability.
- **Both retrievers run, interleaved by rank.** Embeddings find the passage worded differently
  from the question; keyword finds the exact token somebody asked about. Interleaved rather
  than merged, because a cosine distance and a length-normalised term count share no scale.
- **Delete now clears three stores.** A meeting left in the index answers questions after the
  user deleted it.
- **Two weak tests, found by mutation:** the over-fetch before the verbatim filter and the
  time-order sort both survived their mutants, because in each fixture the retriever's scores
  happened to agree with the property under test. Rewritten so rank and time disagree.

---

## W3 — Eyes

### MS11 — desktop system audio · `e3e7937`

- `desktop/meetingsense-audio.js` + a `setDisplayMediaRequestHandler` registered from
  `bootstrap`, `preload.js` exposing `meetingSenseAudio()`, and a popover notice built from the
  shell's own answer. Flag off by default (`MEETINGSENSE_DESKTOP_AUDIO`, or
  `meetingSenseDesktopAudio` in the desktop store).
- **Windows only on Electron 33**, and the popover says so *before* recording starts. macOS has
  no public API for capturing system output; the hint names the virtual-audio-device workaround
  rather than stopping at "unsupported", because a user who believes the call is being recorded
  and finds out afterwards that it was not has lost the meeting.
- **"Off" and "not possible here" are two different messages.** Off on Windows is advice the
  user can act on; the same sentence on macOS would be advice that does not help, so it is not
  shown there.
- **Off means nothing is registered.** A display-media handler changes what every screen share
  in the app does, ScreenSense's included, so the flag-off build is byte-for-byte the old
  behaviour — asserted, not assumed.
- The module deliberately does not `require("electron")`: everything is injected, so the
  platform table is unit-tested in Node. "Manual QA on two machines" is not a test that runs in
  CI, and the decisions around loopback are exactly what a manual pass covers worst.

### MS10 — slides in the card · `8023b3d`

- `SlideStrip.tsx`: a strip under the transcript, and a lightbox joining a slide's caption to
  the transcript spoken while it was up. `mergeSlide` and `segmentsDuring` in `meetingState`,
  because the join is the claim of the batch and a renderer is the wrong place to test an
  interval boundary.
- **The join is half-open at the next slide.** A segment whose `t0` equals the next slide's
  timestamp belongs to the next slide — the words began as it went up — and a closed interval
  would file the opening sentence of every slide under the one before it. Attribution is by
  where a segment *starts*, so a sentence spanning a change appears once.
- **The server now announces a keyframe twice**: when it is taken, and again when the caption
  lands. The strip upserts on `id`. Without the first frame an install with no vision model
  has an empty strip for a meeting full of slides, and a slide that appears three seconds
  late looks like a slide that was missed.
- **A defect a test of my own found:** `mergeSlide` spread the incoming frame over the stored
  one, so a `caption: null` arriving out of order across a reconnect would erase a caption
  already on screen. Fields are now only overwritten by a value that says something.

### MS9 — the keyframe scheduler, and captions · `0e0281f`

- **Client** (`homepilot-meetingsense.js`, mirrored): a 500 ms sampler → 64×36 gray → dHash and
  a changed-pixel ratio; motion gate > 35 % *against the last capture*, 1.5 s stability, an 8 s
  floor, a 5 min heartbeat, and a rolling-hour cap. Keyframe → JPEG → `/upload` → `keyframe`
  frame. `start({ watch: true })` also keeps the shared **video** track when the share carried
  no audio, which it previously stopped.
- **Server** (`keyframes.py`): `analyze_image` with a prompt written for a slide, a dHash
  reused **within one meeting** so a re-shown slide is captioned once, refusal and length
  filtering, and every failure swallowed. Captioning runs as a task beside the frame loop;
  `stop` waits up to 8 s and cancels the rest.
- **The rule is change *plus stillness*, not change.** A slide flip, a scroll and a video all
  move most of the frame; only one of them then stops. That single observation is what the
  1.5 s window buys, and it is why the heartbeat requires stillness too.
- **Keyframes use the transcript's clock**, not `Date.now()` — MS10 joins slide to speech on
  that number, and two clocks would put the join a sentence out.
- **Three test holes that mutation testing found**, each of which had let a wrong
  implementation pass: a capture sequence that started at t = 0 could not tell a rolling hour
  from a calendar bucket (the bucket's cost is at its edge); a vision stub that never suspended
  was finished by any incidental `await` inside `stop`, so the drain could be deleted; and an
  `ok: False` answer with empty text was rejected by the *length* check, so the `ok` check
  itself was doing nothing.
- `hash = NULL` matches nothing in SQL but `hash = ''` matches every other empty one, so the
  guard against an empty hash is load-bearing in a way the SQL alone is not.

---

## W4 — Brain

### MS13 — asking about a meeting · `27e75d9`

- `ask.py`: the `ask` frame on the live socket and `POST /v1/meetingsense/{id}/ask` for ended
  meetings, both through one function. Three tiers — verbatim last 90 s, MS12's recap, top-k
  keyword retrieval (k ≤ 12) — with the verbatim window excluded from retrieval.
- **Trim order is D9's priority made executable:** retrieval first, verbatim second, the recap
  never.
- The frame reports the citations the answer *actually used* from what it was offered, so an
  invented timestamp is never presented as real.
- **The headline test passed for the wrong reason:** the two-hour fixture's segments did not
  match the question, so the prompt was small because retrieval found nothing — it passed with
  the budget *and* `k` removed.
- **A real scoring bug its own test caught:** normalising by *distinct* words made a segment
  repeating one word score highest in the meeting.

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
