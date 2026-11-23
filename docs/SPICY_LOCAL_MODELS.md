# Spicy mode: local models

Spicy (adult) mode used to change only the prompts. The models stayed whatever was selected, so an
explicit request could land on a model that cannot follow it (SDXL base, Flux, SVD), and edits ran
img2img on the image checkpoint. This batch gives Spicy mode its own **local** model set and picks
from it when the person has not chosen a model. Nothing here sends a request off the machine;
remote adult providers are a separate, later step.

## The set

The fewest downloads that cover every capability on one consumer GPU (12–24 GB):

| Capability | Spicy default (best first)                                   | Size    | Notes                                                    |
| ---------- | ------------------------------------------------------------ | ------- | -------------------------------------------------------- |
| Chat       | `huihui_ai/qwen3-abliterated:8b`, `dolphin3`                  | ~5 GB   | Ollama; already in the catalog                           |
| Vision     | `huihui_ai/qwen3-vl-abliterated:8b-instruct`                  | 5 GB    | Ollama; already in the catalog                           |
| Image      | `ponyDiffusionV6XL`, `noobaiXL_vPred10`, **`Chroma1-HD`**     | 6–23 GB | Chroma is new: Apache 2.0, Flux-derived, real CFG        |
| Edit       | **`qwen-image-edit-2511-Q4_K_M.gguf`**                        | 23 GB   | New: edits from words, no mask; needs ComfyUI-GGUF       |
| Video      | **`wan2.2_i2v_14b_fp8_pack`**, `wan2.2_5b_fp16_pack`          | 38 / 22 GB | 14B is new (two experts, 4-step LoRAs); 5B for small cards |

The list lives in `backend/app/model_catalog_data.json` → `spicy_defaults`. Bold entries are new
catalog packs (`install.type: hf_files`), installed from Settings → Models like any other pack.

## Two flags, on purpose

- `nsfw: true` — **adult-oriented**. Hidden when Spicy mode is off (`Models.tsx`) and refused by the
  essay pipeline (`studio/model_manager.py`).
- `adult_capable: true` — **general-purpose, and also follows adult prompts**. Shown everywhere and
  allowed everywhere; the flag only lets Spicy mode use it. Chroma, Qwen-Image-Edit, Wan 2.2
  (5B and 14B) and HunyuanVideo carry this one. Marking them `nsfw` hid Wan and Hunyuan from
  everyone else and broke the essay video bundle.

`recommended_nsfw: true` puts the set first in the model lists while Spicy mode is on.

## How a model is chosen (`backend/app/spicy_defaults.py`)

- **A model the person picked always wins.** Defaults only fill gaps.
- **Image and video:** with no model in the request and Spicy mode on, the first installed default.
- **Edit** has no picker. In Spicy mode an edit **without a mask** runs on Qwen-Image-Edit when it
  is installed (`edit-qwen` workflow). A masked edit keeps the inpaint workflows, which honour the
  mask, and naming another checkpoint with `--ckpt` keeps img2img. Naming the Qwen editor selects
  it in any mode.
- **Only installed models are chosen.** A pack counts as installed when its *last* file is on disk
  (`providers.scan_installed_models`), so a half-finished download is not used. With nothing
  installed, the old behaviour stands.

## Workflows

| File                                     | Model                | Notes                                                                 |
| ---------------------------------------- | -------------------- | --------------------------------------------------------------------- |
| `comfyui/workflows/txt2img-chroma.json`  | Chroma1-HD           | Loads the bf16 weights as FP8 to fit 12–16 GB; euler/beta, CFG ~4     |
| `comfyui/workflows/edit-qwen.json`       | Qwen-Image-Edit 2511 | Input scaled to ~1 MP; Lightning LoRA, so 4 steps at CFG 1            |
| `comfyui/workflows/img2vid-wan22-14b.json` | Wan 2.2 14B I2V    | High-noise expert steps 0–2, low-noise 2–4; Wan 2.1 VAE               |
| `comfyui/workflows/img2vid-wan.json`     | Wan 2.2 5B           | **Fixed**: loaded files the pack never installs and ignored the image |

Node and input names were checked against ComfyUI's source (`comfy_extras/nodes_wan.py`,
`nodes_qwen.py`, `nodes_cond.py`, …). `tests/test_spicy_local_models.py` checks that each workflow
loads only files its pack installs, that every link and `{{placeholder}}` resolves, and the
selection rules above.

**Not yet run on a GPU.** Before relying on them, generate once with each new workflow on a real
ComfyUI and look at the result.

## Adding a model to the set

1. Add the catalog entry (with `install`), marked `nsfw` or `adult_capable`.
2. Add it to `spicy_defaults` in the order it should be preferred.
3. If it needs its own workflow, add the file and the dispatch (image: the `chroma`-style
   architecture in `model_config.py` and the four image workflow tables; video: the substring
   tables in `orchestrator.py` and `render_adapter.py`).
4. Point `providers.scan_installed_models` at the pack's last file.
5. Regenerate the frontend copy: `node frontend/scripts/generate-model-catalog.mjs`.
