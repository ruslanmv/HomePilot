# Quick Start: Model Downloads

## Installation

```bash
# Install dependencies
pip install -r scripts/requirements.txt
```

## Common Tasks

### 1. Download Base Image Models (SDXL)

```bash
# List available models
python scripts/download.py --list --type image

# Download SDXL Base (recommended starting point)
python scripts/download.py --model sd_xl_base_1.0.safetensors
```

### 2. Download All Video Models

```bash
# Download all SVD models
python scripts/download.py --type video --all
```

### 3. Add Your Own Model from Civitai

```bash
# Example: Add DreamShaper 8
# 1. Find on Civitai: https://civitai.com/models/4384/dreamshaper
# 2. Get version ID from URL or download button: 128713
# 3. Add to catalog:
python scripts/download.py --add-civitai --version-id 128713 --type image

# 4. Download it:
python scripts/download.py --model dreamshaper_8.safetensors
```

### 4. Quick Setup: Essential Models

```bash
# Download the essentials
python scripts/download.py --model sd_xl_base_1.0.safetensors  # Image generation
python scripts/download.py --model svd_xt_1_1.safetensors      # Video generation
```

## Where Models Are Installed

After downloading, models are automatically placed in:

```
comfyui/models/checkpoints/
├── sd_xl_base_1.0.safetensors      # Image models
├── flux1-schnell.safetensors
├── svd_xt_1_1.safetensors          # Video models
└── your_custom_model.safetensors   # Civitai models
```

## Verify Installation

Check that ComfyUI can see your models:

```bash
# Start ComfyUI
docker-compose up comfyui

# Or locally
cd comfyui && python main.py

# Models should appear in the UI dropdown
```

## Next Steps

1. Read full documentation: `scripts/README_DOWNLOAD.md`
2. Explore Civitai models: https://civitai.com
3. Check Models Manager in HomePilot UI
4. Configure Enterprise Settings with your preferred models

## Troubleshooting

**Download fails?**
- Script supports resume - just run again
- Check internet connection
- Verify disk space (models are 2-20GB each)

**Model not appearing in UI?**
- Refresh Models Manager page
- Restart backend: `docker-compose restart backend`
- Check file path matches catalog

**Civitai download blocked?**
- Some models require login
- Get API key from Civitai settings
- Set: `export CIVITAI_API_KEY="your-key"`
