# ComfyUI Workflows for HomePilot

This directory contains workflow templates for HomePilot's **Grok-like** image and video generation features.

## Quick Start

### Required Files

Backend expects these workflow files (JSON):

* **txt2img.json** - Text-to-image generation
* **edit.json** - Image editing/inpainting
* **img2vid.json** - Image-to-video animation

### How to Create Real Workflows

1. **Open ComfyUI** at `http://localhost:8188`
2. **Build your workflow** (FLUX txt2img, FLUX inpaint, SVD img2vid, etc.)
3. **Export workflow JSON** (Settings → Enable Dev mode → Save API Format)
4. **Replace placeholders** in the JSON:

   **Available placeholders:**
   * `{{prompt}}` - Refined image generation prompt (auto-enhanced by LLM)
   * `{{negative_prompt}}` - Things to avoid in generation
   * `{{aspect_ratio}}` - "1:1", "16:9", "9:16", "4:3", "3:4"
   * `{{style}}` - "photorealistic", "illustration", "cinematic", "artistic", "anime"
   * `{{image_url}}` - Input image URL (for edit/animate modes)
   * `{{instruction}}` - Edit instruction (for edit mode)
   * `{{seconds}}` - Video duration (for animate mode)
   * `{{motion}}` - Motion style (for animate mode)

5. **Save** the workflow as `txt2img.json`, `edit.json`, or `img2vid.json` in this directory
6. **Restart** the backend

## How HomePilot Works (Grok-like Behavior)

When you type a casual prompt like:
```
"make an image of a sunset"
```

HomePilot automatically:
1. **Refines** your prompt using an LLM:
   ```json
   {
     "prompt": "A breathtaking sunset over the ocean, vibrant orange and pink sky, dramatic clouds, cinematic lighting, photorealistic, 8k quality",
     "negative_prompt": "blurry, low quality, distorted",
     "aspect_ratio": "16:9",
     "style": "photorealistic"
   }
   ```
2. **Substitutes** these values into your ComfyUI workflow
3. **Generates** the image via ComfyUI
4. **Returns** a short caption: "Here you go." + [image]

This mimics Grok's "Imagine" feature: sloppy prompts → great results.

## Workflow Execution Flow

```
User: "imagine a cat"
  ↓
Orchestrator: Detect "imagine" keyword
  ↓
Prompt Refiner: Use LLM to expand prompt
  ↓
Load txt2img.json workflow
  ↓
Replace {{prompt}}, {{negative_prompt}}, {{aspect_ratio}}, {{style}}
  ↓
POST to ComfyUI /prompt endpoint
  ↓
Poll ComfyUI /history until complete
  ↓
Extract image URLs
  ↓
Return to user: "Here you go." + [images]
```

## Configuration

### Environment Variables

Set in your `.env` file:

```bash
# ComfyUI server URL (default: http://comfyui:8188 for docker)
COMFY_BASE_URL=http://localhost:8188

# Workflow directory (auto-detected in local dev, or set explicitly)
COMFY_WORKFLOWS_DIR=/path/to/workflows

# Polling settings
COMFY_POLL_INTERVAL_S=1.0  # Check every 1 second
COMFY_POLL_MAX_S=240       # Timeout after 4 minutes
```

### Local Development

The backend will **automatically find workflows** in this directory during local development. No docker mounting required!

## Example: Mapping Aspect Ratios

If your workflow needs specific dimensions, map `{{aspect_ratio}}`:

| Aspect Ratio | Width × Height |
|--------------|----------------|
| `1:1`        | 1024 × 1024    |
| `16:9`       | 1344 × 768     |
| `9:16`       | 768 × 1344     |
| `4:3`        | 1024 × 768     |
| `3:4`        | 768 × 1024     |

You can hard-code dimensions or use a custom node that interprets the ratio.

## Troubleshooting

### "Workflow file not found"
- Ensure workflow JSON files exist in this directory
- Check that file names match exactly: `txt2img.json`, `edit.json`, `img2vid.json`
- Verify `COMFY_WORKFLOWS_DIR` is not set to wrong path

### "ComfyUI did not return prompt_id"
- Make sure ComfyUI is running at `COMFY_BASE_URL`
- Test your workflow manually in ComfyUI first
- Validate your workflow JSON is not corrupted

### Variables not being replaced
- Use double curly braces: `{{variable}}` not `{variable}`
- Variables are case-sensitive
- Ensure the value is a string in the JSON

### "Image generation is not configured"
- This means the workflow files are missing or not found
- Check that this directory contains the required JSON files
- Restart the backend after adding workflows

## Resources

- [ComfyUI GitHub](https://github.com/comfyanonymous/ComfyUI)
- [FLUX Model](https://huggingface.co/black-forest-labs/FLUX.1-dev)
- [SDXL Model](https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0)
- [Stable Video Diffusion](https://huggingface.co/stabilityai/stable-video-diffusion-img2vid-xt)

## Pro Tip

Use ComfyUI "Load Image" nodes that can fetch HTTP URLs, making it easy to work with the `{{image_url}}` placeholder for edit and animate modes.
