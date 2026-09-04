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

In the desktop app on Windows, the recorder captures the machine's own output rather than
whatever the browser share dialog happened to offer (MS11).

Everything in the recorder works: rolling notes, a summary that carries its own recap and
decisions, asking a question about a meeting live or afterwards, export, and one-call deletion.

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
| `MEETINGSENSE_MODES` | `false` | Participant / Coach / Presenter / Practice, and MS25's chips |

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

### System audio in the desktop app (MS11)

In a browser, `getDisplayMedia({ audio: true })` gets the call's audio only when the user
shares a **tab** and ticks a box. A window share carries no audio anywhere, and on Linux a
whole-screen share carries none either — so on the platforms where most meetings happen, the
browser recorder often records one side of the conversation.

The Electron shell can answer that request itself, with `audio: 'loopback'` — the machine's own
output, which is everything the user hears.

**On Electron 33 that is Windows only, and the popover says so.**

| | what is recorded | what the popover says |
|---|---|---|
| Windows, flag on | the call **and** the microphone | "The call's audio and this microphone are both recorded." |
| Windows, flag off | browser rules | "Desktop system audio is off … turn it on in Settings." |
| macOS | the microphone | "macOS cannot share system audio … install a virtual audio device (BlackHole or Loopback)." |
| Linux desktop | the microphone | the same, without the workaround |
| any browser | browser rules | the existing per-platform notices |

macOS has no public API for capturing system output. Every product that appears to do it ships
a kernel extension or asks for a virtual audio device, and HomePilot is not going to install a
kernel extension quietly. Saying the option exists would be worse than saying it does not: a
user who believes the call is being recorded and finds out afterwards that it was not has lost
the meeting. So the macOS sentence names the workaround rather than stopping at "unsupported",
and "off on Windows" and "impossible on macOS" are two different messages — the first is
advice the user can act on and the second would be advice that does not help.

**The flag is off, and off means nothing is registered.** `MEETINGSENSE_DESKTOP_AUDIO=true`, or
`meetingSenseDesktopAudio` in the desktop store. Installing a display-media handler changes what
*every* screen share in the app does, ScreenSense's included, so a desktop build with this off
behaves exactly as it did before the batch — and a test asserts that nothing is registered.

The decisions live in `desktop/meetingsense-audio.js`, which deliberately does not
`require("electron")`: everything is injected, so the platform table above is unit-tested in
Node. Loopback capture itself cannot be — that is rows 13 and 14 of the manual matrix.

### Searching across meetings (MS15)

MS13 answers a question by keyword-scoring the meeting's own rows. That works, and it stops
working at the point people start asking the questions worth asking: *"when did we last talk
about the vendor contract?"* is a question about six meetings, and *"what did they decide about
pricing?"* needs a passage that shares no words with the question.

So **on stop, a meeting is embedded** — after the client already has its `final` frame, so the
time it takes is time nobody waits on, and swallowing every failure, because the transcript is
in SQLite and that is the copy that cannot be rebuilt.

**A meeting is retrieved from, never absorbed into a project (D4).** The vectors live in a
Chroma namespace of their own — `meetings_…`, never `project_…` — so
`get_project_document_count`, `query_project_knowledge` and `delete_project_knowledge` cannot
see them. Somebody who records a call must not watch their project's document count jump, and
a persona answering from project knowledge must not quote a meeting nobody attached. Attaching
one is a deliberate act, and MS16's route for it is the existing upload path.

`vectordb.py` gained one thing for this: a `namespace` parameter whose default produces the
byte-identical collection name it always produced. A test asserts that against a **fixed hash**
rather than against the expression that builds it — an assertion written as
`f"project_{md5(...)}"` passes for any change made to both sides at once, and what is at risk
is a collection already sitting on somebody's disk.

