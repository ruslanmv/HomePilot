# MeetingSense — implementation waves & batches (Claude Code tracker)

Companion to `MEETINGSENSE_DESIGN.md` (Part 1) and `MEETINGSENSE_DESIGN_PART2.md`.
Same discipline as `docs/design/MONOREPO_BATCHES.md`: small, additive, flag-gated,
independently shippable batches. **Every batch leaves the existing app green with all
flags off.** One batch = one Claude Code session = one PR.

**Revision 6 — after MS8. W0, W1 and W2 are complete.** Supersedes revisions 1–5 and keeps
their structure, decisions D1–D10, §2a and the MS numbering. Where this file and a design
document disagree, **this file wins**: the design documents are the spec for *what*, this file
is the contract for *how and in what order*.

Reflects the branch at `f1028d5`. **316 tests** under `backend/tests/meetingsense/`, 434 in the
frontend, 61 in `ruslanmv/ollabridge`'s avatar suite. A meeting can be recorded end to end —
from the browser on the machine running HomePilot, or from a hosted avatar page through
OllaBridge — survives a dropped connection, renders live, and exports.

Changed in rev 6:

* **W1 and W2 marked done**, with each row carrying what was actually verified rather than what
  was scoped. MS4-a exists because rev 5 expanded MS4 after it had been built.
* §1 gains four facts the work produced: there is **no `conversations` table**; the vitest glob
  was excluding 17 files; the protocol fixture set is **shared byte-for-byte with
  `ruslanmv/3D-Avatar-Chatbot`**; and the resume replay deviates from D10 deliberately.
* §7 gains the byte-level form of the OllaBridge pipe claim and the cross-repo fixture rule.
* **§0 gains the lessons of nine batches** — the traps that cost real time, so the next session
  does not rediscover them.
* Changelog entries now live in [`docs/MEETINGSENSE_CHANGELOG.md`](../MEETINGSENSE_CHANGELOG.md).
  §0 has asked for one since MS0; the repository has no changelog and never had, so the file was
  created at rev 6 and backfilled rather than a repo-wide convention being invented mid-feature.

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
  - Every UI batch checks its rows in §2a (experience quality bar) and ships the test named there.
  - Memory and context follow D8/D9: no agent decides what is remembered; the prompt budget for
    meeting context is fixed and asserted; the transcript is never in the prompt, it is retrieved.
  - Finish by updating the Status column of this file and adding an entry to
    docs/MEETINGSENSE_CHANGELOG.md (the repo has no other changelog; that file is the one §0
    means).
  - Do not start the next batch. Stop, report what was verified, how to run it, and what
    you could not verify from here.

