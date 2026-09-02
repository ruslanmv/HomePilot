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

## Verifying MS0 and MS1

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
cd backend && python3 -m pytest tests/meetingsense -q
```

MS1 touches `backend/app/voice/providers.py`, which the voice backend shares — the plan's
one sanctioned exception to additive-only. The rule it keeps instead is narrower and
checkable, and these are the tests that check it:

```bash
cd backend && python3 -m pytest tests/meetingsense/test_stt_capability.py -q  # 28
cd backend && python3 -m pytest tests/test_voice.py tests/test_voice_call*.py -q
```

What MS0 and MS1 deliberately do **not** do: mount a session route, create a table, write a
message, or read a microphone. The package imports one router and a dataclass, and the
speech layer only grows methods beside the ones that were already there.

---

## Design

- [`design/MEETINGSENSE_DESIGN.md`](design/MEETINGSENSE_DESIGN.md) — Part 1: capture,
  transcript, slide keyframes, notes.
- [`design/MEETINGSENSE_DESIGN_PART2.md`](design/MEETINGSENSE_DESIGN_PART2.md) — Part 2:
  Together mode, catalog, agent engine, MCP, helper modes.
- [`design/MEETINGSENSE_BATCHES.md`](design/MEETINGSENSE_BATCHES.md) — the implementation
  tracker, and **§1 lists the six places the design documents disagree with the source**.
  Read that before trusting a "we reuse X" claim in either design doc.
