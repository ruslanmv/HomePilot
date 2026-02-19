# HomePilot — Repository Structure

A map of the codebase, organized by layer.

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
│   │   ├── Dockerfile               # Single generic image for all MCP/A2A servers
│   │   ├── .dockerignore            # Build-context exclusions
│   │   ├── mcp/                     # 15 MCP tool servers (ports 9101-9119)
│   │   │   ├── personal_assistant_server.py   # Core (9101)
│   │   │   ├── knowledge_server.py            # Core (9102)
│   │   │   ├── decision_copilot_server.py     # Core (9103)
│   │   │   ├── executive_briefing_server.py   # Core (9104)
│   │   │   ├── web_search_server.py           # Core (9105)
│   │   │   ├── local_notes/                   # Local (9110)
│   │   │   ├── local_projects/                # Local (9111)
│   │   │   ├── web/                           # Local (9112)
│   │   │   ├── shell_safe/                    # Local (9113)
│   │   │   ├── gmail/                         # Comms (9114)
│   │   │   ├── google_calendar/               # Comms (9115)
│   │   │   ├── microsoft_graph/               # Comms (9116)
│   │   │   ├── slack/                         # Comms (9117)
│   │   │   ├── github/                        # Dev (9118)
│   │   │   └── notion/                        # Dev (9119)
│   │   └── a2a/                     # 2 A2A agents (ports 9201-9202)
│   │       ├── everyday_assistant_agent.py
│   │       └── chief_of_staff_agent.py
│   ├── forge/                       # Context Forge seed scripts & templates
│   │   ├── seed/seed_all.py         # Register all servers in Forge
│   │   └── templates/               # Gateway & virtual server YAML definitions
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
│   ├── sample/                      # Bootstrap sample data + .hpersona packages
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
│   ├── verification.md              # End-to-end verification guide
│   ├── BLOG.md                      # Medium tutorial / feature overview
│   ├── index.html                   # Landing page (GitHub Pages)
│   ├── gallery.html                 # Community persona gallery browser
│   ├── gallery.js                   # Gallery client-side logic
│   └── registry.json                # Persona catalog (auto-updated by Actions)
│
├── scripts/                         # Utility & automation scripts
│   ├── persona-launch.sh            # Persona-driven MCP server launcher
│   ├── verify_end_to_end.sh         # End-to-end verification (37 checks)
│   ├── mcp-register.sh              # MCP tool registration
│   ├── mcp-start.sh                 # MCP gateway startup
│   └── ...                          # Download, model management, etc.
│
├── docker-compose.mcp.yml          # MCP server orchestration (single-image pattern)
├── tools/                           # Development tooling
├── models/                          # Mounted model directories
│   ├── llm/                         # Local LLM model files
│   └── comfy/                       # Checkpoints, LoRAs, VAEs
├── outputs/                         # Generated artifacts
├── .env.example                     # Environment configuration template
├── Makefile                         # 50+ automation commands
├── API.md                           # Full API reference (160+ endpoints)
├── STRUCTURE.md                     # This file
└── README.md                        # Project overview
```
