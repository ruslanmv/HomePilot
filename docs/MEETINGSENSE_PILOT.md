# MeetingSense — the week-one pilot

Decision D7: **run the recorder in real meetings for a week before building anything else.**
This page is what to do, what to write down, and what the answers decide.

Nothing here is code. Everything here is a thing only a person with a real meeting, a real
microphone and a real network can find out — which is exactly why it comes before W3 and W4
rather than after them.

---

## Why the pilot is a gate and not a formality

Two open items block it, and neither can be closed from a build container.

**1. The browser matrix is unsigned.** jsdom has no `AudioContext`, no `AudioWorklet` and no
`getDisplayMedia`, so the capture graph has *no automated coverage at all* and cannot get any.
Everything about the samples once they arrive is tested — framing, the VAD cuts, WAV layout,
channel order, clamping, resampling. Whether a browser hands over the call's audio in the first
place is not, and rows 1–3 below decide whether MeetingSense records anything.

**2. MS1-b — the real-time factor — is now load-bearing.** §2a says the *"catching up · N s
behind"* threshold derives from a measured real-time factor on the machine that will run
meetings. No such measurement exists: MS6 shipped a provisional **2 s** in its place. Until the
number exists, that threshold is a guess that happens to look like a specification.

---

## Before the first meeting

```bash
# 1. Turn it on. Both flags only if you will record from a hosted avatar page.
export MEETINGSENSE_ENABLED=true
export WHISPER_MODEL=small          # or STT_BASE_URL for a remote endpoint

# 2. Confirm the machine agrees.
curl -s localhost:8000/v1/meetingsense/status | python3 -m json.tool
#    ready: true          → it can record
#    stt.provider         → who will hear the meeting
#    stt.device           → null until the first transcription; check it again after
#    stt.device_note      → present only when the model did not load where you asked
```

If `stt.device_note` says *requested cuda, running on cpu*, stop and fix that first. Everything
about the latency budget assumes the GPU, and a silent CPU fallback runs roughly ten times
slower — you would spend the pilot measuring the wrong machine.

---

## Row 1 of the matrix, first

The browser matrix lives in [`MEETINGSENSE.md`](MEETINGSENSE.md#what-gets-captured). Do row 1
before any real meeting, because it is the one that decides whether the rest is worth doing:

> **Chrome, desktop, share a tab, "Share tab audio" ticked → `audioMode: system+mic`, both
> speakers labelled.**

If the speakers come out swapped, stop. Channel 0 is the call and channel 1 is your microphone;
that convention is fixed in three places (`audio.py`'s `CHANNEL_SPEAKERS`, the addon's
`encodeWav`, and the WAV interleave) and nothing in the stack would notice if it were wrong.

Then work the remaining nine rows and sign each one. A row nobody has run is not a row that
passed.

---

## During the week

Record whatever you would have recorded anyway. Do not stage meetings — a staged meeting has
one speaker, no crosstalk, no network trouble and no accents, which is to say none of the
things that break a recorder.

### The measurement (MS1-b)

Once, on the machine that will run meetings:

```bash
# With a real meeting's audio, not a synthetic tone.
# real-time factor = wall-clock seconds to transcribe ÷ seconds of audio
```

Write the number, the `WHISPER_MODEL`, and the resolved `stt.device` into
[`MEETINGSENSE.md`](MEETINGSENSE.md). Then set the *"catching up"* threshold from it rather
than leaving the provisional 2 s: if a chunk takes 0.3× real time, a 2 s backlog is nothing to
report; if it takes 1.2×, the transcript will never catch up and the label should appear far
sooner and say something different.

### What to write down

For each meeting, four lines is enough:

| | |
|---|---|
| **Length, source, browser** | 52 min · Teams · Chrome |
| **What the transcript got wrong** | names, numbers, crosstalk, accents, the first sentence |
| **What you wanted and could not do** | the honest list, including things not in the plan |
| **Anything that scared you** | a pill that lied, text that changed after you read it, a hole |

The last row matters most. Everything in §2a exists because a live transcript is only useful if
the reader trusts it, and trust breaks quietly.

### Specific things to watch, because they were built on reasoning rather than evidence

- **The 200 ms overlap** only rides out of a hard cut, not out of a close on silence. If words
  are lost at utterance boundaries, that reasoning was wrong.
- **The 350 ms silence close over a 1 s floor.** Too short and sentences get chopped mid-phrase;
  too long and the transcript lags. It has never met a real pause.
- **The 8 s hard cut.** Watch a presenter who does not breathe.
- **Backpressure sheds the least speech-bearing chunk first.** On a bad connection, check that
  what disappears is a cough and not a sentence.
- **Resume.** Turn off Wi-Fi for twenty seconds mid-meeting. The transcript should continue
  with no gap and no duplicated lines, and the pill should stop saying *reconnecting*.
- **The undo.** Press Stop, then Undo within ten seconds while somebody is still talking. Those
  ten seconds should be in the transcript.

---

## What the answers decide

Rev 6 §8 leaves the next wave deliberately unchosen:

> **Order W3 vs W4 by the pilot notes.**

| If the pilot's complaint is… | Do next | Because |
|---|---|---|
| "I could not tell what was on screen" — decisions referenced a slide the transcript cannot show | **W3 — Eyes** (MS9 → MS11) | Keyframes and captions; the transcript is already usable, the context is not |
| "I had to read the whole thing to find anything" — the transcript is right but unusable | **W4 — Brain** (MS12 → MS14) | Rolling notes, ask-about-this-meeting, and a real summary in place of MS6's preview |
| Both, equally | **W4 first** | The summary message is what makes a meeting findable a week later, and W3's captions feed the notes engine rather than the other way round |

If the complaint is neither — if the recorder itself hurt — that is a bug list, and it comes
before both.

---

## Where things stand going in

| | |
|---|---|
| **Waves complete** | W0 (foundation), W1 (local recorder), W2 (reach) |
| **Tests** | 316 backend `tests/meetingsense`, 434 frontend, 61 in ollabridge's avatar suite |
| **Open, carried** | MS1-a (real remote timings, needed before W4), MS1-b (the measurement above) |
| **Open, unsigned** | the 10-row browser matrix |
| **Known gap** | a server restart leaves meetings `live` or `suspended` in the store with nothing to reconcile them; MS3 had this for `live` and MS3-a widened it by one state |
| **Not wired** | MS5's **Start session** calls an `onStart` callback the host application must mount; every piece it needs exists and is tested |
