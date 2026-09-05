# Local Vision Adapter — Batch Plan (screen understanding)

**Status:** V1, V2 and V3 are **shipped**; V4–V8 are still planning.
Below, the shipped batches keep their original text and carry a ✅ with what actually landed.
**Scope:** `ruslanmv/HomePilot` — `backend/app/multimodal.py`, a new
`backend/app/vision_adapter/`, `frontend/public/js/homepilot-screensense.js`,
`frontend/src/ui/meetingsense/MeetingSenseProvider.tsx`, `frontend/src/ui/Models.tsx`,
`backend/app/model_catalog_data.json`, and `backend/app/screensense/routes.py` (RS1).
**Rule for every batch below:** additive only. The adapter starts as a passthrough seam that
changes no behaviour; profiles arrive after it.

---

## 0. The experience we are building toward

Today a user asks *"what can you see?"* and gets:

```text
No usable answer from moondream:latest. It returned nothing that reads as a
description of your screen — try a larger vision model (Settings → Multimodal).
```

That is the product asking the user to understand model size, image resolution and
Moondream's limits. They asked a question about their own screen.

What it should be:

```text
I'm looking at your screen…
```

then either an answer, or — only after every internal retry has failed:

```text
I captured the screen, but the local vision model could not read it clearly.
Install a stronger local screen model: Qwen3-VL 4B or Gemma 3 4B.
```

And in Settings:

```text
Screen understanding
Status:  Ready · Local
Model:   Auto — Recommended
Quality: Balanced
```

The user shares the screen once. HomePilot adapts the image locally to whatever vision model
is installed, and answers. Model complexity never surfaces as the first thing they read.

---

## 1. What is actually true today

Verified against the code, because one widely-assumed cause is wrong and one plausible fix
would not have worked.

### The screenshot was not too big

`homepilot-screensense.js` already downscales every path — desktop capture, browser share and
file upload — through `captureFrame(maxW = 1280)`, and `Math.min(1, maxW / sw)` means it never
upscales. A 1878×958 screen reached the model at roughly **1280×653**, as JPEG quality 0.82.

So an adapter justified purely as *"resize the huge screenshot"* would be solving a problem
that was already solved on the client. The adapter is still worth building — for every caller
that is **not** ScreenSense — but that is not why this failure happened.

### First cause: the user's chosen model never reaches the request

`homepilot-screensense.js` auto-mounts its floating button with no options:

```js
window.hpScreenSense.mountButton();     // no opts → opts.model is undefined
```

`ask()` only sets `body.model` when a caller supplied `opts.model`. Meanwhile
`MeetingSenseProvider.tsx:184-192` binds exactly two things — `bindConversation` and
`setAwareness` — and never passes the multimodal settings through, even though
`App.tsx:3002-3004` reads all three from storage:

```
homepilot_provider_multimodal
homepilot_base_url_multimodal
homepilot_model_multimodal
```

and `/v1/multimodal/analyze` accepts all three. **The Settings choice is read, stored, and
then dropped on the floor.** The backend auto-detects instead.

### A fix that would not have worked

The obvious guess is that `VISION_MODEL_PATTERNS` puts `"moondream"` first. Reordering it
would change nothing. `_detect_first_vision_model` iterates over **installed** models in
Ollama's `/api/tags` order and returns the first that matches *any* pattern:

```python
for m in data.get("models", []):
    name = m.get("name", "")
    if is_vision_model(name):
        return name
```

The fix has to **rank the installed set** by a preference order. The substring list is a
membership test, not a priority list, and treating it as one is a batch spent on the wrong
line.

### Second cause: an empty answer is reported as success

`analyze_image_ollama` ends with an unconditional success, whatever came back:

```python
content = str(content or "").strip()
return {"ok": True, "analysis_text": content, "meta": {...}}
```

So an empty or refused generation is a 200 with `ok: true`. The only thing standing between
the user and noise is `usableAnswer()` in the browser — the UI doing the backend's job, at the
last possible moment, with no way to retry because the backend already declared success.

### Two smaller defects found while reading

* `meta.image_size_bytes` is `len(raw_bytes)`, which is `b""` on the `image_b64` path — so
  every avatar-director analysis and every RS1 `/explain` reports **0 bytes**.
* The model catalogs have genuinely diverged. `frontend/src/ui/Models.tsx:287` lists
  `internvl3:8b` and `smolvlm2:latest`, absent from `backend/app/model_catalog_data.json`;
  the backend lists `qwen2.5vl:7b` and `bakllava:latest`, absent from the frontend.