Traps that cost real time in MS0-MS8. Each of these passed review once and was wrong:
  - A test that HANGS instead of failing. `[receive_json() for _ in range(n)]` blocks forever
    when the server sends fewer frames than expected, and CI reports a timeout with no
    diagnosis. Bound every read: send a ping, stop at the pong.
  - `pytest.approx` on a Unix timestamp. Its default tolerance is RELATIVE — about plus or
    minus 1700 seconds on 1.7e9 — so the assertion cannot fail. Inject a clock instead.
  - A byte-identity fixture that is accidentally canonical. A JSON string in `json.dumps`'
    default format survives a re-serialisation mutant unchanged. Make fixtures non-canonical
    on purpose.
  - An ordering-confounded test. Putting the item you expect to be dropped FIRST means
    "drop by age" and "drop by policy" give the same answer, and the policy could be absent.
  - Leaked `addEventListener` across tests. The handler closes over the variable, not the
    array it held, so every earlier test's listener pushes into the current test's events.
  - Testing the engine and not the ignition. A pure function can be perfect and never called;
    assert the wiring separately.
  - jsdom does not lay out or paint. `offsetHeight` is 0 for everything: pixel and contrast
    claims belong in the manual matrix, not in a vitest that would pass vacuously.
  - A unit test whose fixture is a shape the integration never produces. MS6's export test
    hand-built `{"json": ...}`; `store.get_notes()` returns `{"notes": {...}}`, so the export
    silently dropped its notes section with a green test standing over it. Feed at least one
    test the real function's real output.
  - Mutate every load-bearing claim before believing a green suite. Roughly one in six
    mutations survived first, and every survivor was a real hole.
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
| Part 1 §5.2 spells the audio field `pcm16_b64`; **D6 fixed `data_b64` + `format`** so a meeting frame and a voice frame are one shape | `voice/routes.py:81`, D6 | MS3 ✅ — `data_b64` is the contract, `pcm16_b64` accepted so a client written from the design doc still works |
| Part 1 §5.2 says `ready` carries `session_id` and `final` carries `summary_message_id`/`transcript_url` | design vs. MS2 `session.py` | MS3 ships MS2's `meeting_id` and counts. The summary is MS12's and the export URL is MS6's — neither exists to name yet, and inventing the keys early means two places to change |
| Part 1 §5.2 says `error` carries `error`; MS2 chose `{code, msg}` to match the avatar protocol so one client handles both surfaces | `avatar_director/protocol.py`, MS2 `send_error` | MS3 ✅ — `{code, msg}`, and every refusal has a stable code |
| HomePilot's chat path has **no compaction**: it passes `get_recent(cid, limit=6)` and drops everything older. A meeting thread longer than six messages loses the meeting unless the meeting context is self-contained | `main.py:4951` | D9: MS14's summary message is self-sufficient; MS18 injects a bounded block; older material is retrieval-only. `limit=6` is **not** edited |
| MS3 ends the meeting when the socket drops. Correct for the store (no row says "in progress" forever) but a Wi-Fi blip mid-meeting must not lose the recording | MS3 `routes.py` | D10: MS3-a adds a grace window + `resume` frame; MS4 reconnects with backoff |
| **There is no `conversations` table.** A conversation is `messages` grouped by `conversation_id`, and History labels each one with the *content of its last message* | `storage.list_conversations`, `storage.py:379–436` | MS6 ✅ — D5's auto-title needs no schema change: the meeting message is the last message, so the title leads its first line. A title column would have written a value the History view never reads |
| Part 1 §5.1 puts 2-channel speaker tagging in `transcript.py` | design file list | MS3 puts the byte work in a new `audio.py`: `transcript.py` is pure string comparison and its tests need no audio, which is worth keeping |

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
| **D8** | Do we need deep agents for memory? | **No.** Memory is three deterministic stores: working (rolling 10 min in-session), episodic (`ms_*` tables + one summary message), semantic (vector namespace, `ms.search`, cited). The LangGraph graph (W8) *consumes* memory through a `Recall` node; it never decides what is stored | Agent-managed memory is non-deterministic and unexplainable ("why did it remember X?"). MS23's acceptance — graph output identical to the fixed loop — is only possible if memory lives outside the graph. W1–W7 ship with no agent at all |
| **D9** | How is context kept short? | **Three tiers, one budget (≤ 900 tokens).** (1) verbatim: last 90 s + current slide caption; (2) compressed: rolling notes + a `recap` (3–5 sentences, regenerated from previous recap + new chunk, never from the full transcript); (3) retrieval: everything older via `ms.search`, cited. Pre-compaction pruning is deterministic: VAD silence, filler/sub-3-word segments, duplicate slides (dHash), images never in the prompt — captions only | Same architecture Claude/ChatGPT use for long threads. Inspectable at every tier. The chat path's `limit=6` is untouched: the summary message carries the recap so the persona knows the meeting even when it is the only meeting message in the window |
| **D10** | What happens when the socket drops? | **Resume, never restart.** Server keeps an ended-by-disconnect meeting resumable for a grace window (default 120 s, `MEETINGSENSE_RESUME_GRACE_S`); client reconnects with exponential backoff and a `resume` frame carrying `meeting_id` + last `seq`; server replays nothing (client already has it) and continues numbering. After the window, the meeting is final and a new one starts | Otter/Zoom/Teams all survive a network blip without a split recording. A user who loses ten minutes of a board meeting to Wi-Fi does not come back |

---

## 2a. Experience quality bar (what the UI is judged on)

These are the behaviours users of Otter, Fireflies, Teams Copilot and Zoom AI Companion take
for granted. Each row names the batch that owns it and the test that proves it. A UI batch is
not done while any of its rows is untested.

