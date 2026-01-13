Here is a **clean, professional, production-ready `backend/README.md`** tailored specifically for the **HomePilot backend**.
You can copy-paste this **exactly** into `backend/README.md`.

---

# HomePilot Backend

**HomePilot Backend** is the orchestration layer of the HomePilot Enterprise Mind system.

It is responsible for coordinating **chat (LLMs)**, **image generation**, **image editing**, and **image-to-video workflows** into a **single unified conversational API**.

This backend is designed to be:

* **Local-first**
* **Provider-agnostic**
* **Production-ready**
* **OpenAI-compatible**

---

## Responsibilities

The backend acts as the **control plane** for HomePilot.

It handles:

* Chat requests and conversation state
* Prompt normalization and routing
* Communication with:

  * LLM servers (vLLM, Ollama, future providers)
  * ComfyUI (image & video workflows)
  * Media processing service (ffmpeg)
* File uploads and media URLs
* Polling async image/video jobs
* Persisting conversation metadata

The frontend never talks directly to generation engines — **everything flows through this API**.

---

## API Overview

The backend exposes a **FastAPI** service.

### Core Endpoints

| Endpoint          | Description                |
| ----------------- | -------------------------- |
| `GET /health`     | Health check               |
| `POST /chat`      | Chat + multimodal requests |
| `POST /upload`    | Image upload               |
| `GET /media/{id}` | Serve generated media      |
| `GET /docs`       | OpenAPI documentation      |

The `/chat` endpoint supports **text**, **image**, and **video** generation through a unified schema.

---

## Architecture

```
Frontend (React)
   |
   |  HTTP / JSON
   v
Backend (FastAPI)
   |
   ├─ LLM Provider (vLLM / Ollama)
   ├─ ComfyUI (images & video)
   ├─ Media Service (ffmpeg)
   └─ SQLite (history, metadata)
```

The backend is intentionally **stateless at runtime** and relies on:

* Persistent storage (SQLite)
* Deterministic workflows
* Explicit polling for async tasks

---

## Development Setup (Local, No Docker)

The backend supports **local development using `uv`**.

### Prerequisites

* Python **3.11+**
* `uv` installed

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

### Install

From the repo root:

```bash
make uv
```

This will:

* Create `backend/.venv`
* Install backend in editable mode
* Install dev dependencies (pytest, ruff, mypy)

---

### Run Backend (Hot Reload)

```bash
make uv-run
```

This starts:

```
http://localhost:8000
```

---

### Run Tests

```bash
make uv-test
```

---

## Configuration

The backend is configured via environment variables.

### Common Variables

| Variable         | Description               |
| ---------------- | ------------------------- |
| `LLM_BASE_URL`   | Base URL of LLM provider  |
| `LLM_MODEL`      | Default model name        |
| `COMFY_BASE_URL` | ComfyUI URL               |
| `MEDIA_BASE_URL` | Media service URL         |
| `API_KEY`        | Optional API key          |
| `SQLITE_PATH`    | Path to SQLite DB         |
| `UPLOAD_DIR`     | Upload directory          |
| `OUTPUT_DIR`     | Generated media directory |

These are usually provided via Docker Compose or `.env`.

---

## LLM Providers

The backend is **provider-agnostic**.

Currently supported / planned:

* ✅ **vLLM** (OpenAI-compatible)
* 🔜 **Ollama**
* 🔜 **Remote OpenAI / compatible APIs**
* 🔜 **Multi-provider routing**

Switching providers does **not** require frontend changes.

---

## ComfyUI Integration

The backend does not hardcode generation logic.

Instead it:

1. Loads **workflow JSON templates**
2. Injects runtime values (prompt, image URL, motion, duration)
3. Submits to ComfyUI
4. Polls for completion
5. Returns media URLs to the frontend

This makes the system **model-agnostic** and future-proof.

---

## Testing Philosophy

Tests focus on **API correctness**, not model quality.

Covered areas:

* Health endpoint
* Chat endpoint schema
* Upload handling
* Error handling

All tests are designed to run **without GPUs** by mocking downstream services.

---

## Production Notes

* Bind to `127.0.0.1` by default
* No telemetry
* No external calls unless configured
* Ready for:

  * Docker
  * Reverse proxy
  * Kubernetes
  * Air-gapped environments

---

## Philosophy

> The backend is not a chatbot.
>
> It is a **reasoning and orchestration engine**.