**What gets embedded is decided by rules, not by a model** (D9's pre-compaction pruning):

- consecutive segments are windowed into paragraphs of ~120 words. A segment is eight seconds
  of speech and often half a sentence; embedded alone it is a fragment that matches nothing;
- segments under three words are dropped — "yeah" and "mm-hm" are most of a meeting's segments
  and none of its content — but the same words *inside* a paragraph are kept, because cutting
  them out would embed a transcript nobody said;
- a slide shown twice is embedded once, by dHash; the image never, the caption always.

**Both retrievers run, interleaved by rank.** Embeddings find the passage that answers a
question in words the question did not use; keyword scoring finds the exact token somebody
actually asked about — a part number, a name, "the four-one-two figure". Neither is trusted
alone. They are interleaved by rank rather than merged by score, because a cosine distance and
a length-normalised term count share no scale and sorting one list by both is arithmetic that
means nothing. During a live meeting the vector side is simply empty — indexing happens on
stop — so the live path is exactly what MS13 shipped.

**Delete now means three stores.** Rows, files, and vectors. A meeting removed from SQLite but
left in the index still answers questions after the user deleted it, which is the worst
available reading of "delete" and the one nobody would notice until a persona quoted it back.

**No Chroma is not a broken meeting.** An install without the package records, transcribes,
captions and exports exactly as before; search returns nothing and the keyword tier answers.

### Getting back into a meeting (MS16)

A meeting ends and the useful part starts. Three ways back in, all reusing conversation
machinery that already exists — no meetings tab, no second inbox, no new job type.

**Reopen the chat it was recorded in.** `GET /v1/meetingsense/conversations/{id}` returns the
meetings a conversation can rebuild a card for, with the counts already in the row so a
collapsed card needs no second call. The pairing is recorded in `ms_threads` when the meeting
**starts**, not when it stops: a meeting interrupted by a server restart should still bring its
card back, and nothing on a chat message says which meeting produced it.

**New thread from this meeting.** `POST /v1/meetingsense/{id}/thread` mints a conversation and
writes a brief into it. The brief is deliberately not the summary message: that one is written
where the reader has just been in the meeting, and this one opens a conversation whose reader
may be a week late with no context. So it leads with what is *still open* — unresolved
questions, unfinished actions — and ends with a line saying the transcript is searchable,
without which the reader's first message is "can you see the meeting?" rather than a question
about the meeting. It is written as an **assistant** message, so History labels the new thread
with the meeting it came from before anybody has said anything in it.

**Attach to a project.** `POST /v1/meetingsense/{id}/attach` writes the Markdown export into
the upload directory and hands it to `vectordb.process_and_add_file` — the same function the
project upload button calls. That is the point rather than a shortcut: the project already
knows how to extract, chunk, embed and list a Markdown file, so **this needs no new job type**.
It is also the only route by which a meeting reaches project jobs. Being recorded does not put
a meeting into a project (D4); somebody deciding it should be does.

The file is named `meeting-<title>-<id8>.md` and listed in the project's own files, because it
lands beside the user's own uploads and a uuid there is a row nobody can decide whether to
delete.

Two more tables — `ms_threads` and `ms_artifacts` — and the delete path clears both, on the
same rule as the other three: a thread row left behind hydrates a card for a meeting that no
longer exists.

### Naming a meeting without asking (MS17)

Nobody types a title before they hit record. They are already in the call, somebody is
talking, and the dialog asking what to call this is the reason the recording did not start. So
a meeting is named *afterwards*, from two sources that cost the user nothing.

**The shared window's title**, which the browser hands over for free as
`MediaStreamTrack.label` — `"Q3 planning | Microsoft Teams"`. One string carrying both the
meeting's name and the platform it ran on, with no network call, no permission and no
dependency. Empty on Firefox and Safari, which is a fine answer.

**A calendar event**, when `google_calendar` or `microsoft_graph` is connected through MCP,
which adds the attendees, the join link and a title somebody actually chose.

Both run *after* `ready` is sent, as a background task, and the result arrives as a `meta`
frame. A calendar round trip before `ready` is a dialog-free start turned back into a wait, and
the recording is what the user pressed the button for.

Two rules keep this from being worse than nothing:

- **A title the user gave always wins.** Auto-metadata fills a blank; it never corrects a
  person. Somebody who typed "1:1 with Ana" and got "Microsoft Teams" back would stop typing
  titles, and would be right to.
- **An empty answer is not an answer.** A calendar that matched nothing, a window title that
  was only the app name, an MCP call that timed out — each leaves the meeting as it was rather
  than blanking what is there. `"Zoom Meeting"` yields no title, because it is the absence of a
  name: written in, every Zoom call in History looks identical.

Two details that are easy to get wrong and were:

- **Markers match on word boundaries.** "Cisco Webex Meetings" contains "meet", and a substring
  test tags every Webex call — and every shared document called "Meeting notes" — as a Meet
  call. Underscores are normalised for matching, because a regex counts `_` as a word character
  and a person reads it as a space.
- **The longest surviving part is the name.** Teams titles a call
  `"<current speaker> | <meeting> | Microsoft Teams"`; taking the first part would name the
  meeting after whoever happened to be talking when recording started.

An event *containing* the start beats a nearer one outright — twenty minutes into an hour-long
call you are in that call — and only then does proximity decide, inside fifteen minutes. Ties
break on the shorter event, because on a day of overlapping invitations the specific one is
more likely to be the call than the all-day block around it.

Auto-metadata may only write `title`, `source`, `attendees` and `link`. An allow-list rather
than "whatever the caller passed": this is fed by a calendar event and a window title, neither
of which the user typed, and a metadata path that can set any column is one bad MCP answer
away from rewriting a meeting's conversation or its retention mode.

The window-title half is unit-tested against real titles. The calendar half is tested against
an injected invoker; a live MCP connection is **row 16 of the manual matrix**.

### What a persona knows about the meeting happening now (MS18)

Together mode is a person talking to a persona *while* a meeting runs — "what did she just say
the number was?" — and the whole feature is one block prepended to the system prompt. Everything
hard about it is what that block may **not** contain.

**The transcript is not it.** HomePilot's chat path passes `get_recent(cid, limit=6)` and drops
everything older; that limit is not touched by this batch. A three-hour meeting is perhaps
30,000 words, and a block that grows with the meeting turns every question in the second hour
into a truncated prompt — an answer confidently wrong about the part that got cut. So the block
is **D9 tiers 1 and 2 only**: the last 90 seconds verbatim, the slide on screen now, the rolling
notes, and the recap. Everything older reaches the persona through MS15's retrieval, cited, when
it is asked for.

**900 tokens, enforced.** The same constant MS13 answers under, and the same trim order:
verbatim first (oldest line first), then the notes lists, and **the recap never**. A model with
the recap and no verbatim can still say what the meeting has been about; one with the verbatim
and no recap knows the last thirty seconds of a three-hour call and nothing else.

**Off is byte-identical.** With no live meeting, with the `together` flag down, or on an install
where MeetingSense raises, `build_system_prompt` returns character-for-character what it
returned before this batch. Asserted, not assumed — a context provider that quietly changes
every prompt changes every persona in the product. `build_system_prompt` gained one optional
`conversation_id` argument, and every existing caller that omits it is unaffected.

The block tells the persona what it cannot see, in as many words. Without that a model asked
"what did she say?" answers about the last thing in *its* window — which is the chat, not the
meeting — and cites a timestamp it invented.

### Recording from the 👥 launcher (MS19)

MeetingSense is the eighth activity in the avatar client's Together launcher —
`3D-Avatar-Chatbot`, `src/features/together/activities/meeting.js` — and almost none of it is
new code. B11 there owns the consent and the revoke; this addon owns the audio graph, the
segmenter, the socket and the transcript.

**The recorder does not open its own capture there.** That page has exactly one call site for
`getDisplayMedia` and `getUserMedia`, and a test reads every other file to prove it. So the
addon grew a second entry point, `startWithStreams({screen, mic}, options)`, which is `start`'s
path from the graph onwards — same segmenter, same socket — with somebody else having asked
the browser. `start()` is unchanged, and is still what the HomePilot page uses, where there is
no launcher and no consent machine.

The consent machine gained a `meeting` compound source: the screen, then the microphone, in
that order, because the screen is the dialog a user is most likely to cancel and somebody who
declines it should not already have granted a microphone they now have no use for. Revoking
stops the recorder synchronously — the epoch makes every grant read dead in the same tick, and
a revoke that waits on a network round trip is a revoke that has not happened yet.

### The card on the avatar surface (MS20)

A third *renderer*, not a third source. The same store rows become a `display` message of the
existing `cards` kind, drawn by the avatar client's own panel renderer — no new channel for it
to learn, and a `meeting_panel` frame on the avatar session asks for one.

**A panel is a screen, not a document.** The channel caps a panel at 64 KB and a `cards` panel
at twelve rows, so a four-hundred-segment meeting arrives as a **summary projection**: what the
meeting is, what was decided, what is still open, what is on screen — and at most the last two
lines spoken, so a live panel does not look frozen. The transcript is never rows; the web card,
the export and `ask` are all better at it.

The row cap is **read from `panels.MAX_ROWS`**, not retyped, so a change to the renderer's cap
cannot leave this sending panels that get refused. Cards are built in the order they matter and
truncated from the end, so the first rows a reader glances at are the same ones whether the
meeting is a minute or three hours old — a panel that reshuffles as it grows is one nobody can
glance at.

`panels.build` is what decides whether a panel is legal, and it is called rather than
reimplemented. A panel it refuses is dropped: the meeting is recording either way, and a card
that could not be drawn is not a reason to send an error into a live session.

### A meeting as tools (MS21)

`agentic/integrations/mcp/meetingsense_server.py`, port **9107**, ten tools:
`hp.ms.list_meetings`, `get_meeting`, `get_transcript`, `search`, `get_live_context`,
`get_slide`, `update_action`, `suggest`, `set_mode`, `export`. `make start-meetingsense` runs
it; `stop-meetingsense` and `health-meetingsense` do what they say.

**The prefix is `hp.ms.`, not the design document's `ms.`.** `test_agentic_health.py` requires
every Forge tool prefix to start with `hp.` — that is what stops a virtual server's allow-list
from admitting a namespace nobody registered — and a tested repo-wide invariant beats a design
document's shorthand. The `ms` segment stays, so `hp.ms.search` still reads as MeetingSense's
search, and the design doc's `ms.search` should be read as naming this.

**Nothing here computes anything**, which is the point of the batch landing last. Every tool is
one HTTP call to the backend — the way `inventory` does it — because the MCP image contains
`agentic/` and no `backend/`, so importing the meeting store would work from the Makefile and
fail in the container. MS21 added the four routes that did not exist yet:
`GET /v1/meetingsense/meetings`, `/search`, `/conversations/{id}/live`, and
`POST /{id}/notes`.

**Reads are open; the four writes are gated** behind `WRITE_ENABLED`, with the same wording
`local-notes` uses, so an operator who has seen one refusal recognises the other. Reads need no
gate: a meeting is the user's own recording on the user's own machine, and the server is not
reachable from outside it.

Three smaller decisions worth knowing:

- **`get_meeting` returns counts, not rows.** A "get" that returned the transcript would make
  `get_transcript` and its 200-segment cap pointless.
- **`get_slide(at_ms=…)` is the last slide taken at or before that moment**, not the nearest —
  on a deck clicked through quickly the nearest is often the one the speaker had not reached.
- **A suggestion is recorded beside the notes, not merged into them.** A suggestion is what an
  agent thinks; the notes are what the meeting said, and merging them makes the meeting's own
  record unciteable.

Every tool answers "MeetingSense is not available on this install" rather than raising when the
backend is off, absent or has the flag down — a persona can pass that on and cannot pass on a
tool error. A *missing meeting* is told apart from a missing install, because those are two
different sentences.

### Finding it: Forge, the catalog, and Teams (MS22)

MS21 built a server; MS22 is what makes anything find it. Four registration points, each a
file a human edits and therefore a file a human forgets:

| where | what |
|---|---|
| `agentic/forge/seed/seed_all.py` | `hp-meetingsense`, 9107, so the seeder registers its tools |
| `agentic/forge/templates/gateways.yaml` | the gateway pointing at `localhost:9107/rpc` |
| `agentic/forge/templates/server_catalog.yaml` | the tile, marked `write_gated` |
| `agentic/forge/templates/virtual_servers.yaml` | `hp-meetings-readonly` and `hp-meetings-all` |

The read-only bundle excludes the four write tools **as well as** the server gating them: the
gate is the operator's decision and the bundle is the persona's, and a suite named read-only
that could call `hp.ms.export` would be misnamed. A test builds the exclusion list from the
server's own tool definitions, so a fifth write tool cannot quietly appear in it.

The **Chief-of-Staff** A2A agent now asks `hp.ms.search` when a question is about meetings, and
puts the answers in their own bullet — meeting rows carry a `meeting · hh:mm:ss` citation and
workspace hits do not, and a reader who cannot tell them apart cannot check either. Best-effort,
like the workspace search beside it: with MeetingSense unseeded the briefing reads exactly as
it did before.

**Teams tier 2 is paused, and says so.** The batch offered two ways — build the thin `hp-teams`
server, or mark tier 2 unavailable and make the UI say so rather than fail at click time. This
takes the second, because the catalog entry for `hp-teams` already declares an *external*
source (`github.com/ruslanmv/teams-mcp-server`), and a local server behind the same id would
put two implementations behind one identifier.

Marking it only mattered because something now reads the mark: the catalog loader dropped
unknown keys, so `availability` and `unavailable_reason` were added to `ServerDef`, are always
present in the API, and `install()` refuses with the reason. Without that, the tile looked like
every other one and failed on a timeout while starting a process for a module that is not
there. Meetings record, transcribe, caption and export without it; what is unavailable is
posting back into the Teams chat.

### The agent engine, and the five modes (MS23)

`backend/app/meetingsense/agent/`, behind `MEETINGSENSE_AGENT` (default off). With the flag
off nothing here is reached and the fixed notes loop in `session.py` runs exactly as before.

The batch's acceptance is one sentence: **in Note-taker mode the graph's output is identical to
the fixed loop's.** That is checkable only because D8 keeps memory outside the graph — if a node
could remember something the loop could not, the two would diverge on the second turn and no
test could say which was right. So `reflect` makes `session._maybe_notes`'s three calls (`add`,
`due`, `run`) in the same order on the same engine, `recall` wraps MS15 and `answer` wraps MS13
rather than re-deciding their budgets. A test reads the source of `_maybe_notes`, so the loop
this suite copies cannot silently drift from the one that ships.

