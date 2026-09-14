# Voice — speech to text, text to speech

How HomePilot turns your speech into text and its replies into audio: the paths, the
endpoints, the failure modes that used to be silent, and how to debug them.

**What works today:** hands-free Voice mode, the chat composer microphone, and three
self-tests in Settings → Voice Assistant. Speech-to-text records the microphone you selected
and transcribes it on the machine running HomePilot; the browser's own recognizer is kept as
a fallback for servers with no speech provider configured.

---

## 1. The problem this design exists to solve

Two microphone consumers could not agree on a device.

| Consumer | Which microphone it opens |
|---|---|
| HomePilot's VAD, the Settings recording test, `MediaRecorder` | the `deviceId` selected in **Settings → Audio & Video** |
| The browser's `SpeechRecognition` (Web Speech API) | **the operating system's default input** — the API accepts no `deviceId` |

When those are two different microphones, the level meter moves while a device nobody is
speaking into gets transcribed. The browser reports **no error** for this, so the turn simply
ends with no text. The reported trace looked like:

```
[HomePilot:Mic][vad]   capture_opened   {label: 'Microphone Array (2- Intel...)', ...}
[HomePilot:Mic][vad]   speech_detected  {level: 0.07614, threshold: 0.07374}
[HomePilot:Mic][voice] stt_onstart      {recognitionDevice: 'browser-managed-web-speech'}
[HomePilot:Mic][vad]   speech_ended     {speechMs: 1389, silenceMs: 805}
[HomePilot:Mic][voice] stt_stop_requested {reason: 'vad_silence'}
[HomePilot:Mic][voice] stt_onend        {hadResult: false}
```

No interim, no result, **no error**. There were three compounding causes:

1. **The device split above.**
2. **Recognition was killed during warm-up.** Chrome needs a few hundred milliseconds to open
   its own capture and stream before it emits anything. Starting it on `vad_speech_start` and
   stopping it ~400 ms after the VAD's silence window finalized an empty session — cleanly,
   which is why not even `no-speech` was raised.
3. **Both captures were open at once.** Hands-free Voice started the VAD *and* the browser
   recognizer, whatever the resolved engine was. The VAD holds the selected microphone for
   the whole session; the recognizer opens the OS default on its own. So the split in (1) was
   not an edge case on the browser engine — it was the normal path, every turn.

All three are fixed, and the fix for (1) and (3) is architectural:

> **The resolved engine owns the microphone, alone.**
>
> `web-speech` → the browser recognizer is the only capture. No VAD, no recorder, no meter.
> `homepilot-backend` → HomePilot's VAD and recorder are the only capture, sharing one
> stream. No recognizer.
>
> `media/sttRuntime.ts` holds that one decision and the single microphone lease, so the chat
> composer and the Voice tab cannot disagree about either, and switching engines is a release
> followed by an acquire rather than two live captures.

---

## 2. The two speech-to-text paths

**Which one runs is the user's choice, not a detection.** Settings → Voice Assistant →
**Speech Recognition** sets it for chat and the Voice tab; the default is the browser.

Preferring the local engine whenever it reported itself *available* is what broke chat
speech-to-text on a machine whose CUDA runtime was present but incomplete: the provider
answered "available" and then failed every single turn, while the browser path would have
worked. **Availability is not suitability** — only the person using it can weigh privacy
against latency against setup. So the preference decides and the capability only constrains.

| Preference | Runs |
|---|---|
| **Browser** (default) | The browser's recognizer. Falls back to the local engine only where no recognizer exists (Firefox, Safari). |
| **On this computer** | The local engine. Falls back to the browser when no model is installed or the browser cannot record — **and says so**. |
| **Automatic** | The local engine when genuinely usable, the browser otherwise. |

`resolveSttEngine()` in `media/sttPreferences.ts` is the whole rule, and it is pure: every
combination of preference and capability has a defined answer, and a test walks all of them.
`media/sttRuntime.ts` applies it **once per session** and both surfaces subscribe, so the
"one choice for chat and Voice" the Settings card promises is one object, not two copies.

> **Nothing opens a capture before it resolves.** Until the probe answers, `effectiveEngine`
> is `null` and every surface waits (`handsfree_waiting_for_engine`, `stt_engine_pending`).
> Standing in with the browser "for now" is what sent the first sentence of a session — the
> one that matters most — through an engine the user did not choose.

> **And nothing opens a capture it can already tell will be deaf.** `SpeechRecognition`
> records the OS default input. When the microphone chosen in Audio & Video is a *different*
> device, a browser turn records a microphone nobody is speaking into and reports no error —
> it faithfully transcribed a silent room. `describeMicrophoneRouting` could see that from
> the device list all along, and Settings has been *warning* about it for several batches
> while chat and Voice opened the capture anyway and learned it from two failed turns.
>
> The preflight in `sttRuntime.decide()` now moves such a session to the local engine before
> the first turn, gated on `routing.known` (no `default` alias to compare against is not
> evidence of agreement) and on `backendUsable`. It is announced, never silent, and
> **re-picking an engine in Settings disarms it** — otherwise "Browser" would be unselectable
> for the session on any machine whose default input differs, which is the choice being taken
> away rather than a default. Trace: `stt_runtime_resolved {reason: 'routing-mismatch-preflight',
> routingMismatch, routingKnown}`.

> **When the device list cannot tell, a turn's verdict stands in — and is remembered.**
> Chrome on Windows often exposes no `default` alias, so on those machines the split is real
> and undetectable up front. The only thing that establishes it is a turn: press record,
> speak, and the recognizer reports it opened a capture and heard nothing.
>
> Paying for that discovery once is reasonable; paying for it on every page load is not, and
> that is what happened — each reload started a fresh session, offered the browser recognizer
> again, and burned the user's first sentence proving the same fact. The verdict is now kept
> in `homepilot_stt_deaf_recognizer_v1`, **keyed by the microphone it was reached about**, so a
> different device is re-evaluated and choosing an engine in Settings clears it. Trace:
> `stt_runtime_resolved {reason: 'recognizer-known-deaf'}`.

> **A fallback is always reported.** Somebody who chose on-device transcription for privacy
> and is quietly served the browser's — which ships audio to Google — has been failed in a way
> no later message makes up for. `resolution.fellBack` carries that, the chat composer shows
> a notice, and Settings says *"Not the engine you chose"*.

Meetings are **not** part of this choice — see §3.5.

### 2.1 `homepilot-backend` — the local engine

```
selected microphone ──► getUserMedia(deviceId) ──► MediaRecorder ──► POST /v1/voice/transcribe
                                                                            │
                                                              get_stt_provider().transcribe()
                                                                            │
                                                                        transcript
```

The bytes transcribed are, by construction, the bytes captured from the selected input. The
split cannot happen.

In hands-free Voice mode the recorder attaches to **the VAD's own stream**
(`vad.getStream()`), so detection and transcription are literally the same capture — not two
captures that happen to agree. The level meter reads that same stream, which is why it is
honest here and unavailable on the other engine.

### 2.2 `web-speech` — the default

What HomePilot behaved like before local transcription existed, and what needs no setup. The
device caveat from §1 applies — it records the OS default input — and the UI says so rather
than letting you assume otherwise. The warm-up stop guard (§5) applies here.

