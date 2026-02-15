<p align="center">
  <img src="assets/homepilot-logo.svg" alt="HomePilot" width="400" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Status-Release-brightgreen?style=for-the-badge" alt="Release" />
  <img src="https://img.shields.io/badge/License-Apache_2.0-green?style=for-the-badge" alt="License" />
  <img src="https://img.shields.io/badge/Stack-Local_First-purple?style=for-the-badge" alt="Local First" />
  <img src="https://img.shields.io/badge/AI-Powered-cyan?style=for-the-badge" alt="AI Powered" />
  <img src="https://img.shields.io/badge/Endpoints-160+-blue?style=for-the-badge" alt="160+ Endpoints" />
  <img src="https://img.shields.io/badge/MCP-Context_Forge-orange?style=for-the-badge" alt="MCP Context Forge" />
</p>

**HomePilot** is an all-in-one, local-first GenAI application that unifies **chat, image generation, editing, video creation, and AI-powered storytelling** into a **single continuous conversation**. Designed to deliver a high-end experience, it remains entirely **self-hosted, auditable, and extensible**.

This repository contains the **"Home Edition"**: a production-oriented stack designed to run on a local machine (ideally with an NVIDIA GPU) using Docker Compose.

<p align="center">
  <img src="assets/2026-01-25-09-38-39.png" alt="HomePilot UI" width="800" />
</p>

---

## ✨ What's New

### 🎭 Personas — Persistent AI Identities
A **Persona** in HomePilot is not a chatbot, not a voice skin, and not a prompt template. It is a **persistent AI identity** — a named, visual, voice-enabled entity with its own personality, appearance, long-term memory, and session history that evolves with you over time. Where traditional assistants forget you between conversations, a Persona remembers. Where traditional UIs give you a text box, a Persona gives you a face, a voice, and a relationship. One identity, many sessions, continuous context — this is the foundation for AI that actually knows who it's talking to. See [docs/PERSONA.md](docs/PERSONA.md) for the full specification.

### 📦 Persona Portability — Share & Install Anywhere
Create a persona in Tokyo, share it with someone in Brazil, and they get the exact same identity — personality, tools, and all. HomePilot now packages personas into a portable **`.hpersona`** file that carries everything needed to reproduce the experience on any machine:
- **Export** any persona project as a single `.hpersona` package with one click
- **Import** by dragging the file into HomePilot — a 3-step preview shows the persona card, system prompt, and a dependency check (models, tools, MCP servers, A2A agents) before installing
- **Dependency awareness** — the package records which image models, personality tools, MCP servers, and A2A agents the persona relies on; the importer shows green/amber/red status for each so you know what's ready and what needs setup
- **Schema versioned** (v2) with backward compatibility — today's exports will still import correctly in future versions
- **Durable avatars** — persona images are committed into project-owned storage with top-crop face-anchored thumbnails, surviving host changes and container restarts

