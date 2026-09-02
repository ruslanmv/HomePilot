# MeetingSense — implementation waves & batches (Claude Code tracker)

Companion to `MEETINGSENSE_DESIGN.md` (Part 1) and `MEETINGSENSE_DESIGN_PART2.md`.
Same discipline as `docs/design/MONOREPO_BATCHES.md`: small, additive, flag-gated,
independently shippable batches. **Every batch leaves the existing app green with all
flags off.** One batch = one Claude Code session = one PR.

**Revision 4 — after MS1.** Supersedes revisions 1–3, which it keeps almost entirely: the
structure, the decisions D1–D7 and the MS numbering are rev 3's. What changed is what
implementing MS0 and MS1 taught, and one row of §1 that was **wrong**.

Reflects the branch at `3b8e1a8` — MS0 and MS1 landed, 83 tests under
`backend/tests/meetingsense/`. Where this file and a design document disagree, **this file
wins**; the design documents are the spec for *what*, this file is the contract for *how and
in what order*.

Changed in rev 4, all of it measured rather than assumed:

* §1 row 4 claimed STT is CPU-only. **It is not** — faster-whisper's `device` default is
  already `auto`. Corrected, with the evidence, and with the real problem stated instead.
* §1 gains two rows that will bite a future batch: the test-suite module purge, and a
  cosmetic wart in `transcribe()` that must **not** be tidied.
* MS1's row records the two acceptance items it did **not** meet, rather than reporting done
  and losing them.
* §7 gains the two contracts MS1 created.

---

## 0. Ground rules for every session (paste into each kickoff)

```
Repo: ruslanmv/HomePilot, branch off claude/upgrade-feature-batches-3x0z82.
Read first: docs/design/MEETINGSENSE_BATCHES.md (this file — §0, §1, §2, then your batch row),
            docs/design/MEETINGSENSE_DESIGN.md, docs/design/MEETINGSENSE_DESIGN_PART2.md,
            community/addons/screensense/DESIGN.md,
            backend/app/meetingsense/ (MS0: config.py, routes.py, tests),
            backend/app/voice/routes.py, backend/app/voice/providers.py,
            backend/app/avatar_director/protocol.py.
Rules:
  - Additive only. Never edit an existing endpoint signature, table column, chat path, or
    component behaviour. New code goes in backend/app/meetingsense/**,
    frontend/src/ui/meetingsense/**, frontend/public/js/homepilot-meetingsense.js
    (+ mirrored copy under community/addons/meetingsense/), agentic/integrations/mcp/meetingsense_server.py.
  - "Additive" has exactly one sanctioned exception, MS1 (voice/providers.py). If your batch
    needs a second one, STOP and report — do not widen the exception yourself.
  - Everything behind flags (backend/app/meetingsense/config.py + VITE_*). Default off. With
    flags off, `make test` and `cd frontend && npm run build` must pass unchanged.
  - One audio wire contract in the codebase: {"type":"audio","format":"wav","data_b64":...}
    exactly as /v1/voice/session. MeetingSense adds optional "seq","t0","t1" but never renames.
  - Follow existing patterns: WS JSON frames like /v1/voice/session; router include like
    voice_router; sqlite "CREATE TABLE IF NOT EXISTS"; MCP servers via
    agentic/integrations/mcp/_common/server.py (ToolDef + create_mcp_app) — pick a real
    server there as template (e.g. microsoft_graph_server.py); knowledge_server.py does not exist.
  - Tests for every new module (pytest under backend/tests/meetingsense/, vitest for
    frontend). A batch that changes behaviour ships a test that fails without the change.
  - backend/tests/conftest.py:34 purges every `app.*` module from sys.modules in a session
    fixture. So: import app modules INSIDE a fixture, never at test-module scope, and patch
    the module OBJECT, not the dotted string. A module captured at collection time is a
    different object from the one monkeypatch.setattr("app...") reaches afterwards — the
    patch lands on one and the code runs in the other. This passes alone and fails in the
    suite, which is the worst way for it to fail. MS0's tests hit it; MS1 fixed them.
  - Consent + always-visible recording indicator are never weakened by any UI batch.
  - Finish by updating the Status column of this file and writing a short CHANGELOG entry.
  - Do not start the next batch. Stop, report what was verified, how to run it, and what
    you could not verify from here.
```

