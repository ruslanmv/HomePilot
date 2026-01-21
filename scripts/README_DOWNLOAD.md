# HomePilot Model Download Script

Automatic model downloader for HomePilot. Downloads models from the catalog or Civitai (experimental).

## Installation

Install required dependencies:

```bash
pip install requests tqdm
```

Or use the requirements file:

```bash
pip install -r scripts/requirements.txt
```

## Quick Start

### List Available Models

```bash
# List all models
python scripts/download.py --list

# List only image models
python scripts/download.py --list --type image

# List only video models
python scripts/download.py --list --type video
```

### Download Catalog Models

```bash
# Download a specific model
python scripts/download.py --model sd_xl_base_1.0.safetensors

# Download all image models
python scripts/download.py --type image --all

# Download all video models
python scripts/download.py --type video --all

# Download to custom directory
python scripts/download.py --model flux1-schnell.safetensors --output-dir /custom/path
```

## 🧪 Experimental: Civitai Integration

### Download from Civitai

Download any model from Civitai using its version ID:

```bash
# Download from Civitai
python scripts/download.py --civitai --version-id 128713

# Download to custom path
python scripts/download.py --civitai --version-id 128713 --output my_model.safetensors

# Specify model type (for correct install path)
python scripts/download.py --civitai --version-id 128713 --type image
```

### Add Civitai Model to Catalog

Automatically add a Civitai model to your catalog:

```bash
# Add to catalog (will fetch metadata from Civitai)
python scripts/download.py --add-civitai --version-id 128713 --type image

# This will:
# 1. Fetch model info from Civitai API
# 2. Add entry to model_catalog_data.json
# 3. Make it available in the Models Manager UI
```

## Finding Civitai Version IDs

1. Go to Civitai.com
2. Find a model you like
3. Click on a specific version
4. The URL will look like: `https://civitai.com/models/128713/dreamshaper-8`
5. The number after `/models/` is the version ID: `128713`

Alternatively, you can find it in the model's download button URL.

## Use Cases

### Download All SDXL Models

```bash
# List available models
python scripts/download.py --list --type image | grep SDXL

# Download specific ones
python scripts/download.py --model sd_xl_base_1.0.safetensors
```

### Download All Video Models

```bash
# Download all SVD models at once
python scripts/download.py --type video --all
```

### Add Custom Civitai Models

```bash
# Add DreamShaper 8
python scripts/download.py --add-civitai --version-id 128713 --type image

# Add Realistic Vision
python scripts/download.py --add-civitai --version-id 130072 --type image

# Now these appear in your Models Manager UI!
```

## Features

### ✅ Production Features

- **Resume Support**: Downloads resume if interrupted
- **Progress Bar**: Visual progress with tqdm
- **SHA256 Verification**: Validates file integrity (when hash available)
- **Atomic Writes**: Uses `.part` files, renamed only when complete
- **Auto Install Paths**: Automatically installs to correct ComfyUI folders
- **Catalog Integration**: Works with `model_catalog_data.json`

### 🧪 Experimental Features

- **Civitai API**: Download any model from Civitai
- **Auto Metadata**: Fetches model name, size, description from API
- **Catalog Addition**: Add Civitai models to your catalog
- **Smart File Selection**: Prefers primary + safetensors files

## File Structure

After downloading, files are organized:

```
comfyui/
├── models/
│   └── checkpoints/
│       ├── sd_xl_base_1.0.safetensors
│       ├── flux1-schnell.safetensors
│       ├── svd_xt_1_1.safetensors
│       └── dreamshaper_8.safetensors (from Civitai)
```

## Configuration

The script automatically detects your HomePilot installation structure:

- **Catalog**: `backend/app/model_catalog_data.json`
- **ComfyUI Models**: `comfyui/models/checkpoints/`
- **Install Paths**: Defined in `model_catalog_data.json` per model

## Advanced Usage

### Custom Output Directory

```bash
# Download all to custom location
python scripts/download.py --type image --all --output-dir /mnt/models/custom
```

### Manual Catalog Editing

After adding Civitai models, you can manually edit `model_catalog_data.json`:

```json
{
  "id": "dreamshaper_8.safetensors",
  "label": "DreamShaper 8",
  "description": "Versatile model for diverse art styles",
  "size_gb": 2.0,
  "resolution": "512x512",
  "download_url": "https://civitai.com/api/download/models/128713",
  "install_path": "models/checkpoints/",
  "civitai_version_id": "128713",
  "civitai_model_id": "4384"
}
```

## Troubleshooting

### "Module not found: requests"

```bash
pip install requests tqdm
```

### "Catalog not found"

Make sure you're running from the project root:

```bash
cd /path/to/HomePilot
python scripts/download.py --list
```

### Download Fails / Incomplete

The script supports resume. Just run the same command again:

```bash
# Downloads will resume from where they left off
python scripts/download.py --model flux1-schnell.safetensors
```

### Civitai Download Blocked

Some Civitai models require login. Try:

1. Create a Civitai account
2. Get an API key from Settings > API Keys
3. Set environment variable:

```bash
export CIVITAI_API_KEY="your-key-here"
python scripts/download.py --civitai --version-id 128713
```

## Integration with Frontend

The Models Manager UI automatically shows:

1. **Catalog Models**: From `model_catalog_data.json`
2. **Installed Models**: From ComfyUI/Ollama file system
3. **Download Buttons**: Uses this script via backend

When you add models with `--add-civitai`, they appear in the UI immediately after refreshing the catalog.

## Safety & Security

- ✅ **SHA256 Verification**: When hashes are available
- ✅ **Virus Scan Info**: Shows scan results from Civitai
- ✅ **Atomic Downloads**: `.part` files prevent corruption
- ✅ **Resume Support**: Safe to interrupt and resume
- ⚠️ **Experimental**: Civitai integration is experimental - verify models before use

## Examples

### Complete Workflow: Adding a New Model

```bash
# 1. Find model on Civitai (e.g., DreamShaper 8)
# URL: https://civitai.com/models/4384/dreamshaper

# 2. Get version ID from download button
# Version ID: 128713

# 3. Add to catalog
python scripts/download.py --add-civitai --version-id 128713 --type image

# 4. Download the model
python scripts/download.py --model dreamshaper_8.safetensors

# 5. Refresh Models Manager in UI
# Model now appears with Install button!
```

### Batch Setup: Download All Base Models

```bash
# Download all curated image models
python scripts/download.py --type image --all

# Download all curated video models
python scripts/download.py --type video --all

# Now ComfyUI is fully set up!
```

## Contributing Models

To add models to the official catalog:

1. Test the model thoroughly
2. Add to `model_catalog_data.json` with complete metadata
3. Include: label, description, size, download URL, recommended flag
4. Submit a pull request

## Future Enhancements

Planned features:

- [ ] Hugging Face integration
- [ ] Model conversion (ckpt → safetensors)
- [ ] Automatic model testing
- [ ] Download queue management
- [ ] Speed test different mirrors
- [ ] Model preview/thumbnail download

## License

Part of HomePilot project.
