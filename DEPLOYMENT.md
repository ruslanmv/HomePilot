# HomePilot Deployment Guide

This guide explains how to run HomePilot in different environments.

## Table of Contents

- [Quick Start](#quick-start)
- [Deployment Options](#deployment-options)
  - [Option 1: Docker (Recommended for Production)](#option-1-docker-recommended-for-production)
  - [Option 2: Local Development (No Docker)](#option-2-local-development-no-docker)
- [Ollama Integration](#ollama-integration)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

**Prerequisites:**
- **Ollama** installed and running: `ollama serve`
- **Ollama model** downloaded: `ollama pull llama3.1:latest`
- Docker (for `make run`) OR Python 3.11+ and Node.js (for `make local`)

**Fastest path:**
```bash
# Clone the repo
git clone <repo-url>
cd HomePilot

# Option A: Run with Docker
make run

# Option B: Run locally (no Docker)
make local
```

Then open: http://localhost:3000

---

## Deployment Options

### Option 1: Docker (Recommended for Production)

Use this when you want:
- Full stack with ComfyUI, vLLM, media processing
- GPU support for image/video generation
- Isolated environments
- Production-like setup

#### Setup

```bash
# 1. Make sure Ollama is running on your HOST machine
ollama serve

# 2. Pull a model
ollama pull llama3.1:latest

# 3. Start the Docker stack
make run

# 4. Open the UI
# Navigate to http://localhost:3000
```

**Services that will run:**
- Frontend: http://localhost:3000
- Backend: http://localhost:8000/docs
- LLM (vLLM): http://localhost:8001/v1 (requires GPU)
- ComfyUI: http://localhost:8188 (requires GPU)
- Media: http://localhost:8002

#### How Ollama Connection Works in Docker

**The Problem:**
When running in Docker containers, `localhost:11434` refers to the container itself, not your Windows/Mac host machine where Ollama is actually running.

**The Solution:**
The docker-compose.yml uses `host.docker.internal:11434` to access Ollama on your host:

```yaml
environment:
  OLLAMA_BASE_URL: http://host.docker.internal:11434
  OLLAMA_MODEL: llama3.1:latest
```

This works on:
- ✅ Windows with Docker Desktop
- ✅ Mac with Docker Desktop
- ✅ Linux (with extra_hosts configuration)

#### Verify Docker Can Access Ollama

```bash
# Check if backend container can reach Ollama
docker compose -f infra/docker-compose.yml exec backend curl -s http://host.docker.internal:11434

# You should see: "Ollama is running"
```

#### Stopping

```bash
make down
```

---

### Option 2: Local Development (No Docker)

Use this when you want:
- Fastest development cycle
- No Docker overhead
- Direct access to local Ollama
- Simpler debugging

#### Setup

```bash
# 1. Make sure Ollama is running
ollama serve

# 2. Pull a model
ollama pull llama3.1:latest

# 3. (Optional) Start ComfyUI for image generation
cd /path/to/ComfyUI
python main.py

# 4. Run HomePilot locally
make local
```

**What `make local` does:**
1. Checks if backend `.venv` exists, creates if missing
2. Starts backend on http://localhost:8000
3. Checks if frontend `node_modules` exists, installs if missing
4. Starts frontend on http://localhost:3000
5. Both services run in parallel

**Services that will run:**
- Frontend: http://localhost:3000
- Backend: http://localhost:8000

**External services (must run separately):**
- Ollama: http://localhost:11434 (REQUIRED)
- ComfyUI: http://localhost:8188 (optional, for image generation)

#### How Ollama Connection Works Locally

When running locally, the backend uses `localhost:11434` directly:

```python
OLLAMA_BASE_URL = http://localhost:11434
```

This works because both the backend and Ollama are running on the same machine (not in containers).

#### Stopping

Press `Ctrl+C` in the terminal where you ran `make local`.

---

## Ollama Integration

### Available Models on Your System

You currently have these models:
```
NAME                 SIZE
gemma:2b             1.7 GB
llama3:latest        4.7 GB
granite3.2:latest    4.9 GB
codellama:latest     3.8 GB
llama3.1:latest      4.9 GB
```

### Selecting a Model

#### Option A: In the UI (Easiest)

1. Open Settings (gear icon bottom-left)
2. Select "Ollama (optional)" as provider
3. Set Ollama URL: `http://localhost:11434`
4. Click "Fetch" button
5. Select your model from the list

#### Option B: Environment Variable

Create `.env` file (copy from `.env.example`):

```bash
# For Docker
DEFAULT_PROVIDER=ollama
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.1:latest

# For local development
DEFAULT_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:latest
```

Then restart:
```bash
# Docker
make down && make run

# Local
# Ctrl+C then make local
```

---

## Troubleshooting

### "Failed to connect to Ollama at http://localhost:11434"

**Symptom:** Backend can't reach Ollama

**Solutions:**

1. **Is Ollama running?**
   ```bash
   curl http://localhost:11434
   # Should return: "Ollama is running"
   ```

2. **Running in Docker?**
   - Check that docker-compose.yml uses `host.docker.internal:11434`
   - Verify with:
     ```bash
     docker compose -f infra/docker-compose.yml exec backend env | grep OLLAMA
     # Should show: OLLAMA_BASE_URL=http://host.docker.internal:11434
     ```

3. **Running locally?**
   - Ollama should be at `http://localhost:11434`
   - No special configuration needed

### "Ollama model 'llama3.1:8b' not found"

**Symptom:** Model doesn't exist

**Solution:**
```bash
# See what you have
ollama list

# Pull the model
ollama pull llama3.1:latest

# Or use a different model you already have
# Update OLLAMA_MODEL in .env or UI settings
```

### "CORS errors in browser console"

**Symptom:** Frontend can't reach backend

**Solution:**
- Make sure backend is running
- Check CORS_ORIGINS in `.env` includes your frontend URL
- Default includes: `localhost:3000`, `localhost:3001`, `localhost:5173`

### "ComfyUI workflows not found"

**Symptom:** Imagine mode fails

**This is normal if you haven't set up ComfyUI yet.**

To fix:
1. Install ComfyUI: https://github.com/comfyanonymous/ComfyUI
2. Create workflows (see `comfyui/workflows/README.md`)
3. Save workflow as `comfyui/workflows/txt2img.json`
4. Restart backend

---

## Comparison: Docker vs Local

| Feature | Docker (`make run`) | Local (`make local`) |
|---------|---------------------|----------------------|
| **Setup time** | Longer (build images) | Faster (direct run) |
| **GPU support** | ✅ Full (vLLM, ComfyUI) | ⚠️ Manual setup |
| **Ollama access** | `host.docker.internal` | `localhost` |
| **Services** | All (frontend, backend, LLM, ComfyUI, media) | Frontend + Backend only |
| **Image generation** | ✅ ComfyUI in container | ⚠️ External ComfyUI needed |
| **Resource usage** | Higher (containers) | Lower (native) |
| **Production ready** | ✅ Yes | ❌ Dev only |
| **Best for** | Full stack testing, production | Quick iteration, debugging |

---

## Advanced

### Running Just Backend Locally

```bash
make local-backend
```

### Running Just Frontend Locally

```bash
make local-frontend
```

### Using uv (Faster Python Package Manager)

```bash
# Install dependencies with uv
make uv

# Run backend with uv
make uv-run

# Run tests with uv
make uv-test
```

### Checking Logs (Docker)

```bash
make logs
```

### Health Checks

```bash
make health
```

---

## Summary of Commands

| Command | Description |
|---------|-------------|
| `make run` | Start full Docker stack (production-like) |
| `make local` | Run locally without Docker (dev mode) |
| `make down` | Stop Docker stack |
| `make logs` | View Docker logs |
| `make health` | Check service health |
| `make local-backend` | Run only backend locally |
| `make local-frontend` | Run only frontend locally |
| `make uv` | Install backend with uv |
| `make uv-run` | Run backend with uv |
| `make help` | Show all available commands |

---

## Quick Reference Card

### First Time Setup (Docker)

```bash
ollama serve              # Terminal 1
ollama pull llama3.1      # Terminal 1
make run                  # Terminal 2
# Open http://localhost:3000
```

### First Time Setup (Local)

```bash
ollama serve              # Terminal 1
ollama pull llama3.1      # Terminal 1
make local                # Terminal 2
# Open http://localhost:3000
```

### Daily Development (Local)

```bash
# Just run this:
make local
```

### Daily Development (Docker)

```bash
# Just run this:
make run
```

---

## Need Help?

- Check `GROK_IMAGINE_GUIDE.md` for Imagine feature setup
- Check `comfyui/workflows/README.md` for ComfyUI workflows
- Check `.env.example` for all configuration options
- Run `make help` to see all commands
