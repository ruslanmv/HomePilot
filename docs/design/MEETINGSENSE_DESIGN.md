# MeetingSense — Screen share + audio + live transcript + AI meeting notes

**Status:** **built.** This document is the original design and is kept as the record of what
was intended; where the shipped product differs, §0 below says so and the batch ledger in
[`MEETINGSENSE_BATCHES.md`](./MEETINGSENSE_BATCHES.md) is the current state.
**Branch:** `claude/upgrade-feature-batches-3x0z82` (design written @ `54ff266`; built through MS33)
**Principle:** additive, non-destructive, flag-gated, 100 % local by default. Follows the same contract as ScreenSense (`community/addons/screensense/DESIGN.md`) and the voice backend (`backend/app/voice/`).

---

## 0. As built — where the shipped product differs from this design

Written after MS33. The design below is unedited; this section is the diff, because a design
document quietly rewritten to match what shipped stops being evidence of anything.

**The entry point moved twice.** §2.1 describes a popover on the ScreenSense 👁 button. MS29
shipped that *and* a record button under the composer; MS32 removed the composer button and
made **Meeting a header control beside Call**, because one optional feature under the primary
input competed with the chat on every screen. MS33 restored the `⌄` as a split action, so one
click still starts a meeting and the capture options are a second control rather than a step
in front of the first.

**The setup hint left the chat.** §6 says an unavailable STT provider greys a control and
shows *"Set `WHISPER_MODEL=small` to enable"*. That is right for a developer surface and wrong
under somebody's message box, where it sat permanently for people who will never record a
meeting. It now lives in **Settings → Voice Assistant → Meeting transcription**; the chat
control says *"Meeting transcription isn't configured"* with a link to Settings, and shows it
only when pressed. No environment-variable name reaches a chat user.

**The ended meeting is the product.** §2.3 is one paragraph and the shipped card is the
feature's whole payoff: **Summary → Decisions → Actions → Ask this meeting**, with the
transcript demoted behind a disclosure. People record meetings so they do not have to reread
them, and until MS33 the ended card showed a transcript — the recording rather than the value.
Citations in an answer are links that open the transcript at the line already in progress.

**`ScreenAwarenessPopover.tsx` does not exist.** MS5's `entryPoint.ts` attaches to
ScreenSense's existing button instead, which is what kept the promise that ScreenSense is
edited by no batch. The directory shipped sixteen files rather than six; `MeetingDetail.tsx`
and `VoiceSetup.tsx` are built and not mounted, which is stated here rather than left to be
discovered.

**Stop is a countdown, not an ending.** §2.3 says stop; MS6 made it ten seconds of continued
capture with Undo, because the seconds somebody spends deciding are usually the seconds
somebody else was still talking. The pill says *"Stopping in 8s · still recording"* so nobody
stops talking on account of it.

**Two flags default on.** `MEETINGSENSE_ENABLED` and `MEETINGSENSE_TOGETHER` ship `true`
(MS30) so `make install && make start` needs no exports. This contradicts the programme's own
"flags default off" rule and was an explicit product decision, recorded here rather than
silently.

**Still owed.** The 21-row manual matrix is unsigned, rows 18–20 are unreachable by any
automated test, and the end-to-end path — browser → mic + system audio → Whisper → segments →
notes → persona prompt — has never run as a whole.

---

## 1. What exists today (and what we reuse)

