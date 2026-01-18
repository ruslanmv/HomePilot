# HomePilot Grok-like "Imagine" Feature Guide

This guide explains how HomePilot's "Imagine" mode works like Grok's image generation, and how to set it up.

## What is Grok-like Imagine?

Instead of requiring perfect prompts, HomePilot automatically:
1. **Refines** casual user prompts into detailed image generation prompts
2. **Selects** optimal settings (aspect ratio, style, quality)
3. **Generates** high-quality images via ComfyUI
4. **Returns** short, Grok-like captions ("Here you go.")

### Example Flow

**User types:**
```
"make an image of a sunset"
```

**HomePilot automatically:**
1. Uses LLM to expand the prompt:
   ```json
   {
     "prompt": "A breathtaking sunset over the ocean, vibrant orange and pink sky, dramatic clouds, cinematic lighting, photorealistic, 8k quality",
     "negative_prompt": "blurry, low quality, distorted, oversaturated",
     "aspect_ratio": "16:9",
     "style": "photorealistic"
   }
   ```
2. Passes these parameters to ComfyUI
3. Returns the generated image with: "Here you go."

## Architecture

```
Frontend (User types casual prompt)
    ↓
Backend Orchestrator (detects "imagine" keyword)
    ↓
Prompt Refiner (LLM expands prompt)
    ↓
ComfyUI Workflow Loader (loads txt2img.json)
    ↓
Variable Substitution ({{prompt}}, {{negative_prompt}}, etc.)
    ↓
ComfyUI API (generates image)
    ↓
Response (short caption + image URLs)
```

## Setup Instructions

### Prerequisites

1. **Ollama** (for LLM) - https://ollama.ai
2. **ComfyUI** (for image generation) - https://github.com/comfyanonymous/ComfyUI
3. **Model for ComfyUI** (FLUX, SDXL, SD 1.5, etc.)

### Step-by-Step Setup

#### 1. Install and Start Ollama

```bash
# Install Ollama (see https://ollama.ai for your platform)
# Then pull a model:
ollama pull llama3.1:8b

# Start Ollama (runs on http://localhost:11434)
ollama serve
```

#### 2. Install and Start ComfyUI

```bash
# Clone ComfyUI
git clone https://github.com/comfyanonymous/ComfyUI.git
cd ComfyUI

# Install dependencies
pip install -r requirements.txt

# Download a model (example: FLUX)
cd models/checkpoints
# Download FLUX.1-dev or FLUX.1-schnell from Hugging Face
# Or download SDXL, SD 1.5, etc.

# Start ComfyUI (runs on http://localhost:8188)
cd ../..
python main.py
```

#### 3. Create ComfyUI Workflow

1. Open http://localhost:8188
2. Create a basic text-to-image workflow:
   - **CheckpointLoaderSimple** → Load your model
   - **CLIPTextEncode** (positive) → For the main prompt
   - **CLIPTextEncode** (negative) → For negative prompt
   - **EmptyLatentImage** → For initial noise
   - **KSampler** → For generation
   - **VAEDecode** → Decode latent to image
   - **SaveImage** → Save output
3. In ComfyUI Settings → Enable "Dev mode Options"
4. Click "Save (API Format)"
5. Copy the JSON

#### 4. Add Variable Placeholders

Edit the workflow JSON and replace values with placeholders:

```json
{
  "6": {
    "class_type": "CLIPTextEncode",
    "inputs": {
      "text": "{{prompt}}",  // ← Replace with this
      "clip": ["4", 1]
    }
  },
  "7": {
    "class_type": "CLIPTextEncode",
    "inputs": {
      "text": "{{negative_prompt}}",  // ← Replace with this
      "clip": ["4", 1]
    }
  }
}
```

Available placeholders:
- `{{prompt}}` - Refined prompt from LLM
- `{{negative_prompt}}` - Things to avoid
- `{{aspect_ratio}}` - "1:1", "16:9", "9:16", "4:3", "3:4"
- `{{style}}` - "photorealistic", "illustration", "cinematic", etc.

#### 5. Save Workflow

Save the workflow as:
```
HomePilot/comfyui/workflows/txt2img.json
```

#### 6. Configure Environment

Copy `.env.example` to `.env` and update:

```bash
# LLM Provider (use Ollama for local development)
DEFAULT_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b

# ComfyUI
COMFY_BASE_URL=http://localhost:8188
```

#### 7. Start HomePilot

```bash
# Terminal 1: Backend
cd backend
uvicorn app.main:app --reload

# Terminal 2: Frontend
cd frontend
npm run dev

# Open http://localhost:3000
```

## Usage

### In the UI

1. Select **"Imagine"** mode from the sidebar
2. Type a casual prompt:
   ```
   "create an image of a mountain landscape"
   ```
3. HomePilot will:
   - Refine the prompt using LLM
   - Generate the image via ComfyUI
   - Return: "Here you go." + image

### Advanced: Control Aspect Ratio and Style

You can guide the prompt refiner by being more specific:

```
"make a 16:9 cinematic image of a futuristic city at night"
```

The LLM will extract:
- **aspect_ratio**: "16:9"
- **style**: "cinematic"

## How Prompt Refinement Works

### System Prompt

The backend uses this system prompt for refinement:

```
You are an expert at refining user prompts into detailed, visual image generation prompts.

Given a user's casual request, output a JSON object with these fields:
- "prompt": A detailed, visual, specific prompt optimized for FLUX/SDXL
- "negative_prompt": Things to avoid
- "aspect_ratio": "1:1", "16:9", "9:16", "4:3", "3:4"
- "style": "photorealistic", "illustration", "cinematic", "artistic", "anime"

Keep your response as a single JSON object, no markdown, no explanations.
```