---

## 1. What the source audit found (facts, not assumptions)

Every row below was checked against the working tree. Each is now a batch or a constraint.

| Finding | Evidence | Where it lands |
|---|---|---|
| Port 9120 is the Inventory MCP server | `Makefile:418, 500, 1286` | MS21 uses **9107** (free gap after `hp-teams` 9106) |
| Electron desktop has no `MediaStream`: `enable()` returns early, `stream`/`video` stay null; capture is a PNG still over IPC | `homepilot-screensense.js:69–89`, `desktop/main.js:499` | MS5 opens its **own** stream; MS11 adds the desktop path |
| ScreenSense hardcodes `audio: false` | `homepilot-screensense.js:100` | Not edited. MeetingSense owns capture (§2 D1) |
| ~~STT is CPU-only~~ — **WRONG, corrected in rev 4.** `WhisperModel.__init__` takes `device: str = "auto"`, which already selects CUDA when usable. The earlier claim read the call site, not the library. The *real* problem: `auto` is a request, not an outcome — it falls back to CPU **silently** when CUDA is present but unusable (mismatched ctranslate2 wheel, missing cuDNN), and transcription then runs ~10× slower than Part 2 §F assumes with nothing saying so | faster-whisper 1.0.3 `transcribe.py`, `WhisperModel.__init__` | MS1 ✅ — exposes the knobs *and* reports the **resolved** device, read back off the loaded model |
| STT discards `seg.start/end`, and `get_stt_provider()` builds a fresh provider per call (the model lives on the instance, so a caller fetching one per utterance reloads it) | `voice/providers.py:307–308, 357–360` | **MS1** ✅ |
| `backend/tests/conftest.py` purges `app.*` from `sys.modules` in a session fixture | `conftest.py:34, 78` | Every test-writing batch — see §0. Import inside fixtures; patch objects, not strings |
| `transcribe()` returns `"hello  there"` — faster-whisper segment text carries a leading space and `" ".join()` adds another | `voice/providers.py`, joined-segment path | **Do not tidy.** It is a shared path; `transcribe_segments()` strips per span so transcripts do not inherit it (§7) |
| `get_stt_provider()` prefers `OpenAICompatSTTProvider` whenever `STT_BASE_URL` is set — a cloud surprise for meetings | `voice/providers.py:358` | MS0 status names the provider ✅; MS6 consent sheet shows it |
| `transcribe()` writes bytes to a `.{fmt}` temp file — raw PCM16 is not a WAV | `voice/providers.py:304` | MS3 wraps PCM in a WAV header server-side |
| LTM jobs read `get_recent(conversation_id)` (chat messages) and need a project **and** a `sessions` row | `jobs.py:204, 375` | MS14: retrieval-first, no LTM extraction (§2 D4) |
| `vectordb` is project-scoped end to end | `vectordb.py:58, 111, 155, 178` | MS15 adds `namespace` param, default `"project"` |
| `hp-teams` (9106) is registered in Forge but has no implementation; `microsoft_graph_server.py` exists | `seed_all.py:67`, `ls agentic/integrations/mcp/` | MS22 builds it or defers tier 2; never "reuse" |
| `prompt_builder.py` lives at `backend/app/personalities/prompt_builder.py` | tree | MS18 path fixed |
| The ScreenSense addon ships twice, byte-identical; `index.html:15` loads the public copy | `cmp` of both files | MS4 mirrors + a test asserts identity |
| Electron `^33.3.1`: `audio:'loopback'` is Windows-only | `desktop/package.json:27` | MS11 documents macOS = mic or virtual device. Resolved: **no** |
| A hosted page (yourfriend.online) cannot open `ws://localhost`; OllaBridge already proxies `/v1/avatar/session` as a pipe; the avatar protocol ignores unknown types | `avatar_director/protocol.py`, OllaBridge proxy | Two transports over one core: MS2 `Transport`, MS7/MS8 |
| The 👥 launcher's `screen-insight.js` already owns a consent machine + `CapturePipeline` | avatar client | MS19 borrows it; no third capture path |

