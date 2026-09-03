# MeetingSense

Screen + audio → a live transcript, slide keyframes and rolling notes, in the chat you are
already in. Local by default.

**Status: MS0 + MS1.** The flags, the package, the status endpoint and the speech layer
exist. Nothing records yet — the recorder lands in wave W1. This page grows one section per batch; what is written
below is what works today, not what is planned. The plan is
[`docs/design/MEETINGSENSE_BATCHES.md`](design/MEETINGSENSE_BATCHES.md).

---

## Is it available on this machine?

```bash
curl -s localhost:8000/v1/meetingsense/status | python3 -m json.tool
```

The endpoint answers whether the feature is on or off — deliberately. A frontend has to tell
three states apart, and a 404 collapses them into one:

```json
{
  "enabled": false,
  "ready": false,
  "retention": "text",
  "flags": { "remote": false, "together": false, "catalog": false,
             "mcp": false, "agent": false, "modes": false },
  "stt": {
    "available": false,
    "provider": "null",
    "segments": false,
    "remote": false,
    "hint": "Set WHISPER_MODEL (e.g. small) for local transcription, or STT_BASE_URL for a remote one."
  },
  "vision": {
    "available": false,
    "model": null,
    "hint": "Set MEETINGSENSE_VISION_MODEL or a default multimodal model to caption slides."
  },
  "limits": { "panel_max_kb": 64, "max_keyframes_per_hour": 60 }
}
```

Read it like this:

| Field | Question it answers |
|---|---|
| `enabled` | Did the operator turn MeetingSense on? |
| `ready` | Can this machine actually honour that? (`enabled` **and** speech available) |
| `stt.hint` | If not, what to set — this is the text a UI should show rather than greying a control out |
| `stt.provider` | **Which** engine will transcribe. See "Where your audio goes" below |
| `stt.segments` | Whether the timings are **measured** rather than assumed. Every provider returns spans; only local Whisper reads them off the model |
| `stt.device` | Which device the model actually loaded on — `null` until the first transcription |
| `stt.device_note` | Present only when the resolved device differs from the requested one |
| `vision.available` | Whether slides can be captioned. Never a blocker — the recorder works without it |

`ready: false` with `enabled: true` is the case worth designing for: the operator asked for
the feature and the machine cannot deliver it. `hint` says which.

---

## Turning it on

```bash
MEETINGSENSE_ENABLED=true
```

That is the master switch and it implies nothing else. Six sub-flags, one per wave, all
default false:

| Flag | Default | Turns on |
|---|---|---|
| `MEETINGSENSE_ENABLED` | `false` | the feature at all |
| `MEETINGSENSE_REMOTE` | `false` | reaching it from a hosted avatar through OllaBridge |
| `MEETINGSENSE_TOGETHER` | `false` | live meeting context inside persona chat |
| `MEETINGSENSE_CATALOG` | `false` | the Meetings library view |
| `MEETINGSENSE_MCP` | `false` | the `ms.*` MCP server |
| `MEETINGSENSE_AGENT` | `false` | the LangGraph agent instead of the fixed notes loop |
| `MEETINGSENSE_MODES` | `false` | Participant / Coach / Presenter / Practice |

**None is implied by the master.** A batch lands its capability with the flag off, so turning
the recorder on never turns on something a later wave built.

### Tuning

| Variable | Default | What it tunes |
|---|---|---|
| `MEETINGSENSE_RETENTION` | `text` | `text` \| `text+frames` \| `all`. An unreadable value falls back to `text` — the safe direction to be wrong in is keeping less |
| `MEETINGSENSE_NOTES_INTERVAL_S` | `60` | How often the notes engine runs (W4) |
| `MEETINGSENSE_NOTES_MAX_WORDS` | `400` | …or how many words, whichever comes first |
| `MEETINGSENSE_NOTES_MODEL` | *(chat default)* | LLM for notes and the final summary |
| `MEETINGSENSE_VISION_MODEL` | *(multimodal default)* | Model that captions slides (W3) |
| `MEETINGSENSE_MAX_KEYFRAMES_PER_HOUR` | `60` | Cap on captured slides |
| `MEETINGSENSE_PANEL_MAX_KB` | `64` | Card size on the avatar surface. Mirrors `avatar_director.panels.DEFAULT_MAX_KB`; a test asserts the two stay equal |
| `WHISPER_MODEL`, `STT_BASE_URL` | *(existing)* | Speech selection — unchanged, shared with voice calls |
| `WHISPER_DEVICE` | `auto` | `auto` \| `cuda` \| `cpu`. `auto` is what faster-whisper already picked, so setting nothing keeps today's behaviour |
| `WHISPER_COMPUTE` | `default` | e.g. `float16` on CUDA, `int8` on CPU. `default` is again today's behaviour |