### 🌐 Community Gallery — Browse, Download, Install
A public persona registry where anyone can browse, download, and install community-created personas. HomePilot supports two gallery backends:
- **Browse** — search by name, filter by tag, content rating; see preview cards
- **One-click install** — download → preview (persona card + dependency check) → import, all without leaving the app
- **Backend proxy** — the frontend never calls external URLs; a caching proxy at `/community/*` keeps CORS clean and keys private
- **Cloudflare Worker** — production tier with R2 storage, immutable versioned assets, aggressive CDN caching
- **GitHub-native pipeline** — zero-infrastructure tier using GitHub Issues for submission, Actions for validation, Releases for storage, and Pages for the gallery
- **Submit a persona** — open a [GitHub Issue](https://github.com/ruslanmv/HomePilot/issues/new?template=persona-submission.yml), attach your `.hpersona`, and a maintainer approves it with one label click
- **Automated publish** — once approved, the pipeline validates, creates a Release, updates `registry.json`, and deploys to [GitHub Pages](https://ruslanmv.github.io/HomePilot/gallery.html)
- See [docs/COMMUNITY_GALLERY.md](docs/COMMUNITY_GALLERY.md) for the full architecture and setup guide

### 🎬 Animate Studio Enhancements
Professional video generation controls for image-to-video:
- **Video Settings Panel** - Aspect Ratio, Quality Preset, and Motion controls
- **Resolution Override** - Test different resolutions (Lowest 6GB to Ultra) in Advanced Controls
- **Hardware Presets** - Optimized configurations for RTX 4060, 4080, A100, and custom setups
- **Video Details** - Shows Resolution, Aspect Ratio, and Preset used for reproducibility
- **LTX-Optimized Presets** - Tuned for LTX-Video-2B with optimal CFG (3.0-3.5) and 16:9 native support

### 🖼️ Edit Studio Enhancements
One-click image editing tools integrated into the Edit page:
- **Quick Enhance** - Enhance photo quality, restore artifacts, fix faces
- **Upscale** - 2x/4x resolution increase with UltraSharp AI
- **Background Tools** - Remove, replace, or blur backgrounds
- **Outpaint** - Extend canvas in any direction (7 options)
- **Capabilities API** - Runtime feature availability checking (`/v1/capabilities`)

### 🎬 Creator Studio
A professional content creation suite for YouTube creators, educators, and enterprises:
- **AI Story Outline Generation** - Generate complete story arcs with scene-by-scene planning
- **Project Settings** - Full wizard-style configuration for format, style, and tone
- **Scene Management** - Add, edit, delete, and reorder scenes
- **TV Mode** - Cinematic fullscreen playback experience
- **Export Options** - PDF storyboards, PPTX slides, and asset bundles

### 🤖 Agentic AI with MCP Context Forge
Create intelligent **AI Agents** that can use tools, access knowledge bases, and take actions on your behalf:
- **Agent Projects** - New project type with a guided 4-step wizard (Details → Capabilities → Knowledge → Review)
- **Dynamic Capabilities** - Agents discover available tools at runtime (image generation, video creation, document analysis, external automation)
- **MCP Gateway** - Powered by [MCP Context Forge](https://github.com/ruslanmv/mcp-context-forge), a local gateway that connects your agents to 20+ tool servers
- **Built-in MCP Servers** - 5 MCP tool servers (Personal Assistant, Knowledge, Decision Copilot, Executive Briefing, Web Search) and 2 A2A agents (Everyday Assistant, Chief of Staff) launch automatically with `make start`
- **Web Search** - SearXNG for home users (no API key) or Tavily for enterprise, providing real-time web research tools
- **Ask-Before-Acting** - Safety-first execution with configurable autonomy levels
- **Voice Mode Media** - Generated images and videos now render directly in Voice mode conversations

### 🎮 Play Story Mode
Simple, relaxing story creation for beginners:
- Enter a premise and watch your story come to life
- AI-generated scenes with automatic image generation
- Intuitive scene navigation with visual chips
- One-click TV Mode for immersive viewing

---

## 🎯 Project Aim

HomePilot aims to build a **single conversational GenAI system** where:

* **Unified Timeline:** Text, images, and video live in one chronological feed.
* **Multimodal:** Users can ask questions, generate art, edit assets, create stories, and animate video without context switching.
* **Natural Interaction:** Outputs appear naturally as part of the flow.
* **Privacy First:** Everything runs locally. Your data never leaves your machine.
* **Professional Creation:** Full-featured studio for content creators and enterprises.

This serves as the foundation for an "enterprise mind" capable of expanding into complex tool usage and automation.

---

## ⚡ Key Capabilities

### Core Features

| Feature | Description |
| :--- | :--- |
| **Chat (LLM)** | Multi-turn conversations with OpenAI-style routing. Includes a "Fun mode" for creative tone modification. Support for backend-hosted LLMs or Ollama. |
| **Imagine** | Text-to-image generation powered by a workflow-driven pipeline (ComfyUI). |
| **Edit** | Upload an image and describe changes to modify it naturally within the chat. |
| **Animate** | Turn still images into short video clips with configurable aspect ratio, quality presets, and motion controls. Supports multiple video models (LTX, Wan, SVD, Hunyuan, Mochi, CogVideo). |

### Studio Features

| Feature | Description |
| :--- | :--- |
| **Play Story** | Simple story creation mode. Enter a premise, generate scenes, and watch your story unfold with AI-generated images. |
| **Creator Studio** | Professional project-based workflow with presets, style kits, and advanced generation settings. |
| **AI Story Outline** | Generate complete story structures including beginning, rising action, climax, falling action, and resolution. |
| **Scene Editor** | Edit narration, image prompts, and negative prompts for each scene. Regenerate images on demand. |
| **TV Mode** | Immersive fullscreen playback with auto-advance, narration display, and cinematic transitions. |
| **Project Settings** | Comprehensive configuration: format (16:9/9:16), intent (Entertain/Educate/Inspire), visual style, mood & tone. |
| **Agent Projects** | Create AI agents with custom goals, tool capabilities, and knowledge bases through a guided wizard. Powered by MCP Context Forge. |

---

## 🎬 Studio Modes

### Play Story Mode
*Recommended for beginners*
![](assets/2026-01-25-02-28-53.png)

Perfect for quick, relaxed story creation:
1. Enter your story premise (e.g., "A detective solves mysteries in a cyberpunk city")
2. AI generates scene narration and image prompts
3. Images are automatically generated for each scene
4. Navigate through scenes or watch in TV Mode

### Creator Studio
*Advanced features for professionals*
![](assets/2026-01-25-02-16-36.png)
Full control over your content:

#### Project Configuration
- **Format**: YouTube Video (16:9), YouTube Short (9:16), or Slides
- **Intent**: Entertain, Educate, or Inspire
- **Visual Style**: Cinematic, Digital Art, or Anime
- **Mood & Tone**: Documentary, Dramatic, Calm, Upbeat, Dark
- **Episode Length**: Configure scenes per episode and scene duration

#### AI Story Outline
Generate a complete story structure with:
- Story arc (beginning → climax → resolution)
- Scene-by-scene breakdown
- Narration and image prompts for each scene
- Automatic scene generation from outline

![](assets/2026-01-25-02-14-17.png)


#### Scene Management
- Add, edit, and delete scenes
- Custom narration and image prompts
- Negative prompt support for image quality
- Regenerate images with one click

#### Export Options
- Storyboard PDF
- Presentation slides (PPTX/PDF)
- Asset bundle (ZIP)

---

## 🖥️ User Interface

### Unified Dark Theme
A Grok-like dark minimal interface with:
- Sidebar navigation with mode switching
- Context-aware input with media upload
- Inline media rendering
- Responsive design for desktop and tablet

### TV Mode
![](assets/2026-01-25-02-26-36.png)

Cinematic fullscreen experience:
- Auto-advance through scenes
- Narration subtitle overlay
- Progress indicator
- Keyboard controls (Space to play/pause, arrows to navigate)

### Project Management
- View all projects (Play Story + Creator Studio)
- Quick access with thumbnail previews
- Delete projects you don't need
- Status badges (Draft, In Review, Finished)

---

## 🏗️ Architecture Overview

The system is modular, consisting of replaceable services orchestrated via Docker.

```mermaid
graph LR
    User([User]) -->|Browser| Frontend[Frontend React :3000]
    Frontend -->|API| Backend[Backend Orchestrator :8000]
    Backend -->|Text| LLM[LLM Provider Ollama :11434]
    Backend -->|Gen/Edit| Comfy[ComfyUI :8188]
    Backend -->|Process| Media[Media Service FFMPEG :8002]
    Backend -->|Store| DB[(SQLite)]
    Backend -->|Studio| Studio[Studio API]
    Backend -->|Agentic| MCP[MCP Gateway :4444]
    MCP -->|Tools| Servers[MCP Tool Servers :9101-9105]
    MCP -->|A2A| Agents[A2A Agents :9201-9202]
    Studio -->|Stories| StoryDB[(Story Store)]
```

### Data & Storage

* **Metadata:** Stored locally in SQLite.
* **Media:** Generated outputs are written to disk (`./outputs`).
* **Stories:** Project data and scenes stored in-memory (MVP) or SQLite.
* **Privacy:** No external telemetry. Services bind to `127.0.0.1` by default.

---

## 📂 Repository Structure

```text
homepilot/
├── frontend/                        # React 18 + Vite + TypeScript
│   └── src/
│       ├── main.tsx                 # Application entry point
│       ├── agentic/                 # Agentic UI (catalog, connections)
│       └── ui/
│           ├── App.tsx              # Root component & routing
│           ├── VoiceMode.tsx        # Voice conversation interface
│           ├── Studio.tsx           # Play Story mode
│           ├── CreatorStudioEditor.tsx  # Creator Studio editor
│           ├── CreatorStudioHost.tsx    # Project wizard
│           ├── PersonaWizard.tsx    # Persona creation wizard
│           ├── ProjectsView.tsx     # Project management dashboard
│           ├── api.ts               # API client layer
│           ├── personaApi.ts        # Persona-specific API client
│           ├── personaPortability.ts # Export/import types & API helpers
│           ├── PersonaImportExport.tsx # Import modal + export button
│           ├── CommunityGallery.tsx  # Community gallery browse + install
│           ├── communityApi.ts       # Community gallery API client
│           ├── components/          # Shared UI components
│           ├── edit/                # Image editing UI (mask, outpaint, background)
│           ├── enhance/             # Enhancement APIs (upscale, background, capabilities)
│           ├── sessions/            # Session management UI
│           ├── studio/              # Creator Studio subsystem
│           │   ├── components/      # Scene chips, TV mode, presets, badges
│           │   ├── stores/          # Zustand state (studioStore, tvModeStore)
│           │   └── styles/          # Studio themes and CSS
│           └── voice/               # Voice subsystem
│               ├── personalities.ts # 15 built-in personality definitions
│               ├── voices.ts        # 6 voice persona definitions
│               ├── personalityGating.ts  # Adult gating & persona toggles
│               └── useVoiceController.ts # Voice state machine
│
├── backend/                         # FastAPI orchestrator (Python 3.11+)
│   └── app/
│       ├── main.py                  # Primary route definitions (70+ endpoints)
│       ├── config.py                # Environment & feature configuration
│       ├── llm.py                   # LLM provider integration
│       ├── comfy.py                 # ComfyUI workflow orchestration
│       ├── orchestrator.py          # Request routing & pipeline
│       ├── projects.py              # Project & knowledge base management
│       ├── sessions.py              # Session lifecycle management
│       ├── storage.py               # SQLite persistence layer
│       ├── ltm.py                   # Long-term memory engine
│       ├── vectordb.py              # Vector database for RAG
│       ├── enhance.py               # Image enhancement pipeline
│       ├── upscale.py               # Super-resolution (2x/4x)
│       ├── background.py            # Background removal & replacement
│       ├── outpaint.py              # Canvas extension
│       ├── story_mode.py            # Story generation engine
│       ├── game_mode.py             # Interactive game sessions
│       ├── search.py                # Web search integration
│       ├── community.py             # Community gallery proxy (/community/*)
│       ├── agentic/                 # Agentic AI subsystem
│       │   ├── routes.py            # /v1/agentic/* endpoints (11 routes)
│       │   ├── capabilities.py      # Dynamic tool discovery
│       │   ├── catalog.py           # Wizard-friendly tool catalog
│       │   ├── client.py            # Context Forge HTTP client
│       │   ├── policy.py            # Ask-before-acting safety policies
│       │   ├── runtime_tool_router.py  # Runtime tool dispatch
│       │   └── sync_service.py      # HomePilot ↔ Forge sync
│       ├── personalities/           # Persona & personality system
│       │   ├── registry.py          # Thread-safe personality registry
│       │   ├── prompt_builder.py    # Dynamic system prompt assembly
│       │   ├── memory.py            # Persona memory management
│       │   ├── tools.py             # Persona tool integrations
│       │   ├── types.py             # PersonalityAgent Pydantic models
│       │   └── definitions/         # 15 personality agent modules
│       ├── personas/                # Persona portability (Phase 3)
│       │   ├── avatar_assets.py     # Durable avatar commit + face-crop thumbnails
│       │   ├── export_import.py     # .hpersona v2 package export/import
│       │   └── dependency_checker.py # Model/tool/MCP/agent availability check
│       └── studio/                  # Creator Studio subsystem
│           ├── routes.py            # /studio/* endpoints (65+ routes)
│           ├── service.py           # Studio business logic
│           ├── models.py            # Pydantic schemas
│           ├── repo.py              # Data repository
│           ├── library.py           # Style kits & project templates
│           ├── exporter.py          # PDF, PPTX, ZIP export
│           ├── policy.py            # Content policy & compliance
│           ├── audit.py             # Audit trail
│           └── story_genres.py      # Genre definitions
│
├── agentic/                         # MCP + A2A integration layer
│   ├── integrations/
│   │   ├── mcp/                     # 5 MCP tool servers (ports 9101-9105)
│   │   │   ├── personal_assistant_server.py
│   │   │   ├── knowledge_server.py
│   │   │   ├── decision_copilot_server.py
│   │   │   ├── executive_briefing_server.py
│   │   │   └── web_search_server.py
│   │   └── a2a/                     # 2 A2A agents (ports 9201-9202)
│   │       ├── everyday_assistant_agent.py
│   │       └── chief_of_staff_agent.py
│   ├── forge/                       # Context Forge seed scripts & templates
│   ├── suite/                       # Suite manifests (home + pro profiles)
│   ├── ops/compose/                 # Agentic Docker infrastructure
│   └── specs/                       # Architecture & launch specifications
│
├── community/                       # Community Gallery infrastructure
│   ├── worker/                      # Cloudflare Worker (R2 proxy + caching)
│   │   ├── src/index.ts             # Worker source
│   │   └── wrangler.toml            # Worker config (R2 binding)
│   ├── scripts/                     # GitHub Actions pipeline scripts
│   │   └── process_submission.py    # Validate, extract, registry management
│   ├── pages/                       # Static gallery website (Cloudflare)
│   │   ├── index.html               # Gallery page
│   │   ├── app.js                   # Search + card rendering
│   │   └── styles.css               # Dark theme
│   ├── sample/                      # Bootstrap sample data
│   └── bootstrap.sh                 # One-shot setup script
│
├── comfyui/                         # ComfyUI integration
│   ├── Dockerfile                   # ComfyUI container image
│   └── workflows/                   # 20+ JSON workflow definitions
│       ├── txt2img-flux-schnell.json    # FLUX Schnell generation
│       ├── txt2img-flux-dev.json        # FLUX Dev generation
│       ├── txt2img-pony-xl.json         # Pony XL generation
│       ├── img2vid-ltx.json             # LTX Video animation
│       ├── img2vid-wan.json             # Wan Video animation
│       ├── img2vid-cogvideo.json        # CogVideo animation
│       ├── img2vid-hunyuan.json         # Hunyuan Video animation
│       ├── img2vid-mochi.json           # Mochi Video animation
│       ├── edit.json                    # Image editing
│       ├── upscale.json                 # Super-resolution
│       ├── enhance_realesrgan.json      # Real-ESRGAN enhancement
│       ├── outpaint.json                # Canvas outpainting
│       ├── remove_background.json       # Background removal
│       └── change_background.json       # Background replacement
│
├── media/                           # Media processing service (FFmpeg)
│   ├── Dockerfile
│   └── app.py                       # Media service endpoints
│
├── infra/                           # Docker infrastructure
│   ├── docker-compose.yml           # Main service orchestration
│   ├── docker-compose.edit-session.yml
│   └── ollama/Dockerfile            # Ollama LLM container
│
├── docs/                            # Documentation + GitHub Pages
│   ├── PERSONA.md                   # Persona system specification
│   ├── AGENTIC_SERVERS.md           # MCP & A2A server reference
│   ├── CONNECTIONS.md               # Integration & connection guide
│   ├── TV_MODE_DESIGN.md            # TV mode architecture
│   ├── COMMUNITY_GALLERY.md         # Community gallery architecture & setup
│   ├── BLOG.md                      # Medium tutorial / feature overview
│   ├── index.html                   # Landing page (GitHub Pages)
│   ├── gallery.html                 # Community persona gallery browser
│   ├── gallery.js                   # Gallery client-side logic
│   └── registry.json                # Persona catalog (auto-updated by Actions)
│
├── scripts/                         # Utility & automation scripts
├── tools/                           # Development tooling
├── models/                          # Mounted model directories
│   ├── llm/                         # Local LLM model files
│   └── comfy/                       # Checkpoints, LoRAs, VAEs
├── outputs/                         # Generated artifacts
├── Makefile                         # 50+ automation commands
└── README.md
```

---

## 🛠️ Requirements

### System

* **OS:** Linux or WSL2 (Recommended). macOS supported (CPU-only constraints apply).
* **Runtime:** Docker Engine + Docker Compose plugin.
* **Dev:** Node.js 20+ (Only for local frontend development).

### GPU (Recommended)

* **Hardware:** NVIDIA GPU with 8GB+ VRAM (12GB+ recommended for FLUX models).
* **Drivers:** Latest NVIDIA drivers + NVIDIA Container Toolkit.
* *Note: If running without a GPU, disable GPU runtime settings in `docker-compose.yml`.*

### LLM Requirements

* **Ollama:** Automatically pulls models when needed.
* **Recommended Models:**
  - `llama3.2` - Fast, general purpose
  - `mistral` - Good balance of speed and quality
  - `deepseek-r1` - Advanced reasoning capabilities

---

## 🚀 Quickstart

### 1. Clone

```bash
git clone https://github.com/ruslanmv/homepilot
cd homepilot
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env to set ports, API keys, or paths
```

### 3. Download Models (Automated)

HomePilot provides automated model installation with three preset options:

```bash
# Recommended: FLUX Schnell + SDXL (~14GB)
make download-recommended

# Or choose a different preset:
# make download-minimal      # ~7GB - FLUX Schnell only
# make download-full         # ~65GB - All models including FLUX Dev, SD1.5, SVD
```

The script automatically:
- ✓ Checks if models exist before downloading
- ✓ Resumes interrupted downloads
- ✓ Retries failed downloads with exponential backoff
- ✓ Shows progress and summary statistics

For detailed installation options and manual installation, see [MODEL_INSTALLATION.md](MODEL_INSTALLATION.md)

**LLM Models** are managed separately via Ollama (auto-pulled when needed).

### 4. Build and Run

```bash
make install
make run
```

### 5. Access

* **UI:** `http://localhost:3000`
* **API Docs:** `http://localhost:8000/docs`
* **ComfyUI:** `http://localhost:8188`
* **MCP Gateway:** `http://localhost:4444/admin` *(when agentic mode is enabled)*

---

## 🎮 Using the Interface

### Chat Modes

HomePilot uses **Modes** to route user intent:

1. **Chat Mode:** Standard reasoning and conversation.
2. **Imagine Mode:** Auto-formats prompts for text-to-image generation.
3. **Edit Mode:** Upload an image → Describe changes → Receive edited image.
4. **Animate Mode:** Upload an image → Describe motion → Receive video clip.

### Studio Modes

Access from the sidebar or main interface:

1. **Play Story:** Quick story creation with AI-generated scenes.
2. **Creator Studio:** Professional project workflow with full control.

### Studio Quick Start

#### Play Story
1. Click "Play Story" from the studio menu
2. Click "New Story" and enter a premise
3. Watch as scenes are generated automatically
4. Use scene chips to navigate or enter TV Mode

#### Creator Studio
1. Click "Creator Studio" from the studio menu
2. Complete the 4-step wizard:
   - **Details:** Title, format, intent, episode length
   - **Visuals:** Style preset, mood & tone
   - **Checks:** Consistency lock, content rating
   - **Review:** Confirm settings and create
3. Generate your first scene
4. Use the ⚙️ Settings button to modify project configuration anytime

### Settings

Located in the bottom-left of the sidebar:

* **Backend URL:** Switch backends dynamically.
* **Provider:** Toggle between internal Backend routing (Recommended) or direct Ollama connection.

---

## 🔌 API Reference — 160+ Endpoints

Full interactive documentation is available at `http://localhost:8000/docs` after launch.

### Core

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/health` | GET | Basic health check |
| `/health/detailed` | GET | Full service status with dependency checks |
| `/models` | GET | List installed LLM and image models |
| `/model-catalog` | GET | Browse available models for download |
| `/providers` | GET | List configured LLM providers |
| `/settings` | GET | Application configuration |
| `/chat` | POST | Primary chat endpoint (text, imagine, edit, animate) |
| `/upload` | POST | File upload for chat attachments |

### Conversations & Memory

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/conversations` | GET | List all conversations |
| `/conversations/{id}/messages` | GET | Retrieve conversation history |
| `/conversations/{id}` | DELETE | Delete a conversation |
| `/conversations/{id}/search` | GET | Full-text search within a conversation |

### Projects & Knowledge Base

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/projects` | GET | List all projects |
| `/projects` | POST | Create project (Persona, Agent, or Knowledge) |
| `/projects/{id}` | GET | Get project details |
| `/projects/{id}` | PUT | Update project configuration |
| `/projects/{id}` | DELETE | Delete project |
| `/projects/{id}/upload` | POST | Upload document to project knowledge base |
| `/projects/{id}/documents` | GET | List project documents |
| `/projects/examples` | GET | Browse example project templates |
| `/projects/from-example/{id}` | POST | Create project from template |

### Persona System

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/personalities` | GET | List all 15 built-in personalities |
| `/api/personalities/{id}` | GET | Get personality definition and system prompt |
| `/persona/sessions` | GET | List all persona sessions |
| `/persona/sessions` | POST | Create new session with a persona |
| `/persona/sessions/resolve` | POST | Resolve or resume an existing session |
| `/persona/sessions/{id}` | GET | Get session details and history |
| `/persona/sessions/{id}/end` | POST | End an active session |
| `/persona/memory` | GET | Retrieve long-term memory entries |
| `/persona/memory` | POST | Store a new memory entry |
| `/persona/memory` | DELETE | Clear persona memory |
| `/projects/{id}/persona/avatar/commit` | POST | Commit avatar to durable project-owned storage |
| `/projects/{id}/persona/export` | GET | Download persona as `.hpersona` package |
| `/persona/import` | POST | Upload `.hpersona` and create project |
| `/persona/import/preview` | POST | Preview package contents and dependency check |

### Image Enhancement (v1)

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/v1/capabilities` | GET | Discover available enhancement features |
| `/v1/capabilities/{feature}` | GET | Check specific feature availability |
| `/v1/enhance` | POST | AI enhancement (restore, fix faces, sharpen) |
| `/v1/upscale` | POST | Super-resolution upscale (2x / 4x) |
| `/v1/background` | POST | Remove, replace, or blur background |
| `/v1/outpaint` | POST | Extend canvas in any direction |
| `/v1/edit-models` | GET | List available edit models |
| `/v1/edit-models/preference` | POST | Set model preference |

### Edit Sessions (v1)

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/v1/edit-sessions/{id}` | GET | Get edit session state |
| `/v1/edit-sessions/{id}` | DELETE | Delete edit session |
| `/v1/edit-sessions/{id}/image` | POST | Upload source image |
| `/v1/edit-sessions/{id}/message` | POST | Send edit instruction |
| `/v1/edit-sessions/{id}/select` | POST | Select result variant |
| `/v1/edit-sessions/{id}/revert` | POST | Revert to previous state |

### Story Mode

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/story/start` | POST | Start a new story session |
| `/story/continue` | POST | Continue generating the story |
| `/story/next` | POST | Generate next scene |
| `/story/{id}` | GET | Retrieve story with all scenes |
| `/story/sessions/list` | GET | List all story sessions |
| `/story/{id}` | DELETE | Delete a story |
| `/story/{id}/scene/{idx}` | DELETE | Delete a specific scene |
| `/story/scene/image` | POST | Generate image for a scene |

### Creator Studio (65+ endpoints)

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/studio/videos` | GET | List studio projects |
| `/studio/videos` | POST | Create studio project |
| `/studio/videos/{id}` | GET / PATCH / DELETE | Project CRUD |
| `/studio/videos/{id}/scenes` | GET / POST | Scene listing & creation |
| `/studio/videos/{id}/scenes/{sid}` | GET / PATCH / DELETE | Scene CRUD |
| `/studio/videos/{id}/generate-outline` | POST | AI story outline generation |
| `/studio/videos/{id}/outline` | GET | Retrieve saved outline |
| `/studio/videos/{id}/scenes/generate-from-outline` | POST | Batch-generate scenes from outline |
| `/studio/videos/{id}/export` | POST | Export (PDF, PPTX, ZIP) |
| `/studio/videos/{id}/policy` | GET | Content policy status |
| `/studio/videos/{id}/policy/check` | POST | Run policy compliance check |
| `/studio/videos/{id}/audit` | GET | Audit trail |
| `/studio/genres` | GET | List story genres |
| `/studio/presets` | GET | List visual presets |
| `/studio/library/style-kits` | GET | Browse style kits |
| `/studio/library/templates` | GET | Browse project templates |
| `/studio/projects/{id}/assets` | GET / POST | Asset management |
| `/studio/projects/{id}/audio` | GET / POST | Audio track management |
| `/studio/projects/{id}/captions` | GET / POST | Caption management |
| `/studio/projects/{id}/versions` | GET / POST | Version history |
| `/studio/projects/{id}/share` | GET / POST | Sharing & public links |
| `/studio/health` | GET | Studio subsystem health |

### Agentic AI

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/v1/agentic/status` | GET | Agentic system status |
| `/v1/agentic/capabilities` | GET | Discover available tools and capabilities |
| `/v1/agentic/catalog` | GET | Browse tools, agents, gateways, and servers |
| `/v1/agentic/invoke` | POST | Execute a tool via MCP Gateway |
| `/v1/agentic/suite` | GET | List suite profiles (home, pro) |
| `/v1/agentic/suite/{name}` | GET | Get suite manifest |
| `/v1/agentic/sync` | POST | Sync state with HomePilot |
| `/v1/agentic/register/tool` | POST | Register a new tool server |
| `/v1/agentic/register/agent` | POST | Register a new A2A agent |
| `/v1/agentic/register/gateway` | POST | Register a new gateway |
| `/v1/agentic/admin` | GET | Admin UI URL |

### Community Gallery

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/community/status` | GET | Check if gallery is configured and reachable |
| `/community/registry` | GET | Cached persona registry with search/filter support |
| `/community/card/{id}/{ver}` | GET | Persona card metadata proxy |
| `/community/preview/{id}/{ver}` | GET | Persona preview image proxy |
| `/community/download/{id}/{ver}` | GET | `.hpersona` package download proxy |

### API Keys & Configuration

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/settings/api-keys` | GET | List configured API keys |
| `/settings/api-keys` | POST | Add API key for a provider |
| `/settings/api-keys/{provider}` | DELETE | Remove API key |
| `/settings/api-keys/test` | POST | Test API key connectivity |
| `/video-presets` | GET | Video generation presets |
| `/image-presets` | GET | Image generation presets |

### Model Management

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/models/health` | GET | Model service health |
| `/civitai/search` | POST | Search Civitai model registry |
| `/models/install` | POST | Install model from Civitai |
| `/models/delete` | POST | Remove installed model |

---

## ⚙️ Workflows (ComfyUI)

HomePilot is **workflow-driven**. Instead of hardcoded pipelines, it loads JSON workflows from `comfyui/workflows/`.

* **Flexibility:** To upgrade generation capabilities, simply update the JSON workflow file.
* **Process:** Backend injects prompts into the JSON → Submits to ComfyUI → Polls for results → Returns media URL.

### Available Workflows

- `flux_schnell.json` - Fast FLUX image generation
- `sdxl_base.json` - SDXL image generation
- `animate.json` - Image-to-video animation (LTX-Video)
- `wan_i2v.json` - Wan image-to-video
- `svd_animate.json` - Stable Video Diffusion
- `edit.json` - Image editing with inpainting

---

## 💻 Makefile Commands

| Command | Description |
| --- | --- |
| `make help` | Show available commands |
| `make install` | Install dependencies and build Docker images |
| `make download` | Download recommended models (~14GB) |
| `make download-minimal` | Download minimal models (~7GB) |
| `make download-full` | Download all models (~65GB) |
| `make download-verify` | Verify downloaded models and show disk usage |
| `make run` | Start the full stack (detached) |
| `make logs` | Tail logs for all services |
| `make down` | Stop and remove containers |
| `make health` | Run best-effort health checks |
| `make health-check` | Comprehensive health check of all services |
| `make start` | Start all services (set `AGENTIC=1` for MCP + tool servers) |
| `make start-mcp` | Start MCP Context Forge gateway and servers |
| `make start-agentic-servers` | Start MCP tool servers + A2A agents standalone |
| `make mcp-register-homepilot` | Register default tools with MCP Gateway |
| `make dev` | Run frontend locally + backend in Docker |
| `make clean` | Remove local artifacts and cache |
| `make community-bootstrap` | Bootstrap Cloudflare R2 + Worker + Pages for Community Gallery |
| `make community-deploy-worker` | Deploy the Community Gallery Worker |
| `make community-deploy-pages` | Deploy the Community Gallery static site |

---

## 🎨 Customization

### Adding Visual Styles

Edit `backend/app/studio/library.py` to add custom style kits:

```python
StyleKit(
    id="sk_custom",
    name="My Custom Style",
    thumbnail_url="/assets/styles/custom.jpg",
    base_prompt_suffix="your style keywords here",
    negative_prompt="elements to avoid",
    recommended_models=["flux-schnell"],
)
```

### Adding Templates

Add project templates for quick starts:

```python
ProjectTemplate(
    id="tmpl_custom",
    name="My Template",
    description="Description here",
    category="education",
    default_scene_count=6,
    default_scene_duration_sec=5,
    style_kit_id="sk_modern_light",
    sample_outline=["Scene 1", "Scene 2", ...],
)
```

---

## 🗺️ Roadmap

### Completed
- [x] Play Story mode with AI scene generation
- [x] Creator Studio with project wizard
- [x] AI-powered story outline generation
- [x] Scene management (add, edit, delete)
- [x] TV Mode for immersive playback
- [x] Project settings modal
- [x] Export functionality (PDF, PPTX, ZIP)
- [x] Edit Studio: Quick Enhance, Upscale 2x/4x, Background Tools, Outpaint
- [x] Capabilities API for runtime feature checks
- [x] Animate Studio: Video Settings panel, Resolution Override, Hardware Presets
- [x] Multi-model video support (LTX, Wan, SVD, Hunyuan, Mochi, CogVideo)

- [x] Agentic AI: Agent project type with 4-step creation wizard
- [x] MCP Context Forge integration with dynamic capability discovery
- [x] Built-in MCP tool servers (Personal Assistant, Knowledge, Decision Copilot, Executive Briefing, Web Search) and A2A agents (Everyday Assistant, Chief of Staff)
- [x] Web Search MCP server with SearXNG (home) and Tavily (enterprise) providers
- [x] Voice mode media rendering (images and videos)
- [x] Voice Input/Output with browser TTS and speech recognition
- [x] Voice narration with TTS (6 voice personas, speed control, hands-free mode)
- [x] 15 built-in personality agents with backend-authoritative prompts
- [x] Custom Personas with linked/unlinked project modes
- [x] Adult content gating with age verification
- [x] Persona portability: `.hpersona` export/import with dependency manifests (tools, MCP, A2A, models)
- [x] Durable avatar storage with face-anchored thumbnails
- [x] First-time persona welcome screen (replaces empty "Continue Last Session")
- [x] Community Gallery: Cloudflare R2 + Worker persona registry with MMORPG patcher pattern
- [x] Community browse & one-click install from "Shared with me" tab
- [x] GitHub-native persona submission pipeline (Issue template → Actions → Release → Pages gallery)
- [x] Persona submission moderation workflow (admin-gated label approval)
- [x] Community Gallery web page on GitHub Pages with search, filters, and download

### In Progress
- [ ] Background music integration
- [ ] Timeline editor with drag-and-drop
- [ ] Multi-chapter support

### Planned
- [ ] MP4 video export with ffmpeg
- [ ] Collaborative editing
- [ ] Plugin system for custom workflows
- [ ] Multi-provider LLM routing
- [ ] OpenTelemetry observability

---

## 🐛 Troubleshooting

### Common Issues

**Story outline generation fails**
- Ensure Ollama is running and accessible
- Check that at least one LLM model is available
- Verify the backend can connect to Ollama

**Images not generating**
- Verify ComfyUI is running (`http://localhost:8188`)
- Check that image models are downloaded
- Review backend logs for workflow errors

**TV Mode not working**
- Ensure at least one scene exists
- Check browser console for errors
- Try refreshing the page

### Logs

```bash
# View all logs
make logs

# View specific service
docker compose logs -f backend
docker compose logs -f comfyui
```

---

## 🤝 Contributing

Contributions are welcome! Please check `CONTRIBUTING.md` for coding standards and PR checklists.

### Development Setup

```bash
# Frontend development (hot reload)
cd frontend
npm install
npm run dev

# Backend development
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

---

## 📄 License

Apache-2.0

---

## 🙏 Acknowledgments

- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) - Powerful image generation backend
- [Ollama](https://ollama.ai) - Local LLM inference
- [FLUX](https://blackforestlabs.ai) - State-of-the-art image models
- [React](https://react.dev) - UI framework
- [FastAPI](https://fastapi.tiangolo.com) - Backend framework
- [Zustand](https://zustand-demo.pmnd.rs) - State management
- [MCP Context Forge](https://github.com/ruslanmv/mcp-context-forge) - Agentic AI gateway and tool servers

---

<p align="center">
  <b>HomePilot</b> - Your AI-Powered Creative Studio
  <br>
  <sub>Built with ❤️ for creators, by creators</sub>
  <br><br>
  <sub>🎭 15 personality agents with conversation memory, dynamic prompts, and per-turn engagement — plus portable persona packages you can share with the world.</sub>
</p>
