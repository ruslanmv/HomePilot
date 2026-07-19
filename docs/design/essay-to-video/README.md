# Essay-to-Video Pipeline — Batched Design Series

**Status:** design only. Nothing in this series has been implemented.
**Scope:** `Video Project` in Creator Studio (AI Generation Studio), plus a new bridge into Creator Studio Pro.
**Contract:** every batch is strictly **additive and non-destructive** — new files, new optional fields with defaults that preserve current behavior, new enum values, new endpoints. No existing endpoint, model field, workflow, or wizard flow is removed or changed in meaning.

---

## Executive Summary

The ask: take a ruslanmv.com essay (its text, and optionally its existing narration audio) and turn it into a YouTube video — full-length, a Short, and a square/vertical teaser — using diffusion models and Creator Studio's existing AI generation pipeline, with Civitai as a model source when the built-in checkpoints aren't enough.

Having read the actual repo, this is smaller than it looks. HomePilot already has almost every primitive this needs: a scene model with `narration` + `imagePrompt` fields, a ComfyUI backend with workflows for every major open video-diffusion architecture (several already sitting in `comfyui/workflows/` unused), and a full Creator Studio Pro data model (`StyleKit`, `CanvasSpec`, `AudioTrack`, `CaptionSegment`) that was clearly built for exactly this kind of branded, multi-format, professional output — it just isn't wired to anything that generates content yet.

What's actually missing is three capabilities:

| # | Gap | Where it lives |
|---|-----|----------------|
| A | No way to hand the pipeline a finished script + existing audio instead of a one-line topic | `GenerateOutlineRequest`, a new ingestion module |
| B | Diffusion video hallucinates diagram text/labels — wrong renderer for half the essay's content | scene generation + a new code-driven renderer |
| C | Two subsystems don't talk: AI Studio generates, Pro can't receive; Civitai isn't wired at all | a bridge endpoint + a model manager service |

## The Batches

Smallest-first; each batch is independently shippable and each is provable before the next one adds cost.

| Batch | Document | Delivers | Notably does NOT need |
|-------|----------|----------|------------------------|
| **0** | [BATCH-0-script-ingestion.md](./BATCH-0-script-ingestion.md) | `EssaySource` parser + `source_mode="script"` on `generate-outline` + one `ruslanmv-essays` `StyleKit` row + a fourth "Technical / Editorial" visual style. Proves "the essay's own words become the narration" end to end using the *existing* SDXL/SVD path. | Remotion, WhisperX, Civitai, any new model |
| **1** | [BATCH-1-hybrid-rendering.md](./BATCH-1-hybrid-rendering.md) | `scene_kind`/`rendererKind` classification + Remotion renderer for `motion_graphic` scenes (diagram/proof/quote/CTA archetypes) | diffusion changes |
| **2** | [BATCH-2-audio-alignment.md](./BATCH-2-audio-alignment.md) | WhisperX forced alignment, real scene durations, `CaptionSegment` population, reused Kokoro audio for the full-length format, Kokoro as a second in-app TTS provider | new diffusion models |
| **3** | [BATCH-3-model-manager.md](./BATCH-3-model-manager.md) | `ModelManager` (Civitai + Hugging Face), the video-model-list registration fix, license allowlist, dual-aspect diffusion generation for hero shots | Remotion changes |
| **4** | [BATCH-4-multiformat-bridge.md](./BATCH-4-multiformat-bridge.md) | Condensed-script Shorts/teaser variant, new TTS pass, `social_1_1`/`social_teaser` enum values, `promote-to-project` bridge into Creator Studio Pro, three-canvas final assembly | — |
| **5** | *(explicitly out of scope)* | Thumbnail generation, YouTube Data API upload, scheduling — this design stops before publish automation, by request | — |

## What The Repo Already Has (verified against source)

All file/line references below were verified against the working tree on this branch.

### Two generation surfaces exist side by side today

- **AI Generation Studio** — `frontend/src/ui/CreatorStudioHost.tsx`, backend `/studio/videos/*` in `backend/app/studio/routes.py`, models `StudioVideo` / `StudioScene` in `backend/app/studio/models.py`. Three project types (`video`, `slideshow`, `video_series` — `CreatorStudioHost.tsx:22`), a short topic "Description," a multi-select tone picker, and a single-select `visualStyle` picker (`Cinematic`, `Digital Art`, `Anime`). This surface *generates content*.
- **Creator Studio Pro** — same routes file, `/studio/projects/*`, models `StudioProject`, `CanvasSpec`, `StyleKit`, `TemplateDefinition`, `StudioAsset`, `AudioTrack`, `CaptionSegment`, `VersionSnapshot`, `ShareLink` (`models.py:168–315`). Fully CRUD-wired: `/library/style-kits` (`routes.py:1827`), `/projects/{id}/assets` (`:1941`), `/projects/{id}/audio` (`:2012`), `/projects/{id}/captions` (`:2086`), `/projects/{id}/autosave` (`:2140`), `/projects/{id}/versions` (`:2155`), `/projects/{id}/share` (`:2232`) all exist and work today. This surface has **no generation endpoints of its own** — it's a professional editor with nowhere for AI output to land yet.

