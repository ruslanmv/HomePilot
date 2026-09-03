# MeetingSense

Screen + audio → a live transcript in the chat you are already in, with export. Local by
default.

**What works today:** recording a meeting from the browser on the machine running HomePilot,
or from a hosted avatar page through OllaBridge; a live transcript card with a recording pill
and a consent sheet; resume across a dropped connection; export as Markdown, SRT or JSON; and
the meeting landing in History as a titled conversation.

Slides are captured and captioned too (MS9): the recorder watches the shared screen, decides
which frames are a *new thing to look at*, and a local vision model describes each one.

The card shows them as a strip, and opening one shows the caption beside the words spoken
while that slide was up (MS10).

**What does not, yet:** desktop system-audio loopback (MS11) — the last row of W3. Everything
else in the recorder works: rolling notes, a summary that carries its own recap and decisions,
asking a question about a meeting live or afterwards, export, and one-call deletion.

The order of work, and the reasoning behind each decision, is
[`docs/design/MEETINGSENSE_BATCHES.md`](design/MEETINGSENSE_BATCHES.md). What changed when is
[`MEETINGSENSE_CHANGELOG.md`](MEETINGSENSE_CHANGELOG.md). **Before the next wave is built, the
recorder gets a week of real meetings** — what to run and what to write down is
[`MEETINGSENSE_PILOT.md`](MEETINGSENSE_PILOT.md).

> **It ships disabled.** With `MEETINGSENSE_ENABLED` unset, the status endpoint answers
> honestly, every other route refuses, no table is created and no audio is touched.

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
  "limits": { "panel_max_kb": 64, "max_keyframes_per_hour": 60 },
  "remote_ok": false
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
| `remote_ok` | Whether a meeting may arrive over the avatar session — `enabled` **and** `ready` **and** the remote flag. See "Recording from a hosted page" |

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

### Two things the speech layer does not do yet

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

## Starting a meeting

`frontend/src/ui/meetingsense/entryPoint.ts`. When the backend reports MeetingSense enabled,
the existing ScreenSense button gains a popover — *Watch screen · Record audio · Live AI notes*,
with **Start session** and **Ask once**. When it does not, the button is untouched.

"Untouched" is literal and asserted: `attach()` returns `null` before it sets an attribute,
adds a listener or appends a node, and a test compares the button's `outerHTML` before and
after. A status the frontend cannot read counts as disabled — silence reads as "off", never as
"probably fine", so a stale build can never offer a control the backend would refuse.

**"Ask once" keeps its exact path**, and this took some care. ScreenSense's own click handler
is still on that button, so without intervention one click would both fire a question and open
the popover. ScreenSense is not edited by any batch, so the handler is suppressed in the
capture phase and re-fired by the popover's "Ask once" button, which re-dispatches the click
ScreenSense was written for rather than reimplementing what it does. `destroy()` puts the
button back.

### Every disabled control says why, and what to set

This is the §2a bar the batch exists to meet. A greyed-out toggle with no explanation is worse
than no toggle. Each state has its own sentence and a stable id:

| id | When | What it says |
|---|---|---|
| `disabled` | flag off | names `MEETINGSENSE_ENABLED` |
| `stt-unavailable` | no speech provider | **the server's own hint, verbatim** — it already names the variable, and a second copy in the client is a second place to keep in step |
| `stt-remote` | `STT_BASE_URL` is set | names the provider, says audio leaves this machine — never echoes the endpoint, which can carry a key |
| `stt-no-timestamps` | `supports_segments: false` | the transcript will have no timestamps to cite |
| `stt-device` | `device_note` present | e.g. *requested cuda, running on cpu* — the silent fallback that makes people think the latency budget is unreachable |
| `capture-mac` | macOS | records the microphone only unless a virtual audio device is added |
| `capture-linux` | Linux | share a tab with "Share tab audio"; a window share carries no audio |
| `capture-mobile` | phone or tablet | needs a desktop browser; the capture toggles are **hidden**, not greyed — a disabled control on a phone invites tapping it |
| `capture-unsupported` | desktop without `getDisplayMedia` | Chrome or Edge can |
| `vision-unavailable` | no vision model | slides will not be captioned; tone is *info*, because a meeting records fine without them |