Eight nodes — `perceive reflect decide answer coach act recall deliver` — and the topology is
**data**: `NODES`, `EDGES` and one conditional router. Two things execute it. LangGraph where it
is installed, and a twenty-line walker where it is not. Two schedulers for one set of behaviour
is a real cost, taken deliberately: `langgraph` is in `requirements.txt` but not on every
install, and `langgraph_personas/graph_builder.py` imports it at module scope — which is why its
whole suite is one of the eighteen that cannot be collected here. A graph that cannot be
imported cannot be tested, and this batch's acceptance *is* a test. One test drives both engines
over the same events and asserts the same frames and the same trace.

**Modes are policy objects, not prompt fragments.** `modes.py` is a table of five allow-lists —
note-taker, participant, presenter, coach, practice — and every node asks it rather than
deciding for itself. Note-taker is the floor and the default, and an unknown name resolves
*down* to it: a typo, a stale client or a mode a later wave removes should quiet the assistant,
never hand it tools.

### Two sub-agents, and what a meeting has approved (MS24)

`agent/subagents.py`. Two jobs that are genuinely separate from the main loop, and the policy
that decides what either may reach.

**SlideReader** turns a captioned keyframe into a record the notes can carry — title, claim, at
most three topics. Separate from `reflect` because it reads one artefact and produces one
record, and folding that into the rolling-notes prompt is how a notes engine starts describing
slides that were never shown. A re-shown slide is recorded as a *return*, not a second reading:
MS9's dHash already decided that a slide back on screen is the same slide.

