# HomePilot Container

A **single Docker image** that bundles the frontend, backend, and reverse proxy into one container exposed on **port 7860**.

This is the image used by the [Desktop app](DESKTOP.md), but it also runs standalone on any Docker host, RunPod, Google Colab, or Kubernetes.

---

## Quick Start

### Run a pre-built image

```bash
# CPU only
docker run -p 7860:7860 ruslanmv/homepilot:latest

# With NVIDIA GPU
docker run --gpus all -p 7860:7860 ruslanmv/homepilot:latest
```

Open [http://localhost:7860](http://localhost:7860) in your browser.

### Pass API keys

```bash
docker run -p 7860:7860 \
  -e OPENAI_API_KEY=sk-... \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e HOMEPILOT_LLM_BACKEND=openai \
  ruslanmv/homepilot:latest
```

### Persist data between restarts

```bash
docker run -p 7860:7860 \
  -v homepilot-data:/home/user/app/data \
  ruslanmv/homepilot:latest
```

---

## Build from Source

```bash
# Using the Makefile (recommended)
make build-container

# Or directly with Docker
docker build -f container/Dockerfile -t homepilot:latest .
```

---

## How It Works

The container uses a multi-stage build:

1. **Stage 1** — Node 20 Alpine builds the React frontend (`npm run build`).
2. **Stage 2** — Python 3.11-slim runtime copies the built frontend, installs backend dependencies, and runs:
   - **nginx** on port `7860` — serves the static frontend and proxies `/api/` requests.
   - **uvicorn** on port `8000` — runs the FastAPI backend.
   - **supervisord** manages both processes.

```
                    ┌─────────────────────────────┐
                    │       Port 7860 (nginx)      │
                    │                              │
  browser ────────► │   /         → static files   │
                    │   /api/*    → uvicorn :8000   │
                    │   /docs     → uvicorn :8000   │
                    │   /health   → uvicorn :8000   │
                    └─────────────────────────────┘
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key |
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `HOMEPILOT_LLM_BACKEND` | `openai` | LLM provider: `openai`, `anthropic`, or `ollama` |
| `HOMEPILOT_MODE` | `container` | Runtime mode (set automatically) |

---

## GPU Support

GPU acceleration is auto-detected at startup. The entrypoint script checks for `nvidia-smi` and logs the GPU model if found.

```bash
# Local machine with NVIDIA GPU
docker run --gpus all -p 7860:7860 ruslanmv/homepilot:latest

# RunPod (GPU provided by the platform)
# Just deploy the image — no extra flags needed.

# CPU fallback (works everywhere)
docker run -p 7860:7860 ruslanmv/homepilot:latest
```

---

## Deployment Targets

### Local Machine

```bash
docker run --gpus all -p 7860:7860 \
  -v homepilot-data:/home/user/app/data \
  ruslanmv/homepilot:latest
```

### RunPod

Use `ruslanmv/homepilot:latest` as the container image. Set port `7860` as the HTTP service port. The entrypoint auto-detects the RunPod environment.

### Google Colab

```python
!docker run -d --gpus all -p 7860:7860 ruslanmv/homepilot:latest
```

Then use the Colab port-forwarding URL to access the UI.

---

## Health Check

The container includes a built-in health check:

```bash
curl http://localhost:7860/api/health
```

Docker will automatically mark the container as healthy/unhealthy based on this endpoint (checked every 30 seconds).

---

## Container vs Docker Compose

HomePilot offers **two** deployment models. Choose the one that fits your needs:

| | Single Container | Docker Compose |
|---|---|---|
| **Config** | `container/Dockerfile` | `infra/docker-compose.yml` |
| **Port** | `7860` | `3000` (frontend) + `8000` (backend) + more |
| **Services** | Frontend + Backend in one image | Separate containers per service |
| **GPU services** | Backend only | vLLM, ComfyUI, media, avatar (each with GPU) |
| **Best for** | Desktop app, simple deploys, RunPod, Colab | Development, full GPU pipeline, Kubernetes |
| **Command** | `make build-container` | `make run` |

Both models can run side-by-side — they use different ports and container names.
