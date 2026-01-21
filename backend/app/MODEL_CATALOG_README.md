# Model Catalog Management

This document explains how to manage the HomePilot model catalog (`model_catalog_data.json`).

## Overview

The model catalog is a curated list of recommended models for all providers (Ollama, ComfyUI, OpenAI, Claude, etc.). It's used by the frontend Models Manager to display available models with rich metadata.

## File Structure

```json
{
  "version": "1.0.0",
  "last_updated": "2026-01-21",
  "providers": {
    "provider_name": {
      "model_type": [
        {
          "id": "model-id",
          "label": "Human Readable Label",
          "recommended": true,
          "description": "Model description",
          "size_gb": 4.7,
          "context_window": 8192,
          "download_url": "https://...",
          "install_path": "models/checkpoints/"
        }
      ]
    }
  }
}
```

## Supported Providers

### Ollama
- **Model Type**: `chat`
- **Required Fields**: `id`, `label`
- **Optional Fields**: `recommended`, `description`, `size_gb`, `context_window`

### ComfyUI
- **Model Types**: `image`, `video`
- **Required Fields**: `id`, `label`
- **Optional Fields**: `recommended`, `description`, `size_gb`, `resolution`, `frames`, `download_url`, `install_path`

### OpenAI-Compatible (vLLM)
- **Model Type**: `chat`
- **Required Fields**: `id`, `label`
- **Optional Fields**: `recommended`, `description`, `context_window`

### OpenAI
- **Model Type**: `chat`
- **Required Fields**: `id`, `label`
- **Optional Fields**: `recommended`, `description`, `context_window`

### Claude
- **Model Type**: `chat`
- **Required Fields**: `id`, `label`
- **Optional Fields**: `recommended`, `description`, `context_window`

### Watsonx
- **Model Type**: `chat`
- **Required Fields**: `id`, `label`
- **Optional Fields**: `recommended`, `description`, `context_window`

## How to Add a Model

1. Open `model_catalog_data.json`
2. Navigate to the appropriate provider and model type
3. Add a new model entry:

```json
{
  "id": "new-model:tag",
  "label": "New Model Name",
  "recommended": false,
  "description": "Model description here",
  "size_gb": 5.2,
  "context_window": 8192
}
```

4. Save the file
5. Restart the backend (or it will auto-reload in dev mode)

### Example: Adding a New Ollama Model

```json
{
  "id": "deepseek-coder:6.7b",
  "label": "DeepSeek Coder 6.7B",
  "description": "Code-focused model with strong programming capabilities",
  "size_gb": 3.8,
  "context_window": 16384
}
```

### Example: Adding a New ComfyUI Image Model

```json
{
  "id": "dreamshaper_8.safetensors",
  "label": "DreamShaper 8",
  "description": "Versatile model for diverse art styles",
  "size_gb": 2.0,
  "resolution": "512x512",
  "download_url": "https://civitai.com/api/download/models/128713",
  "install_path": "models/checkpoints/"
}
```

## How to Remove a Model

### Option 1: Comment Out (Recommended)
This preserves the model definition for future reference:

```json
{
  "chat": [
    {
      "id": "llama3:8b",
      "label": "Llama 3 8B",
      "recommended": true
    }
    // Temporarily disabled - uncomment to re-enable
    // {
    //   "id": "old-model:tag",
    //   "label": "Old Model",
    //   "description": "Deprecated model"
    // }
  ]
}
```

**Note**: Standard JSON doesn't support comments. Use this approach only if you have a JSON parser that supports comments, or manually remove the lines when deploying.

### Option 2: Delete (Permanent)
Simply delete the entire model object from the array:

```json
{
  "chat": [
    {
      "id": "llama3:8b",
      "label": "Llama 3 8B",
      "recommended": true
    }
    // Removed: old-model:tag
  ]
}
```

## How to Mark a Model as Recommended

Add or set the `recommended` field to `true`:

```json
{
  "id": "llama3:8b",
  "label": "Llama 3 8B",
  "recommended": true,  // ⭐ This model will show a "Recommended" badge
  "description": "Fast, efficient 8B parameter model"
}
```

**Best Practice**: Keep only 1-2 models per category marked as recommended.

## How to Update Model Metadata

Simply edit the fields in the JSON:

```json
{
  "id": "llama3:8b",
  "label": "Llama 3 8B (Updated)",  // Changed label
  "description": "Updated description with new features",  // Updated description
  "size_gb": 5.0,  // Updated size
  "context_window": 16384  // Updated context window
}
```

## Field Reference

### Common Fields (All Providers)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | ✅ Yes | Model identifier (e.g., "llama3:8b") |
| `label` | string | ✅ Yes | Human-readable name shown in UI |
| `recommended` | boolean | ❌ No | Show ⭐ badge in UI |
| `description` | string | ❌ No | Model description/capabilities |

### Ollama-Specific Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `size_gb` | number | ❌ No | Model size in gigabytes |
| `context_window` | number | ❌ No | Maximum context tokens |

### ComfyUI-Specific Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `size_gb` | number | ❌ No | Model file size in GB |
| `resolution` | string | ❌ No | Native resolution (e.g., "1024x1024") |
| `frames` | number | ❌ No | Number of frames (video models) |
| `download_url` | string | ❌ No | Direct download link |
| `install_path` | string | ❌ No | Installation path relative to ComfyUI root |

### API Provider Fields (OpenAI, Claude, Watsonx)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `context_window` | number | ❌ No | Maximum context tokens |

## Version Management

Update the version and last_updated fields when making significant changes:

```json
{
  "version": "1.1.0",  // Increment for major changes
  "last_updated": "2026-01-25",  // Update date
  "providers": { ... }
}
```

## Testing Your Changes

1. Save `model_catalog_data.json`
2. Restart the backend: `make restart` or `docker-compose restart backend`
3. Open the frontend Models page
4. Click "Refresh Catalog"
5. Verify your changes appear correctly

## API Endpoint

The catalog is served via: `GET /model-catalog`

Response format:
```json
{
  "ok": true,
  "version": "1.0.0",
  "last_updated": "2026-01-21",
  "providers": {
    "ollama": { ... },
    "comfyui": { ... },
    ...
  }
}
```

## Troubleshooting

### Models not showing in frontend
- Check JSON syntax (use a JSON validator)
- Ensure the backend is running
- Check browser console for errors
- Click "Refresh Catalog" button

### JSON parse errors
- Validate JSON syntax at https://jsonlint.com
- Check for trailing commas
- Ensure all strings are quoted

### Models not downloading
- Verify `download_url` is correct
- Check `install_path` matches your ComfyUI structure
- Ensure sufficient disk space

## Best Practices

1. **Keep it organized**: Group models by provider and type
2. **Use descriptive labels**: Make it clear what each model does
3. **Mark recommendations**: Help users choose the best models
4. **Include metadata**: Add size, resolution, context window info
5. **Test changes**: Always verify in the UI after editing
6. **Document changes**: Update version and last_updated
7. **Backup regularly**: Keep a backup before major changes

## Contributing

When adding new models, consider:
- Is this model widely used?
- Is it stable/production-ready?
- Does it add unique capabilities?
- Is the download URL reliable?

Prefer quality over quantity. A curated list is more valuable than an exhaustive list.
