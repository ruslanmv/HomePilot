# Batch 3 — Model Manager (Civitai + Hugging Face) and Model-List Fixes

**Status:** design only — no implementation in this batch document.
**Depends on:** nothing hard (independent of Batches 1–2); dual-aspect hero generation pairs naturally with Batch 4.
**Proves:** "download more models via Civitai" is an actual button instead of a `wget`, with license gating; the video-model dropdown finally matches what the workflows can already do.

---

## 1. What exists today vs. what's proposed

Today: `comfyui/workflows/MODELS_README.md` documents a manual process (`wget` a URL, hand-edit `available_image_models()` in `backend/app/providers.py`, hand-edit the workflow map in `backend/app/orchestrator.py`). Fine for a developer adding one model occasionally; not what "download more models via Civitai if needed" implies.

New, small service — `backend/app/studio/model_manager.py`:

```python
class ModelManager:
    """Wraps the official Civitai REST API (developer.civitai.com/site/reference)
    and Hugging Face Hub downloads. Verifies hashes, registers models into the
    existing available_image_models()/available_video_models() + workflow map,
    never touches the mature/anime workflow set."""

    def search_civitai(self, query: str, sfw_only: bool = True) -> list[CivitaiModelSummary]: ...
    def download_by_version_id(self, version_id: int, api_key: str) -> InstalledModel: ...
    def download_from_huggingface(self, repo_id: str, filename: str) -> InstalledModel: ...
    def register(self, model: InstalledModel) -> None:
        """Appends to available_image_models()/available_video_models() and the
        orchestrator's workflow map; verifies the checkpoint's declared license
        against an allowlist before the model becomes selectable in this pipeline."""
```

## 2. Three sourcing rules specific to this pipeline

1. **civitai.com, not civitai.red.** Civitai split into two front doors in 2026 — `.com` is the PG/PG-13 surface, `.red` carries the broader (including NSFW) catalog. This pipeline is 100% SFW content; there's no reason to ever touch `.red`, and the manager hard-codes that.
2. **Hugging Face first for base checkpoints, Civitai for style layers.** FLUX.2, SD 3.5, Wan 2.2, and Qwen-Image all have official Hugging Face repos — use those for the foundation models, and reserve Civitai specifically for community LoRAs and style finetunes layered on top (the actual "brand look" tuning). This also sidesteps Civitai's occasional regional access changes (it blocked Australian users in March 2026 over local age-verification law) — not a concern for Italy today, but not a dependency worth building the base-model path on either. Encoded as `MODEL_SOURCE_PREFERENCE=huggingface_first`.
3. **Never surface the existing mature-lane models here.** `available_image_models()` / `available_video_models()` (`providers.py:40–62`) already include Pony-XL and the uncensored SD1.5/video entries for HomePilot's general use case — the essay pipeline's model picker filters those out entirely, not just defaults away from them.

## 3. License check before a model becomes selectable

| Model | License | Note |
|---|---|---|
| FLUX.2 [klein] (4B) | Apache 2.0 | free commercial use — default image model |
| FLUX.2 [dev] (32B) | BFL non-commercial (paid license for commercial) | manual/occasional hero shots only, verify license before use in a monetized channel |
| SD 3.5 Large | Stability Community License | free under $1M annual revenue — fine here |
| Wan 2.2 | Apache 2.0 | free commercial use |
| Mochi 1 | Apache 2.0 | free commercial use |
| Qwen-Image 2.0 | verify at integration time | not yet confirmed in this design |

**The manager refuses to register a model into this pipeline's allowlist without a resolved license row.** This is the guard against per-model licensing drift — a manager that doesn't check licenses will eventually pull something not cleared for a monetized channel.

## 4. Fixing the stale model list while we're here

Verified state of the repo today:

- `comfyui/workflows/` already contains `img2vid-wan.json`, `img2vid-hunyuan.json`, `img2vid-ltx.json`, `img2vid-mochi.json`, `img2vid-cogvideo.json` as real files.
- `backend/app/orchestrator.py:999–1016` already routes by model-name substring to every one of those workflows — the routing logic is written and correct.
- But `available_video_models()` (`providers.py:53–62`) only returns `svd`, `wan-2.2` *(commented "uncensored")*, and `seedream` — and **`img2vid-seedream.json` does not exist** (`MODELS_README.md:98` still marks it `[PLANNED]`); selecting it today would error.
- `MODELS_README.md:86` likewise still marks Wan as `[PLANNED]` even though its workflow file exists.

Three changes — pure documentation-and-registration debt, not new engineering:

1. Add `"ltx-video"`, `"hunyuan-video-1.5"`, `"mochi-1"` to `available_video_models()`; **drop `"seedream"`** (no backing workflow exists — this is the one removal in the whole design, and it removes only a vaporware entry that errors if selected, so it is corrective, not destructive; if a workflow file appears later, the ModelManager registers it properly).
2. Rewrite `MODELS_README.md`'s video section to match what `comfyui/workflows/` actually contains and how `orchestrator.py` actually routes.
3. Stop labeling `wan-2.2` `(uncensored)` in the source comment — the model itself is general-purpose; that framing is a leftover from a different use case and will confuse anyone reading the list for a documentary pipeline.

