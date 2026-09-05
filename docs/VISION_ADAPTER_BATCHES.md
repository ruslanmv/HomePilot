# Local Vision Adapter — Batch Plan (screen understanding)

**Status:** V1–V5 are **shipped**; V6–V8 are still planning.
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

✅ **Shipped.** `backend/app/vision_adapter/` exists and both paths meet at it. `adapt()`
measures with Pillow when Pillow is installed, records what it saw, and hands the same bytes
back — `strategy: "passthrough"`, `scale: 1.0`, `tiles: 1`. Every response now carries
`meta.adapter`, which is the batch's real deliverable: until it existed, "the model returned
nothing", "the image was forty megapixels" and "the resize destroyed the text" all arrived as
the same silence.

Two things came out of routing both paths through one place. The `image_b64` path now decodes
before it encodes, so `meta.image_size_bytes` is the measured number rather than V3's
`(len(img_b64) * 3) // 4` estimate — that branch is now dead code, which is how you can tell
the seam is real. And a measurement that cannot be taken is never a failure: no Pillow, a
format it cannot open, or zero bytes all pass through with `width: null` and a warning
(`unmeasured`, `empty`, `unknown-purpose:…`), because a vision request that started failing
over an optional measurement would be a worse product than one that says it does not know.

`model` is accepted and unused. V5 reads it to pick a profile; taking it now means the four
call sites are already passing it, and a seam whose signature changes on the day it does
something is not a seam.

*Original plan:* `backend/app/vision_adapter/` with `passthrough` only, applied to **every** path including
`image_b64`. Behaviour identical, byte for byte, on every existing call.

Fix `meta.image_size_bytes` here, since the adapter is the first place that reliably knows the
real size on both paths.

**Acceptance.** A golden test over the existing call sites: same bytes in, same bytes to the
model, same `analysis_text`. A seam that changes behaviour on the day it lands cannot be
distinguished from the profiles that follow it.

---

### V5 — Screen profiles, with tiling gated on evidence

✅ **Shipped.** `screen_overview`, `screen_text` and `photo` live in
`backend/app/vision_adapter/profiles.py`, and `analyze_image`'s existing `mode`
(`caption | ocr | both`) is what picks between the first two — somebody asking for OCR is asking
to read the screen, so no call site grew a second, parallel way of saying the same thing. A new
`purpose` argument (`screen | photo | document`) defaults to `screen`, which is what every
caller was already getting.

**The overview runs today, for everyone.** An image is fitted to a long-edge cap *and* a pixel
cap — an ultrawide passes the first and not the second — with the aspect ratio kept, and it is
**never enlarged**: the only thing extra pixels add to a 320×200 icon is detail nobody
photographed. A resized screen comes back as **PNG**, because JPEG's ringing lands on
high-contrast edges and at these sizes a glyph stroke *is* a high-contrast edge one or two
pixels wide.

**Tiling ships gated, and the gate is closed.** `supports_multiple_images()` is False for every
model, because `MULTI_IMAGE_VERIFIED` is empty and a list of families that ought to work is not
a measurement — V8's bench set is the batch that fills it. An operator who has watched their own
model read a tiled screenshot can name it in `VISION_MULTI_IMAGE_MODELS` today. When the gate
closes, it says so: `warnings: ["tiling-unavailable:single-image-model"]`, because "the answer
was thin" and "the detail crops were never sent" look identical from outside.

**What tiling does when it runs.** Crops of the *original* — cropping the overview would hand
the model four pieces of the same blur — labelled `top-left`, `center`, `left` and so on, with
the split chosen by shape: a 16:9 screen is 2×2, an ultrawide is three panes across, a long
page is three down. The overview always goes first, and the prompt says the images are one
screen and how they relate; five images with no such account are five separate pictures to a
model, which is the failure the gate exists to keep away from unverified models.

Two claims are held to a standard stronger than a smoke test. The **overlap** (14%) carries a
geometric guarantee — with tiles of width *w* stepping by `w × (1 − overlap)`, any run shorter
than `w × overlap` lies wholly inside at least one tile, so a line of text is never cut in half
with neither crop showing all of it — and a test walks every offset across the screen to check
it. And `test_a_crop_keeps_text_the_overview_loses` measures the actual premise of the batch: a
4-pixel stripe pattern aliases into flat grey in the overview and is still legible in a crop. If
that test ever passes trivially, tiling has stopped being worth its cost.

**Numbers are budgets, not model limits.** A vision encoder's internal resolution is not
something this code can discover, so the caps (1400px long edge, 1.6 MP, 1100px tiles, five
parts) are chosen to be safe on small models and are expected to be tuned by V8 against real
screenshots. Two rules are not tuning-dependent: never enlarge, and never re-encode a screen as
JPEG.

**Found while building it.** EXIF orientation was applied *after* the target size was computed
from the on-disk dimensions, so a photo tagged "rotate 90°" was being fitted to the wrong shape
and stretched — and a small rotated photo took the passthrough shortcut and reached the model on
its side. Both fixed, both tested.

*Original plan:* `screen_overview` and `screen_text`. Overlapping tiles at 10–15%, labelled (`overview`,
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