**ActionExtractor** pulls owners and deadlines out of a window of transcript. Separate for the
opposite reason — it is the one job here that benefits from being wrong cheaply. An extractor
that proposes six actions and has four rejected is useful; a notes engine that does the same is
a notes engine nobody trusts. With no model configured it falls back to one deliberately narrow
pattern ("Ana will send the terms") and misses everything else, which beats a regular expression
guessing at intent.

**Neither writes anything.** They return proposals; `reflect` folds them in through MS12's
`merge`, which never deletes and dedupes on the item text, so a proposal that repeats what the
engine already found costs nothing and one it missed is kept. An extractor that wrote directly
would be a second author of one record.

#### The mode is server state

`hp.ms.set_mode` writes a name; every turn afterwards **reads it back from the store**. A mode on
the wire, per turn, would let a client put a meeting into Practice for one request — and that is
not a mode, it is an escalation. A `mode` arriving with a turn is treated as a *default*, used
only for a meeting nobody has set, and when it disagrees with what is stored the stored one
governs and the disagreement is reported into `errors` rather than dropped, so a client that
thinks it is driving finds out that it is not.

The mode lives in `ms_artifacts` rather than on a session object because it has to survive a
reconnect, a server restart and a second client attaching to the same meeting.

**An unreadable policy store lands on the floor, never the ceiling.** "Nothing was ever set" and
"we cannot tell what was set" are different answers, and only the second has to fail closed: if
they were collapsed, a store outage would be the cheapest way to get a meeting into Practice.