| Capability | Where | Reuse in MeetingSense |
|---|---|---|
| Screen capture (desktop native / browser picker / upload fallback) | `community/addons/screensense/homepilot-screensense.js`, `desktop/main.js` (`screensense:capture`), `desktop/preload.js` | **Extend** — the "👁 Share screen" button is where the new **🎙 Record audio** toggle lives |
| Vision analysis + persistence into a conversation | `POST /v1/multimodal/analyze` (`persist`, `conversation_id`) | Slide keyframes → same endpoint, unchanged |
| STT providers (local faster-whisper, OpenAI-compat/whisper.cpp, Null) | `backend/app/voice/providers.py` → `get_stt_provider()` | Called as-is for every audio utterance |
| WebSocket JSON-frame session pattern, flag-gated | `WS /v1/voice/session` (`VOICE_BACKEND_ENABLED`) | Copy the pattern → `WS /v1/meetingsense/session` |
| Message persistence | `storage.add_message(cid, role, content, media)` | Transcript blocks, notes, final summary |
| Post-session background jobs (summarise, extract memories) | `backend/app/jobs.py` | Enqueue on `stop` for the final summary + LTM |
| Multi-provider LLM client | `backend/app/llm.py`, `voice/session.py::_default_llm_fn` | Incremental notes over transcript windows |
| RAG / vector DB | `backend/app/vectordb.py` | "Ask about this meeting" over segments |
| Upload storage | `POST /upload` → `/files/…` | Keyframes (JPEG) |
| In-chat card pattern (phone) | `frontend/src/ui/phone/PostCallCard.tsx`, `CallEventRow.tsx` | `MeetingCard` live in the thread |

**Gaps that require new code:** audio capture & mixing on the client, a streaming transcript session on the server, slide/motion-aware keyframe scheduling, the incremental analysis loop, and the UI panel. Everything else is wiring.

---

## 2. User experience

### 2.1 The entry point (the toggle you asked for)

Today the ScreenSense button opens the share picker and fires a single question. MeetingSense turns that button into a tiny popover with **two toggles and a start button** — nothing is removed:

```
┌──────────────────────────────────────────┐
│ 👁  Screen awareness                     │
│                                          │
│ [x] Watch screen  (slide-aware snapshots)│
│ [ ] Record audio  → live transcript      │
│      ( ) system/tab audio  (•) mic + tab │
│ [ ] Live AI notes in chat                │
│                                          │
│ ⓘ Everything stays on this machine.     │
│   Tell participants you are recording.   │
│                                          │
│         [ Start session ]  [ Ask once ]  │
└──────────────────────────────────────────┘
```

- **"Ask once"** = the current ScreenSense behaviour (unchanged path).
- **"Start session"** = new. Both toggles off → identical to today.
- The popover only appears when `MEETINGSENSE_ENABLED` is true on the backend (`/v1/meetingsense/status`). Otherwise the button behaves exactly as today.

### 2.2 While a session runs

A persistent, unmistakable **recording pill** (red dot, elapsed time, mute, stop) sits at the top of the chat — the browser also shows its own "sharing" indicator, we don't hide either.

Inside the conversation a single **MeetingCard** message appears and updates live:

```
┌ 🔴 Meeting · 00:14:32 · Teams — "Q3 planning" ─────────────┐
│ Transcript (live)                        ▼ collapse         │
│  14:02  [Speaker A]  …so the launch moves to October        │
│  14:05  [Speaker B]  we still need legal sign-off           │
│  14:06  [Speaker A]  Marina, can you own that?          ▮   │
│                                                             │
│ AI notes  (updated 14:06)                                   │
│  • Decision: launch shifted to October                      │
│  • Action: legal sign-off — owner Marina                    │
│  • Open question: budget impact not yet discussed           │
│                                                             │
│ Slides  [thumb] [thumb] [thumb] ← 3 keyframes, 14:00-14:06  │
│                                                             │
│  Ask about this meeting…            [Mute] [Stop & summarise]│
└─────────────────────────────────────────────────────────────┘
```

- **Transcript** streams in as final segments (partials shown greyed, then solidify).
- **AI notes** refresh incrementally; they never rewrite what was already shown, they append/correct.
- **Slides** row shows keyframes captured only when the screen *actually changed*.
- The user can chat normally the whole time; the persona has the running transcript as context, so "what did she just say about legal?" works.

### 2.3 On stop

