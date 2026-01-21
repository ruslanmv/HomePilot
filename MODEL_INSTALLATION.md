# Model Installation Guide

This guide explains how to automatically download and manage AI models for HomePilot.

## Quick Start

HomePilot provides automated model installation with three preset options:

```bash
# Minimal setup (~7GB) - FLUX Schnell + encoders
make download-minimal

# Recommended setup (~14GB) - FLUX Schnell + SDXL + encoders (default)
make download-recommended

# Full setup (~65GB) - All models including FLUX Dev, SD1.5, SVD
make download-full
```

## Installation Presets

### 📦 Minimal Preset (~7GB)

**Best for**: Quick testing, limited disk space, GPU with 12-16GB VRAM

**Includes:**
- FLUX Schnell (4GB) - Fast image generation (4 steps)
- T5-XXL Text Encoder fp16 (9.5GB)
- CLIP-L Text Encoder (0.2GB)
- FLUX VAE (0.3GB)

**Supported Models:**
- `flux-schnell` - Fast image generation

```bash
make download-minimal
```

### 📦 Recommended Preset (~14GB) - DEFAULT

**Best for**: Balanced quality and performance, most users

**Includes:**
- Everything in Minimal preset
- SDXL Base 1.0 (7GB) - High quality image generation

**Supported Models:**
- `flux-schnell` - Fast image generation
- `sdxl` - High quality image generation

```bash
make download-recommended
# or simply
make download
```

### 📦 Full Preset (~65GB)

**Best for**: Maximum flexibility, production deployments, GPU with 16-24GB VRAM

**Includes:**
- Everything in Recommended preset
- FLUX Dev (24GB) - Highest quality image generation (20 steps)
- Dreamshaper 8 (2GB) - SD 1.5 uncensored
- Stable Video Diffusion (25GB) - Video generation

**Supported Models:**
- `flux-schnell` - Fast image generation
- `flux-dev` - Highest quality image generation
- `sdxl` - High quality image generation
- `sd15-uncensored` - Lightweight SD 1.5
- `svd` - Video generation (via img2vid workflow)

```bash
make download-full
```

## Features

### ✓ Automatic Verification

The download script automatically checks if models already exist before downloading:

```bash
# Models already downloaded will be skipped
make download-recommended

# Output:
# ✓ FLUX.1 Schnell Model already exists (3.8G)
# ✓ SDXL Base 1.0 Model already exists (6.5G)
```

### ✓ Resume Support

Downloads can be resumed if interrupted:

```bash
# If download is interrupted, simply run again
make download-recommended

# The script will resume partial downloads
```

### ✓ Retry Logic

Failed downloads automatically retry with exponential backoff (3 attempts with 2s, 4s, 6s delays).

### ✓ Progress Tracking

Each download shows:
- URL and destination path
- Progress bar
- File size after completion
- Summary statistics

## Model Management

### List Installed Models

```bash
python scripts/manage_models.py list

# Output shows models by type with sizes:
# CHECKPOINTS:
#   ✓ sd_xl_base_1.0.safetensors           6.5 GB
#
# UNET:
#   ✓ flux1-schnell.safetensors           23.4 GB
```

### Verify Preset Models

```bash
# Verify recommended preset
python scripts/manage_models.py verify

# Verify specific preset
python scripts/manage_models.py verify --preset full

# Output shows found and missing models
```

### Show Available Presets

```bash
python scripts/manage_models.py presets

# Shows all presets with:
# - Description
# - Total size
# - VRAM requirements
# - Model list
```

### Clean Orphaned Models

```bash
# Dry run (shows what would be deleted)
python scripts/manage_models.py clean

# Actually delete orphaned models
python scripts/manage_models.py clean --no-dry-run
```

### Verify Downloaded Models

```bash
make download-verify

# Shows all downloaded models organized by type with sizes
```

## Manual Installation

If you prefer to manually download models:

### FLUX Models

```bash
cd models/comfy

# Shared encoders (required for all FLUX models)
wget -P clip/ https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors
wget -P clip/ https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors
wget -P vae/ https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors

# FLUX Schnell (fast, 4 steps)
wget -P unet/ https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors

# FLUX Dev (high quality, 20 steps)
wget -P unet/ https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors
```

### SDXL Models

```bash
cd models/comfy

# SDXL Base 1.0
wget -P checkpoints/ https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors
```

### Stable Video Diffusion

```bash
cd models/comfy

# SVD (video generation)
wget -P checkpoints/ https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt/resolve/main/svd_xt.safetensors
```

### SD 1.5 Models