#### Two gates, and they are different questions

A mode says whether tools may be used **at all** — that is policy. A per-meeting pre-approval
says **which** tools, for **this** meeting — that is consent. Collapsing them would mean somebody
who picks Practice has silently agreed to whatever tools the install happens to have.

So both are checked, and both are closed until something opens them. `approved_tools=None` is a
`Deps` nobody filled in, and `act` reads it exactly as it reads `[]`: approve nothing. The one
place a caller should build dependencies for a live meeting is `graph.deps_for(meeting_id)`,
which reads the approvals from the store — there is no reason for a caller to hold that list,
and passing one a client sent is precisely the escalation this exists to prevent.

Approving is additive and revoking is a separate call, because "also allow this" and "stop
allowing that" are different intentions and a set-replacing API turns the first into the second
whenever a client forgets to resend the old list. A revoke is **recorded**, not deleted: what a
meeting was allowed to do, and when that changed, is the thing an audit reads. A refused call is
recorded too — a tool call that vanishes silently is one nobody can approve, because nobody
knows it was wanted.

Approvals live in `ms_artifacts`, so the delete that removes everything else about a meeting
removes these as well. A consent that outlived its meeting would be a consent nobody could
withdraw.

### Chips: what the meeting offers to do (MS25)

`backend/app/meetingsense/chips.py` and `frontend/src/ui/meetingsense/ChipRow.tsx`, behind
`MEETINGSENSE_MODES` (default off). A chip is a small dismissible offer on the card — *that
looked like a decision*, *there is a date in that sentence*, *the slide has a link*.

**Every trigger is deterministic. Nothing here asks a model.** A chip interrupts: it appears
while somebody is talking and *because* of what they just said, so a chip that is wrong is not
a bad summary the user scrolls past — it is the assistant visibly misunderstanding the room, in
front of the room. MS12's notes can afford to be occasionally loose because they are read
afterwards; a chip cannot.

That buys a trade, stated once: **these triggers miss.** The tests that matter are the ones
that must *not* fire, and they are collected in one list because they are the acceptance
criterion:

| Trigger | Fires on | Stays quiet on |
|---|---|---|
| `question` | a question somebody else asked *you* | a question **you** asked; a question to the room ("what time is the release?"); verbal commas ("does that make sense?", "can you hear me?") |
| `decision` | "we're going with the second option" | asking about deciding ("so we're going with the second option?"); "we have not decided" |
| `action` | "Ana will send the revised terms" | "who will send the terms?"; "so Ana will send the terms?"; "someone will"; "we will see"; "I will try"; "Ana will **not** send" |
| `date` | "by Friday", "2026-04-20", "March 3" | `monday.com`; `example.com/2026-04-20/notes`; a bare weekday ("it has been a long Friday"); "version 3.2" |
| `link` | a URL **on a slide** | a URL somebody read out; `node.js`; `report.pdf`; `ana@example.com` |

Two of those rows are one line of code between them. URLs are stripped — schemes *and* bare
hosts — before any other trigger reads the text, because `monday.com` is a weekday to any
pattern that has not been shown the address. And a bare host on a slide is deliberately **not**
a link: requiring a scheme or `www.` misses `monday.com` written plainly on a slide, and that is
the right miss, because the alternative opens `report.pdf` in a browser.

A slide's link comes from the **caption**, not from the keyframe: a URL is only "on a slide"
once something has read the slide. An install with no vision model gets slides and no link
chips, which is the honest outcome — nothing read the screen.

#### Ask-before-acting, in the order the words are in

A chip may carry a **proposal** — "Add to calendar", "Add to tasks", "Summarise this page" — and
a proposal is a description until somebody presses the button. Rendering runs nothing. Only
`accept` runs anything, and it has three gates that can each say no:

1. The chip has a proposal at all. A `question` chip has nothing to run; the card already has a
   way to ask.
2. The **runtime tool router** resolves the capability inside the project's allow-list —
   `agentic/runtime_tool_router.py`, never a second resolver here. A second allow-list that
   disagrees with the one Forge enforces is a security control that is wrong half the time.
3. MS24's **per-meeting approval** covers the tool the router picked — checked on the *resolved
   tool id*, after the router has spoken, because that is what will actually be invoked.
   Approving the capability name would approve a name and run whatever the catalog maps it to.

Both a refusal and a run are recorded in `ms_artifacts`. A tool call that vanishes silently is
one nobody can approve, because nobody knows it was wanted.

**An id crosses the wire, never a chip.** The server offered the chip and still holds it, so
`chip_action {id}` is all the client sends and what runs is what was shown. Accepting a body
would let whatever is on the page rewrite the arguments between the offer and the acceptance —
ask-before-acting asking about one thing and acting on another. The server ignores a `chip` a
client sends anyway, and the addon never sends one.

Dismissal is the mirror image: **local, and not a deletion.** One reader saying "not interested"
is not a fact about the meeting, so nothing goes to the server and no record changes.