- Final transcript + notes are frozen into the card.
- A **Meeting summary** assistant message is generated (decisions / actions / open items / timeline with slide thumbnails).
- Background jobs: `summarize_session`, `extract_memory` (existing `jobs.py`) so the persona's LTM learns the meeting.
- Raw audio is **discarded by default** (only text is kept). Keyframes are kept (they are already in `/files/`).

### 2.4 Consent & privacy posture (premium ≠ creepy)

- First-run consent sheet explaining what is captured, where it goes (local backend, local Whisper, local vision model), and the reminder to inform others; a checkbox "don't show again".
- Recording indicator can never be hidden.
- **Nothing is sent to a cloud LLM/STT unless the user has explicitly configured a cloud provider** — same rule ScreenSense already follows.
- Per-conversation opt-out for LTM extraction ("don't remember this meeting").
- Retention setting: keep transcript only / transcript + keyframes / also keep audio (`.webm`, off by default).

---

## 3. Architecture

```
  Browser / Electron renderer                        Local HomePilot backend
 ┌───────────────────────────────────┐              ┌──────────────────────────────────┐
 │ homepilot-meetingsense.js (addon) │              │ backend/app/meetingsense/        │
 │                                   │              │                                  │
 │ ┌ Capture ───────────────────┐    │              │  WS /v1/meetingsense/session     │
 │ │ getDisplayMedia(video+audio)│   │  ws: audio  │   ├─ AudioAssembler (VAD merge)  │
 │ │ getUserMedia(mic)  optional│    │─ chunks ───► │   ├─ STT  (voice/providers.py)  │
 │ │ AudioContext mixer → 16k   │    │              │   ├─ TranscriptStore (sqlite)   │
 │ │ AudioWorklet VAD + framer  │    │  ws: text   │   ├─ NotesEngine (LLM, windowed)│
 │ └────────────────────────────┘    │◄─ segments ─│   └─ KeyframeAnalyzer ──────────┼─► POST /v1/multimodal/analyze
 │                                   │   notes      │                                  │      (existing, unchanged)
 │ ┌ Vision scheduler ──────────┐    │              │  GET  /v1/meetingsense/status    │
 │ │ 2 fps sample → 64×36 gray  │    │              │  GET  /v1/meetingsense/{id}      │
 │ │ dHash + Δ → "slide changed"│    │  POST /upload│  POST /v1/meetingsense/{id}/ask  │
 │ │ debounce, min interval     │    │─ keyframe ──►│                                  │
 │ └────────────────────────────┘    │              │  storage.add_message(...)        │
 │                                   │              │  jobs.enqueue(summarize, ltm)    │
 │ MeetingCard (React) ◄─ events ────┘              └──────────────────────────────────┘
 └───────────────────────────────────┘
```

Design choices, briefly:

- **Client does VAD and keyframe detection, server does STT/LLM/vision.** Cheap signal processing stays where the media is; heavy models stay where the GPU is. This mirrors the voice backend's "thin client" philosophy.
- **One WebSocket per session**, JSON frames, binary audio as base64 (same as `/v1/voice/session`) — or raw binary frames as an optimisation later.
- **The vision path is untouched**: a keyframe is just an image upload followed by `/v1/multimodal/analyze` with `persist:false` (we compose it into the meeting record ourselves), exactly like ScreenSense.

---

## 4. Client: capture engine (`homepilot-meetingsense.js`)

Vanilla JS addon in the ScreenSense style, exposed as `window.hpMeetingSense`, inert until called. Depends on `hpScreenSense` for the video stream so screen capture logic isn't duplicated.

### 4.1 Getting audio

| Environment | System / meeting audio | Mic |
|---|---|---|
| **Browser (Chrome/Edge)** | `getDisplayMedia({ video:true, audio:true })`. Chrome: tab audio always available; whole-screen system audio on Windows; **not** on macOS (only tab audio). Teams/Zoom **web** clients in a tab → works. Desktop Teams/Zoom app on macOS → mic only. | `getUserMedia({ audio: { echoCancellation:true, noiseSuppression:true } })` |
| **Electron desktop app** | `session.defaultSession.setDisplayMediaRequestHandler((req, cb) => cb({ video: source, audio: 'loopback' }))` — system loopback on Windows; macOS via ScreenCaptureKit on recent Electron (verify with 33.x; else instruct BlackHole/virtual device). | same |
| **Fallback** | none | mic only — still transcribes what the speakers play into the room |

