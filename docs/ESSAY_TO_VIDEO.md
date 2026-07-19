# Essay-to-Video Pipeline — Production Guide

Turn a ruslanmv.com essay (or any markdown script) into a full-length YouTube
video, a 9:16 Short, and a 1:1 teaser. The essay's own sentences become the
narration — verbatim, guaranteed by construction — and text-bearing scenes
(diagrams, quotes, data, CTAs) render deterministically so a label can never
be misspelled.

Design series: [`docs/design/essay-to-video/`](./design/essay-to-video/README.md)
(Batches 0–4, all implemented). Tests: `backend/tests/test_essay_pipeline.py`.

## What runs where

| Capability | Requirement | Without it |
|---|---|---|
| Essay ingestion (URL or markdown), verbatim segmentation, scene classification | nothing extra | — |
| Motion-graphic scene stills (diagram/proof/quote/CTA) | nothing extra (Pillow) | — |
| Animated motion graphics + final MP4 assembly at 16:9/9:16/1:1 | Node 18+, one `npm install` in the Remotion workspace | stills only |
| LLM shot planning + Short beat selection | Ollama running | deterministic fallbacks (used automatically) |
| Diffusion hero/atmosphere shots | ComfyUI + a video model (see `comfyui/workflows/MODELS_README.md`) | motion-graphic title cards |
| Word-accurate scene timing + captions | `pip install whisperx` (GPU recommended) | proportional timing (still sentence-cut) |
| Short-form audio in the essay's voice | `pip install kokoro` + `KOKORO_VOICE_ID` | no new TTS; full-length still reuses the essay's existing mp3 |

Optional backend extras: `pip install -r backend/requirements-essay.txt`.
Config: the "ESSAY-TO-VIDEO PIPELINE" section of `.env.example`.

## The flow

1. **Create a Video project** in Creator Studio; in the Details step pick
   **Script Source → Essay / Script** and paste the essay markdown or its URL
   (optionally the existing narration audio URL). The visual style locks to
   **Technical / Editorial** (the `ruslanmv-essays` StyleKit).
2. **Generate the outline** — `POST /studio/videos/{id}/generate-outline` with
   `source_mode="script"`. Narration is segmented verbatim; each scene gets a
   `scene_kind` and a `rendererKind`. With audio, scene durations come from
   forced alignment and word timestamps persist for captions.
3. **Render scenes** in the editor. Motion-graphic scenes render via
   `POST .../scenes/{sceneId}/render-motion-graphic` (the editor routes them
   automatically); diffusion scenes go through the normal generate path.
   The per-scene Renderer toggle overrides the default either way.
4. **Condensed script for the Short/teaser** —
   `POST /studio/videos/{id}/condensed-script` picks the Hook → Problem →
   Core → Proof → CTA subset (selection, never rewriting) and synthesizes
   audio with the pinned Kokoro voice.
5. **Promote to Creator Studio Pro** —
   `POST /studio/videos/{id}/promote-to-project` materializes the project:
   style kit, assets, voiceover track, caption rows, one canvas per format,
   and the per-scene aspect plan (motion graphics reflow; diffusion
   regenerates natively per aspect — never crops).
6. **Final assembly** — render the master timeline at any of the three
   canvases:

   ```bash
   ./scripts/render-essay-assembly.sh youtube-16-9 props.json out/full.mp4
   ./scripts/render-essay-assembly.sh shorts-9-16 short-props.json out/short.mp4
   ./scripts/render-essay-assembly.sh social-1-1  short-props.json out/teaser.mp4
   ```

   Props shape: `{"scenes": [...], "audioUrl": "...", "captions": [...]}` —
   see `frontend/src/ui/studio/remotion/README.md`. The promoted project's
   version snapshot (`state.scenes`, `state.canvases`, captions via
   `GET /studio/projects/{id}/captions`) contains everything the props need.

## Model management

`POST /studio/models/manager/install` downloads and registers models with
hash verification and a license allowlist (Hugging Face for base
checkpoints, civitai.com for LoRAs — never civitai.red). Unlicensed models
are refused, and the essay pipeline's pickers never show the mature-lane
models. `GET /studio/models/manager/status` shows what's installed and why
something is blocked.

### Bundles (recommended: one-shot install of everything you need)

Instead of installing models one at a time, install a **bundle** — the
curated set of diffusion models the pipeline needs, with GPU-tuned presets:

```bash
curl http://localhost:8000/studio/models/manager/bundles          # list + status
curl -X POST .../studio/models/manager/bundles/essay-video-4080-high/install
```

Three bundles ship: `essay-video-core` (~16GB, any 8GB+ GPU),
`essay-video-4080-high` (~27GB, everything native on a 12GB laptop 4080),
and `essay-video-4080-ultra` (~72GB, adds Wan 2.2 / Hunyuan hero-shot
models). Reinstalling a bundle repairs a partial install — the underlying
catalog installer skips files already on disk. Full analysis, the model
compatibility table, and the high/ultra generation presets:
[`docs/ESSAY_VIDEO_BUNDLES.md`](./ESSAY_VIDEO_BUNDLES.md).

## Production notes

- **Everything is additive.** Topic-mode projects, NSFW governance, Piper
  TTS defaults, and all existing endpoints behave exactly as before.
- **Security**: local filesystem paths in `existing_audio_url` are refused
  unless `STUDIO_ALLOW_LOCAL_AUDIO=true` (single-user installs only). The
  file-serving endpoints (`/studio/motion-graphics/*`,
  `/studio/files/essay-pipeline/*`) use strict filename allowlists.
- **Remotion license**: free for individuals/small teams
  (`REMOTION_LICENSE_TIER=individual`); re-check before shipping to a
  broader commercial user base.
- **Tests**: `cd backend && pytest tests/test_essay_pipeline.py` — 26 tests,
  no network/GPU/LLM needed, ~2s.