Chip ids are derived from the offer rather than from a counter, so a reconnect replaying
segments — or a second client on one meeting — produces the same row on both cards rather than
two rows on one. Three chips are shown at once, newest first, and a meeting stops at forty:
past that the card is a list, and a list is what the notes already are.

### Participant and Presenter (MS26)

`backend/app/meetingsense/agent/` — `mode_prompts.py`, `participant.py`, `presenter.py` — plus
two new columns on `modes.py`. Behind `MEETINGSENSE_MODES`, default off.

MS23 made a mode an allow-list of what it *may* do. That is half of what a mode is; MS26 adds
the other half — what it sounds like, and which of MS25's offers it makes — and adds both as
**rows in `modes.py` rather than branches in the graph**. Participant and Presenter differ by
data, not by an `if`.

| | note-taker | participant | presenter | coach | practice |
|---|---|---|---|---|---|
| answers to its own name (`addressed`) | — | ✅ | — | ✅ | ✅ |
| speaks unbidden (`proactive`) | — | — | ✅ | — | — |
| collects for the user (`queues`) | — | — | ✅ | — | — |
| offers a `question` chip | — | ✅ | — | ✅ | ✅ |

**`addressed` and `proactive` are different permissions**, and Participant is deliberately the
first mode with one and not the other. Being addressed is a *prompt*: somebody said the
assistant's name and asked it something, and the question arrived down the microphone instead
of down the socket. Speaking unbidden is not.

**`queues` and `addressed` are exclusive by construction**, which is why Presenter has neither
`addressed` nor a `question` chip. While the user is presenting, a question from the floor is
theirs to take, and an assistant answering it out loud is the single thing this mode exists to
prevent — so it is collected instead, and a `queued` frame lets the card show a count. A number
changing is not an interruption.

#### Answering to your own name, and drafting for somebody else's

Two behaviours that look alike and are opposites, which is why they live in one file.

Somebody says *"Ana, what did we decide about pricing?"* and Ana is the assistant → it answers,
through MS13 like every other question. Somebody says *"Ruslan, what did we decide?"* — or just
*"what do you think?"* — and Ruslan is the **user** → it drafts a reply and hands it over on the
chip. Answering that aloud would be the assistant speaking for the person the room believes it
is talking to.

The line between the two is a name, so names are declared at `start` (`names` for the user,
`assistant_names` for the assistant) and never guessed. **With no `assistant_names` declared,
nothing fires** — the failure mode of guessing is answering to somebody else's name in front of
them. A name is matched as a whole word: "Ana" is not in "analysis" and not in "Anahita", and a
one-letter name is refused outright, because it would match most sentences.

A question that names the assistant is answered and **not** also drafted: two answers on screen
for one question leaves the user working out which one is live. And a draft is offered far more
often than not — the prompt asks the model to reply `PASS` when the meeting does not support an
answer, a reply over sixty words is discarded, and a draft the user has to rewrite is slower
than answering themselves.

#### Mode prompts layer, they never replace

A mode's framing goes **above** MS13's `ASK_SYSTEM`, never in place of it. The base carries
*cite the timestamp* and *never invent one*, and those are not a Participant's to relax; putting
them last also gives them the final word in the prompt, which is the position a model weights
hardest. With no mode set the system prompt is byte-identical to what MS13 shipped, and an
unknown mode gets no framing rather than somebody else's — the same direction `modes.resolve`
falls in. Note-taker has no framing at all, because it never answers and dead text in a prompt
file is text a later reader assumes is live.

#### The deck, the clock, and the queue

`POST /v1/meetingsense/{id}/deck` takes `[{"title": …, "minutes": …}]`. **Attached, not
inferred**: pacing built on a guess is wrong the first time it matters, and then the mode gets
turned off.

**A section is a window, not an instant.** It was meant to start when the previous one ended and
to finish at its own planned time, and anywhere inside that window is on time. Comparing against
the end alone makes the first minute of a ten-minute section read as *"eight minutes ahead"* —
the pacer telling a presenter who is exactly where they planned to be that they are early.
Below two minutes of drift it says nothing at all: every presenter drifts, and being told so is
a clock.

`GET`/`POST /v1/meetingsense/{id}/queue` read the audience queue and take a question off it.
Deduped on the text, because a question asked twice from the floor is what happens when the
first asking was not heard. Taking one off is **recorded, not deleted** — what was asked and
when it was dealt with is what an after-the-fact read of a meeting is for — and a question can
be asked again afterwards.

### Coach, and the screen it must never read (MS27)

`backend/app/meetingsense/agent/coaching.py`, behind `MEETINGSENSE_MODES`.

Coach draws talking points **strictly from prep material the user uploaded** — the brief they
wrote, the questions they expect, the numbers they want to land. `POST /v1/meetingsense/{id}/prep`
attaches a document; `DELETE` takes it back out, and that one is a **real delete** rather than
the recorded withdrawal MS24's approvals and MS26's queue use. Those are a history of consent
and of what was asked. This is the user's own document, and "take my brief out of this meeting"
that leaves the brief in the database has not done what it said.

**With no prep material, Coach says nothing at all.** It has nothing to draw a talking point
from, and the alternative — improvising from the transcript — is the thing this mode is defined
as not doing.

#### The refusal, enforced three ways

MeetingSense captures keyframes and a vision model captions them; that is how it knows a slide
said "Q3 revenue is flat". The capability is for the user's **own** slides in Presenter. Pointed
at a Coach it becomes something else: a coach that can read the screen can read the other
participants' documents, their open tabs and their messages, in a meeting where nobody agreed to
that and where the user cannot see what was captured either.