The addon reports `hpMeetingSense.audioMode ∈ {'system+mic','system','mic','none'}` so the UI can say exactly what's being captured instead of failing silently.

### 4.2 Mixing and framing

```
displayStream.audioTrack ─┐
                          ├─► AudioContext (48 kHz) ─► GainNodes ─► ChannelMerger ─► AudioWorklet
micStream.audioTrack ─────┘                                                           │
                                             downsample → 16 kHz mono PCM16, 20 ms frames
                                             energy/ZCR VAD → speech / silence flags
                                             batch into ~1–3 s utterances (VAD-delimited),
                                             hard cut at 8 s so partials never lag
                                                          │
                                                          ▼  {type:"audio", seq, t0, t1, pcm16_b64}
```

- Keep the two sources on separate gain nodes → **"Mute mic"** is a gain change, not a renegotiation.
- Optional two-channel mode (system L / mic R) gives free "me vs. them" speaker attribution to the server without diarisation. Recommended default.
- Mid-session `getDisplayMedia` audio ends when the user stops sharing → addon emits `audio_lost` and the UI offers mic-only continuation.

### 4.3 Slide-aware / motion-aware keyframes (deterministic, no ML)

Runs on the existing `hpScreenSense.video` element:

```
every 500 ms:
  draw frame → 64×36 grayscale
  dhash  = 63-bit difference hash
  mad    = mean |pixel − prevPixel|          (0..255)
  changedPixels = fraction of pixels with |Δ| > 24

  motion  = changedPixels > 0.35 (video playing / scrolling)  → set state MOTION, do NOT capture
  static  = hamming(dhash, lastKeyframeHash) ≤ 3              → nothing new
  candidate = hamming(dhash, lastKeyframeHash) > 6  AND  changedPixels between 0.02 and 0.35

  if candidate and stable for 1500 ms (hash unchanged 3 samples) → KEYFRAME
  min interval between keyframes: 8 s   (rapid clicking → last one wins)
  heartbeat keyframe: every 5 min even if unchanged (recovers from missed changes)
  hard cap: 60 keyframes / hour (configurable)
```

Why this works for presentations: a slide change is a large, *then stable* difference; a talking-head video is a continuous small-to-medium difference; a cursor wiggle is under the 2 % floor. The "stable for 1.5 s" rule also skips transition animations.

Each keyframe → `/upload` (JPEG ≤ 1280 px, q 0.82, same helper as ScreenSense) → `{type:"keyframe", t, url, hash}` over the WS.

Optional later: OCR-on-device via Tesseract.js to detect slide *number/title* text, feeding better alignment. Not needed for v1.

---

## 5. Server: `backend/app/meetingsense/`

New package, mounted like the voice router — a two-line addition in `main.py`:

```python
from .meetingsense import router as meetingsense_router   # additive
app.include_router(meetingsense_router)                    # rejects until MEETINGSENSE_ENABLED
```

### 5.1 Files

```
backend/app/meetingsense/
├── __init__.py          # router export
├── config.py            # MEETINGSENSE_ENABLED, notes interval, retention, caps
├── routes.py            # WS /v1/meetingsense/session, GET status, GET/POST per-session
├── session.py           # MeetingSession: state machine, timers, fan-out to store/notes/chat
├── transcript.py        # segment assembly, optional 2-channel speaker tagging, timestamps
├── notes_engine.py      # windowed LLM notes: decisions / actions / questions / summary
├── keyframes.py         # calls /v1/multimodal/analyze (internal), aligns to transcript time
├── store.py             # sqlite tables: meetings, segments, keyframes, notes (additive migration)
└── prompts.py           # system prompts for notes + final summary + "ask"
```