**No VAD runs on this engine.** The recognizer opens its own capture and can be handed
neither a `deviceId` nor a `MediaStream`, so a VAD alongside it would be a second microphone
nobody transcribes — cause (3) in §1.

**Hands-free runs one continuous session**, which is what makes the transcript read like a
live caption:

```
start({continuous: true})
   ├── onInterim … onInterim … onInterim     ← the caption, updating as you speak
   ├── onResult  "turn on the kitchen lights" ← a finished phrase, sent; session stays open
   ├── onInterim …                            ← the next sentence, already arriving
   └── onEnd (Chrome ends periodically) ──► wait 400 ms ──► start
          ▲                                                    │
          └────────── aborted while TTS speaks ◄───────────────┘
```

A **one-shot** session ends at the first pause, so hands-free was a series of short
recognitions with a restart between each. Two things follow from that, and both were visible:
the caption died at exactly the moment somebody was mid-sentence, and Chrome raised
`no-speech` every few seconds of a quiet room — which surfaced as a red banner under the orb
on a session that was working perfectly.

So `no-speech` and `aborted` are classified as **benign**: the first is Chrome saying nobody
spoke, which is the normal state of waiting, and the second is HomePilot taking the microphone
back for TTS or a hand-off. Neither is a fault and neither reaches `lastError`.

A manual press stays one-shot. It has a Stop button behind it, and a session that outlived the
turn would hold the microphone after the user believed they had released it.

Interim text is dropped while the assistant is speaking: the recognizer cannot separate
HomePilot's own output from the user, so anything arriving then is either its voice coming
back or a barge-in it has already mangled.

What that costs and what it buys:

| | `web-speech` | `homepilot-backend` |
|---|---|---|
| Live words while you speak | **yes** — one continuous session, `interimText` | no — text arrives at end of turn |
| Input level meter | **no** — HomePilot has no stream to read | yes, the transcribed one |
| Barge-in (speak over the reply) | no — listening stops while TTS plays | yes, the VAD watches through it |
| Microphone used | OS default | the one selected in Audio & Video |

A meter is not drawn on the browser engine, and the UI says why
(`data-testid="voice-meter-unavailable"`). Opening a second microphone purely to animate a
bar is exactly the two-capture bug, so a missing meter is the honest outcome.

Listening stops while the assistant speaks because the recognizer has no way to tell
HomePilot's voice from the user's, and leaving it open feeds the reply back in as the next
turn. `bargeInSupported` reports that rather than leaving it silently absent.

It is also the automatic fallback whenever the local engine cannot run.

### 2.2.1 One recognizer, one owner

`media/webSpeechSession.ts` is the only place a `SpeechRecognition` session is started. A
page can run exactly one at a time, and HomePilot used to have two: the Voice tab drove
`window.SpeechService` while the chat composer constructed its own. The composer knew and
aborted the shared session before taking a turn — but nothing did the reverse, so a
recognizer started in chat could outlive the composer and fail the next Voice turn with a
bare `InvalidStateError`.

Now `startWebSpeech(owner, handlers)` drops the previous session first and events are
delivered only to the owner current *when they arrive* (a generation check), so a stale
`onend` from a handed-off session cannot end somebody else's turn.

### 2.3 When the browser recognizer goes deaf

The device caveat has a failure mode that reports nothing at all. If the OS default input is
silent — unplugged, muted, a disconnected headset still holding the default slot — the
recognizer records that silence and considers the turn a success. No error, no result:

```
[HomePilot:Mic][voice] stt_onend {hadResult: false, sawAudioStart: true, sawSpeechStart: false}
```

Meanwhile HomePilot's own VAD, which *does* honour the selected microphone, heard the user
perfectly well — it is what opened the turn. The orb reacts to the voice, the turn ends, and
nothing comes out. This is the bug report *"it recognizes my voice however does not send"*.

`frontend/src/ui/media/sttTurnHealth.ts` catches it by comparing the two captures.
`isDeafTurn()` is true only when the recognizer's capture **opened, stayed open, and heard
nothing** — every other shape is a different fault with a different fix and is excluded:

| Turn signals | Verdict | Why |
| --- | --- | --- |
| `sawAudioStart: true`, `sawSpeechStart: false`, no result | **deaf** | the routing split |
| a transcript, or `sawInterim` | fine | the device works |
| `sawSpeechStart: true`, no result | not deaf | wrong language, or a stop that cut the turn |
| `error` set | not deaf | `not-allowed` / `network` / `audio-capture` name themselves |
| `sawAudioStart: false` | not deaf | the capture never opened: permission or device |
| signals absent (`undefined`) | not deaf | not observed ≠ did not happen |

**The verdict is only worth having if the recognizer was given its chance.** HomePilot's VAD
calls time on the turn from *its* microphone, and the recognizer is on a different one, so
that verdict is not evidence this turn is over — honouring it guarantees an empty turn and
leaves "was it deaf, or did we cut it off?" unanswerable. So a non-forced stop is held while
the recognizer has captured audio and heard no speech, up to `STT_NO_SPEECH_GRACE_MS` (5 s).
Turns that heard *anything* — `speechstart`, interim words, a result — are unaffected and stop
on the VAD's silence as before, so a working recognizer is never slowed down. A forced stop
(turn lock, teardown, the user pressing stop) always wins, and `STT_MAX_LISTEN_MS` still caps
everything. The trace says which guard held it: `stop_deferred_warming_up {deferredBy}`.

**How many deaf turns it takes depends on who opened them**, because they are not the same
kind of fact:

| Turn | Threshold | Why |
|---|---|---|
| The user pressed record, spoke, pressed stop | **1** | A person is asserting they said something. A second turn only costs them another turn to learn what the first proved. |
| Opened automatically (the hands-free loop) | **never counts** | No VAD runs on the browser engine, so nothing says anybody was talking. "The recognizer heard nothing" there is the ordinary sound of a quiet room, and counting it would switch engines under every user who paused. |
| Opened by the VAD on the local engine | 2 | The old rule, kept: one deaf turn is a cough, two in a row is a device. |

That middle row is the one that matters most. The hands-free browser loop opens a turn every
400 ms whether or not anybody is speaking; feeding those to the detector would have moved
every session off the browser engine within two seconds of silence.

Once the threshold is met, `planSttRecovery()` decides:

- **backend usable** → the session moves to `homepilot-backend`, which records the selected
  microphone, and a notice says so and where to change it back;
- **backend not usable** → a notice naming both ways out: make that microphone the system
  default input, or install a speech model and choose *On this computer*.

**There used to be two possible causes; now there is one.** While hands-free held HomePilot's
capture open during browser turns, a second explanation produced an *identical* trace: some
drivers (Windows DSP-backed inputs among them) hand a second recorder on the same endpoint a
live but silent track. The notice had to name both, plus a test to separate them. Exclusive
ownership settles it — nothing else holds the microphone during a browser turn — so the
notice names the routing split and stops there. `planSttRecovery()` still takes
`homepilotHoldsMicrophone`, read from the lease rather than assumed, so the diagnosis stays
honest if that ever stops being true.

Three rules it keeps deliberately:

- **Never silent.** The switch changes which service sees the audio — the browser recognizer
  sends it to Google, the local engine keeps it on the machine. Voice mode renders the notice
  above the voice bar (`data-testid="voice-stt-notice"`), the composer in `micNotice`.
- **Never permanent.** The stored preference is the user's. The recovery holds for the
  session and is discarded the moment the preference changes.
- **Never one-sided.** It is applied to the shared runtime, so a deaf recognizer discovered
  in chat moves the Voice tab too. The same person with the same microphone should not have
  to rediscover the same broken device on the other tab.

It is an emergency fallback, not the mechanism that makes Voice usable. With the engines
exclusive, a correctly configured session should never reach it.

Trace: `stt_deaf_recognizer_recovery {action, deafTurns, backendUsable}` (and
`composer_mic_deaf_recognizer_recovery` in chat).

### Which one am I on?

Settings → Voice Assistant states it in plain text, and the trace records it once per
session:

```
[HomePilot:Mic][settings] stt_runtime_resolved {engine: 'homepilot-backend',
                                                provider: 'whisper-local',
                                                remote: false,
                                                usesOsDefaultInput: false}
```

And the shape of a healthy session says which engine owns the microphone, because only one
family of events appears:

```
Browser + Voice          Local + Voice
──────────────────       ────────────────────────────
stt_runtime_resolved     stt_runtime_resolved
microphone_acquired      microphone_acquired
web_speech_start_…       vad capture_request / capture_opened
stt_onstart              recorder_started {engine: 'homepilot-backend'}
stt_result               stt_transcribe_result
(no vad capture_request) (no web_speech_start_requested)
```

Seeing `vad capture_opened` and `stt_onstart` in the same session is the old bug, and the
capture-ownership tests exist to keep it out.

---

## 3. Endpoints

### `GET /v1/voice/stt/status`

Never 404s and never 500s: collapsing "not installed" into an error is what makes a client
retry forever instead of falling back.

```bash
curl -s localhost:8000/v1/voice/stt/status | python3 -m json.tool
```

```json
{
  "available": true,
  "provider": "whisper-local",
  "remote": false,
  "remote_configured": false,
  "device": "cpu",
  "hint": null
}
```

- `available` — whether anything can transcribe at all.
- `provider` — `whisper-local`, `openai-compat`, or `null` (the no-op provider, which is what
  you see on a machine with neither installed nor configured).
- `remote` — **the recording leaves this machine.** Surfaced so the UI can say so *before*
  you speak.
- `hint` — what to do about it when `available` is false; `null` when it is true.

### `POST /v1/voice/transcribe`

Multipart, so a `MediaRecorder` blob posts as-is instead of being inflated by a third.

```bash
curl -s -X POST localhost:8000/v1/voice/transcribe \
  -F "audio=@turn.webm;type=audio/webm" | python3 -m json.tool
```

```json
{
  "text": "turn the lights on",
  "provider": "whisper-local",
  "remote": false,
  "format": "webm",
  "bytes": 18422,
  "elapsed_ms": 412
}
```

The container is taken from an explicit `format` field, else derived from the upload's MIME
type (Chromium sends `audio/webm;codecs=opus`, Safari `audio/mp4`), else assumed `webm`.

| Status | Means |
|---|---|
| `200` with `text: ""` | **Success.** The clip contained no speech. A different fact from a failure, and the one the old path could not report. |
| `400` | Empty upload, or undecodable base64. |
| `413` | Over the clip ceiling — 25 MB, or `VOICE_TRANSCRIBE_MAX_BYTES`. |
| `503` | No speech provider on this server. Body carries `capability` and `hint`; the client falls back to Web Speech. |
| `502` | The provider itself failed (missing ffmpeg, model load error). Message included. |

### `POST /v1/voice/transcribe/base64`

Same thing from a JSON body (`{"data_b64": "...", "format": "wav"}`), matching the frame shape
`WS /v1/voice/session` already speaks.

> **Not behind `VOICE_BACKEND_ENABLED`.** That flag guards server-side LLM+TTS *orchestration*
> (`WS /v1/voice/session`, which answers with a reply and synthesized audio). These routes only
> turn recorded bytes into text. Gating them would leave the web client with no alternative to
> the device split in §1, which is the bug. `status` reporting `available: false` is the
> mechanism for "off".

---

## 3.5 Meetings are a different path — read this before debugging them

Meeting transcription does **not** go through anything in §2 or §3. It is a separate
subsystem, deliberately:

| | Meetings | Chat / Voice |
|---|---|---|
| Recorder | `frontend/public/js/homepilot-meetingsense.js` (AudioWorklet, its own VAD) | `media/sttService.ts` |
| Transport | `WS /v1/meetingsense/session`, continuous frames | `POST /v1/voice/transcribe`, one clip |
| Sources | `getDisplayMedia` (PC/tab audio) **+** `getUserMedia` (your mic), kept as two channels into a `ChannelMerger` so the server can label speakers | one microphone |
| Provider | `get_meeting_stt_provider()` — **local-first, never crosses to a remote endpoint on its own** | `get_stt_provider()` — prefers `STT_BASE_URL` when set |
| Engine choice | **None — there is one engine.** Settings reports it | The user picks: browser, on this computer, or automatic |
| Live text | **Yes** — `partial` then `segment` | per turn, no interim on the backend path |

That provider split is a privacy decision, not an oversight: somebody who set `STT_BASE_URL`
months ago for voice calls should not thereby have every hour of meeting audio shipped
offsite. `meeting_stt_policy()` reports which rule is in force.

### How live meeting text works

The recorder cuts audio into utterances on silence and sends each as a `wav` frame. Closing
an utterance needs a 350 ms pause (`SILENCE_CLOSE_MS`) — or, for somebody speaking without
pausing, the 8 s hard cut (`HARD_CUT_MS`). Eight seconds of blank screen while a person is
plainly talking reads as broken.

So the open utterance is *also* sent early, every ~1.2 s (`PARTIAL_EVERY_MS`), with
`partial: true`. The server's `on_partial` transcribes it, emits a `partial` frame and
**stores nothing**; the card shows that text greyed and replaces it when the real segment
lands. `Segmenter.takePartial(tMs)` produces the snapshot, and copies the frames — the array
it comes from keeps growing as the person talks.

Three rules stop provisional text from costing the transcript that gets kept:

| Rule | Why |
|---|---|
| Sent **straight down the socket**, never through `_queue` | The queue makes a dropped connection free; that is exactly wrong here. A partial arriving after its own utterance closed would overwrite real text with a stale guess. Sent if it can go now, dropped if not, never counted in `behind_ms`. |
| **One in flight at a time** | The next read waits for the previous reply, so a CPU-only machine throttles itself to what it can keep up with instead of queueing work it will never finish. `PARTIAL_TIMEOUT_MS` is the release valve, because the server stays silent when a provisional read finds no words. |
| **Never while `_queue` is non-empty** | Real audio is already waiting; provisional text must not jump its own transcript. |

`hpMeetingSense.partialsDisabled = true` turns live text off. The transcript still arrives,
one utterance at a time — it is a throughput dial, not a feature flag.

### Media capture — shared audio that never stops

A shared YouTube tab, a video in a deck, music. Every assumption the recorder makes comes
from *conversation*, and continuous audio breaks all three:

| Assumption | What continuous audio does |
|---|---|
| Utterances close on a 350 ms pause | Never closes; every one is an 8 s `HARD_CUT_MS`, so 8 s becomes the whole cadence |
| Partials are cheap | Re-read a growing buffer ~6× per chunk ≈ **4× realtime** decoding per 1× of audio; a CPU-only box cannot keep up |
| Quiet means nobody is talking | A quiet passage sits under `SILENCE_RMS`, so nothing opens and that audio is **never registered** |
| Falling behind is survivable | `shedQueue` drops the oldest **real** utterance once nothing is silent — silent content loss |

So continuous audio gets its own cadence, switched into automatically:

- **Detection** — `MEDIA_STREAK` (2) consecutive hard cuts, i.e. ~16 s of unbroken audio. One
  hard cut is just a long sentence; switching on it would chop up anyone who talks at length.
  A close on silence is the counter-evidence and switches straight back.
- **`MEDIA_HARD_CUT_MS` (2500)** — short fixed windows, still overlapped so the server dedupes.
  This is also the transcript's latency floor.
- **No partials** — a 2.5 s segment *is* live text; re-reading the same audio buys nothing.
  Skipping them is most of what makes continuous capture affordable: decoding becomes linear
  in the audio instead of quadratic.
- **`MEDIA_FLOOR_RMS` (0.0015)** — "is anything coming through", not "is somebody talking", so
  quiet passages are registered. Only essentially digital silence falls below.
- **`MEDIA_MAX_QUEUE_MS` (120 000)** — media capture promises a *complete record*; nothing in a
  shared video is a disposable cough, and a transcript that lags beats one with holes. There
  is still a ceiling, and reaching it fires `ms:audio_dropped` with `lostMs` rather than being
  absorbed into a counter.

> **The floor governs the close decision too, and it must.** With the speech threshold there, a
> quiet passage read as silence → closed the utterance → reset the streak out of media mode →
> and the audio then sat under the speech threshold again and was never registered. The mode
> oscillated and lost precisely the audio it exists to capture. Above the floor is *content*,
> so continuous quiet audio hard-cuts on cadence instead.

**Silent channels are not transcribed.** A stereo frame becomes two tracks and each costs an
inference — so a shared video with nobody talking spent half its budget returning `""` for the
microphone channel. The client measures the peak per channel while framing (it already
computes RMS for the meter), sends it as `energy: [them, me]`, and
`routes.py::_channel_is_silent` skips a track below `SILENT_CHANNEL_PEAK`. It is conservative
by construction: no hint, a length mismatch, or a non-number all transcribe everything. **A
hint is an optimisation and must never become the reason something went untranscribed.**

`ms:capture_mode` announces each switch, so shorter segments don't look like a glitch.

#### Notes when no language model is running

Transcription and note-taking are different subsystems with different dependencies, and an
install where Ollama is not up exercises exactly that seam. The transcript is unaffected — it
comes from the speech provider — but every notes window calls the model twice, so a stopped
model used to raise `httpx.ConnectError` twice a minute and answer each one with
`log.exception`. A half-hour meeting wrote sixty stack traces, and each buried whatever real
failure came next.

`classify_model_failure()` separates the two cases that were being conflated:

| | Nothing answered | Something answered badly |
|---|---|---|
| Example | `ConnectError`, `ConnectTimeout` | malformed JSON, a wrong-typed key |
| Is it a bug? | No — an ordinary state of a self-hosted install | Yes |
| Logging | one `WARNING` per outage, no traceback | `log.exception`, as before |
| Retried | after `MODEL_RETRY_AFTER_S` (60 s) | next window |

While a model is unreachable the engine reports `model_unavailable` on the `notes` frame and
stores it with the notes, so the meeting message can say *"No notes or recap: no language
model was reachable while this meeting ran. The transcript below was recorded and kept."*
rather than showing a header, a count, and nothing. It clears itself — and says so — on the
window where the model answers again.

> **An empty notes record is not a notes record.** `finalize` used to treat one as "there are
> notes", print the header and stop, and suppress the transcript preview that is the whole
> point of the fallback. `_has_note_content()` decides on content now.

#### The live workspace

Two things made a working meeting look broken:

- **The workspace opened on Timeline**, which renders decisions, slides and capture-source
  changes and *no transcript*. The words were arriving one tab away, so a live meeting showed
  "Meeting started" and nothing else, and the only way to learn it had been working was to end
  it and read the recap. It opens on **Transcript** now, and the tab carries a live line count
  so the Timeline no longer reads as silence.
- **The ended recap had no control on it.** The workspace is a full-screen portal, so
  "navigate somewhere else" was not an exit — whatever you would navigate with is underneath
  it. There is a **Close** button once a meeting has ended, and deliberately none while one is
  live: closing a live meeting would be a Stop that does not say it is stopping.

#### A meeting does not require a screen

The wizard has three independent capture toggles — **Meeting audio**, **My microphone**,
**Screen & slides** — and the recorder now honours all three. Untick the first and third and
`getDisplayMedia` is never called: no picker, no dialog, nothing to cancel. That is the whole
of a phone-on-the-table meeting — put the call on speaker next to the microphone, tick only
**My microphone**, and the transcript runs.

| `opts` | Effect |
|---|---|
| `audio: false`, `watch: false` | The display is never opened |
| `audio: false`, `watch: true` | Picker shown for the video; the call's audio is **not** recorded |
| `mic: false` | `getUserMedia` is never called — no microphone indicator, no prompt |
| both `audio` and `mic` false | Refused up front, rather than recording silence and revealing an empty transcript at the end |

Omitting an option still means yes, so every caller written before these were read behaves
exactly as it did.

#### One source means one speaker, and the transcript now says which

A meeting with a single audio source produces a **mono** WAV: the graph is one channel wide,
so `audio.tracks()` has no channel convention to apply and refuses to name the speaker. That
is the right call at that layer — one interleaved channel carries no evidence about who
produced it — but the session has the evidence anyway, and has had it since the `start` frame:

| `audio.mode` | Channels | Speaker |
|---|---|---|
| `system` | 1 | **them** — a display share alone is every word the other side's |
| `mic` | 1 | **me** — a phone-on-the-table meeting is every word yours |
| `system+mic` | 2 | the channel convention: channel 0 `them`, channel 1 `me` |
| anything else, or absent | — | unattributed, which is the honest answer |

`routes.py::_handle_audio` applies `audio.speaker_for_mode()` to a mono frame that nothing
else has named, in order of how much each source knows: the channel convention (evidence from
the bytes) beats the frame's own claim, which beats the meeting's single source.

Before this, every line of such a meeting arrived unattributed — shown as *"Speaker"* live,
and as *"Them"* in the meeting detail view, which was wrong about every line of a
microphone-only meeting. Nothing was lost from the transcript; the words were captured,
transcribed and stored correctly throughout. It is an attribution failure, and attribution
matters more in notes than in a transcript: *"you said"* and *"they said"* are what a recap is
built out of. The presenter queue, which only acts on what **them** said, also never fired in
a display-share-only meeting — the one shape where everything *is* them.

> **A worked example.** Open a tab that reads text aloud, tick **Meeting audio**, untick
> **My microphone**, and record. `audioMode` is `system`, the WAV is mono, and every line
> lands in the transcript labelled **Them**. No microphone is opened and no microphone
> indicator lights.