A test greps the module for generic prose — "not available", "Unavailable", "Not supported" —
so the bar cannot be quietly lowered later.

### Keyboard and screen reader

`Esc` closes the popover and returns focus to the button; opening moves focus to the first
enabled control. The button carries `aria-expanded`, `aria-controls` and `aria-haspopup`, and
the popover is a labelled `<section>` rather than a `<dialog>` — a modal backdrop over a live
meeting would be the wrong thing. axe-core runs over both the healthy and the degraded trees
with zero violations (`color-contrast` is off, since jsdom neither lays out nor paints; that
check belongs to the manual matrix).

---

## What gets captured

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

### Which frames become slides

The recorder samples the shared screen **twice a second**, draws it into a 64×36 grayscale
thumbnail, and asks one question: *is this a new thing to look at, or the same thing still
moving?* Almost always the answer is neither, and answering it costs 2,304 subtractions, which
is why it can run on the main thread without a worker.

A frame is captured when the picture is **both different and settled**:

| | | why |
|---|---|---|
| motion gate | > 35 % of pixels changed **since the last capture** | a slide flip moves most of the frame; a cursor, a caret and a clock move well under a percent |
| stability | < 2 % changed between consecutive samples, held for **1.5 s** | this is the whole difference between a slide flip and a video — both change most of the frame, and only one of them then stops |
| floor | **8 s** between keyframes | a deck clicked through fast is still a deck; eight seconds is roughly "was on screen long enough to be talked about" |
| heartbeat | after **5 min** with nothing captured, if still | catches the screen that changed by less than the gate at every step and is a different screen by the end — a document written into over ten minutes |
| cap | **60 per rolling hour** (`MEETINGSENSE_MAX_KEYFRAMES_PER_HOUR`) | a rolling window, not a bucket: a bucket lets 120 through either side of a boundary |

The four sequences that shaped those numbers are in the test file, and each has a case that
fails if the threshold moves:

- **a slide flip** → one keyframe, of the settled slide rather than the transition;
- **scrolling a document** → one keyframe when it stops, not one per sample;
- **a video playing** → nothing, however long it plays. The heartbeat is not a way around
  this: it requires stillness too, because a still from the middle of a video describes
  nothing and sixty of them describe it sixty times;
- **a cursor wiggling on a static slide** → nothing, for as long as it goes on.

Keyframes are stamped with **the same clock as the transcript** — the audio sample count, not
`Date.now()`. MS10 joins a slide to the words spoken while it was up by comparing that number
with a segment's `t0`, and two clocks that agreed only to within a second would put the join a
sentence out at every boundary.

### The caption, and why a re-shown slide only gets one

Each keyframe carries a **dHash** — 64 bits saying, for each cell of a 9×8 grid, whether it is
brighter than the cell to its right. A *relational* hash, which is the point: it is unchanged
by the exposure difference between two captures of the same slide.

The server captions a keyframe by calling `multimodal.analyze_image` directly with a prompt
written for a slide rather than for a photograph — the generic one produces "a computer screen
showing a presentation with blue text", which is true of every slide in the deck. When a hash
has already been captioned **in the same meeting**, the caption is copied rather than
regenerated: the timeline still shows the slide was up again, but there is one wording. Two
strip entries for one slide whose captions disagree read as two different slides. The reuse is
scoped to one meeting because a 64-bit hash is small enough that a collision across an install
is not a thing to call impossible.

Captioning runs **beside** the frame loop, not inside it — a vision model takes seconds, and
awaiting it would stall the transcript every time a slide changed. `stop` waits up to 8 s for
what is in flight, so the summary message carries the last slide's caption, and cancels the
rest: a task outliving its session would write a `slide` frame to a socket belonging to a
meeting that is over.