### 5.2 WebSocket protocol — `WS /v1/meetingsense/session`

```
client → server
  {"type":"start", "conversation_id":"…", "project_id"?:"…", "persona_id"?:"…",
   "audio": {"rate":16000,"channels":1|2,"mode":"system+mic"}, "notes":true, "watch":true,
   "title"?:"Q3 planning", "source"?:"teams|zoom|meet|other"}
  {"type":"audio", "seq":n, "t0":ms, "t1":ms, "pcm16_b64":"…"}
  {"type":"keyframe", "t":ms, "url":"/files/…", "hash":"…"}
  {"type":"marker", "t":ms, "label":"important"}          # user pressed ⭐
  {"type":"mute", "mic":true|false}
  {"type":"ask", "text":"what did they decide about legal?"}
  {"type":"stop"}
  {"type":"ping"}

server → client
  {"type":"ready", "session_id":"…", "stt":true|false, "vision":true|false, "notes":true|false}
  {"type":"partial", "t0":ms, "text":"…"}                  # low-latency provisional text
  {"type":"segment", "id":"…", "t0":ms, "t1":ms, "speaker":"me|them|?", "text":"…"}
  {"type":"notes", "version":k, "decisions":[…], "actions":[…], "questions":[…], "summary":"…"}
  {"type":"slide", "id":"…", "t":ms, "url":"…", "caption":"…", "text":"…"}
  {"type":"answer", "text":"…"}                            # reply to "ask"
  {"type":"status", "elapsed":ms, "segments":n, "slides":n, "audio_lost"?:true}
  {"type":"final", "summary_message_id":"…", "transcript_url":"…"}
  {"type":"error", "error":"…"}
  {"type":"pong"}
```

Forward-compatible like the voice-call envelopes: unknown types are ignored on both sides.

### 5.3 Session pipeline

1. **Audio in** → `transcript.py` concatenates VAD utterances (with 200 ms overlap to avoid cut words) → `get_stt_provider().transcribe(wav)` in a worker (`asyncio.to_thread`, as `WhisperLocalSTTProvider` already does). With faster-whisper `base`/`small` on GPU this is ≈ 0.1–0.3× real time — comfortable.
   - Two-channel input: transcribe channels separately, tag `speaker: "me"` / `"them"`.
   - Emit `partial` immediately for the hard-cut 8 s chunks; emit `segment` once the utterance closes.
2. **Segments** → `store.py` (append-only) → WS fan-out → every **N = 60 s or 400 words** trigger `notes_engine`.
3. **Notes engine** (LLM): input = previous notes JSON + new window + captions of slides shown during the window. Output = strict JSON delta (`add_decisions`, `add_actions`, `resolve_questions`, `add_questions`, `summary`). Merged server-side so the client never sees flicker. Uses the same JSON-only prompting the repo already uses for jobs.
4. **Keyframes** → `keyframes.py` → internal call to `analyze_image(...)` (the same function `/v1/multimodal/analyze` wraps) with a slide-specific prompt: *"This is a presentation slide. Give the title, the bullet text verbatim, and one sentence on what it argues."* Result stored + pushed as `slide` and fed to the next notes window.
5. **Ask** → retrieval over this meeting's segments/slides (recent-window + simple keyword; vector DB in phase 3) → LLM → `answer`. Optionally persisted as a normal user/assistant pair in the conversation.
6. **Stop** → final summary (LLM over full transcript + notes + slide captions) → `add_message(cid, "assistant", summary, media={"images":[keyframe urls]})` → `jobs.schedule_session_jobs` if a project is attached → `final`.

### 5.4 Persistence into the conversation (keeps chat "readable")

Two write modes, chosen by the user's "Live AI notes in chat" toggle:

| Mode | What lands in `messages` | When |
|---|---|---|
| **Card only** (default) | One `[Meeting]` assistant message holding `meeting_id`; the React card hydrates from `/v1/meetingsense/{id}` | at start; summary message at stop |
| **Live in chat** | Additionally a `[Transcript hh:mm]` block every ~2 min and a `[Notes]` update when notes change | continuous |

Existing message rendering is untouched: the `[Meeting]` prefix is recognised by the new `MeetingCard` component the same way `[Image Analysis]` and phone events are recognised today; anything that doesn't understand it renders plain text.

### 5.5 Storage (additive migration)

```sql
CREATE TABLE IF NOT EXISTS ms_meetings   (id TEXT PK, conversation_id, project_id, title, source,
                                          started_at, ended_at, audio_mode, retention, summary_json);
CREATE TABLE IF NOT EXISTS ms_segments   (id TEXT PK, meeting_id, t0_ms, t1_ms, speaker, text, conf);
CREATE TABLE IF NOT EXISTS ms_keyframes  (id TEXT PK, meeting_id, t_ms, url, hash, caption, ocr_text);
CREATE TABLE IF NOT EXISTS ms_notes      (meeting_id, version, json, updated_at);
```

Export endpoint `GET /v1/meetingsense/{id}/export?fmt=md|json|srt` gives the user their data in one click (Markdown = summary + timeline of slides + full transcript).

---

## 6. Frontend UI (`frontend/src/ui/meetingsense/`)