> **Known wart.** When system audio is wanted but slides are not, the display *video* track
> stays live, so the browser keeps showing its sharing indicator. Stopping that track can tear
> down the whole capture — including its audio — in some browsers, so it is deliberately left
> alone rather than fixed untested.

#### Names are what make a role more than a label

MS26's question detector keys on `names` and the assistant answers only to `assistant_names`.
Nothing in the frontend ever sent either, so **Participant mode — "answers when addressed;
drafts replies for you" — was inert in the product** regardless of what the user picked. The
wizard now collects both for the roles that use them (Participant, Presenter, Coach) and sends
them in the `start` frame, alongside the chosen `mode`.

- **People call me** → `names`. This is what turns "somebody just asked *you* something" from
  a guess into a fact, and what a `question` chip carries its draft on. Empty means the
  detector has only second person to go on, which is the narrow default: the failure mode of
  guessing is the assistant reacting to somebody else's name in front of them.
- **The assistant answers to** → `assistant_names`. Empty is the safe default; it then answers
  nobody out loud.

The `mode` is applied in `_begin` rather than by a follow-up request, because a meeting that
runs even briefly in the default mode has already missed the questions asked in that window.
An unknown mode name is ignored, never refused — the role picker must not be the reason a
recording fails to start.

#### What you can actually capture

| Share | Audio |
|---|---|
| Chrome/Edge **tab** + "Share tab audio" | ✅ |
| **Window** share | ❌ none, any browser |
| **Whole screen** | Windows/ChromeOS ✅, macOS ❌, Linux ❌ |
| Firefox / Safari | ❌ no `getDisplayMedia` audio |
| Mobile browser | ❌ no `getDisplayMedia` at all |
| **Desktop app, Windows** | ✅ `audio: 'loopback'` — everything the machine plays, no checkbox |
| Desktop app, macOS | ❌ no public API; needs a kernel extension or BlackHole |

`desktop/meetingsense-audio.js` is deliberately blunt about this: *"pretending the option
exists is worse than saying it does not — a user who believes the call is being recorded and
finds out afterwards that it was not has lost the meeting."*

> **Throughput.** 2.5 s segments at ~1× realtime is within reach of `small` on a decent CPU,
> but a long video plus a live conversation is two channels of continuous audio. If
> `ms:audio_dropped` fires, the machine is not keeping up: use `WHISPER_MODEL=large-v3-turbo`
> on a GPU, or accept the lag.

### The meeting microphone

The recorder reads `homepilot_media_preferences_v1` directly (`micConstraints()`) — it is a
classic script in `public/` and cannot import `media/mediaPreferences.ts`, so **the key and
the field names are the contract between the two**, and a test keeps them in step. It had
previously called `getUserMedia` with no `deviceId` and hardcoded `true` for all three
processing flags, which meant meetings recorded the OS default input and the Audio & Video
toggles did nothing for them.

`deviceId` is sent as `exact`, so an unplugged device fails loudly; the recorder then retries
on the default and emits `ms:mic_fallback` rather than letting you assume your headset is
being recorded.

> **Echo cancellation matters most here.** With system audio on speakers, turning it off puts
> the call's own voices into your microphone channel, and the server labels them as you.

### Editing the recorder

`frontend/public/js/homepilot-meetingsense.js` is **mirrored** at
`community/addons/meetingsense/homepilot-meetingsense.js`, and
`src/test/meetingsenseAddon.test.js` asserts the two have the same SHA digest. Change one,
copy it to the other, or that test fails.

---

## 4. Text to speech

There is exactly one runtime path, and **everything must use it**:

```
window.SpeechService.speak(text, callbacks)
        │
        └── wrapped by frontend/src/ui/tts/shimSpeechService.ts
                ├── engine === 'web-speech-api' → the original speechSynthesis path,
                │                                 voice from homepilot_voice_config
                └── otherwise                   → the plugin registry (Piper), and mirrors
                                                  svc.isSpeaking so VoiceController's
                                                  SPEAKING → IDLE transition still fires
```

`media/runtimeTts.ts` wraps that call and returns a **verdict** instead of a bare promise,
because `speechSynthesis` reports no error when it produces no audio: a missing voice, a muted
output, and a Chromium autoplay block all look like success. The only evidence available is
whether `onStart` ever fired.

| `failure` | Means |
|---|---|
| `unavailable` | `/js/speech-service.js` never loaded. |
| `disabled` | "Enable Text-to-Speech" is off. A setting, not a fault — reported differently. |
| `never_started` | Accepted the text, produced no audio. Usually output device, volume, a removed voice, or an autoplay block. |
| `engine_error` | The engine raised. Message carried through. |
| `timeout` | Started but never finished within `RUNTIME_TTS_MAX_MS`. |

### Two fixed mismatches

- **The preview spoke the wrong voice.** `TtsEngineSection` read `settings.voiceId` from the
  TTS-provider settings bucket, but for the default engine that section renders no voice field,
  so the key was never written. The Assistant Voice dropdown writes `value.selectedVoice`
  instead. `tts/resolveAssistantVoice.ts` now resolves through the keys the assistant actually
  reads, in order: engine bucket → `homepilot_voice_config.voiceURI` → `homepilot_voice_uri`.
- **The preview tested the wrong function.** It called `provider.speak()` directly, bypassing
  the shim and `homepilot_voice_config`, so it could pass while real assistant audio failed.
  Both previews now go through `speakThroughRuntime()`.

> **Known debt.** `window.SpeechService` is a mutable global monkey-patched by a shim that
> polls for up to 2 s waiting for its `<script>` tag. It is load-order dependent, untyped, and
> single-instance. The better end state is one typed TTS facade module that chat, Voice and
> Settings all import, with `SpeechService` demoted to an internal adapter. Until that exists,
> matching the tests to production is what makes them meaningful.

---

## 5. The warm-up stop guard

In `frontend/public/js/speech-service.js`, a `stopSTT()` arriving while recognition is still
warming up and has produced nothing is **deferred**, not honoured:

```js
STT_MIN_LISTEN_MS = 1600   // a stop before this, with no result yet, waits
STT_MAX_LISTEN_MS = 12000  // ceiling, so a silent recognizer cannot hold the turn open
```

Pass `{ force: true }` to stop immediately. Who forces and who does not:

| Caller | Forced? | Why |
|---|---|---|
| `vad_silence` | no | The VAD reaches silence on a short utterance before the recognizer has anything to finalize. This is the bug. |
| `manual_button` | **yes** | The user pressed Stop. Waiting would feel broken. |
| `turn_lock` | **yes** | The microphone must be released now; a locked turn must not keep recording. |

On the backend path there is no recognizer to warm up, so the guard does not apply — the
recorder gets a 250 ms trailing pad instead, which is what Chrome's own endpointer used to
provide.

---

## 6. Diagnostics — `HomePilot:Mic`

One ring buffer, one console prefix, five scopes. Filter DevTools for `HomePilot:Mic` and the
whole lifecycle appears in order.

```js
window.__HOMEPILOT_MIC_DEBUG__        // last 200 entries, oldest first
window.SpeechService.getSttDiagnostics()  // the most recent recognition turn
```