`CanvasSpec` already has `width`, `height`, `fps`, and — notably — `safe_margin_pct` (`models.py:176`), which is exactly the field a multi-aspect-ratio reflow needs and is unused today. `StyleKit` already has `palette`, `fonts`, `spacing`, `motion` (`models.py:179–187`) — this *is* the "brand identity" object; it just doesn't have a RuslanMV instance yet.

### The current generation loop

```text
StudioVideo.logline (one line, e.g. "a video about typed memory in AI agents")
        ↓
POST /videos/{id}/generate-outline   (GenerateOutlineRequest: target_scenes, scene_duration only — routes.py:941)
        ↓  LLM invents narration + image_prompt + negative_prompt per scene from the logline
StoryOutlineResponse  →  SceneOutline[] (scene_number, title, description, narration, image_prompt, ...)
        ↓
POST /videos/{id}/scenes/generate-from-outline   (routes.py:1545)
        ↓
backend/app/orchestrator.py :: orchestrate()  →  ComfyUI txt2img, optionally img2vid
        ↓
StudioScene.imageUrl / videoUrl / audioUrl populated
```

The narration is **invented by the LLM from a one-line description**. There is no path today for "here is the actual script, use these words." That's gap A.

> Correction vs. earlier drafts: `GenerateOutlineRequest` is defined in `backend/app/studio/routes.py:941`, **not** in `models.py`. Batch 0 places its additive fields there, where the class actually lives.

### ComfyUI already has more than its own docs admit

`comfyui/workflows/` contains, as files, right now: `txt2img.json` (SDXL, default), `txt2img-flux-dev.json`, `txt2img-flux-schnell.json`, `txt2img-sdxl-instantid.json`, `txt2img-sd15-instantid.json`, `txt2img-pony-xl.json`, `txt2img-sd15-uncensored.json`, `img2vid.json` (SVD, default), `img2vid-wan.json`, `img2vid-hunyuan.json`, `img2vid-ltx.json`, `img2vid-mochi.json`, `img2vid-cogvideo.json`, plus inpaint / outpaint / face-swap / face-fix / upscale / background tooling.

`backend/app/orchestrator.py`'s video branch (lines 999–1016) already does substring routing on the model name (`"ltx" → img2vid-ltx`, same for `wan`/`mochi`/`hunyuan`/`cogvideo`) — **the routing logic for every 2026-relevant open video model is already written and already correct.** But `backend/app/providers.py :: available_video_models()` (lines 53–62) — the list that actually reaches the UI dropdown — only returns three IDs: `svd`, `wan-2.2` *(commented "uncensored")*, and `seedream` *(commented "uncensored")*.

Two problems worth naming plainly: `seedream` has no backing workflow file at all (`img2vid-seedream.json` does not exist — `MODELS_README.md:98` still lists it as `[PLANNED]`; selecting it today would error), and the two non-default options are positioned for HomePilot's general entertainment/NSFW use cases, not a documentary technical channel. Meanwhile LTX-Video, Hunyuan Video, Mochi 1, and CogVideoX — all live workflow files with working routing — aren't offered anywhere. `MODELS_README.md` is stale the same way (it lists Wan as `[PLANNED]` at line 86 despite `img2vid-wan.json` existing). None of this needs new engineering — it's a documentation and three-line-list problem, addressed in Batch 3.

### Leave these exactly alone

- **NSFW governance** (`ContentRating` = `sfw`/`mature`, `PolicyMode` = `youtube_safe`/`restricted` — `models.py:19–20` — the genre library, `mature-guide`, "Spice Mode") is fully built; this feature pins itself to the safe end of it and never touches the mature path.
- **TTS**: HomePilot's in-app provider is Piper (`backend/app/voice/providers.py:57`, `PiperTTSProvider`) — separate from the external Kokoro-82M pipeline that already narrates ruslanmv.com essays (R2-hosted, Jekyll-integrated). These are two different systems; this design treats the existing essay audio as an *imported asset*, not something HomePilot's TTS generated.
- **`packages/compute-client`** — the OllaBridge-based remote GPU routing scaffold. Early and thin today; a good future offload target for heavy render jobs, not a dependency for this design.
- **`modelPresets.ts`** only knows four image architectures (`sd15`, `sdxl`, `flux_schnell`, `flux_dev`) — fine as-is for now; Batch 3 flags where it'll eventually need a `flux2_klein` / `sd35` entry.

## End to End (after all batches)

