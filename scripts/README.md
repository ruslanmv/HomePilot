# Scripts Directory

This directory contains automation scripts for HomePilot model management and installation.

## Available Scripts

### download_models.sh

Automated model download script with three preset configurations.

**Usage:**

```bash
# Download recommended models (default: ~14GB)
./scripts/download_models.sh recommended

# Or use Makefile shortcuts
make download-minimal      # ~7GB
make download-recommended  # ~14GB (alias: make download)
make download-full         # ~65GB
```

**Features:**
- ✓ Automatic file existence checking (skips already downloaded models)
- ✓ Resume support for interrupted downloads
- ✓ Retry logic with exponential backoff (3 attempts)
- ✓ Progress tracking and summary statistics
- ✓ Interactive confirmation (can be skipped with `SKIP_CONFIRM=1`)

**Presets:**

| Preset | Size | Models | VRAM |
|--------|------|--------|------|
| minimal | ~7GB | FLUX Schnell + encoders | 12-16GB |
| recommended | ~14GB | FLUX Schnell + SDXL + encoders | 12-16GB |
| full | ~65GB | All models (FLUX Dev, SD1.5, SVD) | 16-24GB |

### manage_models.py

Advanced Python utility for model verification and management.

**Usage:**

```bash
# List all installed models
python scripts/manage_models.py list

# List with detailed timestamps
python scripts/manage_models.py list -v

# Verify models for a preset
python scripts/manage_models.py verify --preset recommended

# Show all available presets
python scripts/manage_models.py presets

# Show orphaned models (dry run)
python scripts/manage_models.py clean

# Actually delete orphaned models
python scripts/manage_models.py clean --no-dry-run
```

**Commands:**
- `list` - Show all downloaded models organized by type
- `verify` - Check if all models for a preset are downloaded
- `presets` - Display preset information and requirements
- `clean` - Remove models not in the registry (orphaned files)

**Options:**
- `-v, --verbose` - Show detailed information including timestamps
- `--preset {minimal,recommended,full}` - Specify preset for verify command
- `--no-dry-run` - Actually delete files when using clean command
- `--models-dir PATH` - Override default models directory

## Quick Reference

### First-Time Setup

```bash
# 1. Clone repository
git clone https://github.com/ruslanmv/homepilot
cd homepilot

# 2. Download models (choose one)
make download-minimal      # Quick start
make download-recommended  # Recommended
make download-full         # All features

# 3. Verify installation
make download-verify

# 4. Start HomePilot
make run
```

### Verify What's Installed

```bash
# Using Makefile (quick summary)
make download-verify

# Using Python script (detailed view)
python scripts/manage_models.py list -v

# Check specific preset
python scripts/manage_models.py verify --preset full
```

### Update Models

Models are automatically skipped if they already exist. To force re-download:

```bash
# Remove model file and re-run download
rm models/comfy/checkpoints/sd_xl_base_1.0.safetensors
make download-recommended
```

### Clean Up Disk Space

```bash
# See what can be removed (dry run)
python scripts/manage_models.py clean

# Actually remove orphaned models
python scripts/manage_models.py clean --no-dry-run
```

## Environment Variables

### download_models.sh

- `SKIP_CONFIRM=1` - Skip interactive confirmation prompt (useful for CI/CD)
- `MODELS_DIR` - Override models directory (default: `../models`)

**Example:**

```bash
# Automated installation (no prompts)
SKIP_CONFIRM=1 ./scripts/download_models.sh recommended

# Custom models directory
MODELS_DIR=/custom/path ./scripts/download_models.sh minimal
```

## Troubleshooting

### Download Fails

If downloads fail:

1. Check internet connection: `ping huggingface.co`
2. Check disk space: `df -h models/`
3. Retry (script will resume): `make download-recommended`
4. Check error messages in script output

### Models Not Found

If ComfyUI can't find models:

1. Verify models exist: `make download-verify`
2. Check directory structure:
   ```bash
   ls -lh models/comfy/checkpoints/
   ls -lh models/comfy/unet/
   ls -lh models/comfy/clip/
   ls -lh models/comfy/vae/
   ```
3. Restart ComfyUI: `docker compose -f infra/docker-compose.yml restart comfyui`

### Permission Issues

If you get permission denied errors:

```bash
# Make scripts executable
chmod +x scripts/download_models.sh
chmod +x scripts/manage_models.py

# Fix model directory permissions
sudo chown -R $USER:$USER models/
```

## Model Registry

The `manage_models.py` script includes a built-in registry of known models:

- **FLUX Models**: Schnell (fast), Dev (high quality)
- **SDXL**: Base 1.0
- **SD 1.5**: Dreamshaper 8
- **Video**: Stable Video Diffusion
- **Encoders**: T5-XXL, CLIP-L, VAE

The registry tracks:
- Download URLs (HuggingFace/CivitAI)
- Expected file sizes
- Model types (checkpoint, unet, clip, vae)
- Preset associations

## Advanced Usage

### Parallel Model Management

```bash
# Download one preset while managing another
make download-full &
python scripts/manage_models.py list
```

### Custom Model Integration

To add custom models not in the registry:

1. Download manually to appropriate directory:
   - Checkpoints: `models/comfy/checkpoints/`
   - UNET: `models/comfy/unet/`
   - CLIP: `models/comfy/clip/`
   - VAE: `models/comfy/vae/`

2. Verify with: `python scripts/manage_models.py list`

3. Update ComfyUI workflows to reference your model:
   - Edit workflow JSON in `comfyui/workflows/`
   - Change model filename in appropriate node

### CI/CD Integration

```bash
#!/bin/bash
# Example CI script

set -e

# Download models non-interactively
SKIP_CONFIRM=1 bash scripts/download_models.sh minimal

# Verify all models downloaded
python scripts/manage_models.py verify --preset minimal || exit 1

# Start services
make run

# Run health checks
sleep 30
make health-check
```

## See Also

- [MODEL_INSTALLATION.md](../MODEL_INSTALLATION.md) - Comprehensive installation guide
- [Makefile](../Makefile) - Build automation commands
- [comfyui/workflows/MODELS_README.md](../comfyui/workflows/MODELS_README.md) - Model requirements per workflow

## Support

For issues with model downloads or management:

1. Check the troubleshooting section above
2. Review script output for error messages
3. Open an issue on GitHub with:
   - Script output (including error messages)
   - System info (`uname -a`, disk space)
   - Models directory structure (`tree -L 2 models/`)