Calling `analyze_image` directly rather than `POST /v1/multimodal/analyze` is exactly the
`persist` flag that endpoint carries. The chat path writes its analysis into a conversation
and hands it to the memory extractor; this path writes a caption onto one keyframe row. Per
D4 a meeting is retrieved from, never extracted into long-term memory.

**No vision model is a complete meeting, not a degraded one.** Slides are still captured, and
the strip shows timestamps with no captions.

### The strip, and the join (MS10)

Slides hang under the transcript rather than beside it: a strip in the margin competes with the
transcript for the same attention and adds a horizontal scroll on every phone, and the slides
are what a reader goes looking for rather than what they watch.

**Two `slide` frames arrive for one slide** — one when the recorder takes it, one when the
caption lands seconds later. The card upserts on `id`. A slide that only appeared once the
model answered would look, for those seconds, like a slide that was missed.

Opening one shows the caption **and the transcript spoken while it was up**, which is the
point of the batch: a slide on its own is a picture of a screen, and a picture of a screen is
not why anybody records a meeting. Two rules make the join right:

- **Half-open at the next slide.** A segment whose `t0` equals the next slide's timestamp
  belongs to the *next* slide — the words began as the new slide went up. A closed interval
  would file the opening sentence of every slide under the one before it, and that sentence is
  usually the one that says what the new slide is about.
- **Attribution by where a segment starts.** A sentence that ran across a slide change belongs
  to the slide it began under, once. Splitting on overlap would show the same words under two
  slides.

This is why keyframes carry the transcript's clock (above). The join is exact because there is
one clock, not two that agree to within a second.

### What the automated tests cover, and what they cannot

jsdom has no `AudioContext`, no `AudioWorklet`, no `getDisplayMedia` and no canvas, so neither
the capture graph nor the screen sampler is exercised by any automated test. What is covered —
84 tests over synthetic buffers and synthetic screens — is every decision made about the data
after it arrives: framing without drift, the VAD cuts, the WAV layout and channel order,
clamping, resampling, base64 chunking, and every keyframe threshold above.

Both the graph and the sampler need the manual matrix below. **Nobody has run it yet.**

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
| 11 | Chrome | a slide deck, `watch: true` | one keyframe per slide, captioned; none while a video plays | ⬜ |
| 12 | Chrome | a window share with no audio, `watch: true` | video kept for slides, `audioMode: 'mic'` | ⬜ |

Rows 1–3 are the ones that decide whether MeetingSense records a meeting at all; row 10 is the
one a short test cannot substitute for. Row 11 is the only place the thresholds meet a real
screen: the synthetic sequences prove the scheduler does what it says, not that "35 % changed"
is what a real deck does.

---

## While it runs — the card, the pill and consent

The first thing a user actually sees. `frontend/src/ui/meetingsense/` — `meetingState.ts`
(every decision as a pure function), `MeetingCard.tsx`, `RecordingPill.tsx`,
`ConsentSheet.tsx`, `useMeetingSense.ts`.

### Stop keeps recording

Pressing **Stop** does not stop the recorder. It starts a ten-second countdown during which
capture continues, and only then sends `stop`. That is the whole point of the undo: the ten
seconds somebody spends deciding are usually ten seconds somebody else was still talking, so a
Stop that stopped immediately would make Undo a lie — you would get the meeting back with a
hole in it.

### What the card promises

- **Nothing already shown changes.** Segments are keyed by `id`, so the replay after a
  reconnect is invisible rather than doubling the last few lines — at exactly the moment a
  "reconnecting" pill has already unsettled the reader. Out-of-order replays sort by `seq`.
- **No layout jump.** A provisional line is the same element with the same class as the
  segment that replaces it, so solidifying swaps text in place instead of adding a row.