### One caveat carried forward honestly

The upstream research could not reach the Ollama model pages — the proxy returned 403, the
research service 401 — and neither can this environment. So the ranking in V2 is a
**preference order over what is installed**, never a claim that a particular tag, size or
image limit exists. No batch below asserts a model-specific limit that has not been measured
here.

---

## 2. The design

One backend layer, between `_load_image_bytes()` and `_image_to_base64()` — that position
covers local files and remote URLs in a single place.

```text
ScreenSense frame  /  chat upload  /  remote URL  /  MeetingSense keyframe  /  RS1 frame
                                   │
                     preserve the original, on disk, untouched
                                   │
                            Vision Adapter
                     ├─ model profile (or passthrough)
                     ├─ resize / crop / tile
                     ├─ rank the installed models
                     └─ retry internally on an empty answer
                                   │
                            one answer to the user
```

```python
adapt_image(raw, *, mime, model, purpose="screen") -> AdaptedImage
#   bytes, mime, width, height, original_width, original_height,
#   scale, strategy, tiles, warnings
```

**The `image_b64` path must decode first and pass through the same adapter**, or the avatar
director and RS1's `/explain` stay unprotected — which is the exact gap that lets a defect
reach two features while being fixed in one.

**Never resize before storing.** The original goes to disk; analysis versions are derived from
it. RS1 already depends on this: the frame on disk is the frame the user was shown, and the
`↳ Screenshot · 10:42:18` citation only means anything while that stays true.

**Constrain on five axes, not width.** Long edge, decoded megapixels, encoded bytes, animated
frame count, tile budget. A very tall page satisfies a width limit and is still enormous; an
ultrawide desktop squeezed to 1280 satisfies every limit and has destroyed the text somebody
is trying to read.

**Profiles, not model-name conditionals.**

| Profile | For | Behaviour |
|---|---|---|
| `screen_overview` | "what is on my screen?" | fit long edge, moderate JPEG |
| `screen_text` | OCR, errors, UI labels | overview **plus** detail tiles, 10–15% overlap |
| `photo` | general description | fit dimensions, no tiling |
| `document` | dense pages, charts | page-aware or tiled |
| `passthrough` | unknown model | today's behaviour, unless a safety limit is exceeded |

**Missing capability metadata means `passthrough`.** Never infer a limit from parameter count;
never mark multi-image support unless it has been tested here.

---

## 3. The batches

### V1 — The Settings choice reaches the request

✅ **Shipped.** `hpScreenSense.setVision()` holds the choice; `MeetingSenseProvider` reads the three `localStorage` keys and hands them over; RS1's `/explain` falls back to `MULTIMODAL_MODEL` / `MULTIMODAL_BASE_URL`, because its caller is a browser on another machine and cannot know this HomePilot's Settings.

Pass `homepilot_provider_multimodal`, `homepilot_base_url_multimodal` and
`homepilot_model_multimodal` into `hpScreenSense` — through `mountButton()` options and a
setter alongside the existing `bindConversation` / `setAwareness` — and into RS1's
`/v1/screensense/explain`.

Wiring only. No architecture. **This alone is likely to resolve the reported failure**, and it
should be measured before anything else is built, so the rest of the plan is justified by what
is left rather than by what it was assumed to be.

**Acceptance.** With a model selected in Settings, the outgoing `/v1/multimodal/analyze` body
carries that model. A test asserts it for the floating button, for the chat path, and for RS1
— three call sites, because fixing one and assuming the others is how this defect happened.

---

### V2 — Rank the installed models instead of taking the first match

✅ **Shipped.** `VISION_PREFERENCE` ranks the installed set, `VISION_LAST_RESORT` pins Moondream behind even an unranked vision family, and a test fails if the ranking is ever made to depend on `VISION_MODEL_PATTERNS`. Also found and fixed: `qwen2.5vl` matched no pattern, so the catalog's own Qwen2.5-VL was not classified as a vision model at all.

Replace "first installed model matching any pattern" with a preference order applied to the
installed set:

```text
Qwen3-VL 4B / 8B  →  Qwen2.5-VL 7B / 3B  →  MiniCPM-V 2.6  →  Gemma 3 4B
→  Llama 3.2 Vision 11B  →  LLaVA 7B  →  Moondream
```

Moondream stops being the default for reading a desktop and stays what it is genuinely good
at: the fast fallback.

