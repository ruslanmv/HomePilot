# HomePilot Enterprise Mind (Home Edition) — v2

A local “Grok-like” assistant: chat + “Imagine” (generate/edit) + “Animate” (image → video), built from open components.
Runs entirely on your machine using Docker.

## Architecture (production oriented)

User -> Frontend (3000) -> Backend Orchestrator (8000)
Backend uses:
- LLM via vLLM OpenAI-compatible API (8001)
- Images / video via ComfyUI API (/prompt + /history polling) (8188)
- Video upscale/encode via Media service (8002)
Data:
- SQLite conversation history
- Local uploads, outputs mounted to ./outputs

### Services
- **frontend**: Vite/React UI that mimics Grok’s dark, minimal interface (typewriter, carousel, lightbox, fun-mode toggle)
- **backend**: FastAPI orchestrator + ComfyUI runner + upload + history
- **llm**: vLLM OpenAI-compatible server (mount your model at ./models/llm)
- **comfyui**: ComfyUI server (mount workflows + models)
- **media**: ffmpeg microservice for upscale/encode

## Quickstart

1) Requirements:
- Docker + docker compose
- NVIDIA drivers + NVIDIA Container Toolkit (for GPU acceleration)
- Node 20+ (only needed for `make dev`; docker can run everything)

2) Create env:
```bash
cp .env.example .env
````

3. Put models in ./models:

* ./models/llm  (a vLLM-loadable model directory)
* ./models/comfy (ComfyUI models: checkpoints, clip, vae, loras, etc.)

4. Start:

```bash
make install
make run
```

Open:

* UI:      [http://localhost:3000](http://localhost:3000)
* Backend: [http://localhost:8000/docs](http://localhost:8000/docs)
* ComfyUI: [http://localhost:8188](http://localhost:8188)

## ComfyUI Workflows (important)

This repo ships **template workflows** in `comfyui/workflows/`.
You should:

1. Open ComfyUI (8188)
2. Import a workflow for txt2img / inpaint / img2vid (FLUX, SVD, etc.)
3. Export it to JSON
4. Put it in `comfyui/workflows/` and insert template placeholders:

   * {{prompt}}
   * {{instruction}}
   * {{image_url}}
   * {{seconds}}
   * {{motion}}

Backend will:

* Load the JSON workflow
* Replace placeholders recursively in the graph
* POST to ComfyUI /prompt
* Poll /history until done
* Return /view URLs for images or videos

## Make targets

```bash
make help
make install
make run
make dev
make download
make test
make logs
make health
make clean
```

## Security notes

* Stack binds to 127.0.0.1 by default (local-only).
* Set API_KEY in .env to require requests to include `X-API-Key`.