- **The reader is never yanked.** New lines scroll into view only when the reader is already
  at the bottom; otherwise a *"↓ N new lines"* button counts what is waiting and going there
  stays their decision.
- **A slow transcript says it is slow.** Over two seconds behind, the card reads
  *"catching up · N s behind"* from `behind_ms`. Below that it says nothing — a transcript one
  utterance behind is working normally, and a label that flickers every sentence is worse than
  none.
- The transcript is a `<section aria-label="Live transcript" aria-live="polite">` and each line
  a `<p data-t0>`. The timestamp is data: MS10's slide join reads it.

The pill carries elapsed time, provider, audio mode and a **live level meter** — the meter is
what answers "is it actually hearing me", which a static red dot never does — as a
`role="status"` with `aria-live="polite"`, because a screen-reader user has no red dot.

### Consent

The sheet names **which** provider will hear the meeting and **where** the audio goes, built
from the same `/status` the popover reads. The endpoint is never shown; it can carry a key.
"Don't show again" is per machine — it is a browser preference and the machine is what has the
microphone — and it does not cover the reminder to tell participants, which stays in the pill
on every start. It is a real modal with a hand-rolled focus trap in both directions: tabbing
out of a consent sheet and starting a recording from a control behind it is the exact outcome
the sheet exists to prevent.

### Reading a meeting back

| Route | What it gives |
|---|---|
| `GET /v1/meetingsense/{id}` | meeting, segments, keyframes, notes, and whether it is live — the card hydrates from this rather than replaying the socket |
| `GET /v1/meetingsense/{id}/export?fmt=md` | Markdown to paste into a document |
| `…?fmt=srt` | real cues from `t0`/`t1`, to lay over a recording |
| `…?fmt=json` | everything, in the shape it is stored |

Both are **404 while the flag is off**, the same answer as a meeting that does not exist —
`/status` is where a client asks whether the feature exists, and answering it again here would
let a caller tell a real id from a fabricated one.

**`t1: None` is the normal case on a remote-STT install** (MS1-a is unbuilt), so every format
handles it. SRT takes the end from the measured `t1`, failing that the next segment's start —
a real bound, not a guess — and failing both a two-second span; a measured end always wins,
because taking the next start first would stretch a two-second sentence across a thirty-second
silence. JSON leaves `t1_ms` null: the other formats have to put something on screen, a data
export does not, and inventing an end hands the next tool a measurement nobody made.

### Where the meeting lands

**HomePilot has no `conversations` table.** A conversation is `messages` grouped by
`conversation_id`, and History labels each one with the *content of its last message*. So D5's
auto-title needs no schema change at all: the meeting message is the last message written when
a meeting stops, and the D5 title leads it —

```
[Meeting] 🎙 Q3 planning · teams · 2026-09-03
00:30:00 · 14 segments · 3 slides
```

Adding a title column instead would have written a value the existing History view never
reads. The body is plain text on purpose: a client that has never heard of MeetingSense — an
export, another persona reading the conversation later — sees an account of the meeting rather
than a marker and a blank.

Writing it can never break a stop. The transcript is already in the store, which is the part
that cannot be reconstructed, so a failure here is logged and swallowed.

### What is not covered here

jsdom does not lay out or paint, so *"the DOM height is identical before and after a partial
solidifies"* cannot be measured in a test. What is asserted is the structural fact underneath
it — same element, same class, replaced in place. Pixels, and the colour contrast axe-core is
told to skip, belong to the manual matrix.

---

## When the network goes

MS3 ended a meeting when its socket dropped. Right for the store — no row saying "in progress"
forever — and wrong for the person whose Wi-Fi blinked forty minutes into a board meeting.

A drop now **suspends** the meeting for a grace window rather than ending it:

| Setting | Default | Meaning |
|---|---|---|
| `MEETINGSENSE_RESUME_GRACE_S` | `120` | how long a dropped meeting stays resumable. **`0` reproduces the old behaviour exactly** — a drop is final |
| `MEETINGSENSE_RESUME_MAX_REPLAY` | `200` | most segments a single resume will replay |

