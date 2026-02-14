<p align="center">
  <img src="../assets/homepilot-logo.svg" alt="HomePilot" width="400" />
</p>

# Meet HomePilot: The Self-Hosted AI Platform That Replaces Your Entire Creative Stack

*A local-first GenAI system with persistent AI identities, studio-grade content creation, and agentic tool access — running entirely on your hardware.*

---

## You don't need another AI chatbot. You need an AI system.

Every week there is a new AI wrapper. A new chat interface. A new "copilot" that does one thing, badly, and sends your data to someone else's server.

Meanwhile, the real problem has not changed: creative professionals, small teams, and enterprises need a **unified AI system** that handles text, image, video, and automation in a single workflow — without vendor lock-in, without per-seat pricing, and without sending proprietary data to a third party.

That is what HomePilot is.

<p align="center">
  <img src="../assets/2026-01-25-09-38-39.png" alt="HomePilot — Unified AI Interface" width="800" /><br>
  <em>The main HomePilot interface — chat, generate, edit, animate — all in one continuous conversation.</em>
</p>

---

## What HomePilot Actually Does

HomePilot is an all-in-one, self-hosted GenAI platform. You install it once. It runs on your machine. Everything stays local.

Here is what you get out of the box:

### Conversation Intelligence

A multi-turn chat system that routes your intent automatically. Ask a question — it reasons. Describe an image — it generates one. Upload a photo and describe changes — it edits. Request a video — it animates. All in one continuous conversation. No mode switching, no copy-pasting between tools.

The system supports multiple LLM backends (Ollama for local inference, or connect your own provider), and every conversation is stored locally in SQLite with full search.

### Studio-Grade Content Creation

Two creation modes, depending on your ambition:

<p align="center">
  <img src="../assets/2026-01-25-02-28-53.png" alt="Play Story Mode" width="700" /><br>
  <em>Play Story Mode — type a premise, watch a visual story come to life.</em>
</p>

**Play Story** is for quick, relaxed creation. Type a premise like *"A detective solves mysteries in a cyberpunk city"* and watch the system generate a complete visual story — scene narration, image prompts, AI-generated artwork — in minutes. Navigate scenes, enter TV Mode for cinematic fullscreen playback, and export when you are ready.

<p align="center">
  <img src="../assets/2026-01-25-02-16-36.png" alt="Creator Studio" width="700" /><br>
  <em>Creator Studio — professional project workflow with full scene, style, and export control.</em>
</p>

**Creator Studio** is the professional tier. A full project wizard with format selection (16:9, 9:16, slides), visual style kits, mood and tone presets, and AI story outline generation that produces complete story arcs. Edit narration and image prompts per scene. Regenerate images on demand. Export as PDF storyboards, PPTX presentations, or asset bundles.

<p align="center">
  <img src="../assets/2026-01-25-02-14-17.png" alt="AI Story Outline" width="700" /><br>
  <em>AI Story Outline — generate complete story arcs with scene-by-scene breakdown.</em>
</p>

Both modes support content policy enforcement, audit trails, and version history.

### Image Processing Pipeline

Upload any image and access a complete editing toolkit:

- **Quick Enhance** — restore artifacts, fix faces, sharpen details
- **Upscale** — 2x or 4x super-resolution with Real-ESRGAN
- **Background Tools** — remove, replace, or blur backgrounds in one click
- **Outpaint** — extend the canvas in any direction
- **Mask Editing** — paint regions for targeted inpainting

All powered by ComfyUI workflows — swappable, upgradeable JSON files that you control.

### Video Animation

Turn any still image into a short video clip. HomePilot ships with workflow support for six video models: **LTX-Video**, **Wan**, **Stable Video Diffusion**, **Hunyuan**, **Mochi**, and **CogVideo**. Configure aspect ratio, quality presets, motion intensity, and resolution. Hardware presets are included for RTX 4060 through A100 — or define your own.

### TV Mode — Cinematic Playback

<p align="center">
  <img src="../assets/2026-01-25-02-26-36.png" alt="TV Mode" width="700" /><br>
  <em>TV Mode — immersive fullscreen playback with auto-advance, narration overlay, and keyboard controls.</em>
</p>

---

## Personas: A New Primitive for AI

<p align="center">
  <img src="../assets/persona-logo.svg" alt="Persona" width="320" /><br>
</p>

This is the part that changes the conversation.

Every AI product today gives you a stateless text box. You type, it answers, it forgets. HomePilot introduces something fundamentally different: **Personas**.

### What Is a Persona?

A Persona is a **persistent AI identity** — not a chatbot, not a voice skin, not a prompt template. It has a name, a role, a face, a voice, a personality, and long-term memory. It does not reset between sessions. It does not forget what you told it last week.

```
Identity + Voice + Appearance + Memory + Sessions = Persona
```

