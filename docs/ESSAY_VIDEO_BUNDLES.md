# Essay-Video Model Bundles & RTX 4080 Presets

The diffusion models the essay-video pipeline needs, packaged as one-click
(re)installable bundles with generation presets tuned per GPU. Defined in
`backend/app/studio/bundles.py`; served under `/studio/models/manager/bundles`.

## The analysis: which models are essay-video compatible

Of every diffusion model HomePilot knows (`model_catalog_data.json` +
`comfyui/workflows/` + orchestrator routing), a model qualifies for essay
video only if it is **SFW**, has a **resolved commercial license**, ships a
**real workflow file**, and has **working name-based routing** in
`orchestrator.py`. That yields:

| Model | Role | License | 12GB laptop 4080 | Why it's in |
|---|---|---|---|---|
| **SDXL Base 1.0** | image | CreativeML Open RAIL++-M | native | Reliable branded stills; the default |
| **Flux.1 Schnell** | image | Apache-2.0 | offload (still fast, 4-step) | Sharper text-adjacent stills |
| **SVD-XT** | video | Stability Community | native (25 frames) | Compatibility/fallback img2vid |
| **LTX-Video 2B** | video | LTX community | **native** | The 12GB star — fast *and* final quality |
| **Wan 2.2 TI2V-5B** | video | Apache-2.0 | offload | Best open quality-per-compute; hero shots |
| **HunyuanVideo Q4 GGUF** | video | Tencent community | offload | Occasional premium hero shot |

**Excluded, and why:** Mochi 1 (A100-class VRAM), CogVideoX (softer output —
LTX is the better 12GB choice), Flux.1 Dev (non-commercial license + won't
fit 12GB), Pony-XL / uncensored SD1.5 (mature lane — the pipeline filters
these out by design).

## The three bundles

| Bundle | Disk | Target | Contents |
|---|---|---|---|
| `essay-video-core` | ~16 GB | any 8GB+ GPU | SDXL + SVD-XT + VHS. The Phase-0 proof path. |
| `essay-video-4080-high` | ~27 GB | **RTX 4080 Laptop (12GB)** | SDXL + LTX + SVD, all native. The daily driver. |
| `essay-video-4080-ultra` | ~72 GB | 4080 Laptop (offload) / desktop (16GB native) | Adds Flux Schnell + Wan 2.2 + Hunyuan for hero shots. |

> **RTX 4080 Laptop = 12GB. Desktop 4080 = 16GB.** These are different cards.
> The `high` bundle is everything-native on the 12GB laptop; `ultra` adds
> models that run via ComfyUI weight-offloading on 12GB (slower, not lower
> quality) and natively on the 16GB desktop.

## Presets (best-practice generation specs)

Every bundle carries `high` / `ultra` presets — exact width, height, steps,
cfg, frames, fps, and ComfyUI launch flags. The 4080-Laptop numbers:

### `essay-video-4080-high`

| | HIGH | ULTRA |
|---|---|---|
| Stills | SDXL 1344×768, 30 steps, cfg 6.5 | SDXL 1536×864, 40 steps, cfg 7.0 |
| Video | LTX 768×512, 97f @24fps, 25 steps, cfg 3.0 | LTX 1024×576, 121f @24fps, 30 steps |
| Speed | ~35s/still, ~1min/4s clip (native) | ~1min/still, ~3min/5s clip |
| Flags | — | `--preview-method none` |

### `essay-video-4080-ultra`

| | HIGH (volume scenes) | ULTRA (hero shots) |
|---|---|---|
| Stills | Flux Schnell 1344×768, **4 steps, cfg 1.0** | same |
| Video | LTX 768×512, 97f @24fps | **Wan 2.2** 1280×704, 81f @24fps, cfg 5.0 |
| Speed | stills ~45s, clips ~1min | ~10–15min/3s clip (12GB offload); ~4min native on 16GB |
| Flags | — | `--lowvram --preview-method none` |

**Best-practice notes baked into the presets:**
- Flux Schnell is distilled — keep it at **4 steps / cfg 1.0**; more of
  either wastes time and degrades output (a test enforces this).
- Reserve Wan/Hunyuan for the diffusion **hero/transition** scenes only —
  a minority after the renderer split. Diagrams, quotes, proofs, and CTAs
  render deterministically and never touch diffusion.
- LTX at 24fps/97 frames ≈ 4s clips, matching the pipeline's per-scene beat
  length — so `high` is genuinely a finals tier on 12GB, not just drafts.

## (Re)installing a bundle

```bash
# list bundles, disk cost, install status, presets
curl http://localhost:8000/studio/models/manager/bundles

# install (or repair) everything the pipeline needs
curl -X POST http://localhost:8000/studio/models/manager/bundles/essay-video-4080-high/install
# -> {"id": "<job>", ...}; poll:
curl http://localhost:8000/studio/models/manager/jobs/<job>
```

Reinstall is **safe and idempotent**: a bundle install shells the existing
`scripts/download.py` per component (addons first, then models), and that
installer skips files already on disk — so the same command repairs a
partial install or re-hydrates a fresh machine. `model_catalog_data.json`
stays the single source of download URLs; bundles just group + order the
catalog ids and attach the presets.

## Applying a preset

`GET /studio/models/manager/bundles/{id}` returns the presets; the wizard/
editor apply `image_width`/`image_steps`/`image_cfg` (and the video
equivalents) through the existing generation params — the same
`imgWidth`/`imgSteps`/`imgCfg` the advanced settings already send. Start
ComfyUI with the preset's `comfyui_flags` for the ultra tier.