The client keeps capturing, queues what is said, and reconnects on a **1-2-4-8 s backoff
capped at 15 s**, sending `resume {meeting_id, last_seq}`. The server holds the session with
everything that makes the transcript continuous — the per-speaker assemblers with their 200 ms
overlap windows, the counters, the sequence. Rebuilding the assemblers would restart the
dedupe with an empty window and duplicate a line at every reconnection.

**What died in the socket comes back.** D10 says the server replays nothing because the client
already has it — true of everything that arrived, and false of exactly the frames that were in
flight when the socket died. Those exist only in the store, so segments above the client's
`last_seq` are replayed, marked `replayed: true`. Ordered by `seq`, never by time: two channels
of one chunk share a `t0`, so time is not a numbering.

A meeting recorded before this batch has `seq = NULL` on its segments and cannot be resumed,
which is correct — it was recorded by a server that had no resume.

### When reconnecting is not winning

If the queue outgrows **two seconds** something has to give, and the choice is made by how much
speech a chunk carries rather than by how old it is: a cough, a chair or a keyboard that
cleared the VAD by accident goes first, oldest of those first, never the newest — the newest is
what the reader is waiting for. One chunk is always kept, so a saturated connection cannot
quietly record silence. `behind_ms` on `ms:status` says how far behind that leaves the
transcript, and is what MS6's *"catching up · N s behind"* label reads.

`hpMeetingSense.levels` carries an RMS per channel for the recording pill's meter — a property
polled on the pill's own frame loop, not an event, because pushing fifty events a second at a
meter that repaints sixty times a second is noise rather than data.

Two new events: `ms:reconnecting {attempt, delay, meetingId}` and `ms:resumed`. When the grace
window has closed the server answers `not_resumable`; the client stops retrying and clears
`reconnecting`, because a pill that says "reconnecting…" forever over a meeting that is gone is
worse than one that says nothing.

**Not covered:** a server restart loses the in-memory sessions, so meetings left `live` or
`suspended` in the store are stale until something reconciles them at startup. MS3 had the same
gap for `live` and it is still open.

---

## Recording from a hosted page

The path a hosted page actually takes:

```
yourfriend.online  ──ws──▶  OllaBridge /v1/avatar/session  ──ws──▶  HomePilot /avatar/session
                            (swaps the credential, pumps the rest)
```

No new URL and no second token: the browser presents OllaBridge's own credential, and the
proxy replaces it with HomePilot's key before forwarding. HomePilot's key never reaches the
browser.

**The proxy is a pipe, and MS8 asserts it in bytes.** OllaBridge reads exactly one frame — the
`hello` — and forwards everything after it verbatim. The tests there compare *strings*, not
parsed objects, because a proxy that round-tripped each frame through JSON would pass a
compare-the-dictionaries test while reordering keys and re-encoding the base64 audio chunk it
had no business touching. A separate test greps the proxy for meeting vocabulary and requires
there to be none: the moment it learns what a `meeting_audio` is, there are two implementations
of one protocol.

The **cloud path** — HomePilot on the operator's machine, unreachable from the bridge process —
rides the existing `sig`/`ev` relay with the raw frame as the payload *string*, which is what
keeps that same byte guarantee true on the path that is harder to watch.

### Two questions, two answers

| Question | Who answers | Where |
|---|---|---|
| "will meeting frames survive the trip?" | OllaBridge | `meetings` in `/health`'s avatar feature list |
| "will this server accept a meeting from there?" | HomePilot | `remote_ok` on `/v1/meetingsense/status` |

`remote_ok` is `enabled AND ready AND flags.remote` — one boolean rather than two flags for a
client to combine, because the flags deliberately do not imply each other and a client guessing
the relationship would guess wrong in the direction that matters: offering a control the server
will refuse. It is also false when nothing can transcribe, which is honest rather than
optimistic — a client told otherwise would start a meeting whose every audio frame is refused.