For Dreamshaper 8 and other CivitAI models, visit:
- [Dreamshaper 8](https://civitai.com/models/4384/dreamshaper)

Download and place in `models/comfy/checkpoints/`

## Directory Structure

```
models/
├── comfy/                    # ComfyUI models (mounted to /ComfyUI/models in container)
│   ├── checkpoints/          # Checkpoint models (SDXL, SD1.5, SVD, etc.)
│   ├── unet/                 # FLUX UNET models
│   ├── clip/                 # CLIP text encoders
│   └── vae/                  # VAE models
└── llm/                      # LLM models (optional, for vLLM)
```

## Configuration

After downloading models, configure which model to use by setting `IMAGE_MODEL` in `.env`:

```bash
# .env
IMAGE_MODEL=flux-schnell    # Fast generation (4 steps)
# or
IMAGE_MODEL=sdxl            # High quality
# or
IMAGE_MODEL=flux-dev        # Highest quality (requires full preset)
# or
IMAGE_MODEL=sd15-uncensored # Lightweight SD 1.5
```

Available image models are determined by which workflows you have models for:
- `flux-schnell` - requires FLUX Schnell UNET + shared encoders
- `flux-dev` - requires FLUX Dev UNET + shared encoders
- `sdxl` - requires SDXL checkpoint
- `sd15-uncensored` - requires Dreamshaper 8 or similar SD 1.5 checkpoint
- `pony-xl` - requires Pony Diffusion XL checkpoint (manual download from CivitAI)

## LLM Models

LLM models are managed separately via Ollama or vLLM:

### Using Ollama (Recommended)

```bash
# Start HomePilot with Ollama
make run

# Ollama will auto-pull models when needed, or manually:
docker exec -it homepilot-ollama-1 ollama pull llama3:8b

# Available models:
# - llama3:8b (size varies by build)
# - codellama:latest (3.8 GB)
# - gemma:2b (1.7 GB)
# - granite3.2:latest (4.9 GB)
```

### Using vLLM (Advanced)

For vLLM, manually download HuggingFace models:

```bash
pip install -U huggingface_hub[cli]
huggingface-cli download meta-llama/Meta-Llama-3-8B-Instruct --local-dir models/llm/llama3-8b

# Configure in .env:
DEFAULT_PROVIDER=openai_compat
LLM_BASE_URL=http://llm:8001/v1
LLM_MODEL=meta-llama/Meta-Llama-3-8B-Instruct
```

## Disk Space Requirements

| Preset | Disk Space | VRAM | Models |
|--------|------------|------|--------|
| Minimal | ~7 GB | 12-16 GB | FLUX Schnell + encoders |
| Recommended | ~14 GB | 12-16 GB | + SDXL |
| Full | ~65 GB | 16-24 GB | + FLUX Dev, SD1.5, SVD |

## Troubleshooting

### Download Fails

If downloads fail:

1. **Check internet connection**
   ```bash
   ping huggingface.co
   ```

2. **Check disk space**
   ```bash
   df -h models/
   ```

3. **Retry download**
   ```bash
   # The script will resume partial downloads
   make download-recommended
   ```

4. **Manual download**
   - Visit HuggingFace URLs directly
   - Download models to correct directories

### Model Not Found in ComfyUI

If ComfyUI can't find models:

1. **Verify models are in correct directories**
   ```bash
   make download-verify
   ```

2. **Check Docker volume mounts**
   ```bash
   docker inspect homepilot-comfyui-1 | grep -A 10 Mounts
   ```

3. **Restart ComfyUI**
   ```bash
   docker compose -f infra/docker-compose.yml restart comfyui
   ```

### Out of Disk Space

If you run out of disk space:

1. **Check current usage**
   ```bash
   python scripts/manage_models.py list
   ```

2. **Remove unused models**
   ```bash
   # Remove specific model
   rm models/comfy/checkpoints/old_model.safetensors

   # Or clean orphaned models
   python scripts/manage_models.py clean --no-dry-run
   ```

3. **Download smaller preset**
   ```bash
   # Use minimal instead of full
   make download-minimal
   ```

## Advanced Usage

### Custom Model Locations

Override the models directory:

```bash
# Download to custom location
MODELS_DIR=/path/to/models bash scripts/download_models.sh recommended

# Manage custom location
python scripts/manage_models.py list --models-dir /path/to/models
```

### Automated Installation (CI/CD)

Skip confirmation prompt:

```bash
SKIP_CONFIRM=1 bash scripts/download_models.sh recommended
```

### Parallel Downloads

For faster downloads, you can run multiple preset downloads in parallel (not recommended as they share some models):

```bash
# Download in background
make download-recommended &
```

## Next Steps

After installing models:

1. **Start HomePilot**
   ```bash
   make run
   ```

2. **Verify services are running**
   ```bash
   make health-check
   ```

3. **Access the UI**
   - Open http://localhost:3000
   - Try the "Imagine" mode for image generation
   - Set your preferred model in Settings

4. **Customize workflows** (optional)
   - See `comfyui/workflows/README.md` for workflow customization
   - Create custom workflows for specific use cases

## Additional Resources

- [ComfyUI Workflows Guide](comfyui/workflows/README.md)
- [Model Requirements](comfyui/workflows/MODELS_README.md)
- [Deployment Guide](DEPLOYMENT.md)
- [Main README](README.md)