**Acceptance.** Given an installed set in an adversarial order (Moondream first in
`/api/tags`), the ranked choice is not Moondream. And a test that fails if somebody "fixes"
this by reordering `VISION_MODEL_PATTERNS`, since that list is a membership test.

---

### V3 — An empty answer is a typed failure

✅ **Shipped.** `error_code: "empty_model_response"` alongside the human `error` string, so every existing caller keeps working. `meta.image_size_bytes` no longer reports 0 on the `image_b64` path.

```json
{"ok": false, "error": {"code": "empty_model_response",
                        "message": "The vision model returned no description."}}
```

This is what makes retry possible at all — while the backend reports success, no layer above
it can do anything but print the noise.

**Acceptance.** A stubbed Ollama returning `""`, whitespace, and a refusal opening each
produce `empty_model_response`, and the browser's `usableAnswer()` becomes a second line of
defence rather than the only one.

---

### V4 — The adapter seam, changing nothing

`backend/app/vision_adapter/` with `passthrough` only, applied to **every** path including
`image_b64`. Behaviour identical, byte for byte, on every existing call.

Fix `meta.image_size_bytes` here, since the adapter is the first place that reliably knows the
real size on both paths.

**Acceptance.** A golden test over the existing call sites: same bytes in, same bytes to the
model, same `analysis_text`. A seam that changes behaviour on the day it lands cannot be
distinguished from the profiles that follow it.

---

### V5 — Screen profiles, with tiling gated on evidence

`screen_overview` and `screen_text`. Overlapping tiles at 10–15%, labelled (`overview`,
`top-left`, `center`, …), with a hard tile budget from the selected model and available memory.

**Gate tiling on verified multi-image support.** Sending four tiles to a model that has never
been shown to reason across images turns one bad answer into four.

**Acceptance.** Ultrawide and high-DPI inputs keep readable text at the model's dimensions;
tile boundaries never cut a control or a line of text in the corpus; a model without verified
multi-image support receives exactly one image.

---

### V6 — Retry internally, and say the right thing

```text
overview → empty or unusable? → detail tiles → better installed model → only then, say so
```

The user sees `I'm looking at your screen…`, then an answer. The raw model failure is never
the first thing they read, and the model name appears only in the final message, where it is
actionable.

**Acceptance.** A model stubbed to return noise on the overview and a real answer on a tile
produces the answer with no failure text shown. When every retry fails, the message names a
model to install, not a model that failed.

---

### V7 — One catalog

Generate the frontend list from `backend/app/model_catalog_data.json` at build time; delete
the hand-maintained copy in `Models.tsx`. Add optional `vision_input` capability metadata
(`max_long_edge`, `max_megapixels`, `preferred_mime`, `supports_multiple_images`, `strategy`)
**only** for entries where it has been confirmed.

**Acceptance.** A test fails if the two lists diverge — which is the only thing that keeps
them from diverging again.

---

### V8 — The bench set

Desktop screenshot · code error · browser page · SVG · settings window · terminal ·
1920×1080 · 2560×1440 · 3840×2160 · ultrawide 5120×1440 · very tall page · tiny image that
must not be enlarged · transparent PNG · EXIF-rotated JPEG · animated GIF/WebP · corrupt bytes
· decompression bomb · dense terminal text · multi-monitor as one surface · unknown model with
no metadata · explicit selection vs auto-detection · empty, refusal and malformed responses.

Report adapter details in `meta` so the six failure modes stay distinguishable: model returned
empty, image could not be decoded, image exceeded a safety limit, resize damaged OCR
resolution, model selection ignored Settings, provider rejected the format.

---

## 4. Order, and where the value is

```text
V1 ─► V2 ─► V3 ─►│─► V4 ─► V5 ─► V6 ─► V7
                 └─────────────────────────► V8 (parallel from V4)
```

**V1–V3 are small and change what the user sees today.** V1 in particular may be the whole
fix; measure after it before committing to the rest. V4 onward is the architecture that stops
the next caller — a new feature, a new provider — from reintroducing the same class of defect.

---

## 5. What we are deliberately not doing

* No cloud vision by default. Not as a fallback, not as error recovery.
* No continuous screen streaming. One frame per explicit request, as RS1 already enforces.
* No asking the user to choose a model before they can ask a question.
* No exposing "moondream returned empty" as the primary user-facing message.
* No resizing before the original is stored.
* No model-specific limits written down that have not been measured in this repository.