| Behaviour | Standard | Owner | Test |
|---|---|---|---|
| **Time-to-first-word** | ≤ 3 s from speech to a `partial` on screen (GPU); if slower, the card shows *"catching up · 12 s behind"* rather than silence | MS4 / MS6 | e2e measures lag from synthetic audio; a stalled STT stub triggers the label |
| **No layout jump** | Partials render in muted colour at fixed line height and solidify in place; the transcript never scrolls under the reader unless they are at the bottom (sticky-scroll with "↓ new lines" pill) | MS6 | vitest: DOM height identical before/after partial→segment; scroll position preserved when not at bottom |
| **Nothing already shown changes** | Segments are append-only; notes correct by strikethrough, never rewrite (MS2 already trims the *later* span for this reason) | MS6 / MS12 | vitest: a re-rendered card contains every previously rendered segment text |
| **Recording state is unmissable** | Red pill with elapsed time, live level meter, provider name and audio mode; visible on every scroll position; browser's own share indicator never hidden | MS6 | vitest: pill present in all card/scroll states; a11y role `status`, `aria-live="polite"` |
| **Honest degraded modes** | Every unavailable capability says *why* and *what to set*: no STT → env var; no system audio on macOS → "mic only — see how to add a virtual device"; remote STT → named, with "timestamps unavailable" if `supports_segments` is false | MS5 | vitest: each `/status` shape renders the matching sentence; no generic "unavailable" string exists in the bundle |
| **Reconnect resumes** | A dropped socket shows *"reconnecting…"* and resumes the same meeting (D10); the pill keeps counting; no duplicate segments | MS3-a / MS4 | pytest: resume within grace continues `seq`; after grace, a new meeting; vitest: backoff schedule 1-2-4-8 s capped at 15 s |
| **One-tap stop, one-tap undo** | Stop asks nothing; the card offers *Undo · 10 s* before the summary job starts; delete is one click and removes rows and files per retention | MS6 / MS14 | e2e: undo within 10 s re-opens the session; delete leaves no `ms_*` rows and no files |
| **Consent that informs** | First-run sheet names the STT provider, where audio goes, what is kept, and reminds to tell participants; "don't show again" is per-machine; a one-line reminder still appears in the pill on every start | MS6 | vitest: the sheet text contains the resolved provider from `/status`; a cloud provider renders the cloud sentence |
| **Keyboard + screen reader** | `⌘/Ctrl+Shift+M` mute, `Esc` from popover, focus trap in consent sheet; transcript is a `<section aria-label="Live transcript">` with each segment a `<p>` carrying `data-t0`; colour contrast ≥ 4.5:1 in both themes | MS5 / MS6 | axe-core in vitest with zero violations; keyboard e2e |
| **Mobile degrades, does not break** | Capture is unavailable on mobile browsers (no `getDisplayMedia` audio); the popover says so; the card collapses to summary + last 3 lines and still hydrates from `/v1/meetingsense/{id}` | MS5 / MS6 | vitest at 380 px width: no horizontal scroll; capture control hidden with the explanatory line |
| **Export is complete and portable** | `.md` (summary → slides timeline → transcript with `hh:mm:ss` and speaker), `.srt` (real cues from `t0/t1`), `.json` (everything). Exports work for meetings with `t1: None` by using segment order | MS6 | pytest: round-trip fixtures; an SRT validator passes; a `t1: None` meeting exports without error |
| **Slides you can trust** | A slide thumbnail opens the caption *and* the words spoken while it was up; a re-shown slide is not a new slide | MS9 / MS10 | vitest: join on `t0` at a boundary; dHash equality reuses the caption |
| **Latency is measured, not assumed** | Real-time factor recorded for the reference GPU and CPU fallback in `docs/MEETINGSENSE.md`; the "catching up" label threshold derives from it | MS1-b | the number exists in the doc |

---

## 3. Overview

| Wave | Theme | Batches | Exit criterion |
|---|---|---|---|
| **W0** | Foundation | MS0 ✅ → MS1 ✅ → MS1-a ✅ | Flags, status endpoint; STT that returns timed spans — locally and remotely — names its device, loads once. One item carried: **MS1-b**, the measurement |
| **W1** | Recorder (local) | MS2 ✅ → MS3 ✅ → MS4 ✅ → MS5 ✅ → MS3-a ✅ → MS4-a ✅ → MS6 ✅ | Screen + audio → live transcript in a chat card, export, resume on reconnect. **Pilot for a week here** |
| **W2** | Reach | MS7 ✅ → MS8 ✅ | Same recorder from yourfriend.online through OllaBridge, no new URL/token |
| **W3** | Eyes | MS9 → MS11 | Slide-aware keyframes captioned locally; desktop loopback (Windows) |
| **W4** | Brain | MS12 ✅ → MS13 ✅ → MS14 ✅ | Rolling notes, "ask about this meeting", final summary + retention |
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
| **MS1-a** | *Carried from MS1* | `OpenAICompatSTTProvider.transcribe_segments` asking for `response_format=verbose_json`, plus a shared `_spans_from_verbose_json()` parser. **A second call site, not a modified one** — `transcribe()` still sends the default format, because changing it would alter a return value the voice call shares. `supports_segments` is now true for this provider. `verbose_json` is documented, not guaranteed, so every degraded shape falls back to the one-span answer: no `segments` key, a proxy that rewrote it, junk in the list, a body that is not JSON at all. **A segment the server did not time is skipped, never given `t0: 0`** — these get cited in notes, and a citation pointing at the wrong minute is worse than a note without one | 28 tests. Seven mutations each fail, including one that gives an untimed segment `t0: 0` and one that changes `transcribe()` to `verbose_json`. 383 green across the voice suites and `tests/meetingsense` together; backend baseline unchanged | ✅ `97fc3e4` |
| **MS1-b** | *Carried from MS1* | **Measure the real-time factor on the reference GPU** and record it in `docs/MEETINGSENSE.md`. Could not be done from the build container: no CUDA, and `faster_whisper` is not installed there. Part 2 §F's latency budget stays a hypothesis until this number exists | one measured RTF for the chosen `WHISPER_MODEL`, on the machine that will run meetings | ⬜ at the end of W1's pilot |