Scopes: `settings`, `chat`, `voice`, `vad`, `speech-service`.

> **Metadata only.** The trace records device and recognition state, character *counts*, and
> timings. Never audio bytes, and never transcript text. `speech-service.js` is a classic
> script served from `public/` and cannot import the TypeScript module, so it appends to the
> same buffer with the same entry shape — see `micTrace()`.

### Telling the three silent failures apart

`hadResult: false` alone names no cause. These four flags do, and each has a different fix:

| Evidence | Cause | Fix |
|---|---|---|
| no `sawAudioStart` | The recognizer never opened a capture. | Site microphone permission; another app holding the device exclusively. |
| `sawAudioStart`, no `sawSpeechStart` | It captured a **silent** device. | Almost always the OS-default split of §1. Make the microphone you speak into the OS default, or switch to the backend path. |
| `sawSpeechStart`, `sawNoMatch` | Heard speech, matched no words. | Recognition language — `SpeechService.setRecognitionLang('es-ES')`, stored as `homepilot_stt_lang`. |
| `sawSpeechStart`, no result, no `sawNoMatch` | Heard speech, returned nothing. | Cut off too early; see the guard in §5. |

### 6.1 The capture must not reopen on every render

`useVoiceController`'s hands-free effect opens the microphone. Anything in its dependency
list that changes identity per render restarts that effect — and because the restart calls
`setState`, the restart causes the next render. The result is not a slow loop but an endless
one:

```
handsfree_vad_start_requested {generation: 76}
handsfree_vad_cleanup         {generation: 76}
handsfree_vad_start_requested {generation: 77}
...
```

Callers pass `onSendText` as a plain function declared in their component body —
`VoiceModeGrok` does exactly that — so it is a **new identity every render**. A `useCallback`
that lists it is therefore also new every render.

So `startRecordingTurn`, `finishRecordingTurn` and `discardRecording` are all
**dependency-free**, reading the caller's handler through `onSendTextRef` and the mode through
`isHandsFreeRef`. `src/test/voiceControllerStability.test.tsx` asserts that invariant against
the source, because it is a property of the dependency lists rather than of any one render.

> **Rule of thumb:** nothing render-scoped may reach that effect's dependencies. If a turn
> handler needs a new value, feed it a ref.

### Recognition error codes worth knowing

`explainSttError()` in `media/voiceSelfTest.ts` turns each into an instruction:

- `network` — Chrome's Web Speech API sends audio to a **Google** speech service. Offline, it
  cannot work; the backend path can.
- `aborted` / `InvalidStateError` — a page can hold **one** recognition session. Another
  surface took it. This is why every surface calls `abortSTT()` before starting.
- `not-allowed`, `audio-capture`, `no-speech`, `language-not-supported` — permission, busy
  device, silence, unsupported language.

---

## 7. Settings → Voice Assistant self-tests

Each runs the path production uses, so a pass means voice works in chat.

| Test | What it proves |
|---|---|
| **Test speech-to-text** | Records one turn and shows the recognized text. On failure, names which of §6's causes it was. |
| **Test text-to-speech** | Speaks through `window.SpeechService` with the configured Assistant Voice, and fails when the engine never starts. |
| **Test speech → text → voice** | Records, transcribes, then reads the text back aloud. The only check that can fail for a reason neither half catches. |

**Stop and check** means *transcribe what I said*, not *discard it*.

Settings → Audio & Video keeps its 5-second record-and-play-back test, which proves the device
works, and now warns when the selected microphone is not the OS default — the condition that
breaks the Web Speech fallback. The warning is suppressed on the backend path, where there is
no split to warn about.

---

## 8. Where the code lives

### Backend

| Path | Role |
|---|---|
| `backend/app/voice/transcribe.py` | `POST /v1/voice/transcribe`, `/base64`, `GET /v1/voice/stt/status`, `stt_capability()` |
| `backend/app/voice/providers.py` | `get_stt_provider()` — `openai-compat` if `STT_BASE_URL` is set, else local Whisper, else null |
| `backend/app/voice/routes.py` | `WS /v1/voice/session` — server-side STT+LLM+TTS, flag-gated, untouched |
| `backend/app/main.py` | Mounts `voice_transcribe_router` unconditionally |

### Frontend

| Path | Role |
|---|---|
| `frontend/src/ui/media/sttService.ts` | Capability probe, `openSelectedMicrophone`, `transcribeBlob`, `recordAndTranscribe` |
| `frontend/src/ui/media/sttPreferences.ts` | The stored engine choice and `resolveSttEngine()` — the whole rule, pure |
| `frontend/src/ui/components/SpeechRecognitionSettings.tsx` | Settings → Speech Recognition: the choice, its cost, and what is actually running |
| `frontend/src/ui/media/runtimeTts.ts` | `speakThroughRuntime` + verdicts |
| `frontend/src/ui/media/voiceSelfTest.ts` | `explainSttOutcome`, `explainSttError`, `describeMicrophoneRouting` |
| `frontend/src/ui/media/microphoneDebug.ts` | The `HomePilot:Mic` ring buffer |
| `frontend/src/ui/media/mediaPreferences.ts` | Device selection, `buildAudioConstraints` |
| `frontend/src/ui/voice/vad.ts` | Adaptive VAD; `getStream()` shares its capture |
| `frontend/src/ui/voice/useVoiceController.ts` | State machine, one capture per engine, per-turn recorder |
| `frontend/src/ui/media/sttRuntime.ts` | §2 — the one engine decision and the one microphone lease, shared by chat and Voice |
| `frontend/src/ui/media/useSttRuntime.ts` | That runtime as React state |
| `frontend/src/ui/media/webSpeechSession.ts` | §2.2.1 — the only `SpeechRecognition` session, with an owner |
| `frontend/src/ui/media/sttTurnHealth.ts` | §2.3 — spotting a recognizer that hears nothing, and what to do about it |
| `frontend/src/ui/tts/resolveAssistantVoice.ts` | The three-key voice resolution of §4 |
| `frontend/src/ui/tts/shimSpeechService.ts` | Routes `SpeechService.speak` through the plugin registry |
| `frontend/src/ui/components/VoiceAssistantSelfTest.tsx` | The three self-tests |
| `frontend/src/ui/components/AudioVideoSettings.tsx` | Device pickers, record-and-play-back test |
| `frontend/public/js/speech-service.js` | Legacy global: recognition lifecycle, stop guard, `speak()` |
| `frontend/src/ui/App.tsx` | Chat composer microphone (`toggleListening`) |
| `frontend/public/js/homepilot-meetingsense.js` | Meeting recorder: system+mic capture, `Segmenter`, partials, `micConstraints()`. **Mirrored** in `community/addons/meetingsense/` |

### Tests

> **Before adding one: the test runner used to import the wrong file.**
>
> The source tree still carries stale `.js`/`.jsx` mirrors of modules that have since become
> `.ts`/`.tsx` — `voice/useVoiceController.js` is untouched since the first commit. Vite's
> default extension order puts `.js` *before* `.ts`, so a bare `import './voice/useVoiceController'`
> resolves to the mirror. `vite.config.ts` flips the order for exactly that reason;
> `vitest.config.ts` did not, so **the app was built from the TypeScript and the tests ran
> against the dead JavaScript.** A suite in that state passes and measures nothing.
>
> That is also why a jsdom harness written during the capture-loop work passed against code
> known to be broken: it was importing the mirror, which never had the bug.
> `vitest.config.ts` now carries the same `resolve.extensions` override. Keep the two in step
> until the duplicate source tree is deleted, at which point both become no-ops.