With `MEETINGSENSE_REMOTE` off, avatar-session meeting frames are refused **per frame**, not
just at start: a client that ignored the first refusal and carried on must not find a later
frame accepted. The refusal names what is true rather than the environment variable, because a
hosted client cannot set one on somebody else's machine. The local WebSocket is untouched by
this flag — W1 keeps working exactly as it did.

---

## The wire protocol

`WS /v1/meetingsense/session`. One connection is one meeting.

```
client → server   start · audio · keyframe · mute · ask · status · stop · ping
server → client   ready · partial · segment · slide · notes · answer · status · final · error · pong
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

## The same recorder over the avatar session

The batch MS2 was written for. A hosted page cannot open a WebSocket to `ws://localhost`, but
it already holds one to the avatar session — and OllaBridge already proxies that as a pipe. So
a meeting reaches a local HomePilot over a socket that already exists, with **no new URL and
no second token**.

```
client → server   {"v":1,"type":"meeting_start", "conversation_id":…, "audio":{…}}
                  {"v":1,"type":"meeting_audio", "format":"wav", "data_b64":…, "t0":…}
                  {"v":1,"type":"meeting_stop"}
server → client   {"v":1,"type":"meeting","meeting":{…}}     ← an MS3 frame, verbatim
```

**`PROTOCOL_VERSION` stays 1.** Three new client types and one server type, and every existing
peer is still correct — that is what §6.9's silent-ignore rule buys, and a bump would have made
this a breaking change for the avatar, the voice channel and the display panels too.

One outbound type carrying the MS3 frame untouched, rather than a flattened
`meeting_segment` / `meeting_status` / `meeting_final` family. A client that already renders
the local transcript works by reading `.meeting`, and a frame added by a later wave needs no
change to the contract at all.

### What this batch is *not*

It is not a second implementation. The core is MS2's `MeetingSession`, the audio decoding is
MS3's `audio.py`, and the per-frame split is MS3's own `_handle_audio`. What MS7 adds is a
`Transport` — two forwarding methods — and an envelope. The two transports therefore *cannot*
answer differently, because there is only one thing answering, and a test drives the same
script through both and compares frame for frame.

The bridge writes into the handler's outbox rather than the socket, because that socket already
has exactly one writer and a second is how interleaved frames and half-written JSON happen.
Closing a meeting never closes the avatar socket: it is also carrying the persona, the gestures
and possibly a spoken conversation.

### Two flags, not one

`MEETINGSENSE_REMOTE` is separate from `MEETINGSENSE_ENABLED` and neither implies the other. An
operator who wants meetings on their own machine has not thereby agreed to accept them from a
hosted page, so with the master flag on and the remote flag off an avatar-session meeting is
refused by name (`remote_disabled`) and no table is touched.

A dropped avatar socket **suspends** the meeting on MS3-a's grace window rather than ending it:
somebody on a hosted page loses their connection for the same reasons a local one does.

### The fixture set is shared with the client

`backend/tests/fixtures/protocol/` is byte-identical to `tests/fixtures/protocol/` in
`ruslanmv/3D-Avatar-Chatbot`, and `CHECKSUMS.txt` is the proof — each repo verifies its own
copy against the same manifest. Adding these four frames therefore had to land in **both**
repos in the same shape, and the server-side change went red until it did. That is the
mechanism working, not an obstacle to route around.

---

## How the pieces fit

Three modules under `backend/app/meetingsense/` carry everything a meeting is, and none of
them knows how it arrived. That separation is what lets the same recorder serve a local
WebSocket and a hosted avatar page without being written twice.

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

**`session.py`** — `MeetingSession`, `idle → live → suspended → ended`. A stopped meeting is a
record; a second `stop` is a no-op rather than an error, because both ends of a socket notice
a disconnect and both will try.

