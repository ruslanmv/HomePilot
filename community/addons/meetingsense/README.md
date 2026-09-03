# HomePilot MeetingSense — audio capture

**The recorder half of MeetingSense: screen + microphone in, transcript out.**

This addon opens its own capture, turns it into 16 kHz audio, cuts it into utterances when
the room goes quiet, and streams them to your HomePilot backend over
`WS /v1/meetingsense/session`. Transcription happens wherever your backend's speech provider
points — with `WHISPER_MODEL` set and no `STT_BASE_URL`, that is your own machine and nothing
leaves it. `GET /v1/meetingsense/status` tells you which it is, and names the provider.

> **MeetingSense ships disabled.** The backend refuses the socket until
> `MEETINGSENSE_ENABLED=true`, so installing this addon on its own records nothing.

## Install

```html
<script src="/js/homepilot-meetingsense.js"></script>
<!-- or, from this folder: -->
<script src="/addons/meetingsense/homepilot-meetingsense.js"></script>
```

There is no auto-mounted button. The recorder starts when something asks it to, because a
control that records a meeting belongs next to the meeting, not floating over every page.

## Use

```js
const started = await hpMeetingSense.start({
    conversationId: currentConversationId,   // required — where the meeting lands
    title: 'Q3 planning',                    // optional
    source: 'teams',                         // optional: teams | zoom | meet | other
});
// → { ok: true, meetingId, audioMode: 'system+mic' }

hpMeetingSense.muteMic(true);   // your side only; the call keeps recording
await hpMeetingSense.stop();
```

Results arrive as DOM events on `window`, so the chat card and the recording pill can both
listen without either one owning the recorder:

| Event | Fires when | `detail` |
|---|---|---|
| `ms:segment` | a line is transcribed | `{id, t0, t1, speaker, text, conf}` |
| `ms:partial` | provisional text arrives | `{t0, speaker, text}` |
| `ms:status` | counters or mute state change | `{elapsed, segments, slides, mic_muted}` |
| `ms:audio_lost` | a track ends mid-meeting | `{track, audioMode}` |

## Why it does not extend ScreenSense

ScreenSense promises one silent still, no backend, and `audio: false`. MeetingSense breaks
both halves of that on purpose: it holds a stream open for an hour and it records sound.
Sharing the code would mean one of the two features constantly bending the other out of shape,
so MeetingSense opens its own `getDisplayMedia` and ScreenSense is left exactly as it is.

## What it records, and what it tells you

`hpMeetingSense.audioMode` is one of four values, and the consent copy should show it:

| Mode | Meaning |
|---|---|
| `system+mic` | the call and your microphone — the normal case |
| `system` | the call only, because the microphone was declined |
| `mic` | your side only, because the browser shared video without audio |
| `none` | nothing was granted; `start` refuses rather than pretending |

The two sources are kept on **separate channels**, never summed. Channel 0 is the call and
channel 1 is your microphone, which is how the server can label who said what. Muting sets
your channel's gain to zero, so the call keeps recording while your side goes quiet.

## Browser support

| Browser | Screen audio | Notes |
|---|---|---|
| Chrome / Edge (desktop) | ✅ tab and screen | Pick **a tab** and tick "Share tab audio" to capture the call |
| Firefox | ❌ | Shares video only, so you get `audioMode: 'mic'` |
| Safari | ❌ | Same — microphone only |
| Any browser, window share | ❌ | Window shares carry no audio in any browser; share a tab or a screen |

Requires `AudioWorklet`, which every current browser has. Without it `start` refuses and says
so rather than recording silence.