Think of it as: **a named, visual, voice-enabled assistant with a defined personality, behavior, and memory scope that you can talk to over time.**

### Why This Matters

The difference between a chatbot and a Persona is the difference between a tool you use and an assistant that works *for you*.

| Dimension | Traditional Chatbot | HomePilot Persona |
| :--- | :--- | :--- |
| **Identity** | Anonymous, generic | Named, with face, voice, role |
| **Memory** | Resets every session | Persistent across sessions, months, years |
| **Sessions** | One-shot, disposable | Resumable, browsable, non-destructive |
| **Appearance** | None | Authoritative avatar, wardrobe system |
| **Tools** | None | MCP gateway with real-world tool access |
| **Relationship** | Stranger every time | Knows your preferences, style, history |

### Core Capabilities

A Persona in HomePilot currently supports:

1. **Stable Identity** — name, role, personality, behavioral prompts that persist across all sessions
2. **Visual Presence** — selectable avatar, multiple generated portraits, wardrobe system. *"Show me your photo"* always works.
3. **Voice Integration** — 6 voice personas (Ara, Eve, Leo, Rex, Sal, Gork) with speed control, mixable with any identity
4. **Multi-Session Management** — unlimited voice and text sessions, all resumable, all browsable
5. **Long-Term Memory** — facts, preferences, emotional patterns, relationship context — persistent, cross-session, compact
6. **Project-Backed Architecture** — stored in HomePilot's existing Projects system, fully additive, non-destructive

### 15 Built-in Personality Agents

HomePilot ships with personalities ready to use — from a professional **Assistant** to a **Kids Story Time** narrator, a **Therapist** using CBT techniques, a **Meditation** guide, a high-energy **Motivational** coach, a **Storyteller**, a **Debater**, and more. Each carries its own system prompt, behavioral dynamics, and conversation style. The AI stays in character throughout the session.

But built-in personalities are just the starting point. **Custom Personas** are project-backed characters you create — with their own avatars, wardrobe systems, and configurable behavior. Create a "Personal Secretary" Persona and it will remember your preferences, your schedule patterns, your communication style — across every session, indefinitely.

> The full Persona specification is at [docs/PERSONA.md](PERSONA.md).

---

## MCP Context Forge: From Conversation to Action

<p align="center">
  <em>"A Persona that remembers you is powerful. A Persona that can <b>act for you</b> is transformative."</em>
</p>