### W1 — Recorder (local transport)

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS2** | Store + session core | `store.py` (`ms_meetings ms_segments ms_keyframes ms_notes`, `CREATE TABLE IF NOT EXISTS`, `migrate_if_enabled()` so an install that never turns the flag on never grows the tables; reuses `storage._get_db_path()` rather than a second database); `session.py` `MeetingSession` (`idle→live→ended`, one way; `stop` idempotent because both ends of a socket notice a disconnect and both will try), in-memory registry, `elapsed_ms` frozen at end; `transcript.py` utterance assembler — 200 ms overlap, `MIN_OVERLAP_WORDS=2` (one shared word is ordinary English), and the window is over **emitted** words, not the last surviving fragment. **The core takes a `Transport` protocol (`send(frame)`, `close()`) and never imports FastAPI** — two transports, one core | 68 tests (31 assembler, 37 core). Mutations: a `fastapi` import, a third `Transport` method, a non-idempotent `stop` and a dropped dedupe each fail the suite. `dedupe()` now takes the assembler's own window, so the streaming and batch cases are one implementation of the rule rather than two. Full backend run unchanged against the 18-file baseline | ✅ `82c8ff4` |
| **MS3** | Local WebSocket transport | `WS /v1/meetingsense/session` in `routes.py` + new `audio.py` (wire format). Client `start/audio/keyframe/mute/status/stop/ping`, server `ready/partial/segment/status/final/error`; unknown types ignored both ways. PCM16 wrapped in a RIFF header server-side; `transcribe_segments(..., duration_s=<frame length>)`; **one provider held per connection**; stereo split per channel with **ch0 → `them`, ch1 → `me`** and one assembler each; refuses flag-off the way the voice route does (accept, say why, close 1008). A dropped socket ends the meeting in the store rather than leaving a row that says "in progress" forever | 40 tests. Eight mutations: swapped channels, unwrapped PCM, a stored partial, a shared assembler, a leaked live session, a dropped `duration_s`, migration before the flag check, and no flag check — each fails, and each fails *as an assertion* (a missing frame used to hang the suite; the helper now provokes a `pong` end-marker). 191 green in `tests/meetingsense`; full backend run unchanged against the 18-file baseline | ✅ `15b2b24` |
| **MS3-a** | Resume on reconnect (D10) | `suspended` state + `MEETINGSENSE_RESUME_GRACE_S` (default 120, **0 reproduces MS3 exactly** and a test pins that); `resume {meeting_id, last_seq}` re-attaches a socket to the live `MeetingSession` — same assemblers, same provider, `seq` continues; store gains `ms_meetings.suspended_at` and `ms_segments.seq`, both also added by **ALTER when missing**, since `CREATE TABLE IF NOT EXISTS` does nothing to an existing table and the failure would be an `OperationalError` on the first resume, mid-meeting; `status` carries `resumable_until` and `seq`. **Deviation from D10, deliberate:** the server *does* replay. "The client already has it" holds for everything that arrived and fails for exactly the frames in flight when the socket died — those exist only in the store, so segments above `last_seq` are replayed (marked `replayed`, bounded by `MEETINGSENSE_RESUME_MAX_REPLAY`, ordered by `seq` because two channels share a `t0`) | 50 tests. Ten mutations each fail — one survived first: the "ends when the socket dropped, not when the timer noticed" test compared two real timestamps with `pytest.approx`, whose default tolerance is *relative* (~±1700 s on a Unix timestamp) and could not fail; it runs on an injected clock now. 231 green in `tests/meetingsense`; full backend run unchanged against the 18-file baseline | ✅ `ada9408` |
| **MS4** | Audio capture addon | **Landed against the rev-4 scope; rev 5's additions are MS4-a, now done.** Built: the mirrored addon pair, `start/stop/muteMic`, own `getDisplayMedia`+`getUserMedia`, separate gain nodes into a channel merger (ch0 call / ch1 mic, never summed), AudioWorklet via Blob URL → 16 kHz PCM16 20 ms frames, energy VAD (350 ms close over a 1 s floor, 8 s hard cut), WAV chunks per D6, `audioMode`, and `ms:segment ms:partial ms:status ms:audio_lost`. **Only the hard cut carries the 200 ms overlap** — a close on silence cut nothing, and carrying one there turned a 200 ms overlap into 140 ms in the first draft | 39 vitest tests + a sha256 identity check on the two copies (it caught a real drift). Eight mutations each fail. Capture graph untested — jsdom has no AudioContext/AudioWorklet/getDisplayMedia — so the 10-row manual matrix in `docs/MEETINGSENSE.md` is **unsigned and blocks the pilot** | 🔄 `6ee54ab` — see **MS4-a** |
| **MS4-a** | *Carried from MS4 — the rev-5 delta* | Reconnect on **1-2-4-8 s backoff capped at 15 s** sending `resume` with the last `seq` actually seen (the highest, not the latest — frames arrive out of order across a resume and taking the latest would move the marker backwards); `ms:reconnecting` / `ms:resumed`; `levels` as an RMS per channel, a polled property rather than an event because fifty events a second at a sixty-hertz meter is noise; backpressure — over 2 s queued, shed by **how much speech a chunk carries**, oldest of those first, never the newest, always keeping one, and report `behind_ms`. Capture keeps running through the outage: what someone says during a ten-second reconnect is the part they most want back | 61 tests (22 new), including the wiring driven against a fake socket — the pure backoff and shed functions can be perfect and never called. Eight mutations each fail; **two survived first**, both my tests' fault: the shed tests put the near-silent chunk first, so dropping by age gave the same answer, and the "gives up" test never asserted the pill stops saying *reconnecting*. A third defect surfaced here too — leaked `addEventListener`s across tests made every event count once per prior test | ✅ `63dffcd` |
| **MS5** | Entry point | `frontend/src/ui/meetingsense/entryPoint.ts` — framework-free DOM, so it attaches to the button ScreenSense already mounted instead of replacing it. Popover per Part 1 §2.1 (*Watch screen · Record audio · Live AI notes*, **Start session** + **Ask once**); `describe()` is a pure `/status` → sentences function with a stable id per state; `Esc` closes and returns focus; `aria-expanded`/`-controls`/`-haspopup`; capture toggles **hidden** on mobile, not greyed. **"Ask once" needed real care**: ScreenSense's own click handler is still on that button, so one click would have both asked a question and opened the popover — it is suppressed in the capture phase and re-fired by the popover's button re-dispatching the click ScreenSense was written for, since the file may not be edited | 39 tests. Flag off → `outerHTML` byte-identical and nothing appended (asserted, not "no popover appears"); unreachable `/status` reads as off; each `/status` shape renders its sentence; a grep asserts no generic "unavailable" prose survives; axe-core zero violations on **both** the healthy and degraded trees. Eleven mutations each fail. 346 frontend tests green; `npm run build` and `tsc --noEmit` clean | ✅ `1ee3227` |
| **MS6** | Live card + export | `frontend/src/ui/meetingsense/{meetingState.ts, MeetingCard.tsx, RecordingPill.tsx, ConsentSheet.tsx, useMeetingSense.ts}` + backend `export.py`, `finalize.py`, `GET /v1/meetingsense/{id}` and `/export?fmt=md|srt|json` (both 404 with the flag off, the same answer as a missing meeting). **Stop keeps recording**: it starts the 10 s undo countdown and only then sends `stop`, because the seconds somebody spends deciding are seconds somebody else was still talking. §2a: segments keyed by `id` so a resume replay is invisible; provisional line is the same element and class as the segment replacing it; sticky-scroll with a counted "↓ N new lines"; `catching up · N s behind` above 2 s only; `aria-live` transcript with `data-t0` per line; level meter, provider and audio mode in a `role="status"` pill; consent names the provider and never the endpoint, remembered per machine, focus-trapped both ways | 66 vitest + 59 pytest. Twelve frontend and eight backend mutations each fail; two survived first — the focus-trap test only tabbed forwards, and jsdom cannot measure the height claim at all (the structural fact is asserted instead, pixels go to the manual matrix). 434 frontend tests, 276 in `tests/meetingsense`, build and `tsc --noEmit` clean, backend baseline unchanged | ✅ `657f592` |

