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

No interim, no result, **no error**. There were two compounding causes:

1. **The device split above.**
2. **Recognition was killed during warm-up.** Chrome needs a few hundred milliseconds to open
   its own capture and stream before it emits anything. Starting it on `vad_speech_start` and
   stopping it ~400 ms after the VAD's silence window finalized an empty session — cleanly,
   which is why not even `no-speech` was raised.

Both are fixed, and the fix for (1) is architectural: **transcribe the bytes we captured.**

---

## 2. The two speech-to-text paths

### 2.1 `homepilot-backend` — preferred

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
captures that happen to agree.

### 2.2 `web-speech` — fallback only

Used when `GET /v1/voice/stt/status` reports `available: false`: no local Whisper installed
and no `STT_BASE_URL` configured. The device caveat from §1 applies, and the UI says so
rather than letting you assume otherwise. The warm-up stop guard (§5) applies here.

### Which one am I on?

Settings → Voice Assistant states it in plain text, and the trace records it once per
session:

```
[HomePilot:Mic][voice] stt_engine_resolved {engine: 'homepilot-backend',
                                            provider: 'whisper-local',
                                            remote: false,
                                            usesOsDefaultInput: false}
```

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
| `413` | Over `MAX_AUDIO_BYTES` (25 MB). |
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
| `frontend/src/ui/media/runtimeTts.ts` | `speakThroughRuntime` + verdicts |
| `frontend/src/ui/media/voiceSelfTest.ts` | `explainSttOutcome`, `explainSttError`, `describeMicrophoneRouting` |
| `frontend/src/ui/media/microphoneDebug.ts` | The `HomePilot:Mic` ring buffer |
| `frontend/src/ui/media/mediaPreferences.ts` | Device selection, `buildAudioConstraints` |
| `frontend/src/ui/voice/vad.ts` | Adaptive VAD; `getStream()` shares its capture |
| `frontend/src/ui/voice/useVoiceController.ts` | State machine, engine resolution, per-turn recorder |
| `frontend/src/ui/tts/resolveAssistantVoice.ts` | The three-key voice resolution of §4 |
| `frontend/src/ui/tts/shimSpeechService.ts` | Routes `SpeechService.speak` through the plugin registry |
| `frontend/src/ui/components/VoiceAssistantSelfTest.tsx` | The three self-tests |
| `frontend/src/ui/components/AudioVideoSettings.tsx` | Device pickers, record-and-play-back test |
| `frontend/public/js/speech-service.js` | Legacy global: recognition lifecycle, stop guard, `speak()` |
| `frontend/src/ui/App.tsx` | Chat composer microphone (`toggleListening`) |
| `frontend/public/js/homepilot-meetingsense.js` | Meeting recorder: system+mic capture, `Segmenter`, partials, `micConstraints()`. **Mirrored** in `community/addons/meetingsense/` |

### Tests

| Path | Covers |
|---|---|
| `backend/tests/test_voice_transcribe.py` | Both endpoints: formats, silence, limits, 503 fallback, 502 provider failure |
| `frontend/src/test/sttService.test.ts` | Capability caching and degradation, upload shape, error mapping |
| `frontend/src/test/runtimeTts.test.ts` | Runtime speech verdicts, including silence-as-failure |
| `frontend/src/test/speechServiceStt.test.js` | The stop guard and lifecycle diagnostics |
| `frontend/src/test/voiceSelfTest.test.ts` | Failure explanation, routing detection, voice resolution |
| `frontend/src/test/voiceAssistantTesting.test.js` | Wiring contracts across all of the above |
| `frontend/src/test/microphoneDiagnostics.test.js` | The original diagnostics contract |
| `frontend/src/test/meetingsenseRealtime.test.js` | `takePartial` cadence and snapshot isolation, `micConstraints`, the three partial rules |

---

## 9. Configuration

| Variable | Effect |
|---|---|
| `STT_BASE_URL`, `STT_API_KEY`, `STT_MODEL` | An OpenAI-compatible transcription endpoint. **Recordings leave the machine** — reported as `remote: true`. |
| `WHISPER_MODEL`, `WHISPER_DEVICE`, `WHISPER_COMPUTE` | Local faster-whisper. `WHISPER_DEVICE=auto` falls back to CPU silently; `status.device` reports where it actually landed. |
| `VOICE_BACKEND_ENABLED` | `WS /v1/voice/session` only. **Does not** gate transcription. |

Browser-side keys: `homepilot_media_preferences_v1` (devices), `homepilot_voice_config` (voice,
rate, pitch, enabled), `homepilot_voice_uri` (legacy), `homepilot_stt_lang`,
`homepilot_voice_handsfree`, `homepilot_tts_enabled`.

Local speech install (from `backend/`, the same set MeetingSense uses):

```bash
pip install -r requirements/speech-cpu.txt     # or .[whisper]
```

---

## 10. Debugging checklist

1. **Which engine?** Settings → Voice Assistant says so; or look for `stt_engine_resolved`.
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
| Meter moves, no text, no error | §1 device split. Are you on `web-speech`? |
| `stt_onend {hadResult: false}`, nothing else | §5 warm-up stop, or the split. Check `sawAudioStart` / `sawSpeechStart`. |
| Mic button does nothing, no logs | Fixed. Every outcome now traces under scope `chat` and shows a notice by the composer. |
| Text appears in the wrong language | `homepilot_stt_lang` — `SpeechService.setRecognitionLang(...)`. |
| "Test voice" sounds unlike assistant replies | Fixed. Both go through `speakThroughRuntime()`. |
| TTS silent, no error | §4 `never_started`. Output device, volume, removed voice, or autoplay block. |
| `network` error on every turn | Web Speech needs internet. Install local speech and use the backend path. |
| Meeting transcript only moves every ~8 s | Partials are not getting through. Check `_partialsWanted`: a non-empty `_queue` (you are behind), a backed-up socket, or `partialsDisabled`. |
| Meeting records the wrong microphone | §3.5. Was fixed; check `ms:mic_fallback` for a selected device that was gone. |
| Meeting hears the call's voices as you | Echo cancellation off with system audio on speakers. §3.5. |
| Meeting transcript is blank but slides work | `get_meeting_stt_provider()` has no local model. Meetings never fall back to `STT_BASE_URL` on their own — see `meeting_stt_policy()`. |
| Shared video is not transcribed at all | No audio track: window share, macOS screen share, or "Share tab audio" unticked. See the capture table in §3.5. |
| Shared video transcript has gaps | `ms:audio_dropped` — the machine is behind. Turbo + GPU, or accept the lag. |
| Quiet parts of a video are missing | Media mode should cover this via `MEDIA_FLOOR_RMS`; check `ms:capture_mode` actually fired. |
| Video audio is transcribed twice, as both speakers | Playing through speakers with mic echo cancellation off. |
