# HomePilot — Hugging Face Space Templates

Two-Space Architecture for deploying HomePilot on Hugging Face Spaces.

## Live Spaces

| Space | URL | Type |
|-------|-----|------|
| **Builder** | [ruslanmv/HomePilot](https://huggingface.co/spaces/ruslanmv/HomePilot) | Docker (Ollama + full stack) |
| **Installer** | [ruslanmv/HomePilot-Installer](https://huggingface.co/spaces/ruslanmv/HomePilot-Installer) | Gradio wizard |

## Architecture

```
┌──────────────────────────┐
│  Installer Space         │  ← Public, Gradio UI
│  (ruslanmv/HomePilot-    │     Authenticates user
│   Installer)             │     Creates user's Space
└───────────┬──────────────┘     Pushes template
            │
            │ HF API + Git Push
            ▼
┌──────────────────────────┐
│  User's Private Space    │  ← Private, Docker + GPU
│  (username/HomePilot)    │     Ollama + HomePilot
│                          │     14 Chata personas
│  Built from: builder/    │     Full AI stack
└──────────────────────────┘
            ▲
            │ Source template
┌───────────┴──────────────┐
│  Template Space          │  ← Public reference
│  (ruslanmv/HomePilot)    │     Docker blueprint
│                          │     Used by installer
│  Built from: builder/    │
└──────────────────────────┘
```

## Directory Structure

```
hf/
├── README.md              ← This file
├── installer/             ← Installer Space (Gradio)
│   ├── app.py             ← 3-step wizard: Auth → Config → Install
│   ├── requirements.txt   ← gradio 5.x, requests
│   ├── README.md          ← HF frontmatter (sdk: gradio)
│   └── deploy.sh          ← Deploy script
└── builder/               ← Builder Template (Docker)
    ├── Dockerfile          ← Multi-stage: Vite + Python + Ollama
    ├── README.md.template  ← HF frontmatter (sdk: docker)
    ├── start.sh            ← Entrypoint: Ollama → model → personas → app
    ├── hf_wrapper.py       ← Serves React frontend from FastAPI
    ├── auto_import_personas.py ← Extracts .hpersona on first run
    ├── .dockerignore
    └── chata-personas/     ← 14 bundled .hpersona files
```

## Deployment

A single command deploys **both** Spaces (auto-sync):

```bash
HF_TOKEN=hf_... bash deploy/huggingface-space/scripts/deploy-hf.sh
```

Or via GitHub Actions: push to `main` triggers `.github/workflows/sync-hf-spaces.yml`.

## Pre-installed Chata Personas

14 social chat personas bundled and auto-imported on first boot.

| Pack | Personas |
|------|----------|
| **Starter** | Lunalite Greeter, Chillbro Regular, Curiosa Driver, Hypekid Reactions |
| **Retro** | Volt Buddy, Ronin Zero, Rival Kaiju, Glitchbyte, Questkid 99, Sigma Sage, Wildcard Loki, Oldroot Oracle, Morphling X, Nova Void |

Each `.hpersona` includes: manifest, system prompt, preview card (tags, backstory, stats), avatar image, and dependency declarations.

## Changelog

### 2026-04-12

- **Two-Space Architecture**: Installer (Gradio) + Builder (Docker) pattern.
  Installer creates user-owned private Spaces via HF API + git push.
- **Ollama sidecar**: Bundled in Docker image, `qwen2.5:1.5b` pulled on first
  start. Configurable via `OLLAMA_MODEL` env var.
- **14 Chata personas**: Auto-imported from `.hpersona` ZIP files on first boot
  via `auto_import_personas.py`. Includes Starter Pack (4) + Retro Pack (10).
- **Persona quality pass**: Added `tags`, `backstory`, `stats`, `style_tags`,
  `tone_tags` to all 34 persona `preview/card.json` files to match HomePilot
  gallery display requirements.
- **Mobile-responsive sidebar**: Drawer overlay on `< 768px` with bottom-left
  FAB hamburger button (Grok-style). Desktop layout unchanged.
- **iOS zoom fix**: Chat textarea bumped to `16px`, viewport `maximum-scale=1`.
- **Auto-sync deploy**: `deploy-hf.sh` now pushes both Builder and Installer
  Spaces in a single run. GitHub Action `sync-hf-spaces.yml` triggers on push.
- **Gallery sync workflow** (Chata repo): `sync-gallery.yml` publishes only the
  14 public personas to Cloudflare R2 gallery. Core and system personas are
  never published (platform-locked IP).
- **Docker build cache-bust**: `.cache-bust` timestamp file ensures HF's Docker
  layer cache doesn't serve stale frontend builds.
- **LFS for binaries**: `.hpersona`, `.png`, `.webp` files tracked via Git LFS
  for HF Spaces compatibility.

### Architecture decisions

| Decision | Rationale |
|----------|-----------|
| Ollama CPU (no GPU) | Free tier has no GPU; qwen2.5:1.5b runs on CPU |
| ComfyUI disabled | Needs CUDA; set `COMFY_BASE_URL=""` |
| `/tmp` for storage | HF constraint: only `/tmp` is writable |
| Single port 7860 | HF requirement; FastAPI serves API + frontend |
| hf_wrapper.py | Adds frontend catch-all without modifying main.py |
| Public-only gallery | Core/system personas are platform IP |