Thin React layer over the addon; gated by `VITE_MEETINGSENSE_ENABLED` **and** backend `/v1/meetingsense/status` (so a stale frontend can't show a dead feature).

```
frontend/src/ui/meetingsense/
├── useMeetingSense.ts     # hook: wraps hpMeetingSense events → React state, reconnect, elapsed
├── ScreenAwarenessPopover.tsx  # the toggle popover (section 2.1) — replaces ScreenSense auto-button
├── RecordingPill.tsx      # sticky top indicator: red dot, timer, mic mute, stop
├── MeetingCard.tsx        # in-thread live card: transcript / notes / slides / ask
├── ConsentSheet.tsx       # first-run explainer, retention choice
└── SlideStrip.tsx         # horizontal keyframe thumbnails, click → lightbox with caption
```

UX details that make it feel premium rather than bolted on:

- Partial text renders in muted colour and slides into final text without layout jump (fixed line height, `will-change`).
- Notes use *append + strikethrough* for corrections instead of rewriting — the user can trust what they read 30 s ago.
- Slide thumbnails are clickable → lightbox shows the vision caption and the transcript that was spoken while that slide was up (join on timestamps).
- Keyboard: `⌘/Ctrl+Shift+M` toggles mute; `⭐` marker button drops a bookmark that the final summary honours ("You marked 14:06 …").
- Degrades explicitly: if STT is unavailable the popover greys out "Record audio" with *"Set `WHISPER_MODEL=small` to enable"* — the same helpful-error style `/v1/multimodal/analyze` uses for missing vision models.
- Mobile: the card collapses to summary + last 3 lines; capture itself is desktop/browser only (no `getDisplayMedia` audio on mobile browsers) — the popover says so.

Set `window.HOMEPILOT_SCREENSENSE_NO_AUTOBUTTON = true` when MeetingSense is enabled so the two don't both mount; ScreenSense's API is still called under the hood.

---

## 7. Desktop (Electron) additions — additive only

`desktop/main.js`:
```js
// MeetingSense: let the renderer's getDisplayMedia() include system audio.
session.defaultSession.setDisplayMediaRequestHandler(async (request, callback) => {
  const sources = await desktopCapturer.getSources({ types: ['screen', 'window'] })
  // reuse the primary-display preference from screensense:capture
  callback({ video: pickPrimary(sources), audio: 'loopback' })   // Windows; macOS: see note
}, { useSystemPicker: true })   // macOS 15+ shows the native picker
```
`desktop/preload.js`: expose `isDesktop` (already) + `meetingSenseAudio: 'loopback'|'none'` capability flag so the addon can label the mode accurately.

macOS: request Screen Recording permission (already needed for `desktopCapturer`) and Microphone permission via `systemPreferences.askForMediaAccess('microphone')`.

---

## 8. Configuration surface

| Env | Default | Meaning |
|---|---|---|
| `MEETINGSENSE_ENABLED` | `false` | mount + accept sessions |
| `MEETINGSENSE_NOTES_INTERVAL_S` | `60` | notes engine cadence |
| `MEETINGSENSE_NOTES_MODEL` | (chat default) | LLM for notes/summary |
| `MEETINGSENSE_VISION_MODEL` | (multimodal default) | slide captioning model |
| `MEETINGSENSE_RETENTION` | `text` | `text` \| `text+frames` \| `all` |
| `MEETINGSENSE_MAX_KEYFRAMES_PER_HOUR` | `60` | cap |
| `WHISPER_MODEL` / `STT_BASE_URL` | existing | STT selection — unchanged |
| `VITE_MEETINGSENSE_ENABLED` | `false` | frontend gate |

---

## 9. Delivery plan (each phase ships independently and is useful alone)

| Phase | Scope | New files | Touches existing |
|---|---|---|---|
| **1 — Record & transcribe** | Popover toggle, audio capture + mixer + VAD, WS session, STT → live segments, MeetingCard transcript, export `.md/.srt` | addon, `meetingsense/{routes,session,transcript,store,config}.py`, `MeetingCard`, `RecordingPill`, `ConsentSheet` | `main.py` (+2 lines), `config.py` (+flags), `index.html` (+1 script) |
| **2 — Slide-aware vision** | dHash keyframe scheduler, upload, caption via existing analyze, SlideStrip, slide↔transcript alignment | `keyframes.py`, `SlideStrip` | `desktop/main.js` (+loopback handler), `preload.js` (+flag) |
| **3 — AI in the loop** | Windowed notes engine, "ask about this meeting", final summary + LTM jobs, markers | `notes_engine.py`, `prompts.py`, card "Ask" input | none |
| **4 — Polish / premium** | 2-channel speaker tagging, on-device OCR of slides, vector retrieval over past meetings, Nexus-style "Meeting Secretary" persona bundle, Teams/Zoom/Meet source auto-detection from window title | bundle under `community/shared/bundles/` | `shared_registry.json` |

Nothing in any phase edits an existing endpoint, schema column, or chat path.

---

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| No system audio on macOS browsers / desktop apps | Detect and *say so*; default to mic; Electron loopback where available; document virtual-device workaround |
| STT latency on CPU-only machines | `WHISPER_MODEL=tiny/base`, partials every 8 s, show "catching up" state; OpenAI-compat provider for users who opt into cloud |
| Word-cut at utterance boundaries | 200 ms overlap, drop duplicate trailing tokens |
| Keyframe spam during scrolling/video | motion gate (> 35 % changed pixels), 1.5 s stability, 8 s min interval, hourly cap |
| Notes hallucinating decisions | JSON-delta prompt with "only if explicitly stated", cite `t0` timestamps per item so the user can jump to the source segment |
| Legal/consent | Consent sheet, always-visible indicator, no hidden capture, local-only default, one-click delete of a meeting |
| Disk growth | Retention default `text`; keyframes ≤ 1280 px JPEG; cleanup in `jobs.cleanup_old_jobs`-style task |

---

## 11. Summary

MeetingSense is ScreenSense with three additive layers: **audio** (browser/Electron capture mixed on the client, transcribed by the STT providers the repo already has), **slide-aware vision** (a deterministic dHash/motion scheduler feeding the existing `/v1/multimodal/analyze`), and **AI in the loop** (a windowed notes engine and a per-meeting "ask", persisted through the existing `add_message` and `jobs` machinery). The UI is one toggle popover, one recording pill and one live card in the thread — flag-gated end to end, local by default, and every phase leaves the current product untouched when the flag is off.