| Path | Covers |
|---|---|
| `backend/tests/test_voice_transcribe.py` | Both endpoints: formats, silence, limits, 503 fallback, 502 provider failure |
| `frontend/src/test/sttService.test.ts` | Capability caching and degradation, upload shape, error mapping |
| `frontend/src/test/runtimeTts.test.ts` | Runtime speech verdicts, including silence-as-failure |
| `frontend/src/test/speechServiceStt.test.js` | The stop guard and lifecycle diagnostics |
| `frontend/src/test/voiceSelfTest.test.ts` | Failure explanation, routing detection, voice resolution |
| `frontend/src/test/sttPreferences.test.ts` | The engine choice, every preference × capability combination, and the fallback wording |
| `frontend/src/test/voiceSendPath.test.tsx` | Transcript → `onSendText` on both engines; the manual button opens and closes its own capture |
| `frontend/src/test/sttTurnHealth.test.ts` | §2.3 — what counts as a deaf turn, and what each run of them does |
| `frontend/src/test/voiceDeafRecognizerRecovery.test.tsx` | The controller wiring: two deaf turns switch the session and say so; anything else does not |
| `frontend/src/test/voiceControllerStability.test.tsx` | Nothing render-scoped reaches the capture effect's dependencies |
| `frontend/src/test/sttRuntime.test.ts` | One engine for both surfaces; a session override; the microphone lease releases before it grants |
| `frontend/src/test/sttCaptureOwnership.test.tsx` | §1 cause (3): the browser engine opens no `getUserMedia`, the local engine starts no recognizer, and switching releases before it acquires |
| `frontend/src/test/voiceAssistantTesting.test.js` | Wiring contracts across all of the above |
| `frontend/src/test/microphoneDiagnostics.test.js` | The original diagnostics contract |
| `frontend/src/test/meetingsenseRealtime.test.js` | `takePartial` cadence and snapshot isolation, `micConstraints`, the three partial rules, media-capture mode |
| `frontend/src/test/meetingAudioOnly.test.tsx` | Capture sources honoured (no screen required), `parseNames`, the wizard's name fields |
| `backend/tests/meetingsense/test_silent_channel_skip.py` | The per-channel energy hint, and every way it must fall back to transcribing |

---

## 9. Configuration

| Variable | Effect |
|---|---|
| `STT_BASE_URL`, `STT_API_KEY`, `STT_MODEL` | An OpenAI-compatible transcription endpoint. **Recordings leave the machine** — reported as `remote: true`. |
| `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE` | Local faster-whisper. `auto` grants a GPU whenever CTranslate2 can see one, and **raises at load time if the CUDA runtime is incomplete** — so the load is retried on CPU rather than turning "slower" into "speech-to-text is broken". `status.device` reports where it actually landed and `status.device_note` why. A GPU-only `WHISPER_COMPUTE` (`float16`) becomes `default` on the retry, since it does not exist on CPU. An explicit `WHISPER_DEVICE=cpu` still raises: there is nothing to fall back to. |
| `VOICE_BACKEND_ENABLED` | `WS /v1/voice/session` only. **Does not** gate transcription. |
| `VOICE_TRANSCRIBE_MAX_BYTES` | Clip ceiling for `POST /v1/voice/transcribe`, in bytes. Default 25 MB; an unparseable or non-positive value falls back to it, since the wrong answer here is refusing audio somebody meant to send. Read per request via `max_audio_bytes()` rather than bound at import — the backend suite purges and re-imports `app.*` in several fixtures, so the module global is not reliably the one a mounted route reads. |

Browser-side keys: `homepilot_stt_preferences_v1` (the chat/Voice engine choice),
`homepilot_media_preferences_v1` (devices), `homepilot_voice_config` (voice,
rate, pitch, enabled), `homepilot_voice_uri` (legacy), `homepilot_stt_lang`,
`homepilot_voice_handsfree`, `homepilot_tts_enabled`.

Local speech install (from `backend/`, the same set MeetingSense uses):

```bash
pip install -r requirements/speech-cpu.txt     # or .[whisper]
```

---

## 9.5 Before shipping: what the tests prove, and what they cannot

Automated tests cover the logic. They **cannot** cover a microphone, a browser's recognizer,
or a GPU — no CI runner has any of them — so the list below separates the two honestly.

**Proved by the suite** (`make test`, and the named CI steps):

- A recognized sentence reaches `onSendText` on both engines, trimmed, unmodified — and an
  empty transcript does not (`voiceSendPath.test.tsx`). `VoiceModeGrok` forwards that to
  `App`'s `sendTextOrIntent`, which is what posts to the model, so this is the join between
  "speech became text" and "the assistant was asked".
- The manual listen button opens its own capture when the VAD is not running, and closes it
  afterwards. Before this it failed with `microphone_not_open` — a dead press-to-talk for
  everyone on the local engine.
- A deaf recognizer is detected and recovered from, never silently, and across both surfaces
  at once (§2.3).
- Hands-free on the browser engine opens **no** `getUserMedia`, and hands-free on the local
  engine starts **no** recognizer — cause (3) of §1, as a property rather than a timeout.
- Whisper falls back to CPU when CUDA is unusable, at load *and* at first inference.
- `POST /v1/voice/transcribe` on every format, on silence, over the size ceiling, and with a
  provider that fails.

**Only a real machine can answer** — run these once against the build you intend to ship:

1. Settings → Audio & Video → **Test microphone**, then play it back. If you cannot hear
   yourself, nothing downstream matters.
2. Settings → Voice Assistant → **Test speech-to-text**, then **text-to-speech**, then
   **speech → text → voice**. The third is the whole loop.
3. Chat composer microphone: speak, confirm the words land in the input box. (By design it
   *fills* the composer — it does not press send for you.)
4. Voice tab, hands-free: speak, confirm the text appears as your message **and** a reply
   comes back. This is the only check that exercises transcript → `sendTextOrIntent` → model.
5. Repeat 3–4 with Speech Recognition set to **On this computer**, then to **Browser**. They
   are different code paths and both ship. On **Browser**, watch the words appear as you
   speak (the *Hearing …* strip); on **On this computer**, watch the level meter move. Each
   engine has exactly one of those, and seeing the other would mean two captures again.
6. `curl -s localhost:8000/v1/voice/stt/status` — confirm `available: true` and read
   `device_note`. A note saying it landed on CPU means transcription works but is slow;
   budget for that before calling it production-ready.

---

## 10. Debugging checklist

1. **Which engine?** Settings → Voice Assistant says so; or look for `stt_runtime_resolved`.
2. **Is the server able to transcribe?** `curl -s localhost:8000/v1/voice/stt/status`.
3. **Does the device work at all?** Settings → Audio & Video → Test microphone, then play it
   back. If you cannot hear yourself, nothing downstream can help.
4. **Does speech become text?** Settings → Voice Assistant → Test speech-to-text. The verdict
   names the cause.