```text
ruslanmv.com essay (or pasted markdown) + existing audio (optional)
        │
        ▼
EssaySource ingestion  ──────────────────────────  backend/app/studio/essay_import.py  (NEW, Batch 0)
        │
        ▼
generate-outline, source_mode="script"  ─────────  segmentation + scene_kind, not invention  (EXTENDED, Batch 0/1)
        │
        ▼
WhisperX alignment (if audio provided)  ─────────  real durations + CaptionSegment rows  (NEW, Batch 2)
        │
        ├── scene_kind → diffusion ──────► ComfyUI txt2img/img2vid (EXISTING, model list fixed in Batch 3)
        │
        └── scene_kind → motion_graphic ─► Remotion component per archetype  (NEW, Batch 1)
        │
        ▼
promote-to-project  ──────────────────────────────  StyleKit + CanvasSpec × 3 + AudioTrack + Captions (NEW bridge, EXISTING Pro models, Batch 4)
        │
        ▼
Remotion final assembly, one composition, three canvases  ──  16:9 / 9:16 / 1:1 MP4  (Batch 4)
```

## Configuration & Deployment (cumulative across batches)

New environment variables, additive to whatever `.env` already has:

```bash
# Essay ingestion (Batch 0)
ESSAY_IMPORT_SOURCE=url          # or "repo" for direct Jekyll-source reads

# Forced alignment (Batch 2)
WHISPERX_MODEL=large-v3
WHISPERX_DEVICE=cuda

# TTS (Batch 2/4)
KOKORO_VOICE_ID=<voice matching the existing essay narration>
CHATTERBOX_ENABLED=false

# Model manager (Batch 3)
CIVITAI_API_KEY=<from developer.civitai.com>
MODEL_SOURCE_PREFERENCE=huggingface_first

# Remotion (Batch 1/4)
REMOTION_LICENSE_TIER=individual   # re-check if HomePilot itself scales past a few employees
```

## What Stays Exactly The Same (all batches)

- Every existing `/studio/videos/*` and `/studio/projects/*` endpoint, unchanged.
- The `video` / `slideshow` / `video_series` wizard flow for topic-mode (non-essay) projects — untouched, still the default.
- NSFW governance, genre library, "Spice Mode," Pony-XL/uncensored workflows — untouched, and explicitly excluded from this pipeline's model picker.
- Piper as HomePilot's default TTS for every project type other than this one.
- `packages/compute-client` / OllaBridge routing — a future offload target, not touched by this design.
- `modelPresets.ts`'s existing four architectures — untouched; a `flux2_klein` entry is the only addition implied, and it's additive.

## Risks (cross-batch)

- **Diffusion still occasionally drifts on text** even in motion_graphic-adjacent shots that touch diffusion output (e.g. a diffusion background behind a Remotion-rendered label). Mitigation is architectural (Batch 1), not a prompting fix — keep text-bearing content on the deterministic path, full stop.
- **Per-model licensing drift.** A model manager that doesn't check licenses will eventually pull something not cleared for a monetized channel. Batch 3's allowlist check exists specifically to prevent this, not as a formality.
- **Civitai policy/regional volatility.** Mitigated by treating Civitai as a style-layer source and Hugging Face as the base-checkpoint source (Batch 3).
- **Remotion's license tier.** Free today for solo/tiny-team use; worth re-checking if HomePilot the product scales into something with more than a couple of people touching it commercially.
- **Voice mismatch across formats.** Mitigated by pinning Kokoro (same voice as the source essay) across every variant of a given essay, rather than letting Shorts default to Piper (Batch 2/4).

## Files Touched (complete list, cumulative)

**New files**
```text
backend/app/studio/essay_import.py         (EssaySource, EssaySection, URL + repo ingestion)      Batch 0
backend/app/studio/model_manager.py        (Civitai + HF model manager)                           Batch 3
frontend/src/ui/studio/remotion/*          (DiagramScene, ProofScene, QuoteScene, CTAScene)       Batch 1
```

**Modified — additive fields/values only, no removals**
```text
backend/app/studio/models.py               (+SourceMode, +RendererKind,
                                             +PlatformPreset.social_1_1, +ProjectType.social_teaser)   Batch 0/1/4
backend/app/studio/routes.py               (+GenerateOutlineRequest fields + source_mode branch,
                                             +POST /videos/{id}/promote-to-project)                    Batch 0/4
backend/app/orchestrator.py                (no routing logic changes needed — already handles
                                             ltx/wan/mochi/hunyuan/cogvideo by name)
backend/app/providers.py                   (available_video_models(): +3 entries, -1 vaporware entry)  Batch 3
backend/app/voice/providers.py             (+Kokoro provider, alongside existing Piper)                Batch 2
frontend/src/ui/CreatorStudioHost.tsx      (+"Technical / Editorial" visualStyle,
                                             +PlatformPreset.social_1_1 — keep in sync with models.py) Batch 0/4
comfyui/workflows/MODELS_README.md         (rewrite video section to match actual files + routing)     Batch 3
```

**Not modified**
```text
Everything under NSFW governance, the genre/preset library, "Spice Mode"
The video / slideshow / video_series topic-mode wizard flow
Every existing /studio/projects/* Pro endpoint (assets, audio, captions, versions, share)
packages/compute-client
modelPresets.ts's existing four architectures
```
