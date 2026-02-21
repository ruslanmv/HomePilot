# InstantID "Same Person" Workflow (HomePilot)

## Goal

Enable "Generation mode: Same Person" so that:
- "Generate 4 more" preserves identity (face)
- Outfit / wardrobe variations preserve identity

## When this workflow should run

Only when:
- `payload.generation_mode == "identity"` **AND**
- `payload.reference_image_url` is provided (selected avatar image)

Otherwise, fall back to the existing standard txt2img workflow.

## Required variables (passed from backend to ComfyUI workflow)

| Variable | Type | Description |
|----------|------|-------------|
| `prompt` | string | Positive prompt text |
| `negative_prompt` | string | Negative prompt text |
| `width` | int | Output image width |
| `height` | int | Output image height |
| `steps` | int | Sampling steps |
| `cfg` | float | Classifier-free guidance scale |
| `seed` | int | Random seed |
| `ckpt_name` | string | Checkpoint filename |
| `batch_size` | int | Number of images (usually 1 or 4) |
| `reference_image_url` | string | Must point to an image ComfyUI can load |
| `identity_strength` | float | Recommended default 0.85 |

## Workflow files

- `comfyui/workflows/txt2img-sd15-instantid.json` — SD 1.5 architecture
- `comfyui/workflows/txt2img-sdxl-instantid.json` — SDXL architecture

## ComfyUI custom node requirements

Requires **cubiq/ComfyUI_InstantID** (`make install` clones it automatically).
Install manually if needed: `git clone https://github.com/cubiq/ComfyUI_InstantID.git ComfyUI/custom_nodes/ComfyUI-InstantID`

Also requires `insightface` and `onnxruntime` in the ComfyUI venv (`make install` handles this).

Node class names used by the workflows (from cubiq's NODE_CLASS_MAPPINGS):

| class_type | Purpose |
|------------|---------|
| `InstantIDFaceAnalysis` | Loads InsightFace analysis model (AntelopeV2) |
| `InstantIDModelLoader` | Loads InstantID IP-Adapter model (`ip-adapter.bin`) |
| `ControlNetLoader` | Loads InstantID ControlNet (built-in ComfyUI node) |
| `ApplyInstantID` | Applies identity conditioning to model (works for both SD1.5 and SDXL) |

Model files expected (downloaded via `make download-avatar-models-basic`):

| File | Location |
|------|----------|
| `ip-adapter.bin` | `models/comfy/instantid/ip-adapter.bin` |
| `diffusion_pytorch_model.safetensors` | `models/comfy/controlnet/InstantID/diffusion_pytorch_model.safetensors` |
| `antelopev2.zip` (extracted) | `models/comfy/insightface/models/` |

## Best practice UX behavior

- If identity mode is selected but `reference_image_url` is missing:
  show "Pick an avatar to lock identity" and run standard generation for the first batch.
- After user selects an avatar, "Generate 4 more" should include `reference_image_url`.

## Backend routing

The orchestrator routes to these workflows based on `generation_mode` and checkpoint
architecture:

```python
if generation_mode == "identity" and reference_image_url:
    workflow_map_identity = {
        "sd15": "txt2img-sd15-instantid",
        "sdxl": "txt2img-sdxl-instantid",
    }
    workflow_name = workflow_map_identity.get(architecture, workflow_name)
```

Unsupported architectures (Flux, etc.) fall back to the standard workflow with a
log message.
