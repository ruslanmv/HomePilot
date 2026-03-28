# HomePilot Container

Self-hosted HomePilot container that runs on any machine with Docker. GPU-accelerated when available.

Pre-built images are published automatically to **Docker Hub** and **GitHub Container Registry**.

## Pull & Run

Pick whichever registry you prefer:

```bash
# Docker Hub
docker pull ruslanmv/homepilot:latest

# GitHub Container Registry
docker pull ghcr.io/ruslanmv/homepilot:latest
```

**With GPU (NVIDIA):**
```bash
docker run --gpus all -p 7860:7860 \
  -e OPENAI_API_KEY=your-key \
  -v homepilot-data:/home/user/app/data \
  ruslanmv/homepilot:latest
```

**CPU only:**
```bash
docker run -p 7860:7860 \
  -e OPENAI_API_KEY=your-key \
  -v homepilot-data:/home/user/app/data \
  ruslanmv/homepilot:latest
```

Then open http://localhost:7860

## Build from Source (Optional)

```bash
docker build -f container/Dockerfile -t homepilot .
docker run --gpus all -p 7860:7860 homepilot
```

## RunPod

Use the pre-built image directly:

1. In RunPod, create a new Pod with:
   - **Container Image:** `ruslanmv/homepilot:latest`
   - **Expose HTTP Port:** `7860`
   - **Volume Mount:** `/home/user/app/data` (for persistent storage)

2. Set environment variables:
   - `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`

## Google Colab

```python
# Pull and run the container:
!docker pull ruslanmv/homepilot:latest
!docker run -d --gpus all -p 7860:7860 ruslanmv/homepilot:latest

# Access via Colab tunneling:
from google.colab.output import eval_js
print(eval_js("google.colab.kernel.proxyPort(7860)"))
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | - | OpenAI API key for GPT models |
| `ANTHROPIC_API_KEY` | - | Anthropic API key for Claude models |
| `HOMEPILOT_LLM_BACKEND` | `openai` | LLM backend to use (`openai`, `anthropic`, `ollama`) |
| `HOMEPILOT_MODE` | `container` | Deployment mode |

## Persistent Data

Mount a volume to `/home/user/app/data` to persist:
- Uploaded files
- Conversation history
- Cached models
- User settings

## CI/CD

Two GitHub Actions workflows publish the container image:

| Workflow | Registry | Triggers |
|---|---|---|
| `container.yml` | `ghcr.io/ruslanmv/homepilot` | Push to `main`, release, manual |
| `dockerhub.yml` | `ruslanmv/homepilot` (Docker Hub) | Release, manual |

**Tags:**
- `latest` — most recent stable release
- `v1.2.3` / `1.2` / `1` — semver on release
- `sha-abc1234` — git commit SHA

**Required secrets for Docker Hub** (set in repo Settings > Secrets):
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

## Architecture

- **Nginx** — Reverse proxy (port 7860)
- **FastAPI** — Backend API and AI orchestration (port 8000)
- **React** — Frontend served as static files
- **Supervisord** — Process manager for all services

Both `linux/amd64` and `linux/arm64` are supported.
