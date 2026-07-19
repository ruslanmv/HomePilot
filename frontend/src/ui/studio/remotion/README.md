# Motion-Graphic Compositions (Essay-to-Video, Batch 1)

Deterministic, code-driven scene renderers for the `motion_graphic` half of
the hybrid rendering split (`docs/design/essay-to-video/BATCH-1-hybrid-rendering.md`).
Diagram, proof, quote, and CTA scenes render from structured data - the
essay's own words, StyleKit colors, safe-margin-relative layout - so a label
can never be misspelled: there is no sampling step between the text and the
pixels.

## Relationship to the backend renderer

`backend/app/studio/motion_graphics.py` renders a **PNG still** from the
same props contract (see `types.ts`) using Pillow - that's what the
`POST /studio/videos/{id}/scenes/{sceneId}/render-motion-graphic` endpoint
serves today, and it slots into the existing img2vid / Ken Burns / MP4
export paths. This workspace renders the **animated** version of the same
scenes. Keep `types.ts` and `MotionGraphicSpec` in sync.

## This is a standalone workspace

Deliberately **not** part of the main frontend build - the main app never
imports Remotion (this directory is excluded in `frontend/tsconfig.json`).
Install and run it on its own:

```bash
cd frontend/src/ui/studio/remotion
npm install

# Interactive preview of all archetype x canvas combinations
npx remotion studio

# Render one scene
npx remotion render Diagram-youtube-16-9 out/scene-04.mp4 \
  --props='{"kind":"diagram","title":"The Architecture","narration":"The extractor pulls typed records. The registry validates them. The router picks a memory expert."}'
```

Composition IDs are `{Diagram|Proof|Quote|CTA}-{youtube-16-9|shorts-9-16|social-1-1}`.
Same component, three canvases - layout reflows via `safeMarginPct`
(`CanvasSpec.safe_margin_pct`), never via per-format authoring.

## Master assembly (Batch 4)

`Assembly-{canvas}` (hyphenated canvas ids) renders the full timeline: diffusion scenes drop in as
their rendered image/video (`OffthreadVideo`/`Img`, regenerated natively
per aspect per the promote-to-project `aspect_plan` - never cropped),
motion-graphic scenes nest the archetype compositions, the voiceover
audio track plays underneath, and an always-on caption track (the
`ruslanmv-essays` StyleKit motion rule) renders the cues materialized
from the WhisperX alignment. Duration follows the scene list via
`calculateMetadata`.

```bash
npx remotion render Assembly-youtube-16-9 out/full.mp4 --props=props.json
# props.json: {"scenes":[...], "audioUrl":"...", "captions":[...]}
# same props, vertical + square:
npx remotion render Assembly-shorts-9-16 out/short.mp4 --props=short-props.json
npx remotion render Assembly-social-1-1 out/teaser.mp4 --props=short-props.json
```

## License note

Remotion is free for individuals and small teams; a company license is
required past that. Tracked as `REMOTION_LICENSE_TIER` in the deployment
config - re-check if HomePilot itself ships this to a broader user base
(see the risk list in `docs/design/essay-to-video/README.md`).
