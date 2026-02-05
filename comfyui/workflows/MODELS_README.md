# ComfyUI Workflow Model Requirements

This document lists the model files required for each workflow in this directory.

## Image Generation Workflows

### txt2img.json (SDXL - Default)
**Required Models:**
- `checkpoints/sd_xl_base_1.0.safetensors`

**Download:**
```bash
# From Hugging Face
wget -P models/checkpoints/ https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors
```

### txt2img-flux-schnell.json (Flux Schnell - Fast Uncensored)
**Required Models:**
- `unet/flux1-schnell.safetensors`
- `clip/t5xxl_fp16.safetensors`
- `clip/clip_l.safetensors`
- `vae/ae.safetensors`

**Download:**
```bash
# Flux models from Black Forest Labs
wget -P models/unet/ https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors
wget -P models/clip/ https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors
wget -P models/clip/ https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors
wget -P models/vae/ https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors
```

### txt2img-flux-dev.json (Flux Dev - High Quality Uncensored)
**Required Models:**
- `unet/flux1-dev.safetensors`
- `clip/t5xxl_fp16.safetensors`
- `clip/clip_l.safetensors`
- `vae/ae.safetensors`

**Download:**
```bash
# Flux Dev model (requires HuggingFace token and agreement to terms)
# Same CLIP and VAE as Flux Schnell
wget -P models/unet/ https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors
```

### txt2img-pony-xl.json (Pony Diffusion XL - NSFW Optimized)
**Required Models:**
- `checkpoints/ponyDiffusionV6XL_v6.safetensors`

**Download:**
```bash
# Download from CivitAI (requires account)
# URL: https://civitai.com/models/257749/pony-diffusion-v6-xl
# Manual download required - place in models/checkpoints/
```

**Special Notes:**
- Pony XL requires specific prompt format
- Use score tags: `score_9, score_8_up, score_7_up` at start of prompt
- Negative prompt should include: `score_6, score_5, score_4`

### txt2img-sd15-uncensored.json (SD 1.5 - Lightweight Uncensored)
**Required Models:**
- `checkpoints/dreamshaper_8.safetensors` (or any SD 1.5 checkpoint)

**Download:**
```bash
# Dreamshaper 8 (example uncensored SD1.5 model)
# Download from CivitAI: https://civitai.com/models/4384/dreamshaper
# Or use any other SD 1.5 checkpoint
```

## Video Generation Workflows

### img2vid.json (SVD - Default)
**Required Models:**
- `checkpoints/svd.safetensors`

**Download:**
```bash
# Stable Video Diffusion
wget -P models/checkpoints/ https://huggingface.co/stabilityai/stable-video-diffusion-img2vid/resolve/main/svd.safetensors
```

### img2vid-wan.json (WAN 2.2 - Uncensored Video) [PLANNED]
**Required Models:**
- `checkpoints/wan-2.2.safetensors` or `wanxian-2.2.safetensors`

**Download:**
```bash
# Search for "Wanxian 2.2" or "WAN 2.2" on:
# - https://civitai.com/
# - https://huggingface.co/
# Note: This workflow may need to be created based on the model's requirements
```

### img2vid-seedream.json (Seedream - Uncensored Video) [PLANNED]
**Required Models:**
- `checkpoints/seedream-4.0.safetensors` or newer

**Download:**
```bash
# Search for "Seedream" on:
# - https://civitai.com/
# - https://huggingface.co/
# Note: This workflow may need to be created based on the model's requirements
```

## Quick Setup Guide

1. **Install ComfyUI** (if not already installed):
```bash
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI
pip install -r requirements.txt
```

2. **Create model directories**:
```bash
cd ComfyUI
mkdir -p models/checkpoints models/unet models/clip models/vae
```

3. **Download models** (choose what you want):
```bash
# For fast uncensored generation - Flux Schnell (recommended)
wget -P models/unet/ https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors
wget -P models/clip/ https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors
wget -P models/clip/ https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors
wget -P models/vae/ https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors

# For SDXL (default)
wget -P models/checkpoints/ https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors

# For video (SVD)
wget -P models/checkpoints/ https://huggingface.co/stabilityai/stable-video-diffusion-img2vid/resolve/main/svd.safetensors
```

4. **Start ComfyUI**:
```bash
python main.py
# Access at http://localhost:8188
```

5. **Verify in HomePilot**:
- Open Settings in HomePilot
- Set Image/Video Provider to "ComfyUI"
- Click "Fetch models"
- Select your model
- Enable "Spice Mode" for NSFW content

## VRAM Requirements

| Model | Minimum VRAM | Recommended VRAM |
|-------|-------------|------------------|
| SD 1.5 | 6GB | 8GB |
| SDXL | 8GB | 12GB |
| Flux Schnell | 12GB | 16GB |
| Flux Dev | 16GB | 24GB |
| Pony XL | 10GB | 12GB |
| SVD (Video) | 12GB | 16GB |

## Optimization Tips

### For Low VRAM (< 12GB)
1. Use `--lowvram` flag when starting ComfyUI
2. Use SD 1.5 models instead of SDXL/Flux
3. Reduce image resolution (512x512 for SD1.5, 768x768 for SDXL)
4. Close other GPU applications

### For Medium VRAM (12-16GB)
1. Use Flux Schnell or SDXL
2. Standard resolutions (1024x1024)
3. Can run video generation with reduced frames

### For High VRAM (24GB+)
1. Use Flux Dev for best quality
2. Higher resolutions (1536x1536 or more)
3. Run video generation with full settings
4. Can load multiple models simultaneously

## Workflow Customization

To customize workflows:
1. Open ComfyUI web interface (http://localhost:8188)
2. Load the workflow JSON
3. Modify parameters (steps, CFG, sampler, etc.)
4. Export API format
5. Replace the workflow file in `comfyui/workflows/`

## Troubleshooting

### "Model not found" error
- Verify model file is in correct directory
- Check filename matches exactly what's in the workflow
- Restart ComfyUI

### Out of memory error
- Reduce image resolution
- Use `--lowvram` flag
- Use smaller model (SD1.5 instead of SDXL)
- Close other applications

### Slow generation
- This is normal for large models
- Flux Schnell is fastest (4 steps)
- Reduce steps in custom settings
- Consider upgrading GPU

### Black images or errors
- Check model file isn't corrupted (re-download)
- Verify all required model files are present
- Check ComfyUI console for specific error messages

## Advanced: Adding Custom Models

To add your own models:

1. Download model to appropriate directory
2. Create/modify workflow in ComfyUI web interface
3. Export as API format
4. Save to `comfyui/workflows/` with descriptive name
5. Update `backend/app/providers.py` to add model to list:
```python
def available_image_models() -> List[str]:
    return [
        "sdxl",
        "flux-schnell",
        # ... existing models ...
        "your-custom-model",  # Add your model here
    ]
```
6. Update `backend/app/orchestrator.py` workflow_map:
```python
workflow_map = {
    "sdxl": "txt2img",
    # ... existing mappings ...
    "your-custom-model": "txt2img-your-custom-model",
}
```

## Support

For issues:
1. Check ComfyUI logs
2. Verify model files are correct
3. Check HomePilot backend logs
4. Search r/StableDiffusion or r/comfyui for similar issues
5. Report bugs in HomePilot GitHub issues