### Why the device is reported, not just configurable

`auto` is a request, not an outcome. When CUDA is present but unusable — a mismatched
ctranslate2 wheel, a missing cuDNN — faster-whisper falls back to CPU **silently**, and
transcription runs perhaps ten times slower than the design's latency budget assumes. Nothing
says so.

So the provider reads the device back off the loaded model rather than echoing the request,
and the status endpoint reports it:

```json
"stt": { "provider": "whisper-local", "device": "cpu",
         "device_note": "requested cuda, running on cpu" }
```

`device: null` means the model has not loaded yet, which is a different answer from `"cpu"`
and is kept distinct.

### Two things MS1 did not finish

Both are tracked as rows in the batches file rather than left as intentions.

**A remote STT provider still cannot cite timestamps.** `OpenAICompatSTTProvider` inherits the
one-span fallback, so with `STT_BASE_URL` set you get `t1: null` and `segments: false`. That is
honest, not broken — but the notes engine cites `t0` per item, so real remote timings
(`verbose_json`) are needed before W4. Tracked as **MS1-a**.

**The latency budget is still a hypothesis.** Part 2 §F assumes GPU transcription at roughly
0.2× real time. Nobody has measured it: the build container has no CUDA and no
`faster_whisper`. Take the number during the W1 pilot, on the machine that will actually run
meetings, and record it here. Tracked as **MS1-b**.

---

## Where your audio goes

This matters more than the defaults suggest, so the status endpoint names it and the consent
sheet will too.

`get_stt_provider()` prefers the OpenAI-compatible endpoint **whenever `STT_BASE_URL` is
set** — it is the shared speech stack, and that precedence is right for voice calls. For a
meeting it is a surprise: someone who configured a remote endpoint months ago would otherwise
send an hour of audio to it without being told.

- `stt.provider: "whisper-local"` → transcription happens on this machine.
- `stt.provider: "openai-compat"` and `stt.remote: true` → audio leaves this machine for
  whatever `STT_BASE_URL` points at. The endpoint is deliberately **not** echoed in the
  status body, because it can carry a key.
- `stt.provider: "null"` → nothing can transcribe; `hint` says what to install.

To force local transcription, unset `STT_BASE_URL` and set `WHISPER_MODEL=small`.

---

## What MS2 added, and what it still cannot do

MS2 is three modules and no route. Nothing in it is reachable over HTTP yet — that is MS3's
job — so turning the flag on after MS2 changes nothing a user can see. What it buys is the
shape everything above it is written against.

**`store.py`** — four tables (`ms_meetings`, `ms_segments`, `ms_keyframes`, `ms_notes`) in
HomePilot's existing SQLite file, reached through `storage._get_db_path()` rather than a
database of their own. Every statement is `CREATE TABLE IF NOT EXISTS`, and `migrate()` runs
**only when the flag is on**: an install that never enables MeetingSense never grows the
tables.

**`transcript.py`** — the utterance assembler. Chunks overlap by 200 ms because cutting on
silence still cuts words, and the overlap is therefore transcribed twice. The assembler trims
the **head of the later** span, never the tail of the earlier one: a segment already sent to
the client and written to the store must not change afterwards, or the live card flickers and
the reader stops trusting what they read a moment ago. Two words is the floor for calling a
match an overlap — one shared word between utterances is ordinary English.

**`session.py`** — `MeetingSession`, `idle → live → ended`, one way. A stopped meeting is a
record; a second `stop` is a no-op rather than an error, because both ends of a socket notice
a disconnect and both will try.

The load-bearing constraint is one line long:

> **`session.py` must never import FastAPI.**

MeetingSense has to run over two transports — a WebSocket the browser opens directly (MS3),
and the avatar session OllaBridge proxies for a hosted page (MS7). A core that knows about
either one has to be written twice. So it knows about a `Transport` instead, which is `send`
and `close` and deliberately nothing else: the peer address, the negotiated capabilities,
whether the socket is still open are all knowledge the core would start branching on, and
branching on it is how one core becomes two. A test asserts the protocol has exactly those
two methods, and another reads `session.py`'s own source to check the import never appears.

Not yet done, and not in MS2's scope: a route, a microphone, a UI, captioning a keyframe
(MS9), or generating notes (MS12).

---

## The session socket (MS3)

`WS /v1/meetingsense/session`. One connection is one meeting.