The load-bearing constraint is one line long:

> **`session.py` must never import FastAPI.**

MeetingSense runs over two transports — a WebSocket the browser opens directly, and the
avatar session OllaBridge proxies for a hosted page. A core that knows about either one has to
be written twice. So it knows about a `Transport` instead, which is `send`
and `close` and deliberately nothing else: the peer address, the negotiated capabilities,
whether the socket is still open are all knowledge the core would start branching on, and
branching on it is how one core becomes two. A test asserts the protocol has exactly those
two methods, and another reads `session.py`'s own source to check the import never appears.

Both transports are now built, and a test drives the same script through each and compares the
frames it produces. If that ever diverges, one of them has acquired its own copy of the core.

---

## Verifying an install

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
cd backend && python3 -m pytest tests/meetingsense -q   # 506
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
cd backend && python3 -m pytest tests/meetingsense/test_resume.py -q         # 50  (MS3-a)
cd backend && python3 -m pytest tests/meetingsense/test_export.py -q         # 59  (MS6)
cd backend && python3 -m pytest tests/meetingsense/test_avatar_bridge.py -q  # 46  (MS7)
cd backend && python3 -m pytest tests/avatar -q                              # the shared contract
cd ../ollabridge && python3 -m pytest tests/avatar -q                        # 61  (MS8: the pipe)
cd backend && python3 -m pytest tests/meetingsense/test_ask.py -q            # 45  (MS13)
cd backend && python3 -m pytest tests/meetingsense/test_keyframes.py -q     # 26  (MS9)
cd frontend && npx vitest run src/test/meetingsenseAddon.test.js            # 84  (MS4, MS4-a, MS9)
cd frontend && npx vitest run src/test/meetingsenseEntry.test.ts            # 39  (MS5)
cd frontend && npx vitest run src/test/meetingsenseCard.test.tsx            # 90  (MS6 + MS10)
```

MS4 also widened `frontend/vitest.config.ts` from `src/**/*.test.{ts,tsx}` to include `js` and
`jsx`. That glob had been quietly excluding **17 test files and 124 tests** — the whole
phone/call primitives suite among them — which had never run in CI since they were written.
All of them pass; nothing was fixed to make that true.

**W0, W1, W2 and W4 are complete, and W3 needs only MS11.** A meeting records, resumes,
transcribes, takes rolling notes, answers questions, summarises itself into History, exports,
deletes, works from a hosted page — and now captures its slides, captions them, and shows each
one beside what was said while it was up.

**Two wiring seams are open**, and it is worth being exact about which:

1. MS5's **Start session** calls an `onStart` callback and the host application decides what
   to mount it against. Everything it needs — the hook, the card, the pill, the consent sheet
   — exists and is tested. Deliberate.
2. **MS12's `NotesEngine` is not constructed by either transport.** `start` echoes
   `notes: true` back to a client, `MeetingSession` accepts a `notes=` engine and drives it
   correctly, and no route builds one — so no meeting has ever produced a `notes` frame. The
   engine and its 60 tests are right; the four lines that hand one to the session are missing.
   Found while wiring MS9's vision bridge through the same constructor, and left for whoever
   picks up MS10, which is the batch that renders what it produces.

---

## Design

- [`design/MEETINGSENSE_DESIGN.md`](design/MEETINGSENSE_DESIGN.md) — Part 1: capture,
  transcript, slide keyframes, notes.
- [`design/MEETINGSENSE_DESIGN_PART2.md`](design/MEETINGSENSE_DESIGN_PART2.md) — Part 2:
  Together mode, catalog, agent engine, MCP, helper modes.
- [`design/MEETINGSENSE_BATCHES.md`](design/MEETINGSENSE_BATCHES.md) — the implementation
  tracker, and **§1 lists the six places the design documents disagree with the source**.
  Read that before trusting a "we reuse X" claim in either design doc.