---

## 2. Decisions (resolved — do not reopen inside a batch)

| # | Question | Decision | Why (best practice + simplest UX) |
|---|---|---|---|
| **D1** | Own capture or extend ScreenSense? | **Own it.** MeetingSense opens its own `getDisplayMedia`/`getUserMedia`. ScreenSense is untouched | ScreenSense's promise is "silent still, zero backend". MeetingSense breaks both by design. ~150 duplicated lines buy a stable ScreenSense forever; the popover can state exactly which capture it uses |
| **D2** | May MS1 edit `voice/providers.py`? | **Yes, additively, once. Done in `3b8e1a8`.** `WHISPER_DEVICE`/`WHISPER_COMPUTE` (defaults `auto`/`default` = today's behaviour exactly), `transcribe_segments()` beside `transcribe()`, a provider cache keyed on config, and `supports_segments` | Every alternative (fork, monkeypatch, subclass elsewhere) is worse. Held: `transcribe` keeps its signature, `transcribe` stays the only abstract method, selection order is unchanged, every voice suite green. The cache is keyed rather than a singleton so an edited `.env` is not served a stale provider |
| **D3** | MCP port | **9107** | Free; adjacent to hp-teams where a reader looks |
| **D4** | Should meetings reach long-term memory? | **Retrieval, not extraction.** The final summary is a normal chat message (readable, deletable). Everything else reaches personas through `ms.search` + vector namespace. No MeetingSense job type, no LTM claim in v1 | This is how Otter / Fireflies / Copilot work: index + cite, never "remember". Deletes finding 04 instead of fixing it. If a meeting is attached to a project, existing jobs work unchanged because the summary is a message |
| **D5** | Where does the catalog live? | **History.** Meeting = conversation, auto-titled `🎙 <title> · <source> · <date>`. Sidebar tab (MS28) only if History gets crowded | Zero nav change; reuses `/conversations/{id}/search` |
| **D6** | Wire format for audio | **Identical to voice**: `format:"wav"`, `data_b64`; optional `seq/t0/t1` | One contract to debug |
| **D7** | Local pilot vs. hosted reach first | **W1 → one-week pilot on localhost → W2.** The `Transport` protocol in MS2 makes the order free | Fastest real feedback; W2 is still mandatory before W3 |

---

## 3. Overview

| Wave | Theme | Batches | Exit criterion |
|---|---|---|---|
| **W0** | Foundation | MS0 ✅ → MS1 ✅ | Flags, status endpoint; STT that returns timed spans, names its device, loads once. Two items carried: MS1-a, MS1-b |
| **W1** | Recorder (local) | MS2 → MS6 | Screen + audio → live transcript in a chat card, export. **Pilot for a week here** |
| **W2** | Reach | MS7 → MS8 | Same recorder from yourfriend.online through OllaBridge, no new URL/token |
| **W3** | Eyes | MS9 → MS11 | Slide-aware keyframes captioned locally; desktop loopback (Windows) |
| **W4** | Brain | MS12 → MS14 | Rolling notes, "ask about this meeting", final summary + retention |
| **W5** | Memory | MS15 → MS17 | Retrieval namespace, binding/resume/branch, auto-metadata |
| **W6** | Together | MS18 → MS20 | Live grounded chat, meeting as 8th 👥 activity, card on avatar surface |
| **W7** | Capability | MS21 → MS22 | MeetingSense MCP server (9107) + Forge; Teams server or explicit defer |
| **W8** | Engine | MS23 → MS24 | LangGraph agent, output-identical to the fixed loop in Note-taker |
| **W9** | Modes & voice | MS25 → MS27 | Chips; Participant / Presenter / Coach / Practice; TTS into the call |
| **W10** | Optional UI | MS28 | Meetings catalog — only if History gets crowded |

Waves are sequential. Batches inside a wave are sequential unless marked ∥ (parallel-safe).

---

## 4. Batches

Status: ⬜ todo · 🔄 in progress · ✅ done · ⏸ deferred

### W0 — Foundation

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS0** | Skeleton + flags | `backend/app/meetingsense/{__init__,config,routes}.py`; `MEETINGSENSE_ENABLED` + sub-flags `_REMOTE _TOGETHER _CATALOG _MCP _AGENT _MODES` (none implied by the master); `GET /v1/meetingsense/status` always mounted, always 200, returning seven keys: `{enabled, ready, retention, flags, stt, vision, limits}`; probes run through a wrapper that turns any escape into "unknown" (never 500s); provider named, endpoint/credential never echoed; router in `main.py` (+2 lines); `VITE_MEETINGSENSE_ENABLED`; design docs in `docs/design/`; `docs/MEETINGSENSE.md` | 55 tests green; `make test` green | ✅ `6ad44e7` |
| **MS1** | STT capability layer | **The one sanctioned exception — spent.** In `voice/providers.py`, no existing signature changed: `WHISPER_DEVICE`/`WHISPER_COMPUTE` (defaults `auto`/`default`) passed to `WhisperModel`; the **resolved** device read back off the loaded model and reported (`device`, plus `device_note` when it differs from the request); `transcribe_segments(audio, fmt, duration_s=None) -> [{t0,t1,text,conf}]` **concrete on the ABC** with a one-span fallback; `WhisperLocalSTTProvider` returns real `seg.start/end` and `conf = exp(avg_logprob)`; `get_stt_provider()` cached on a config key, with `reset_stt_provider_cache()` for tests | 28 tests. `transcribe()` byte-identical (incl. its double space); spans returned; same object twice; text-only degrades to one span with `t1: None`; 122 green with every voice suite alongside; full backend run unchanged against baseline | ✅ `3b8e1a8` |
| **MS1-a** | *Carried from MS1* | `OpenAICompatSTTProvider.transcribe_segments` using `verbose_json` for real remote timings. **Not built** — it inherits the one-span fallback, so a remote-STT install gets `t1: None` and `supports_segments: false`. Correct and honest, but a meeting transcribed remotely cannot cite timestamps | a remote fixture returns spans with real `t0/t1`; `supports_segments` becomes true for that provider | ⬜ before W4 (MS12 cites `t0` per note) |
| **MS1-b** | *Carried from MS1* | **Measure the real-time factor on the reference GPU** and record it in `docs/MEETINGSENSE.md`. Could not be done from the build container: no CUDA, and `faster_whisper` is not installed there. Part 2 §F's latency budget stays a hypothesis until this number exists | one measured RTF for the chosen `WHISPER_MODEL`, on the machine that will run meetings | ⬜ at the end of W1's pilot |

### W1 — Recorder (local transport)

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS2** | Store + session core | `store.py` (`ms_meetings ms_segments ms_keyframes ms_notes`, `CREATE TABLE IF NOT EXISTS`, migration at startup only when the flag is on); `session.py` `MeetingSession` (`idle→live→ended`), in-memory registry, elapsed ticker; `transcript.py` utterance assembler (200 ms overlap, trailing-token dedupe). **The core takes a `Transport` protocol (`send(frame)`, `close()`) and never imports FastAPI** — two transports, one core | unit: assembler dedupe, lifecycle, store round-trip; a fake `Transport` receives the expected frame sequence | ⬜ |
| **MS3** | Local WebSocket transport | `WS /v1/meetingsense/session` — client `start/audio/mute/stop/ping`, server `ready/partial/segment/status/final/error` (Part 1 §5.2, audio frame per D6); wraps PCM16 in a WAV header before the provider; calls **`transcribe_segments(..., duration_s=<the VAD frame length>)`** — the client framed the audio and knows the span the provider may not; **one provider held per connection** (`voice/routes.py:56`, and MS1's cache makes a second fetch cheap rather than catastrophic); 2-channel → `speaker: me/them`; refuses when flag off exactly like the voice route | pytest: `TestClient` websocket with a stub STT; fake frames produce segments with `t0/t1` from `transcribe_segments`; flag-off refusal | ⬜ |
| **MS4** | Audio capture addon | `frontend/public/js/homepilot-meetingsense.js` + mirrored `community/addons/meetingsense/`; `hpMeetingSense.start/stop/muteMic`; `getUserMedia` + own `getDisplayMedia({video:true,audio:true})` (D1); AudioContext mixer on **separate gain nodes**; AudioWorklet → 16 kHz PCM16 20 ms frames; energy VAD → 1–3 s utterances, 8 s hard cut; WAV-wrapped chunks per D6; reports `audioMode ∈ {system+mic, system, mic, none}`; emits DOM events `ms:segment ms:partial ms:status ms:audio_lost` | vitest: framer/VAD on synthetic buffers; **a test asserts the two addon copies are byte-identical**; manual matrix in `docs/MEETINGSENSE.md` (Chrome tab audio, Edge, Firefox → mic) | ⬜ |
| **MS5** | Entry point | The ScreenSense button becomes the two-toggle popover (Part 1 §2.1): *Watch screen / Record audio (source) / Live notes*. **"Ask once" keeps its exact current path.** Popover shows the resolved STT provider from `/status` and greys "Record audio" with the env var that would enable it | flag off → rendered button byte-identical to today (asserted); flag on → popover; "Ask once" e2e unchanged | ⬜ |
| **MS6** | Live card + export | `frontend/src/ui/meetingsense/{useMeetingSense.ts, MeetingCard.tsx, RecordingPill.tsx, ConsentSheet.tsx}`; card renders for assistant messages beginning `[Meeting]`, plain-text fallback preserved; pill always visible while live (timer, mute, stop); **consent sheet names the STT provider and where audio goes**, remembers "don't show again", reminds to inform participants; `GET /v1/meetingsense/{id}`, `/export?fmt=md\|srt\|json`; on stop: `add_message(cid,"assistant","[Meeting]…")` and auto-title the conversation `🎙 <title> · <source> · <date>` (D5) | vitest snapshots for card states; e2e: start → speak → segments → stop → export; History shows the titled conversation | ⬜ |

**W1 exit:** a working recorder for anyone whose browser and backend are the same machine.
**→ Pilot for one week in real meetings before W2 (D7). Record what hurt in `docs/MEETINGSENSE.md`.**

### W2 — Reach (the compatibility spine)

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS7** | Avatar-session transport | Add client `meeting_start meeting_audio meeting_stop` and server `meeting` to `avatar_director/protocol.py` type sets — **no version bump** (unknown types are ignored by contract); `avatar_director/session.py` routes them to the same `MeetingSession` through the same `Transport`; segments may ride `voice_transcript` where the client has a recogniser | pytest: a session driven through the avatar handler produces frame-for-frame the same output as through MS3; an old client sending no meeting frames is unaffected; unknown sub-type ignored | ⬜ |
| **MS8** | Through OllaBridge | Document and test end to end: avatar client on yourfriend.online → OllaBridge `/v1/avatar/session` → HomePilot. **Assert the proxy is a pipe** (reads `hello`, pumps the rest); Cloud path rides the existing `sig`/`ev` relay; `status` gains `remote_ok` | pytest in ollabridge: a meeting frame crosses proxy and relay byte-identically, stream id intact; HomePilot: `_REMOTE` off refuses avatar-session meeting frames | ⬜ |

**W2 exit:** the same recorder reached from a hosted avatar with no new URL or token.

### W3 — Eyes

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS9** | Keyframe scheduler | In the addon: 500 ms sampler → 64×36 gray → dHash + changed-pixel ratio; motion gate (> 35 %), 1.5 s stability, 8 s min interval, 5 min heartbeat, hourly cap; JPEG → `/upload` → `keyframe` frame. Server `keyframes.py` stores and calls `analyze_image()` (`persist=false`) with the slide prompt → `slide` frame | vitest: synthetic sequences (slide flip / scroll / video / cursor wiggle) → expected decisions — **this test earns the thresholds**; pytest: keyframe → caption with a vision stub | ⬜ |
| **MS10** | Slides in the card | `SlideStrip.tsx`; lightbox joins caption to the transcript spoken while the slide was up (join on `t0`) | vitest: the join picks the right segments at a boundary | ⬜ |
| **MS11** ∥ | Desktop loopback | `desktop/main.js` `setDisplayMediaRequestHandler(..., audio:'loopback', useSystemPicker)`; `preload.js` exposes `meetingSenseAudio`; mic permission request. **macOS on Electron 33: no loopback — mic or virtual device, stated in the popover** | manual QA Windows + macOS; desktop build unchanged with flag off | ⬜ |

### W4 — Brain

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS12** | Notes engine | `notes_engine.py` + `prompts.py`: every 60 s / 400 words, JSON-delta prompt (add/resolve decisions, actions, questions, summary) with `t0` citations, merged server-side into `ms_notes`, pushed as `notes`; card uses append + strikethrough, never rewrite | pytest with LLM stub → merge correctness; malformed JSON tolerated without dropping the session | ⬜ |
| **MS13** | Ask about this meeting | `ask` frame → recent window + keyword retrieval over `ms_segments`/`ms_keyframes` → LLM → `answer`; `POST /v1/meetingsense/{id}/ask` for ended meetings | pytest: the answer cites timestamps present in the fixture | ⬜ |
| **MS14** | Final summary + retention | On stop: summary assistant message with slide thumbnails in `media.images`; retention `text` / `text+frames` / `all`; one-click delete endpoint. **Per D4: no job is enqueued, no LTM extraction; the persona's route to a meeting is retrieval (MS15).** Docs say so explicitly | pytest: stop produces the summary message; delete removes rows + files per retention; **a test asserts nothing is enqueued in `jobs`** | ⬜ |

### W5 — Memory

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS15** | Embeddings + retrieval | `vectordb.py` gains `namespace: str = "project"` — every existing call resolves to the same collection name; meetings use `namespace="meeting"` so `get_project_document_count` / `delete_project_knowledge` never see them. On stop, embed segments + captions into per-meeting and global `meetings` collections; internal `ms.search`; MS13 uses it beyond the 90 s window | pytest: existing project collection names unchanged (asserted against current hash); cross-meeting query cites `meeting · t0` | ⬜ |
| **MS16** | Binding + resume | `ms_threads`, `ms_artifacts`; frozen card hydrates on reopening; "New thread from this meeting" → new conversation with a brief + attached `meeting_id`; "Attach to project" pushes `transcript_md` + captions through the existing project upload path (this is the only route by which a meeting reaches project jobs, and it needs no new job type) | e2e: reopen → card; branch → brief; attach → project KB finds it | ⬜ |
| **MS17** ∥ | Auto-metadata | Calendar match via `google_calendar` / `microsoft_graph` MCP → title, attendees, link; source detection from the shared window title (Teams / Zoom / Meet / Webex) | pytest: title heuristics; manual: calendar match | ⬜ |

### W6 — Together

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS18** | Live context provider | Optional hook in `backend/app/personalities/prompt_builder.py`: when a conversation has a live `meeting_id`, prepend `[LIVE MEETING CONTEXT]` (last 90 s + notes + current slide, ≤ 900 tokens); behind `_TOGETHER` | pytest: prompt byte-identical when no live meeting or flag off; block present otherwise; budget holds on a long fixture | ⬜ |
| **MS19** | The eighth activity | `meeting.js` joins the 👥 launcher. **Borrows B11's consent machine and `CapturePipeline`** rather than calling `getDisplayMedia` — asks for screen + mic after the choice, never before; revocation stops capture within a frame | vitest: exactly screen + mic requested; revoke mid-meeting stops capture; the other seven activities untouched | ⬜ |
| **MS20** | Card on the avatar surface | Meeting card rendered through the existing `display` panel as a `cards` kind — one data source, two renderers. Panels are capped (64 KB, row-limited) so the live card sends a **summary projection**, not the transcript | pytest: a panel from a 400-segment meeting passes `panels.validate()` and is not 400 rows | ⬜ |

### W7 — Capability

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS21** | MCP server | `agentic/integrations/mcp/meetingsense_server.py` on **9107** (D3) with `ms.list_meetings get_meeting get_transcript search get_live_context get_slide update_action suggest set_mode export`; write tools policy-gated; added to `docker-compose.mcp.yml`, Makefile start/stop/health | RPC tests per tool in the `tests/test_mcp_servers_rpc.py` style; **a test asserts the port is not one the Makefile already starts** | ⬜ |
| **MS22** | Forge + Teams | Register in `seed_all.py`, gateway/virtual-server YAML, suite manifests; Chief-of-Staff A2A gets a "this week's meetings" example. **`hp-teams` (9106) is registered but unbuilt**: build the thin server for tier-2 "post to meeting chat" (template: `microsoft_graph_server.py`) **or** mark tier 2 ⏸ and make the UI say "unavailable" rather than fail at click time | `make test-mcp-servers` green; catalog lists 9107; tier-2 state visible in UI | ⬜ |

### W8 — Engine

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS23** | LangGraph graph | `meetingsense/agent/{graph,state,modes}.py` + `nodes/` (perceive reflect decide answer coach act recall deliver); `Reflect` wraps MS12, `Recall` wraps MS15, `Act` uses `agentic/runtime_tool_router.py`; behind `_AGENT`, fixed loop when off | pytest: end-to-end on a recorded event fixture with every external stubbed; **output identical to the fixed loop in Note-taker mode** | ⬜ |
| **MS24** | Sub-agents + policy | `SlideReader`, `ActionExtractor`; per-meeting tool pre-approval; `ms.set_mode` enforced server-side — modes are server policy objects, not client compositions | pytest: unapproved `Act` → chip, approved → call; a client cannot compose an undefined mode | ⬜ |

### W9 — Modes & voice

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS25** | Chips | Deterministic triggers (question aimed at me, decision, action, date, URL on a slide) → `chip` frame; chip UI; actions via runtime tool router under ask-before-acting | vitest: render/dismiss; pytest: trigger fixtures **including the ones that must not fire** | ⬜ |
| **MS26** | Participant + Presenter | Mode prompts + trigger sets; Participant answers when addressed by persona name and proposes answers to questions aimed at the user; Presenter takes an attached deck, paces, queues audience questions | e2e fixtures per mode | ⬜ |
| **MS27** | Coach + Practice + voice | Coach draws talking points strictly from user-uploaded prep material; pill reads "Coach"; consent copy says so. Practice runs a mock interview/exam through `voice_call/`. Tier-3 TTS (`voice/providers.py` TTS) into a virtual microphone, desktop only, barge-in via `voice_call/barge_in.py`, setup wizard for VB-Cable/BlackHole | e2e; **an explicit test that Coach never receives screen OCR text** (Part 2 §E.2's refusal is only real if enforced); manual matrix for the virtual device | ⬜ |

### W10 — Optional UI

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS28** | Meetings catalog | `MeetingLibrary.tsx` + `MeetingDetail.tsx` reusing the Teams landing grid + `MeetingRightRail`; nav item after Voice behind `_CATALOG`. Cheaper first step: a "Meetings" filter chip in History | flag off → sidebar identical; vitest for filters/search | ⏸ decide after W5 (D5) |

---

## 5. Kickoff prompt template (one per batch)

```
You are working in ruslanmv/HomePilot on a new branch `claude/meetingsense-<MSn>` from
`claude/upgrade-feature-batches-3x0z82`.

Task: implement batch <MSn> "<name>" exactly as scoped in docs/design/MEETINGSENSE_BATCHES.md §4,
honouring the decisions in §2 and the facts in §1. Use MEETINGSENSE_DESIGN.md §<sections> and
MEETINGSENSE_DESIGN_PART2.md §<sections> as the spec for behaviour; where they disagree with the
batches file, the batches file wins.

Before coding: list the existing files you will touch and the new files you will add, and confirm
the touch list is only the additive edits allowed by §0 (MS1 is the sole exception). If it is not,
stop and say so.

Then implement, write tests, and run `make test` plus `cd frontend && npm run build` with all
MEETINGSENSE flags off, then again with this batch's flag on. Update the Status cell for <MSn>
and add a CHANGELOG line.

Stop after reporting: what was built, how to verify it manually, and what you could not verify
from here. Do not begin the next batch.
```

---

## 6. Definition of done (per batch)

- [ ] Flags off → `make test`, `npm run build`, desktop build unchanged
- [ ] Flag on → new tests pass; manual steps written into `docs/MEETINGSENSE.md`
- [ ] No existing endpoint / column / component behaviour modified — diff reviewed; MS1 exception not widened
- [ ] Consent sheet and visible recording indicator preserved in any UI batch; STT provider named wherever audio starts
- [ ] Audio wire frame matches `/v1/voice/session` (D6)
- [ ] From W2 onward: works on **both** transports, or states explicitly why it is local-only
- [ ] Addon pair byte-identical (test from MS4 still green)
- [ ] Status updated here; CHANGELOG entry

---

## 7. Compatibility contracts (do not break these)

**OllaBridge.** The avatar-session proxy reads exactly one frame — `hello` — and pumps the rest verbatim. Meeting frames need no proxy change; MS8 asserts it. If a batch ever needs the proxy to understand a meeting frame, the design has gone wrong.

**The avatar protocol.** `PROTOCOL_VERSION` stays 1. New types go into the type sets and nothing else.

**Together mode.** The 👥 launcher's seven activities, its activity-scoped permission model and consent machine are not modified. MeetingSense is an eighth activity that borrows them.

**The voice backend.** MS1 added to `voice/providers.py`; nothing it added changed an existing return type or default. Two contracts came out of it and outlive the batch:

* **`transcribe()`'s output is frozen, warts included.** It returns `"hello  there"` — segment text carries a leading space and `" ".join()` adds another. Tidying that is a behaviour change in a path voice calls share, and it is the widening §0 forbids. `transcribe_segments()` strips per span, so a transcript never inherits it. A test pins the double space on purpose.
* **"Can it time?" is `supports_segments`, never "does the method exist".** `transcribe_segments` is concrete on the ABC so no caller has to branch — which means it exists on every provider, and asking for the method answers yes even for one that only guesses. MS0's probe asked the wrong question and its own test caught it when MS1 landed.

**ScreenSense.** Not edited by any batch. `audio: false` stays; the "Ask once" path stays.

---

## 8. Cadence

1. ~~MS1~~ ✅ `3b8e1a8`. Two items carried out of it, **MS1-a** and **MS1-b** — neither blocks MS2, and both have a deadline in the table rather than a hope.
2. **MS2 next**, then MS3–MS6 — five sessions to a usable local recorder. MS2 is the one to get right: the `Transport` protocol it defines is what makes W2's second transport free instead of a rewrite, so the core must be testable with a list-backed fake and must not import FastAPI.
3. **Pilot one week.** Use it in real Teams/Zoom meetings. Write down what hurt — and take **MS1-b**'s measurement here, on the machine that will actually run meetings.
4. **MS7–MS8** — reach, before any new capability, so everything after is written once.
5. **Order W3 vs W4 by the pilot notes** (missing slides vs. missing notes).
6. W5–W7 deliver the "together" and "capability" value; W8–W10 are refinement and can be reordered or dropped.
