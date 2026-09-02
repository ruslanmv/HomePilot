# MeetingSense — implementation waves & batches (Claude Code tracker)

Companion to `MEETINGSENSE_DESIGN.md` (Part 1) and `MEETINGSENSE_DESIGN_PART2.md`.
Same discipline as `docs/design/MONOREPO_BATCHES.md`: small, additive, flag-gated,
independently shippable batches. **Every batch leaves the existing app green with all
flags off.** One batch = one Claude Code session = one PR.

**Revision 2.** The first revision assumed a single deployment — a browser on the same
machine as the backend — and a set of reuse claims that a source audit did not support.
Both assumptions are corrected here. See §1 for what changed and why; the batch list is
different enough that MS numbers were not reused.

---

## 0. Ground rules for every session (paste into each kickoff)

```
Repo: ruslanmv/HomePilot, branch off claude/upgrade-feature-batches-3x0z82.
Read first: docs/design/MEETINGSENSE_DESIGN.md, docs/design/MEETINGSENSE_DESIGN_PART2.md,
            docs/design/MEETINGSENSE_BATCHES.md (this file, esp. §1 and §2),
            community/addons/screensense/DESIGN.md,
            backend/app/avatar_director/protocol.py, backend/app/voice/providers.py.
Rules:
  - Additive only. Never edit an existing endpoint signature, table column, chat path, or
    component behaviour. New code goes in backend/app/meetingsense/**,
    frontend/src/ui/meetingsense/**, frontend/public/js/homepilot-meetingsense.js,
    agentic/integrations/mcp/meetingsense_server.py.
  - "Additive" has one documented exception, MS1, and it is spelled out there. If a batch
    finds it needs a second one, STOP and report — do not widen the exception yourself.
  - Everything behind flags (config.py + VITE_*). Default off. With flags off, `make test`
    and `cd frontend && npm run build` must pass unchanged.
  - Follow the existing patterns: WS JSON frames like /v1/voice/session; router include like
    voice_router; sqlite migrations "CREATE TABLE IF NOT EXISTS"; MCP servers via
    agentic/integrations/mcp/_common/server.py (ToolDef + create_mcp_app).
  - Tests for every new module (pytest under backend/tests/meetingsense/, vitest for
    frontend). A batch that changes behaviour ships a test that fails without the change.
  - Finish by updating the Status column of this file and writing a short CHANGELOG entry.
  - Do not start the next batch. Stop, report what was verified and how to run it.
```

---

## 1. What revision 2 changes, and why

### 1.1 Findings from the source audit

Six claims in the design documents did not survive a check against the tree. Each is now
either a batch or a stated constraint rather than an assumption a session would discover
halfway through.

| Finding | Evidence | Where it lands |
|---|---|---|
| Port 9120 is the Inventory MCP server | `Makefile:418, 500, 1286` | MS17 takes **9107** |
| Electron desktop has no `MediaStream` — `enable()` returns early, `stream`/`video` stay null | `homepilot-screensense.js:69–89`, `desktop/main.js:499` returns a still | MS5 owns its own capture; MS9 adds the desktop path |
| STT discards `seg.start`/`seg.end` and rebuilds the model per call. ~~CPU-only~~ — **corrected in MS1**: faster-whisper's `device` default is already `auto`, so CUDA is used when usable; the real problem is that `auto` falls back to CPU *silently*, which is why MS1 reports the resolved device rather than only exposing the knob | `voice/providers.py:302, 307, 357`; faster-whisper 1.0.3 `transcribe.py` | **MS1**, before anything depends on it |
| LTM jobs read chat messages, not `ms_segments`; `schedule_session_jobs` needs a project + a `sessions` row | `jobs.py:204, 375` | MS14 — and the claim is scoped down, not fixed by force |
| `vectordb` is project-scoped end to end | `vectordb.py:58, 111` | MS15 adds a `namespace` parameter |
| `hp-teams` (9106) is registered in Forge but has no implementation | `seed_all.py:67`, no `teams_server.py` | MS22 builds it; it is not reuse |