**W1 exit:** a working recorder for anyone whose browser and backend are the same machine.
**→ Pilot for one week in real meetings before W2 (D7). Record what hurt in `docs/MEETINGSENSE.md`.**

### W2 — Reach (the compatibility spine)

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS7** | Avatar-session transport | `meeting_start meeting_audio meeting_stop` + server `meeting` added to `protocol.py`'s type sets, **no version bump**; the handler *queues* them (`meeting_inbox`, `take_meeting_frames()`) rather than answering, because a meeting transcribes audio and `handle()` is synchronous by design. New `meetingsense/avatar_bridge.py`: an `AvatarTransport` writing to the handler's outbox — the socket already has exactly one writer — and a `MeetingBridge` that reuses MS2's core, MS3's `audio.py` and MS3's own `_handle_audio`. One outbound type carries the MS3 frame verbatim, so a later wave's frame needs no contract change. `_REMOTE` is separate from the master flag; a dropped avatar socket suspends on MS3-a's grace window | 46 tests. **Parity is the load-bearing one**: the same script through both transports produces frame-identical output, with the clock injected so the comparison is behaviour rather than "close enough". Eight mutations each fail. **Cross-repo:** the shared fixture set gained four frames, so `ruslanmv/3D-Avatar-Chatbot` took the byte-identical copy in the same shape (`303b722`, 2199 tests green) — the checksum manifest went red until it did, which is the mechanism working. 308 in `tests/meetingsense`, backend baseline unchanged | ✅ `75d7294` |
| **MS8** | Through OllaBridge | ollabridge: `tests/avatar/test_meeting_frames.py` proves the proxy is a pipe **in bytes** — non-canonical JSON fixtures and string equality, up and down, a whole meeting in order, plus the cloud `sig`/`ev` path where the raw frame travels as the payload string; a grep test forbids meeting vocabulary in the proxy at all. `/health` advertises `meetings`. HomePilot: `/v1/meetingsense/status` gains **`remote_ok`** (`enabled AND ready AND flags.remote` — one boolean, because the flags do not imply each other and a client guessing would guess wrong towards offering a control the server refuses), and `_REMOTE` off refuses avatar-session frames **per frame**, not just at start | 10 ollabridge + 12 HomePilot tests. Eight mutations each fail — **one survived first**: the audio fixture happened to be byte-identical to `json.dumps` output, so a re-serialising relay passed the whole suite; the fixtures now carry spacing `json.dumps` cannot reproduce. ollabridge avatar suite 61 green and its repo baseline unchanged (142 pre-existing failures before and after); 316 in `tests/meetingsense`, HomePilot baseline unchanged | ✅ `27b6e15` + ollabridge `48520da` |