The design document refuses it. A refusal in a design document is a sentence until something
enforces it, so:

| | what it catches |
|---|---|
| **allow-list** | `context()` assembles from two named sources and there is no branch that reaches a keyframe |
| **`scrub()`** | drops any row carrying a slide's fingerprint, so a caller that hands over a mixed list cannot smuggle one in |
| **source test** | reads the module and fails if it so much as mentions a keyframe — catching the edit nobody has written yet |

Three gates for one rule is more than a rule usually gets. This one earns it: the failure is
silent, nothing looks wrong, the coaching just gets better — and the people it affects are not
in the room and would never know. `scrub` is deliberately generous about what counts as coming
off the screen: being wrong in that direction costs a line of transcript, and being wrong in the
other direction is the failure the whole file exists to prevent.

### Practice, through the voice stack that already exists (MS27)

`agent/practice.py`. Practice plays the other side — the interviewer, the examiner, the
sceptical customer — and it runs as a **voice call** rather than growing a second voice stack
inside MeetingSense.

`voice_call/` already owns turn-taking, streaming, resume tokens, the policy that decides who
may open a call, and `barge_in.py`. **The policy check is theirs**: `create_session` gates on
entitlement, and a MeetingSense path that skipped it would be a second door into the same room.
The resume token it returns is deliberately *not* echoed back — its own docstring says callers
must keep it out of anything that lands in a log, and a meeting frame is a thing that lands in a
log.

**Barge-in is the feature, not a nicety.** In an interview the interesting moments are the
interruptions. `interrupt()` goes straight to `voice_call/barge_in.py`, whose `cancel_active`
refuses a stale `turn_id` so an interruption racing a new turn is a silent no-op rather than a
turn cancelled by accident. MeetingSense keeps no turn state of its own — a second answer to "is
the assistant still talking" would disagree with the first exactly when it mattered.

`POST /v1/meetingsense/{id}/rehearsal` sets the shape (`interview`, `exam`, `pitch`,
`negotiation`), who the assistant plays, and what to push on. A bare shape is enough: demanding
a paragraph before the user can start is how a rehearsal feature goes unused.

### Speaking into the meeting: TTS and the virtual microphone (MS27)

`agent/voice_out.py`. Practice needs its voice in the **call**, not on the user's speakers, and
a browser tab cannot do that — it can play audio, and the meeting's microphone will not hear it
unless the operating system routes it there.

So this is **desktop only**, through a virtual audio device the user installs: VB-Cable on
Windows, BlackHole on macOS, a PulseAudio/PipeWire null sink on Linux. `GET
/v1/meetingsense/voice-out` answers with a named reason rather than a bare boolean, because the
two "no"s need completely different things from the user:

| reason | what it means |
|---|---|
| `browser` | wrong app. Nothing to install would help, so nothing is offered |
| `no_virtual_device` | right app, missing driver. Comes with the install steps for this platform |

**It never falls back to the speakers.** A rehearsal partner audible in the room but not in the
call is a feature that appears to work and does not, which is worse than one that says it needs
a driver.

The setup wizard's last step is a **check**, not a congratulation. A setup flow that ends on
"you're all set" without verifying is how somebody arrives at a mock interview with no sound and
no idea which of four steps did not take — and on Windows the answer is usually "the restart".

**The TTS tier is `providers.py`'s choice, not MeetingSense's.** That module's own words: the
quality tier is a server-side choice, never a client change. `get_tts_provider` takes an
entitlement and returns the neural voice where one is configured; this passes that through and
picks nothing itself. A MeetingSense-specific voice selection would be a second place deciding
what a user is entitled to, which is the shape of every entitlement bug. Citations are stripped
before synthesis: `[00:12:30]` is right on a card and unreadable out loud.

### The mode on the pill, and in the consent sheet (MS27)

§2a says recording state is unmissable, and a mode changes what a recording is *for*. A pill
saying only "recording" while the assistant is about to speak aloud into the call would be
accurate and would hide the part that matters. So the mode is a badge on the pill — inside the
`role="status"` live region and **not** `aria-hidden`, because a screen-reader user has no badge
to glance at. Note-taker is unlabelled: a badge that is always there is one nobody reads, which
would cost it its meaning in the four modes where it matters.

The consent sheet gains a sentence per mode, in the mode's own terms — Coach says where its
suggestions come from *and where they do not*, and Practice says plainly that everyone in the
meeting will hear it. Note-taker's copy is byte-identical to what MS6 shipped, and every mode
still ends on the one thing the user has to do: tell the other people they are recording.

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
| 13 | Desktop app, Windows | flag on, any share | `audioMode: 'system+mic'`, the call audible in the transcript | ⬜ |
| 14 | Desktop app, macOS | flag on | `mic` only, and the popover says why before recording starts | ⬜ |
| 15 | Desktop app, either | flag off | ScreenSense's "Ask once" unchanged; no share dialog behaves differently | ⬜ |
| 16 | Any | a real `google_calendar` / `microsoft_graph` connection | the meeting takes its title, attendees and link from the event that contains its start | ⬜ |
| 17 | Desktop app, Windows | VB-Cable installed, **before** restarting | the wizard's check still fails, and says the restart is why | ⬜ |
| 18 | Desktop app, Windows | VB-Cable installed and restarted | the check passes and names `CABLE Input`; Practice is audible to the other participants | ⬜ |
| 19 | Desktop app, macOS | BlackHole + a Multi-Output Device | the check passes; the user hears the rehearsal **and** so does the call | ⬜ |
| 20 | Desktop app, either | Practice speaking, user talks over it | the voice stops mid-sentence — barge-in, end to end through `voice_call/` | ⬜ |
| 21 | Browser | Practice mode | the wizard says the desktop app is needed and offers no driver and no retry | ⬜ |