HomePilot integrates a full **MCP (Model Context Protocol) gateway** powered by [MCP Context Forge](https://github.com/ruslanmv/mcp-context-forge). This is the open protocol for connecting AI assistants to real-world tools — and it is what turns a Persona from a conversational partner into an operational agent.

### How It Works

```
User  →  Persona  →  MCP Gateway (:4444)  →  Tool Server  →  External Service
                          │
                ┌─────────┼─────────┐
                │         │         │
          Tool Server  Tool Server  A2A Agent
          (:9101)      (:9105)     (:9201)
          Personal     Web Search  Everyday
          Assistant                Assistant
```

When a Persona is in **Linked mode**, it discovers available tools at runtime through the MCP gateway. The Persona's identity and memory inform *how* it uses tools — a "Personal Secretary" Persona sends emails with your preferred sign-off; a "Chief of Staff" Persona prioritizes your calendar based on what it knows about your week.

### Built-in Tool Servers (Ship with HomePilot)

| Tool Server | Port | What It Does |
| :--- | :--- | :--- |
| **Personal Assistant** | 9101 | Task management, reminders, scheduling |
| **Knowledge** | 9102 | Document search, RAG queries across your knowledge base |
| **Decision Copilot** | 9103 | Pro/con analysis, decision frameworks, risk assessment |
| **Executive Briefing** | 9104 | Daily digests, status summaries, reporting |
| **Web Search** | 9105 | Real-time web research (SearXNG — no API key — or Tavily) |

### A2A Agents (Agent-to-Agent Coordination)

| Agent | Port | What It Does |
| :--- | :--- | :--- |
| **Everyday Assistant** | 9201 | General-purpose help with multi-step tasks |
| **Chief of Staff** | 9202 | Prioritization, delegation, executive-level coordination |

### External Service Connectors

Through the extensible MCP gateway, you can connect **any external service**. Each connector is a standalone MCP tool server:

| Connector | Use Case |
| :--- | :--- |
| **Email (SMTP/IMAP)** | Send, read, draft, archive emails |
| **WhatsApp** | Send messages, read incoming threads |
| **Calendar (CalDAV/Google)** | Create events, check availability, send invites |
| **Slack** | Post messages, read channels, manage threads |
| **GitHub** | Create issues, review PRs, check CI status |
| **Home Automation** | Control smart devices, scenes, routines |
| **Database** | Query, insert, update structured data |

Real-world examples:

- *"Scarlett, draft a reply to the client email from this morning"*
- *"Send my wife a WhatsApp that I'll be 20 minutes late"*
- *"Block 2 hours tomorrow for the proposal review"*
- *"Post the weekly update to #engineering in Slack"*
- *"Open a GitHub issue for the login bug I described yesterday"*

### Safety: Ask-Before-Acting

All tool invocations follow a **safety-first execution model**:

| Level | Behavior | Example |
| :--- | :--- | :--- |
| **0 — Read-only** | Search, query, read — no confirmation needed | "Check my calendar for tomorrow" |
| **1 — Confirm** (default) | Persona describes the action, waits for approval | "I'll send this email. Proceed?" |
| **2 — Autonomous** | Acts independently within configured boundaries | "Meeting scheduled, invite sent." |

You control autonomy per tool, per Persona, or globally.

> The full integration guide is at [docs/INTEGRATIONS.md](INTEGRATIONS.md).

---

## The Architecture: Why It Works

HomePilot is not a monolith. It is a modular system of replaceable services orchestrated via Docker:

```
User → Frontend (React :3000) → Backend (FastAPI :8000) → Services
                                        ├── LLM Provider (Ollama :11434)
                                        ├── ComfyUI (:8188)
                                        ├── Media Service (:8002)
                                        ├── SQLite (metadata + memory)
                                        ├── MCP Gateway (:4444)
                                        │     ├── 5 Tool Servers (:9101-9105)
                                        │     └── 2 A2A Agents (:9201-9202)
                                        └── Studio API (content pipeline)
```

**150+ API endpoints** cover every operation — from chat and image generation to persona sessions, content policy enforcement, version history, and tool registration. Full OpenAPI docs ship at `/docs`.

**20+ ComfyUI workflows** handle image and video generation. To upgrade capabilities, swap a JSON file. No code changes needed.

**Everything is local.** No external telemetry. No cloud dependencies. Services bind to `127.0.0.1` by default. Your data, your models, your hardware.

---

## Getting Started

### Prerequisites

- Linux or WSL2 (macOS supported, CPU-only)
- Docker Engine + Docker Compose
- NVIDIA GPU with 8GB+ VRAM recommended (12GB+ for FLUX models)

### Install

```bash
git clone https://github.com/ruslanmv/homepilot
cd homepilot
cp .env.example .env

# Download models (choose your tier)
make download-recommended    # ~14GB — FLUX Schnell + SDXL
# make download-minimal      # ~7GB  — FLUX Schnell only
# make download-full         # ~65GB — Everything

# Build and launch
make install
make run
```

### Access

| Service | URL |
| :--- | :--- |
| **HomePilot UI** | `http://localhost:3000` |
| **API Documentation** | `http://localhost:8000/docs` |
| **ComfyUI** | `http://localhost:8188` |
| **MCP Admin** | `http://localhost:4444/admin` |

From zero to running in under 15 minutes on a modern workstation.

---

## Who Is This For?

**Content creators** who want a complete AI studio — text, image, video, export — in one place, without monthly subscriptions.

**Small teams** that need a shared AI platform with project management, version control, and content policy enforcement, running on their own infrastructure.

**Enterprises** evaluating AI for internal workflows, who need audit trails, configurable safety policies, and zero data exfiltration risk.

**Developers** building AI applications who want a production-ready reference architecture with 150+ endpoints, modular services, and extensible tool integration.

**Anyone** who is tired of AI products that forget you the moment you close the tab.

---

## What Makes This Different

| | Traditional AI Chat | HomePilot |
| :--- | :--- | :--- |
| **Memory** | Per-session only | Persistent across sessions, months, years |
| **Identity** | Generic assistant | Named Personas with face, voice, personality |
| **Modality** | Text only (or separate apps) | Text + image + video + voice in one conversation |
| **Content creation** | Copy-paste workflows | Integrated studio with outlines, scenes, export |
| **Tools** | None or proprietary plugins | Open MCP gateway with unlimited tool servers |
| **Integrations** | Closed ecosystem | Email, WhatsApp, Slack, GitHub, Calendar, Home Automation |
| **Data** | Sent to vendor servers | 100% local, self-hosted |
| **Cost** | Per-seat, per-month | One-time setup, your hardware |
| **Extensibility** | Closed ecosystem | Swap any service, add any tool, modify any workflow |

---

## The Bottom Line

HomePilot is not a wrapper around an API. It is a **complete AI operating environment** — conversation, creation, memory, identity, and action — running on your hardware, under your control.

Install it. Create a Persona. Start a conversation that does not end when you close the browser.

```bash
git clone https://github.com/ruslanmv/homepilot && cd homepilot && make install && make run
```

---

<p align="center">
  <img src="../assets/homepilot-logo.svg" alt="HomePilot" width="300" /><br><br>
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/homepilot">GitHub</a> · <a href="PERSONA.md">Persona Spec</a> · <a href="INTEGRATIONS.md">Integrations Guide</a>
</p>