**W2 exit:** the same recorder reached from a hosted avatar with no new URL or token.

### W3 — Eyes

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS9** | Keyframe scheduler | In the addon: 500 ms sampler → 64×36 gray → dHash + changed-pixel ratio; motion gate (> 35 %), 1.5 s stability, 8 s min interval, 5 min heartbeat, hourly cap; JPEG → `/upload` → `keyframe` frame. Server `keyframes.py` stores and calls `analyze_image()` (`persist=false`) with the slide prompt → `slide` frame | vitest: synthetic sequences (slide flip / scroll / video / cursor wiggle) → expected decisions — **this test earns the thresholds**; pytest: keyframe → caption with a vision stub | ✅ |
| **MS10** | Slides in the card (**also: wire `NotesEngine` into both transports — MS12's engine is built, tested and constructed by nothing, so no meeting has ever emitted a `notes` frame; found during MS9**) | `SlideStrip.tsx`; lightbox joins caption to the transcript spoken while the slide was up (join on `t0`) | vitest: the join picks the right segments at a boundary | ⬜ |
| **MS11** ∥ | Desktop loopback | `desktop/main.js` `setDisplayMediaRequestHandler(..., audio:'loopback', useSystemPicker)`; `preload.js` exposes `meetingSenseAudio`; mic permission request. **macOS on Electron 33: no loopback — mic or virtual device, stated in the popover** | manual QA Windows + macOS; desktop build unchanged with flag off | ⬜ |

### W4 — Brain

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS12** | Notes engine + recap (D9 tier 2) | `notes_engine.py` + `prompts.py`. Trigger is a floor, not a schedule: 60 s **or** 400 words, and nothing pending is never due. **Deltas, not rewrites** — the model says what to add and what to resolve, and the merge happens server-side, because asking for the whole notes object lets every pass silently drop what the last got right. Nothing deletes: resolving marks `resolved` so the card can strike through. **`recap_messages()` takes a string, not a meeting id**, so it *cannot* reach the transcript — that is D9 tier 2 in one signature — and the 120-word cap is enforced in code, not requested in the prompt. A citation the transcript cannot support is dropped while the observation is kept. Small talk stores nothing | 56 tests. Eight mutations each fail. **Found and fixed an MS6 bug on the way:** `to_markdown` read `notes["json"]` while `store.get_notes()` returns the parsed object under `notes["notes"]`, so the Markdown export had been silently omitting its notes section — the MS6 test hand-built a shape the store never produces and passed over it. A regression test now feeds it the real store output. 398 in `tests/meetingsense`; backend baseline unchanged | ✅ `1e90e18` |
| **MS13** | Ask about this meeting (D9 tier 3) | New `ask.py`: `ask` frame on the live socket + `POST /v1/meetingsense/{id}/ask` for ended meetings, both through one function. Three tiers — verbatim last 90 s, MS12's recap, and top-k keyword-retrieved segments and captions (k ≤ 12), with the verbatim window excluded from retrieval so nothing is paid for twice. **Trim order is D9's priority made executable: retrieval first, verbatim second, the recap never.** Results come back in time order, not score order. The frame reports the citations the answer *actually used* from what it was offered, so a timestamp the model invented is never presented as real. The live path uses the session clock, not the last segment — a question asked during a silence is still about now. `retrieve()` is a separate function so MS15 swaps the scoring for a vector search and changes nothing above it | 45 tests. Eight mutations each fail. **The headline test passed for the wrong reason first**: the two-hour fixture's segments did not match the question, so the prompt was small because retrieval found nothing — it passed with both the budget *and* `k` removed. Rewritten so the filler shares one term and the answer shares two. Also fixed a real scoring bug found by its own test: normalising by *distinct* words made a segment repeating one word score highest. 480 in `tests/meetingsense`; backend baseline unchanged | ✅ `27e75d9` |
| **MS14** | Final summary + retention | The summary message is now **self-sufficient (D9)**: recap, decisions, actions with owners and citations, open questions (resolved ones left out), slide timeline, thumbnails in `media.images` capped at 8. Falls back to the transcript preview when no notes exist. New `retention.py` + `DELETE /v1/meetingsense/{id}` — rows and the files the meeting owned, reporting counts rather than "ok". **Retention does not modify deletion**: whatever was kept is removed, because a mode that spared something from an explicit delete would be a setting overriding an instruction. Every path resolved under the upload root with `is_relative_to`. `session.stop()` forces the last notes window, or the final minute of every meeting is missing from its summary. **Per D4 nothing is enqueued** | 45 tests. Eight mutations each fail; **two survived first** — a symlink test does not separate `is_relative_to` from a string prefix (both refuse it; a sibling directory named `uploads-evil` is what does), and an empty-list test does not reach a section whose items all render blank. 445 in `tests/meetingsense`; backend baseline unchanged | ✅ `f537783` |

### W5 — Memory

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS15** | Embeddings + retrieval | `vectordb.py` gains `namespace: str = "project"` — every existing call resolves to the same collection name; meetings use `namespace="meeting"` so `get_project_document_count` / `delete_project_knowledge` never see them. On stop, embed segments + captions into per-meeting and global `meetings` collections; internal `ms.search`; MS13 uses it beyond the 90 s window | pytest: existing project collection names unchanged (asserted against current hash); cross-meeting query cites `meeting · t0` | ⬜ |
| **MS16** | Binding + resume | `ms_threads`, `ms_artifacts`; frozen card hydrates on reopening; "New thread from this meeting" → new conversation with a brief + attached `meeting_id`; "Attach to project" pushes `transcript_md` + captions through the existing project upload path (this is the only route by which a meeting reaches project jobs, and it needs no new job type) | e2e: reopen → card; branch → brief; attach → project KB finds it | ⬜ |
| **MS17** ∥ | Auto-metadata | Calendar match via `google_calendar` / `microsoft_graph` MCP → title, attendees, link; source detection from the shared window title (Teams / Zoom / Meet / Webex) | pytest: title heuristics; manual: calendar match | ⬜ |

### W6 — Together

| # | Batch | Scope | Acceptance | Status |
|---|---|---|---|---|
| **MS18** | Live context provider | Optional hook in `backend/app/personalities/prompt_builder.py`: when a conversation has a live `meeting_id`, prepend `[LIVE MEETING CONTEXT]` — D9 tiers 1+2 only: last 90 s verbatim, current slide caption, notes, recap — **hard-capped at 900 tokens, truncating verbatim first and never the recap**; behind `_TOGETHER`. `limit=6` in `main.py` is not touched | pytest: prompt byte-identical when no live meeting or flag off; block present otherwise; **a 3-hour fixture stays ≤ 900 tokens and still contains the recap**; the transcript body never appears in the prompt | ⬜ |
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
- [ ] §2a rows owned by this batch are tested; axe-core zero violations for any new UI
- [ ] Meeting context stays within the D9 budget; nothing decides memory contents but code (D8)
- [ ] Status updated here; CHANGELOG entry

---

## 7. Compatibility contracts (do not break these)

**OllaBridge.** The avatar-session proxy reads exactly one frame — `hello` — and pumps the rest verbatim. Meeting frames need no proxy change; MS8 asserts it. Asserted **in bytes**, not as parsed objects: a proxy that re-serialised each frame would pass an object comparison while re-encoding an audio chunk. The same holds on the cloud path, where the raw frame is the `sig`/`ev` payload string. If a batch ever needs the proxy to understand a meeting frame, the design has gone wrong.

**The avatar protocol.** `PROTOCOL_VERSION` stays 1. New types go into the type sets and nothing else. MS7 added four and did not move it. The protocol fixture set is **byte-identical to `ruslanmv/3D-Avatar-Chatbot`**, held by `CHECKSUMS.txt`: a type added on one side goes red on the other until both carry the same files.

**Together mode.** The 👥 launcher's seven activities, its activity-scoped permission model and consent machine are not modified. MeetingSense is an eighth activity that borrows them.

**The voice backend.** MS1 added to `voice/providers.py`; nothing it added changed an existing return type or default. Two contracts came out of it and outlive the batch:

* **`transcribe()`'s output is frozen, warts included.** It returns `"hello  there"` — segment text carries a leading space and `" ".join()` adds another. Tidying that is a behaviour change in a path voice calls share, and it is the widening §0 forbids. `transcribe_segments()` strips per span, so a transcript never inherits it. A test pins the double space on purpose.
* **"Can it time?" is `supports_segments`, never "does the method exist".** `transcribe_segments` is concrete on the ABC so no caller has to branch — which means it exists on every provider, and asking for the method answers yes even for one that only guesses. MS0's probe asked the wrong question and its own test caught it when MS1 landed.

**The meeting wire (MS3).** `data_b64` + `format` is the audio contract (D6); `pcm16_b64` is accepted for clients written from the design doc. Errors are `{code, msg}` with stable codes and the socket stays up; only a dropped socket or `stop` ends a meeting. Channel order is fixed: **ch0 → `them`, ch1 → `me`**. Unknown frame types are ignored in both directions. From MS3-a, `resume` is part of this contract and an old client that never sends it behaves exactly as today.

**Context budget (D9).** The meeting block a persona sees is ≤ 900 tokens and never contains the transcript body. Any batch that needs more context adds a retrieval call, not tokens.

**ScreenSense.** Not edited by any batch. `audio: false` stays; the "Ask once" path stays.

---

## 8. Cadence

1. ~~MS1~~ ✅ `3b8e1a8`, ~~MS1-a~~ ✅. One item still carried: **MS1-b**, which only a real machine can close.
2. ~~MS2~~ ✅ `82c8ff4`, ~~MS3~~ ✅ `15b2b24`. The core and the local wire exist; 191 tests.
3. ~~MS4~~ ✅ `6ee54ab`, ~~MS5~~ ✅ `1ee3227`, ~~MS3-a~~ ✅ `ada9408`, ~~MS4-a~~ ✅. Built out of rev-5 order — MS4 and MS5 landed against rev 4, then the resume pair caught up. A Wi-Fi blip no longer loses a recording, which was the pilot's largest exposure.
4. ~~MS6~~ ✅. **W1 is complete**: a recorder, a socket that survives a dropped connection, an entry point, a live card, a pill, consent, and export in three formats.
5. **Pilot for one week** — [`docs/MEETINGSENSE_PILOT.md`](../MEETINGSENSE_PILOT.md) is what to run, what to write down, and which answer picks W3 or W4. Two things gate it, neither of them code. The **10-row browser matrix** in `docs/MEETINGSENSE.md` is unsigned, and rows 1–3 decide whether MeetingSense records at all. **MS1-b** is now load-bearing rather than informational: §2a says the "catching up" threshold derives from the measured real-time factor, and MS6 shipped a provisional 2 s in its place. Take that measurement on the machine that will run meetings.
6. ~~MS7–MS8~~ ✅. **W2 is complete**: the same recorder reached from a hosted avatar, with no new URL and no second token, and the pipe claim asserted in bytes on both the direct and the cloud path.
7. **Order W3 vs W4 by the pilot notes** (missing slides vs. missing notes). The pilot page carries the decision table; do not pick before the week has run.
8. ~~W4~~ ✅. **W0, W1, W2 and W4 are complete.** W3 (Eyes) is the only wave left before W5, and the pilot still gates both.
9. W5–W7 deliver the "together" and "capability" value; W8–W10 are refinement and can be reordered or dropped.