```
client → server   start · audio · keyframe · mute · status · stop · ping
server → client   ready · partial · segment · status · final · error · pong
```

Unknown types are ignored in both directions. A newer client talking to an older server
should lose the feature it asked for, not the meeting it is recording.

**Turning the flag off refuses the way the voice route refuses** — the socket is accepted, an
`error` frame says `disabled`, and then it closes with 1008. Rejecting the handshake instead
would leave the client unable to tell "disabled" from "wrong URL" from "server down", and the
popover has to explain which.

### Audio on the wire

`{"type":"audio", "format":"wav"|"pcm16", "data_b64":"…", "t0":ms, "t1":ms}` — the same shape
as a `/v1/voice/session` frame, so there is one contract to debug rather than two. (A frame
using the design document's `pcm16_b64` field works too.)

Two things happen to it server-side:

- **A RIFF header goes on raw PCM16.** The provider writes the bytes it is given to a `.wav`
  temp file; headerless PCM named `.wav` has its first 44 bytes of *speech* read as a header,
  and the result is a garbled transcript rather than an error.
- **A stereo frame is split into two transcriptions**, because MS4's mixer keeps system audio
  and microphone on separate gain nodes rather than summing them. The convention is fixed:

  | channel | speaker | what it is |
  |---|---|---|
  | 0 | `them` | system audio — the other people in the call |
  | 1 | `me` | this machine's microphone |

  Each channel gets its own assembler. The 200 ms overlap is an artefact of how *one* stream
  was chunked, so deduplicating across the two would compare your microphone against the call
  and drop whichever of two people said the same words second — attributing the line to
  whichever channel happened to be transcribed first.

`t0`/`t1` describe where the chunk sat; the client framed the audio, so the frame length is
passed to the provider as `duration_s`. The timings inside a `segment` come from
`transcribe_segments`, not from the frame.

### `partial` is shown, never recorded

A frame marked `"partial": true` is transcribed and echoed as provisional text. It is not
stored and does not advance the assembler — the same audio arrives again when the utterance
closes, and a partial that had been remembered would make the real segment look like a
duplicate of itself, so the meeting would lose the line.

### When something goes wrong

One bad frame does not end a recording. Every refusal is an `error` frame with a stable code
— `disabled`, `not_live`, `stt_unavailable`, `conversation_required`, `url_required`,
`audio_missing`, `audio_undecodable`, `audio_format`, `audio_misaligned`, `audio_too_large`,
`frame_failed` — and the socket stays up.

A dropped socket ends the meeting. The session *is* the socket and nothing is going to
reconnect to it; leaving it live would leave a row that says "in progress" forever. What
survives is in the store.

If no speech provider is available the meeting still starts, with `"stt": false` in `ready`
and a named refusal on each audio frame. A meeting that records slides and markers without a
transcript is still a meeting, and is a better answer than refusing the connection.

The tables are created on the **first connection** with the flag on, not at import — an
install that never enables MeetingSense never grows the schema.

---

## The capture addon (MS4)

`frontend/public/js/homepilot-meetingsense.js`, mirrored byte-for-byte in
`community/addons/meetingsense/`. It opens its own capture rather than extending ScreenSense
(decision D1): ScreenSense promises one silent still with `audio: false`, and MeetingSense
breaks both halves of that by holding a stream open for an hour and recording sound.

```js
await hpMeetingSense.start({ conversationId, title, source });
hpMeetingSense.muteMic(true);     // your side only; the call keeps recording
await hpMeetingSense.stop();
```

Results arrive as `ms:segment`, `ms:partial`, `ms:status` and `ms:audio_lost` events on
`window` — events rather than callbacks, so the chat card and the recording pill can both
listen and neither owns the recorder.

**The two sources stay on separate channels.** Screen audio goes to a gain node into merger
input 0 and the microphone to input 1; summing them would be one line shorter and would throw
away the only speaker signal there is. Muting is that gain going to zero, which is why mute
has to be a node rather than a flag.

### When a chunk is cut

An energy VAD closes an utterance after **350 ms** of quiet, provided it has run for at least
**1 s** — a shorter pause is a breath in the middle of a sentence, and a shorter utterance is
a cough. A speaker who never pauses is **hard-cut at 8 s**, which bounds both the memory held
and how long a reader waits for a line to appear.

Only the hard cut carries the **200 ms overlap** into the next chunk, and that asymmetry is
the point: a hard cut fires regardless of what the speaker is doing, so it lands inside a
word and the next chunk has to repeat the tail for the server to reconcile. A close on silence
cut nothing — that is what waiting for the quiet buys — so repeating audio there would hand
the server a duplicate to remove for no reason.

Every utterance still opens slightly *before* the frame that tripped the threshold, using a
rolling buffer of the preceding frames. The attack of a word is quieter than its body, so the
frame that trips the VAD is already a syllable in.

### What the tests cover, and what they cannot

jsdom has no `AudioContext`, no `AudioWorklet` and no `getDisplayMedia`, so the capture graph
is not exercised by any automated test. What is covered — 39 tests over synthetic buffers — is
every decision made about the samples after they arrive: framing without drift, the VAD cuts,
the WAV layout and channel order, clamping, resampling, base64 chunking.

The graph itself needs the manual matrix below. **Nobody has run it yet.**

| # | Browser | Share | Expected | Signed off |
|---|---|---|---|---|
| 1 | Chrome, desktop | a tab, "Share tab audio" ticked | `system+mic`, both speakers labelled | ⬜ |
| 2 | Chrome, desktop | a whole screen | `system+mic` on Windows/macOS; `mic` on Linux | ⬜ |
| 3 | Chrome, desktop | a window | `mic` — window shares carry no audio anywhere | ⬜ |
| 4 | Edge, desktop | a tab | as Chrome | ⬜ |
| 5 | Firefox | any | `mic`; the popover says why | ⬜ |
| 6 | Safari | any | `mic`; the popover says why | ⬜ |
| 7 | Any | microphone declined | `system`, and the meeting still records | ⬜ |
| 8 | Any | both declined | `start` refuses with `audioMode: 'none'` | ⬜ |
| 9 | Chrome | stop sharing mid-meeting | `ms:audio_lost`, recording continues on the mic | ⬜ |
| 10 | Chrome | 30-minute meeting | memory flat, no drift between audio and timestamps | ⬜ |

Rows 1–3 are the ones that decide whether MeetingSense records a meeting at all; row 10 is the
one a short test cannot substitute for.

---

## Verifying MS0 – MS4

With the flag off — the shipped state:

```bash
curl -s localhost:8000/v1/meetingsense/status | grep -o '"enabled": [a-z]*'   # false
```

With it on, and no speech configured:

```bash
MEETINGSENSE_ENABLED=true make start
# status → enabled: true, ready: false, and a hint naming WHISPER_MODEL
```

Tests:

```bash
cd backend && python3 -m pytest tests/meetingsense -q   # 191
```

MS1 touches `backend/app/voice/providers.py`, which the voice backend shares — the plan's
one sanctioned exception to additive-only. The rule it keeps instead is narrower and
checkable, and these are the tests that check it:

```bash
cd backend && python3 -m pytest tests/meetingsense/test_stt_capability.py -q  # 28
cd backend && python3 -m pytest tests/test_voice.py tests/test_voice_call*.py -q
```

MS2 adds 68 of those tests and touches nothing outside `backend/app/meetingsense/`:

```bash
cd backend && python3 -m pytest tests/meetingsense/test_transcript.py -q     # 31
cd backend && python3 -m pytest tests/meetingsense/test_session_core.py -q   # 37
cd backend && python3 -m pytest tests/meetingsense/test_session_ws.py -q     # 40  (MS3)
cd frontend && npx vitest run src/test/meetingsenseAddon.test.js            # 39  (MS4)
```

MS4 also widened `frontend/vitest.config.ts` from `src/**/*.test.{ts,tsx}` to include `js` and
`jsx`. That glob had been quietly excluding **17 test files and 124 tests** — the whole
phone/call primitives suite among them — which had never run in CI since they were written.
All of them pass; nothing was fixed to make that true.

What MS0 – MS4 deliberately do **not** do: draw a UI, caption a slide (MS9), or write a
message into the conversation (MS12). There is now a recorder and a socket for it to talk to,
and nothing yet that offers either to a user — the entry point is MS5.

---

## Design

- [`design/MEETINGSENSE_DESIGN.md`](design/MEETINGSENSE_DESIGN.md) — Part 1: capture,
  transcript, slide keyframes, notes.
- [`design/MEETINGSENSE_DESIGN_PART2.md`](design/MEETINGSENSE_DESIGN_PART2.md) — Part 2:
  Together mode, catalog, agent engine, MCP, helper modes.
- [`design/MEETINGSENSE_BATCHES.md`](design/MEETINGSENSE_BATCHES.md) — the implementation
  tracker, and **§1 lists the six places the design documents disagree with the source**.
  Read that before trusting a "we reuse X" claim in either design doc.