### Example Refinements

| User Input | Refined Prompt |
|------------|----------------|
| "a cat" | "A beautiful domestic cat sitting on a windowsill, soft natural lighting, photorealistic, detailed fur texture, professional photography, 8k quality" |
| "sunset beach" | "A stunning sunset over a tropical beach, golden hour lighting, vibrant orange and purple sky, gentle waves, palm trees silhouette, cinematic composition, photorealistic" |
| "cyberpunk city" | "A futuristic cyberpunk cityscape at night, neon lights, rain-slicked streets, towering skyscrapers, holographic advertisements, moody atmosphere, cinematic style, high detail" |

## Troubleshooting

### "Image generation is not configured on this server"

**Cause:** ComfyUI workflow file not found

**Fix:**
1. Ensure `txt2img.json` exists in `comfyui/workflows/`
2. Verify workflow JSON is valid
3. Check that `COMFY_WORKFLOWS_DIR` is not set incorrectly
4. Restart backend

### "ComfyUI did not return prompt_id"

**Cause:** ComfyUI is not running or workflow is invalid

**Fix:**
1. Check ComfyUI is running at `http://localhost:8188`
2. Test your workflow manually in ComfyUI first
3. Verify `COMFY_BASE_URL` is correct
4. Check ComfyUI logs for errors

### "Ollama model not found"

**Cause:** Model not downloaded in Ollama

**Fix:**
```bash
ollama pull llama3.1:8b
# Or pull the model specified in OLLAMA_MODEL
```

### Prompt refinement fails / returns original prompt

**Cause:** LLM not responding or not following JSON format

**Fix:**
1. Check Ollama is running: `ollama list`
2. Test manually: `ollama run llama3.1:8b "refine this prompt: a cat"`
3. If LLM doesn't return JSON, the system falls back to the original prompt
4. Try a different model: `ollama pull llama3.2:3b`

### Image generation is slow

**Solutions:**
1. Use FLUX.1-schnell instead of FLUX.1-dev (much faster)
2. Reduce image dimensions in your workflow
3. Lower sampling steps (try 20 instead of 50)
4. Use SD 1.5 instead of SDXL/FLUX for fastest results

## Best Practices

### Workflow Design

1. **Keep it simple**: Start with basic workflows, add complexity later
2. **Test manually**: Always test in ComfyUI before using in HomePilot
3. **Use good models**: FLUX.1-dev > SDXL > SD 1.5 for quality
4. **Optimize for speed**: schnell models, lower steps, smaller sizes for dev

### Prompt Guidelines

Users can be casual! The system will refine:
- ✅ "a sunset" → Refined to detailed prompt
- ✅ "make a cat picture" → Refined with style/quality
- ✅ "cyberpunk city 16:9" → Refined with correct aspect ratio

### Model Recommendations

| Use Case | Model | Speed | Quality |
|----------|-------|-------|---------|
| Best quality | FLUX.1-dev | Slow | Excellent |
| Fast generation | FLUX.1-schnell | Fast | Very Good |
| Balanced | SDXL | Medium | Very Good |
| Maximum speed | SD 1.5 | Very Fast | Good |

## Architecture Details

### Backend Components

1. **orchestrator.py**
   - Detects "imagine" mode
   - Calls `_refine_prompt()` with LLM
   - Loads workflow and substitutes variables
   - Calls ComfyUI API

2. **comfy.py**
   - Auto-detects workflow directory
   - Deep replaces `{{variables}}` in workflow JSON
   - Posts to ComfyUI `/prompt`
   - Polls `/history` until complete
   - Extracts image/video URLs

3. **llm.py**
   - Handles both Ollama and vLLM
   - Better error messages for model not found
   - Returns OpenAI-compatible format

### Frontend Behavior

- Frontend always calls backend `/chat` endpoint
- No direct browser → Ollama calls (avoids CORS)
- Passes `provider`, `ollama_base_url`, `ollama_model`
- Backend handles all routing and refinement

## Advanced: Custom Workflows

### Edit Workflow (edit.json)

For image editing, add:
```json
{
  "inputs": {
    "image_url": "{{image_url}}",
    "instruction": "{{instruction}}"
  }
}
```

### Animate Workflow (img2vid.json)

For image-to-video, add:
```json
{
  "inputs": {
    "image_url": "{{image_url}}",
    "motion": "{{motion}}",
    "seconds": "{{seconds}}"
  }
}
```

## Performance Tuning

### For 24GB VRAM (e.g., RTX 4090)

- Use FLUX.1-schnell (fits in VRAM)
- Max resolution: 1024×1024 or 1344×768
- 20-30 sampling steps

### For 48GB VRAM (e.g., RTX 6000 Ada)

- Use FLUX.1-dev (better quality)
- Max resolution: 1344×1344 or higher
- 30-50 sampling steps

### For Multiple GPUs

- Use tensor parallelism in vLLM
- Offload LLM to one GPU, ComfyUI to another
- Much faster overall

## Resources

- [ComfyUI Documentation](https://github.com/comfyanonymous/ComfyUI)
- [FLUX Model Card](https://huggingface.co/black-forest-labs/FLUX.1-dev)
- [Ollama](https://ollama.ai)
- [Stable Diffusion](https://stability.ai)

## Support

For issues or questions:
1. Check ComfyUI logs
2. Check backend logs (`uvicorn` output)
3. Verify all services are running
4. Test each component individually