`orchestrator.py` needs **zero routing changes** — it already handles `ltx`/`wan`/`mochi`/`hunyuan`/`cogvideo` by name.

## 5. Dual-aspect diffusion generation for hero shots

Cropping a 16:9 diffusion frame down to 9:16 usually cuts off whatever the shot was about. Cheaper and better: generate two native passes from the same seed and (where the model supports it) the same IPAdapter/reference image — one 16:9, one 9:16 — so the composition is right for both instead of centered-and-hoping. This roughly doubles diffusion cost for hero shots only, which are a minority of scenes given Batch 1's renderer split. (Consumed by Batch 4's multi-format output.)

## 6. Model & hardware recommendations (mid-2026)

### Video diffusion

| Model | License | VRAM (practical) | Use in this pipeline |
|---|---|---|---|
| Wan 2.2 (TI2V-5B) | Apache 2.0 | ~24GB, runs on RTX 4090 | default for hero/atmosphere shots — best quality-to-compute ratio, T2V+I2V+editing in one model |
| LTX-Video | open, community license | 12GB+ | fast draft passes before committing to a final render |
| HunyuanVideo 1.5 | community license | ~14GB with offloading | occasional highest-quality hero shot when the extra render time is worth it |
| Mochi 1 | Apache 2.0 | high-end (A100/H100 for full quality) | only if heavier compute is available; not a default |
| CogVideoX-5B | open | lower / lighter | fallback for constrained hardware, softer output |

### Image diffusion

| Model | License | VRAM | Use |
|---|---|---|---|
| FLUX.2 [klein] (4B) | Apache 2.0 | ~8GB | default stills for hero/thumbnail shots |
| FLUX.2 [dev] (32B) | paid commercial license | ~32GB (FP8) | occasional premium hero shot, license-gated |
| SD 3.5 Large | Stability Community | 12–16GB | best LoRA/ControlNet ecosystem if custom style training is wanted |
| Qwen-Image 2.0 | verify | ~moderate | worth evaluating specifically for quote-card text fidelity |

`frontend/src/ui/modelPresets.ts` currently knows four image architectures (`sd15`, `sdxl`, `flux_schnell`, `flux_dev`) — untouched by this batch; a `flux2_klein` (and eventually `sd35`) entry is the only addition implied when those models are actually installed, and it's additive.

### GPU

For this specific workload — a solo creator's pipeline, LLM calls already going through hosted providers via the existing multi-provider router, local GPU only doing image/video diffusion and Remotion's headless-Chrome rendering:

- **RTX 4090 (24GB)** is the realistic sweet spot right now: comfortably runs FLUX.2 [klein], SDXL, SD3.5, Wan 2.2's TI2V-5B variant, and LTX-Video; used-market pricing is currently well under the 5090.
- **RTX 5090 (32GB)** is worth it specifically if hero-shot video generation becomes frequent enough that its ~45% faster image-to-video inference and hardware AV1 encode matter, or if HunyuanVideo's full 13B / Mochi 1 become regular choices rather than occasional ones. As of mid-2026 there's an unusually wide gap between the 5090's MSRP and its street price due to a GDDR7 memory shortage — check current pricing before buying rather than assuming MSRP.
- For occasional heavy jobs beyond either card, cloud burst (the kind of on-demand GPU rental already discussed in the OllaBridge compute-network plan, `packages/compute-client`) is more sensible than over-provisioning local hardware for peak-only demand. That scaffold stays untouched by this design — future offload target only.

## 7. Files touched in this batch

**New:** `backend/app/studio/model_manager.py`
**Modified (additive/corrective only):**
- `backend/app/providers.py` — `available_video_models()`: `+ltx-video`, `+hunyuan-video-1.5`, `+mochi-1`; `−seedream` (vaporware entry, errors today); comment cleanup on `wan-2.2`
- `comfyui/workflows/MODELS_README.md` — rewrite video section to match actual files + routing
- `backend/app/orchestrator.py` — **no routing changes** (documented here to make the no-op explicit)

**Config:** `CIVITAI_API_KEY=...`, `MODEL_SOURCE_PREFERENCE=huggingface_first`

## 8. Acceptance criteria

1. Selecting `ltx-video`, `hunyuan-video-1.5`, or `mochi-1` in the dropdown routes to the correct existing workflow JSON with no orchestrator edits.
2. `seedream` no longer appears (and can no longer produce the current selection error).
3. `search_civitai(sfw_only=True)` never returns `.red`-catalog entries; the manager refuses `register()` for any model without a resolved license row.
4. The essay pipeline's model picker never lists Pony-XL or the uncensored SD1.5/video entries; HomePilot's general picker still does (untouched).
5. A model downloaded via the manager appears in the correct `available_*_models()` list and workflow map without any hand-editing.

## 9. Risks specific to this batch

- **Per-model licensing drift** — mitigated by the mandatory license allowlist in `register()`.
- **Civitai policy/regional volatility** — mitigated by `huggingface_first` for base checkpoints; Civitai is style-layer only.