### 1.2 The deployment that revision 1 did not plan for

Revision 1 specifies one transport: `WS /v1/meetingsense/session`, opened by the browser.
That works when the browser and the backend are the same machine. It does not work for
**yourfriend.online**, which is the deployment this feature is for:

- an HTTPS page may not open `ws://localhost:8000` — mixed content, blocked;
- a hosted page's `localhost` is the server that served it, not the user's PC.

This is the same wall the Behavior Director hit, and it has an answer already built:
OllaBridge proxies `wss://…/v1/avatar/session` to HomePilot's `/avatar/session`, injecting
the credential, locally as a direct proxy and through Cloud over the relay link.

So MeetingSense needs **two transports over one session core**, and the core must not know
which one it is talking to. That is the spine of this revision.

### 1.3 The avatar session already carries almost every frame MeetingSense needs

`avatar_director/protocol.py` is explicitly built to grow:

> **An unknown `type` is ignored, silently.** That is what lets addendum v1.2 add
> `display`, `adult_ack` and `streak` without a version bump.

And it already carries the shapes:

| MeetingSense needs | The avatar session already has |
|---|---|
| audio → transcript | `voice_transcript` — client recogniser, final text up (`rtc.py:56`) |
| screen frame → caption | `vision_ask` → `vision_insight` (`vision.py:187`) |
| a live card | `display` with kinds `agenda cards tool_result stats share` (`panels.py:41`) |
| server-initiated notes | `intent`, `say` — how curiosity already speaks first |

**Do not build a second session protocol.** MS7 adds four frame types to the existing one
and gets the OllaBridge path, the relay, the credential handling and VR rendering for free.

### 1.4 MeetingSense is a Together activity, not a parallel product

The avatar client ships seven activities behind the 👥 launcher, and one of them —
`screen-insight.js`, "Look at my screen" — already owns a consent machine, a grant-based
`CapturePipeline`, and revocation that cancels in-flight frames. ScreenSense owns a second
capture path. A third would be the one nobody maintains, and the one that gets consent
wrong.

MeetingSense is therefore an eighth activity (`meeting.js`) that **borrows B11's consent
machine and capture pipeline** rather than calling `getDisplayMedia` itself. Audio is the
only genuinely new capture surface.

### 1.5 Consequences for sequencing

- **MS1 moves first.** Three separate STT defects each break a headline promise, and every
  later batch depends on transcription. Fixing them after MS4 means rewriting MS4.
- **The compatibility wave (W2) comes before the interesting features.** A recorder that
  only works on localhost is a demo. Two transports early means every later batch is
  written once, for both.
- **W1 is still shippable alone**, on the local transport, as revision 1 intended.

---

## 2. Overview

| Wave | Theme | Batches | Outcome when done |
|---|---|---|---|
| **W0** | Foundation | MS0 → MS1 | Flags, skeleton, status endpoint; STT that reports timestamps and uses the GPU |
| **W1** | Recorder | MS2 → MS6 | Screen + audio → live transcript in a chat card, export. Local transport |
| **W2** | Reach | MS7 → MS8 | Same recorder from yourfriend.online through OllaBridge; a Together activity |
| **W3** | Eyes | MS9 → MS11 | Slide-aware keyframes captioned by the local vision model; desktop loopback |
| **W4** | Brain | MS12 → MS14 | Rolling notes, "ask about this meeting", final summary |
| **W5** | Memory | MS15 → MS17 | Retrieval, meeting↔conversation binding, resume/branch |
| **W6** | Together | MS18 → MS20 | Live grounded chat, chips, panels on the avatar surface |
| **W7** | Capability | MS21 → MS22 | MeetingSense MCP server (**9107**) + Forge; the Teams server that does not exist yet |
| **W8** | Engine | MS23 → MS24 | LangGraph agent replaces the fixed loop |
| **W9** | Modes & voice | MS25 → MS27 | Participant / Coach / Presenter / Practice; TTS into the call |
| **W10** | Optional UI | MS28 | Meetings catalog — only if History gets crowded |