Rows 1–3 are the ones that decide whether MeetingSense records a meeting at all; row 10 is the
one a short test cannot substitute for. **Rows 17–21 are MS27's, and rows 18–20 are the ones
nothing automated can reach**: whether audio actually arrives in somebody else's meeting is a
question about two drivers and a conferencing app, and `detect` only proves this code recognised
a device name. Row 20 in particular — barge-in heard by a person, not asserted on an
`asyncio.Event` — is the difference between a rehearsal partner and a podcast. Row 11 is the only place the thresholds meet a real
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
| `GET /v1/meetingsense/conversations/{id}` | the meetings a chat can bring a card back for (MS16). Never errors; empty with the flag off |
| `POST /v1/meetingsense/{id}/thread` | open a new conversation from this meeting, with a brief (MS16) |
| `POST /v1/meetingsense/{id}/attach` | push the transcript into a project's knowledge base (MS16) |
| `GET /v1/meetingsense/meetings` | recent meetings, or one conversation's (MS21) |
| `GET /v1/meetingsense/search` | MS15's retrieval, cited (MS21) |
| `GET /v1/meetingsense/conversations/{id}/live` | MS18's bounded live block (MS21) |
| `POST /v1/meetingsense/{id}/notes` | amend an action, leave a suggestion, or set a mode (MS21) |
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
client → server   start · audio · keyframe · mute · ask · chip_action · status · stop · ping
server → client   ready · partial · segment · slide · notes · answer · chip · chip_result · queued · status · final · error · pong
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
cd backend && python3 -m pytest tests/meetingsense -q   # 706
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
cd backend && python3 -m pytest tests/meetingsense/test_retrieval.py -q     # 37  (MS15)
cd backend && python3 -m pytest tests/meetingsense/test_binding.py -q       # 33  (MS16)
cd backend && python3 -m pytest tests/meetingsense/test_metadata.py -q      # 72  (MS17)
cd backend && python3 -m pytest tests/meetingsense/test_notes_wiring.py -q  # 11  (MS12-a)
cd backend && python3 -m pytest tests/meetingsense/test_live_context.py -q  # 26  (MS18)
cd backend && python3 -m pytest tests/meetingsense/test_panel.py -q         # 21  (MS20)
cd backend && python3 -m pytest tests/test_mcp_meetingsense_rpc.py -q       # 48  (MS21)
cd backend && python3 -m pytest tests/test_mcp_meetingsense_registration.py -q  # 18  (MS22)
cd frontend && npx vitest run src/test/meetingsenseAddon.test.js            # 90  (MS4, MS4-a, MS9, MS19)
cd ../3D-Avatar-Chatbot && npx jest tests/behavior/meeting.test.js           # 21  (MS19)
cd frontend && npx vitest run src/test/meetingsenseEntry.test.ts            # 55  (MS5 + MS11)
cd frontend && npx vitest run src/test/meetingsenseCard.test.tsx            # 90  (MS6 + MS10)
```

MS4 also widened `frontend/vitest.config.ts` from `src/**/*.test.{ts,tsx}` to include `js` and
`jsx`. That glob had been quietly excluding **17 test files and 124 tests** — the whole
phone/call primitives suite among them — which had never run in CI since they were written.
All of them pass; nothing was fixed to make that true.

**W0 through W7 are complete.** A meeting records, resumes, transcribes, takes rolling notes,
answers questions, summarises itself into History, exports, deletes, works from a hosted page,
captures its slides, captions them, shows each one beside what was said while it was up, and on
Windows in the desktop app records the call itself rather than whatever the share dialog offered.

Beyond that it remembers: a finished meeting is embedded and searchable across every meeting
ever recorded, reachable from any chat, branchable into a new thread and attachable to a
project — and it names itself.

What is left before the pilot can be signed off is not code: the sixteen-row matrix below,
none of which anybody has run.

**One wiring seam is open**, and it is worth being exact about which:


1. MS5's **Start session** calls an `onStart` callback and the host application decides what
   to mount it against. Everything it needs — the hook, the card, the pill, the consent sheet
   — exists and is tested. Deliberate.


---

## Design

- [`design/MEETINGSENSE_DESIGN.md`](design/MEETINGSENSE_DESIGN.md) — Part 1: capture,
  transcript, slide keyframes, notes.
- [`design/MEETINGSENSE_DESIGN_PART2.md`](design/MEETINGSENSE_DESIGN_PART2.md) — Part 2:
  Together mode, catalog, agent engine, MCP, helper modes.
- [`design/MEETINGSENSE_BATCHES.md`](design/MEETINGSENSE_BATCHES.md) — the implementation
  tracker, and **§1 lists the six places the design documents disagree with the source**.
  Read that before trusting a "we reuse X" claim in either design doc.