5. **Does the whole loop work?** Test speech → text → voice.
6. **Still wrong?** Filter DevTools for `HomePilot:Mic`, reproduce, then read
   `window.__HOMEPILOT_MIC_DEBUG__` against the table in §6.

### Symptom → likely cause

| Symptom | Look at |
|---|---|
| Meter moves, no text, no error | §1 device split, with both captures open. Fixed: the engines are now exclusive, so a `vad capture_opened` and an `stt_onstart` can no longer appear in the same session. If you still see both, that is a regression — `sttCaptureOwnership.test.tsx` is the guard. |
| Browser mode: the input level meter is gone | Deliberate — §2.2. The recognizer opens its own capture and hands HomePilot no audio to measure. Opening a second microphone purely to animate a bar is the bug above. Switch to *On this computer* for a live meter on the microphone you selected. |
| Browser mode: cannot speak over the assistant any more | Deliberate — §2.2. Barge-in needs the VAD, which does not run on this engine, and leaving the recognizer open during TTS transcribes the reply back as the next turn. `bargeInSupported` reports it. |
| The composer mic button disappears when there is text | Fixed. It used to be the *alternative* to Submit, so any draft hid it — dictating a correction meant clearing the field first. Both buttons are shown now. |
| `stt_onend {hadResult: false}`, nothing else | §5 warm-up stop, or the split. Check `sawAudioStart` / `sawSpeechStart`. |
| Mic button does nothing, no logs | Fixed. Every outcome now traces under scope `chat` and shows a notice by the composer. |
| Text appears in the wrong language | `homepilot_stt_lang` — `SpeechService.setRecognitionLang(...)`. |
| "Test voice" sounds unlike assistant replies | Fixed. Both go through `speakThroughRuntime()`. |
| TTS silent, no error | §4 `never_started`. Output device, volume, removed voice, or autoplay block. |
| `network` error on every turn | Web Speech needs internet. Install local speech and use the backend path. |
| Browser mode: turns now take ~5 s before giving up | Deliberate — §2.3. A recognizer that has heard nothing is given until `STT_NO_SPEECH_GRACE_MS` rather than being cut off on another microphone's silence. `stop_deferred_warming_up {deferredBy: 'no_speech_yet'}`. Turns that hear speech are not delayed. |
| Every turn returns **502**, `libcublas.so.12 not found` | `WHISPER_DEVICE=auto` picked a GPU whose CUDA runtime is incomplete. **CTranslate2 loads the CUDA libraries lazily**, so this surfaces at the *first inference*, not at load — the retry therefore lives in `_run_with_cpu_fallback`, not only in `_ensure_model`. `status.device_note` names the reason. `WHISPER_DEVICE=cpu` skips the wasted attempt. |
| Settings says "Using the browser's speech recognition" on a session that recovered onto on-device | Fixed. `VoiceAssistantSelfTest` and `SpeechRecognitionSettings` were the last two copies of the engine decision, re-resolving the *preference* and so blind to a session override. Both read the shared runtime through `describeSttRuntime()` now, which is why the card can say "Not the engine you chose". |
| The Settings speech-to-text test keeps failing on a session that works | Same cause. It aimed at the preference's engine, so after a recovery it went on testing the one that had just been abandoned. |
| "Recognition captured silence" shown above recognized text | Fixed. One `heard` panel was written by two tests, so the end-to-end check's transcript rendered under the speech-to-text check's verdict. The loop test has its own. |
| The chat microphone wastes a turn on every page load | Fixed. The deaf verdict is remembered per microphone, so the next session starts on the working engine — see §2. |
| The Settings speech-to-text test dies with a bare `aborted` | Fixed. The test used to take the recognizer with `abortSTT`, which worked in one direction only — the Voice tab's hands-free loop restarts every 400 ms and took it straight back. Both now go through the microphone lease: the test acquires it, and the loop waits (`handsfree_browser_yielded`) rather than fighting for it. |
| "The end-to-end check needs HomePilot speech-to-text", on a server that has it | Fixed. It was gated on the engine the *preference* resolved to, so the default (Browser) refused and told the user to install a model they were already running. It is gated on `capability.available && recorderSupported` now — whether the check can run, which is a different question from what chat uses. |
| Browser engine: `sawAudioStart: true, sawSpeechStart: false` every time | The browser recognizer opened a capture on your **OS default input** and heard nothing. It cannot be pointed at the microphone in Audio & Video. HomePilot now detects this after two consecutive turns and switches the session to on-device transcription when it can — see §2.3. Either make that mic the OS default, or set Speech Recognition to *On this computer*. |
| Manual "press to talk" does nothing, `recorder_start_no_stream` | Fixed. The VAD runs only in hands-free mode, so a manual turn on the local engine had no capture to borrow. It now opens the selected microphone itself (`recorder_opening_own_capture`) and releases it on stop. |
| Voice changed engine on its own mid-session | §2.3, and the trace says so: `stt_deaf_recognizer_recovery {action: 'switch-to-backend'}`. Your stored preference is untouched; the notice names where to change it. |
| The trace says `routingMismatch: false` but the split is clearly real | `routingKnown: false` means it could not tell — the browser exposed no `default` alias to compare against. "No mismatch" and "cannot tell" are separate fields for exactly this reason. |
| Voice reopens the microphone forever (`handsfree_vad_start_requested` counting up) | A render-scoped identity reached the capture effect's dependencies. See §6.1. |
| Meeting transcript only moves every ~8 s | Partials are not getting through. Check `_partialsWanted`: a non-empty `_queue` (you are behind), a backed-up socket, or `partialsDisabled`. |
| Meeting records the wrong microphone | §3.5. Was fixed; check `ms:mic_fallback` for a selected device that was gone. |
| Meeting hears the call's voices as you | Echo cancellation off with system audio on speakers. §3.5. |
| Every meeting line says "Speaker", or a microphone-only meeting says "Them" | Fixed. A mono frame is now attributed from the meeting's single audio source — see §3.5. A line that is still unattributed means the session never reported an `audio.mode`. |
| The transcript does not update during the meeting, but appears after it ends | Fixed. The workspace opened on the Timeline tab, which shows no transcript. It opens on Transcript now, and the tab shows a live line count. |
| No way out of the meeting recap | Fixed. A full-screen portal with no control on it is a dead end; there is a Close button once the meeting has ended. |
| `meetingsense: recap failed`, repeatedly, with a `ConnectError` traceback | The language model is not running. The transcript is unaffected. It is one warning per outage now, retried every 60 s, and the meeting message says why there is no recap. |
| Meeting transcript is blank but slides work | `get_meeting_stt_provider()` has no local model. Meetings never fall back to `STT_BASE_URL` on their own — see `meeting_stt_policy()`. |
| Shared video is not transcribed at all | No audio track: window share, macOS screen share, or "Share tab audio" unticked. See the capture table in §3.5. |
| Shared video transcript has gaps | `ms:audio_dropped` — the machine is behind. Turbo + GPU, or accept the lag. |
| Quiet parts of a video are missing | Media mode should cover this via `MEDIA_FLOOR_RMS`; check `ms:capture_mode` actually fired. |
| Video audio is transcribed twice, as both speakers | Playing through speakers with mic echo cancellation off. |