Waves are sequential; batches inside a wave are sequential unless marked ∥ (parallel-safe).

Status legend: ⬜ todo · 🔄 in progress · ✅ done · ⏸ deferred

---

## 3. Batches

### W0 — Foundation

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS0** | Skeleton + flags | `backend/app/meetingsense/{__init__,config,routes}.py`; `MEETINGSENSE_ENABLED` plus sub-flags `_REMOTE _TOGETHER _CATALOG _MCP _AGENT _MODES`, all default false; `GET /v1/meetingsense/status` → `{enabled, stt:{provider,timestamps,device}, vision, flags}`; router included in `main.py` (+2 lines, mirroring `voice_router`); `VITE_MEETINGSENSE_ENABLED`; design docs into `docs/design/`; `docs/MEETINGSENSE.md` stub | status returns a disabled body when the flag is off and never 500s; pytest for both states; `make test` green | ✅ |
| **MS1** | STT capability layer | **The one sanctioned exception to additive-only.** `voice/providers.py` gains, without changing any existing signature: `device`/`compute_type` from `WHISPER_DEVICE`/`WHISPER_COMPUTE` (default `auto`, which is today's behaviour); a `transcribe_segments()` returning `[{t0,t1,text,conf}]` beside the existing `transcribe()`; a module-level provider cache so `get_stt_provider()` stops rebuilding `WhisperModel`. `status` reports which of the three are available | pytest: `transcribe()` byte-identical behaviour on a fixture; `transcribe_segments()` returns spans; the same provider object is returned twice; a provider without segment support degrades to one span covering the whole clip | ✅ |

> **Why MS1 is allowed to touch `voice/providers.py`.** Every alternative is worse: a fork
> of the provider means two Whisper loaders and two bug surfaces; wrapping it cannot recover
> timestamps the wrapped function has already discarded. The rule the batch keeps is
> narrower and checkable — *no existing signature or default changes*, and the voice
> backend's own tests pass untouched. Any second exception stops the wave.

### W1 — Recorder (local transport)

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS2** | Store + session core | `store.py` (`ms_meetings ms_segments ms_keyframes ms_notes`, `CREATE TABLE IF NOT EXISTS`, migration called at startup only when the flag is on); `session.py` `MeetingSession` state machine (`idle→live→ended`), in-memory registry, elapsed ticker; `transcript.py` utterance assembler (200 ms overlap, trailing-token dedupe). **The core takes a `Transport` protocol — `send(frame)` and nothing else — and never imports FastAPI.** | unit tests: assembler dedupe, lifecycle, store round-trip; a test constructs `MeetingSession` with a list-backed fake transport and no web framework imported | ⬜ |
| **MS3** | Local WebSocket transport | `WS /v1/meetingsense/session` implementing Part 1 §5.2 — `start/audio/mute/stop/ping` → `ready/partial/segment/status/final/error`; wraps raw PCM16 in a WAV header before the provider (`transcribe` writes bytes to a `.{fmt}` temp file — raw PCM is not a WAV); one provider held per connection, as `voice/routes.py:56` does; 2-channel → `speaker: me/them`; rejects when the flag is off | pytest with `TestClient` websocket + `NullSTTProvider`; synthetic PCM produces segments; a second connection reuses the cached provider | ⬜ |
| **MS4** | Audio capture addon | `frontend/public/js/homepilot-meetingsense.js` (+ the mirrored copy under `community/addons/meetingsense/` — the ScreenSense pair are byte-identical today and `frontend/index.html:15` loads the public one; keep the discipline): `hpMeetingSense.start/stop/muteMic`; `getUserMedia` + `getDisplayMedia({audio:true})`; AudioContext mixer on **separate gain nodes** so mute is a gain change; AudioWorklet → 16 kHz PCM16 20 ms frames; energy VAD, 1–3 s utterances, 8 s hard cut; reports `audioMode ∈ {system+mic, system, mic, none}` | vitest for the framer and VAD against synthetic buffers; manual matrix (Chrome tab audio, Edge, Firefox → mic) in `docs/MEETINGSENSE.md` | ⬜ |
| **MS5** | Entry point | The ScreenSense button becomes the two-toggle popover (Part 1 §2.1). **"Ask once" keeps its exact current path.** MeetingSense opens its *own* video stream rather than reading `hpScreenSense.video`, which is null in desktop mode; the popover states which capture it is using | flag off → the button is byte-identically what it is today, asserted by a test on the rendered DOM; flag on → popover; desktop and browser both reach a working session | ⬜ |
| **MS6** | Live card + export | `frontend/src/ui/meetingsense/{useMeetingSense.ts, MeetingCard.tsx, RecordingPill.tsx, ConsentSheet.tsx}`; card renders for assistant messages beginning `[Meeting]`, plain-text fallback preserved; pill always visible while live; `GET /v1/meetingsense/{id}` and `/export?fmt=md\|srt\|json`; on stop, persist the `[Meeting]` message via `add_message`. **The consent sheet names the resolved STT provider** — `get_stt_provider()` prefers `OpenAICompatSTTProvider` whenever `STT_BASE_URL` is set, so "local by default" is not automatic | flag off → no header button, no card branch executed; vitest snapshots per card state; e2e start → speak → segments → stop → export; a test asserts the sheet shows the provider name when `STT_BASE_URL` is set | ⬜ |

**W1 exit:** a working recorder for anyone whose browser and backend are the same machine.

### W2 — Reach (the compatibility spine)

> This wave is what makes the feature exist for **yourfriend.online**. Nothing here adds a
> user-facing capability; it makes the W1 capability reachable, and it is the point at which
> every later batch stops needing to be written twice.

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS7** | Avatar-session transport | Four frame types added to `avatar_director/protocol.py`'s sets — client `meeting_start`, `meeting_audio`, `meeting_stop`; server `meeting`. **No version bump**: the protocol's contract is that an unknown type is ignored, which is exactly what an older client or server will do. `avatar_director/session.py` routes them to the same `MeetingSession` MS2 built, through the same `Transport` protocol. Segments may ride the existing `voice_transcript` shape where the client already has a recogniser | pytest: a `MeetingSession` driven through the avatar handler produces frame-for-frame the same output as through MS3's WS; an old client sending no meeting frames is unaffected; an unknown meeting sub-type is ignored rather than erroring | ⬜ |
| **MS8** | Through OllaBridge | Verify and document the path end to end: the avatar client on yourfriend.online → OllaBridge `/v1/avatar/session` → HomePilot. **Confirm the proxy is a pipe** — it reads only the `hello` and pumps the rest verbatim, so meeting frames need no proxy change; add a test that asserts that. Cloud path: meeting frames ride the existing `sig`/`ev` relay stream. `GET /v1/meetingsense/status` gains `remote_ok` so the avatar can say why it cannot record | pytest in ollabridge: a meeting frame crosses the proxy byte-identically; a meeting frame crosses the relay with its stream id intact; HomePilot-side test that `_REMOTE` off refuses avatar-session meeting frames with a named error | ⬜ |

**W2 exit:** the same recorder, reached from a hosted avatar, with no new URL or token for the
user to configure.

### W3 — Eyes

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS9** | Keyframe scheduler | In the addon: 500 ms sampler → 64×36 gray → dHash + changed-pixel ratio; motion gate (> 35 %), 1.5 s stability, 8 s min interval, 5 min heartbeat, hourly cap; JPEG → `/upload` → `keyframe` frame. Server `keyframes.py` stores and calls `analyze_image()` with `persist=false` | vitest: synthetic sequences (slide flip / scroll / video / cursor wiggle) produce the expected capture decisions — this is the test that earns the thresholds; pytest: keyframe → caption with a vision stub | ⬜ |
| **MS10** | Slides in the card | `SlideStrip.tsx`, lightbox showing caption plus the transcript spoken while that slide was up (join on `t0`) | vitest: the join picks the right segments at a boundary | ⬜ |
| **MS11** ∥ | Desktop loopback | `desktop/main.js` `setDisplayMediaRequestHandler(..., audio:'loopback')` with `useSystemPicker`; `preload.js` exposes `meetingSenseAudio`. **Document the answer rather than leaving the TODO**: `desktop/package.json` pins electron ^33.3.1, where loopback is Windows-only — macOS is mic-or-virtual-device, and the addon should say so | manual QA on Windows and macOS; desktop build unchanged with the flag off | ⬜ |

### W4 — Brain

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS12** | Notes engine | `notes_engine.py` + `prompts.py`: every 60 s / 400 words, a JSON-delta prompt (add/resolve decisions, actions, questions, summary) with `t0` citations, merged server-side, stored in `ms_notes`, pushed as a `notes` frame; card section uses append + strikethrough, never rewrite | pytest with an LLM stub returning fixed deltas → merge correctness; malformed JSON tolerated without dropping the session | ⬜ |
| **MS13** | Ask about this meeting | `ask` frame → recent-window + keyword retrieval over `ms_segments`/`ms_keyframes` → LLM → `answer`; `POST /v1/meetingsense/{id}/ask` for ended meetings | pytest: the answer cites timestamps that exist in the fixture | ⬜ |
| **MS14** | Final summary + retention | On stop: a summary message with slide thumbnails in `media.images`; retention (`text` / `text+frames` / `all`); one-click delete. **LTM is scoped down, not forced**: `_process_summarize_session` reads `get_recent(conversation_id)`, which in Card-only mode holds one marker and one summary — so this batch enqueues `schedule_session_jobs` only when a project *and* a session row exist, and documents that the persona's route to a meeting is retrieval (MS15), not memory extraction | pytest: stop produces the summary message; delete removes rows and files per retention; a test asserts no job is enqueued when there is no session row, instead of enqueuing one that no-ops | ⬜ |

### W5 — Memory

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS15** | Embeddings + retrieval | `vectordb.py` gains a `namespace` parameter defaulting to `"project"` — every existing call keeps its collection name, and meetings stop borrowing the project namespace where `get_project_document_count` and `delete_project_knowledge` would find them. On stop, embed segments and slide captions; internal `ms.search`; MS13 uses it beyond the 90 s window | pytest: existing project collections resolve to the same names as before the change (asserted against the current hash); cross-meeting query cites `meeting · t0` | ⬜ |
| **MS16** | Binding + resume | `ms_threads`, `ms_artifacts`; the frozen card hydrates on reopening the conversation; "New thread from this meeting" creates a conversation with a brief message and an attached `meeting_id`; "Attach to project" pushes `transcript_md` + captions through the existing project upload path | e2e: reopen → card; branch → brief present; attach → the project KB finds it | ⬜ |
| **MS17** ∥ | Auto-metadata | Calendar match through the `google_calendar` / `microsoft_graph` MCP servers → title, attendees, link; source detection from the shared window title | pytest: title heuristics; manual: calendar match | ⬜ |

### W6 — Together

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS18** | Live context provider | An optional hook in `personalities/prompt_builder.py` (note the path — it is not at `backend/app/prompt_builder.py`): when a conversation has a live `meeting_id`, prepend the `[LIVE MEETING CONTEXT]` block, ≤ 900 tokens; behind `MEETINGSENSE_TOGETHER` | pytest: the prompt is byte-identical when no meeting is live or the flag is off; the block appears otherwise; the token budget holds on a long fixture | ⬜ |
| **MS19** | The eighth activity | `meeting.js` joins the seven activities behind the 👥 launcher. **It borrows B11's consent machine and `CapturePipeline` rather than calling `getDisplayMedia`** — a third capture path is the one that gets revocation wrong. The launcher's activity-scoped permission model already fits: a meeting asks for screen and microphone, after the choice, never before | vitest: choosing Meeting requests exactly screen + mic and nothing else; revoking consent mid-meeting stops capture within a frame, as `screen-insight` already proves for frames; the launcher's other seven activities are untouched | ⬜ |
| **MS20** | Card on the avatar surface | The meeting card renders through the existing `display` panel channel as a `cards` kind — one data source, two renderers (React for the HomePilot web UI, `PanelRenderer` for the avatar and VR). Panels are capped at 64 KB and row-limited server-side, so the live card sends a **summary projection**, not the transcript | pytest: a panel built from a long meeting passes `panels.validate()` and stays under `DEFAULT_MAX_KB`; a meeting with 400 segments does not produce a 400-row panel | ⬜ |

### W7 — Capability

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS21** | MCP server | `agentic/integrations/mcp/meetingsense_server.py` on **port 9107** (9120 is Inventory — `Makefile:418`; 9107 sits in the free gap after `hp-teams` at 9106) with `ms.list_meetings get_meeting get_transcript search get_live_context get_slide update_action suggest set_mode export`; write tools policy-gated; added to `docker-compose.mcp.yml` | `tests/test_mcp_servers_rpc.py`-style RPC tests per tool; a test asserts the port is not one the Makefile already starts | ⬜ |
| **MS22** | Forge + Teams | Register in `seed_all.py`, gateway/virtual-server YAML, suite manifests. **`hp-teams` (9106) is registered but has no implementation** — this batch either builds the thin server for tier-2 "post to meeting chat" or moves that promise to ⏸, but does not describe it as reuse | `make test-mcp-servers` green; the catalog lists the server; if Teams is deferred, tier 2 is marked unavailable in the UI rather than failing at click time | ⬜ |

### W8 — Engine

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS23** | LangGraph graph | `meetingsense/agent/{graph,state,modes}.py` + `nodes/`; `Reflect` wraps MS12, `Recall` wraps MS15, `Act` uses `agentic/runtime_tool_router.py`; behind `MEETINGSENSE_AGENT`, falling back to the fixed loop when off | pytest: the graph runs end to end on a recorded event fixture with every external stubbed, and produces **identical output to the fixed loop** in Note-taker mode — that equivalence is the batch's real acceptance | ⬜ |
| **MS24** | Sub-agents + policy | `SlideReader`, `ActionExtractor`; per-meeting tool pre-approval; `ms.set_mode` enforced server-side | pytest: an unapproved `Act` produces a chip, an approved one calls; a client cannot compose a mode the server did not define | ⬜ |

### W9 — Modes & voice

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS25** | Chips | Deterministic triggers (question aimed at me, decision, action, date, URL on a slide) → a `chip` frame; chip UI in the card; actions routed through the runtime tool router under ask-before-acting | vitest: chip render and dismiss; pytest: trigger fixtures, including the ones that must *not* fire | ⬜ |
| **MS26** | Participant + Presenter | Mode prompts and trigger sets; Participant answers when addressed by persona name; Presenter takes an attached deck, paces, queues audience questions | e2e fixtures per mode | ⬜ |
| **MS27** | Coach + Practice + voice | Coach draws talking points strictly from user-uploaded prep material, the pill reads "Coach", and the consent copy says so; Practice runs a mock interview through `voice_call/`; tier-3 TTS into a virtual microphone, desktop only, with barge-in via `voice_call/barge_in.py` | e2e; **an explicit test that Coach never receives screen OCR text** — Part 2 §E.2's refusal is only real if something enforces it; manual matrix for the virtual device | ⬜ |

### W10 — Optional UI

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS28** | Meetings catalog | `MeetingLibrary.tsx` + `MeetingDetail.tsx`; nav item behind `MEETINGSENSE_CATALOG`. Cheaper first step: a "Meetings" filter chip in History | flag off → the sidebar is identical; vitest for filters and search | ⏸ decide after W5 |

---

## 4. Kickoff prompt template (one per batch)

```
You are working in ruslanmv/HomePilot on a new branch `claude/meetingsense-<MSn>` from
`claude/upgrade-feature-batches-3x0z82`.

Task: implement batch <MSn> "<name>" exactly as scoped in docs/design/MEETINGSENSE_BATCHES.md §3,
using MEETINGSENSE_DESIGN.md §<sections> and MEETINGSENSE_DESIGN_PART2.md §<sections> as the spec,
and §1 of the batches file as the list of things the design documents get wrong.

Before coding: list the existing files you will touch and the new files you will add, and confirm
the touch list is only the additive edits allowed by §0. If it is not, stop and say so.

Then implement, write tests, and run `make test` plus `cd frontend && npm run build` with all
MEETINGSENSE flags off, then again with this batch's flag on. Update the Status cell for <MSn>
and add a CHANGELOG line.

Stop after reporting: what was built, how to verify it manually, and what you could not verify
from here. Do not begin the next batch.
```

---

## 5. Definition of done (per batch)

- [ ] Flags off → `make test`, `npm run build`, desktop build unchanged
- [ ] Flag on → new tests pass; manual steps written into `docs/MEETINGSENSE.md`
- [ ] No existing endpoint / column / component behaviour modified — diff reviewed, and the
      one sanctioned exception (MS1) not widened
- [ ] Consent and the visible recording indicator preserved in any UI batch
- [ ] From W2 onward: the batch works on **both** transports, or says explicitly why it is
      local-only
- [ ] Status updated here; CHANGELOG entry

---

## 6. Compatibility contracts (do not break these)

Three things outside this repo depend on what MeetingSense touches. Each has a test that
belongs to whichever batch first puts it at risk.

**OllaBridge.** The avatar-session proxy reads exactly one frame — the `hello` — and pumps
everything after it verbatim. Meeting frames therefore need no proxy change, and that is a
property to assert rather than assume: MS8 ships a test that a meeting frame crosses the
proxy and the Cloud relay byte-identically. If a batch ever needs the proxy to understand a
meeting frame, the design has gone wrong.

**The avatar protocol.** `PROTOCOL_VERSION` stays 1. New types are added to the type sets
and nothing else, because the protocol's stated contract is that an unknown type is ignored
silently — that is how `display`, `adult_ack` and `streak` landed without a bump, and it is
what lets an old avatar and a new HomePilot keep talking.

**Together mode.** The 👥 launcher's seven activities, its activity-scoped permission model,
and the consent machine are not modified. MeetingSense is an eighth activity that borrows
them. A test asserts the other seven are untouched, in the same way B30's launcher tests
assert the footer buttons keep their order.

---

## 7. Suggested cadence

W0 and W1 first — six sessions — for a usable recorder on a local machine. **Then W2 before
anything else**, because it is what makes the feature exist for yourfriend.online and because
every batch after it is written once instead of twice.

Pause there and use it in real meetings for a week. Then order W3 against W4 by what actually
hurt: not seeing the slides, or not having the notes. W6 is where the "together" value shows
up; W8 through W10 are refinement and can be reordered or dropped.

One honest caveat about the whole plan: the latency budget in Part 2 §F assumes GPU
transcription, and until MS1 lands and someone runs it on the reference machine, that budget
is a hypothesis. Measure it at the end of W1 rather than at the end of W9.
