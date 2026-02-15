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

### Persona Portability — Share & Install Anywhere

Create a persona in Tokyo, share it with someone in Brazil, and they get the exact same identity — personality, tools, and all. HomePilot packages personas into a portable **`.hpersona`** file:

- **Export** any persona project as a single `.hpersona` package with one click
- **Import** by dragging the file into HomePilot — a 3-step preview shows the persona card, system prompt, and a dependency check before installing
- **Dependency awareness** — the package records which image models, personality tools, MCP servers, and A2A agents the persona relies on; the importer shows green/amber/red status for each
- **Schema versioned** (v2) with backward compatibility

> The full Persona specification is at [docs/PERSONA.md](PERSONA.md).

---

## Community Gallery: Share Personas with the World

HomePilot includes a **Community Gallery** — a public registry where anyone can browse, download, and install personas created by other users. The gallery runs on two tiers:

### Cloudflare-Hosted Gallery (Production)

For high-traffic production deployments, HomePilot supports a **Cloudflare R2 + Workers** backend following an MMORPG patcher pattern:

- `registry.json` as a patch manifest with aggressive CDN caching
- Immutable versioned packages — once uploaded, never changed
- Backend proxy at `/community/*` keeps CORS clean and keys private
- Users browse and install directly from the **"Shared with me"** tab

### GitHub-Native Gallery (Zero Infrastructure)

For open-source communities and projects that want **zero infrastructure cost**, HomePilot now ships a fully serverless persona sharing pipeline powered entirely by GitHub:

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│  USER            │     │  ADMIN           │     │  GITHUB ACTIONS      │
│                  │     │                  │     │                      │
│ 1. Export        │     │ 4. Review issue  │     │ 6. Download package  │
│    .hpersona     │────▶│ 5. Add label     │────▶│ 7. Validate ZIP      │
│ 2. Open Issue    │     │    "persona-     │     │ 8. Extract preview   │
│ 3. Attach file   │     │     approved"    │     │ 9. Create Release    │
│                  │     │                  │     │ 10. Update registry  │
└─────────────────┘     └──────────────────┘     │ 11. Comment + close  │
                                                  └──────────┬───────────┘
                                                             │ auto-rebuild
                                                  ┌──────────▼───────────┐
                                                  │  GITHUB PAGES        │
                                                  │                      │
                                                  │  gallery.html        │
                                                  │  registry.json       │
                                                  │  previews/           │
                                                  └──────────┬───────────┘
                                                             │ fetch
                                                  ┌──────────▼───────────┐
                                                  │  HOMEPILOT CLIENT    │
                                                  │                      │
                                                  │  Browse → Download   │
                                                  │  → Preview → Install │
                                                  └──────────────────────┘
```

**How to submit a persona:**

1. In HomePilot, go to **My Projects**, find your persona, and click **Export** to get a `.hpersona` file
2. Go to the [Persona Submission](https://github.com/ruslanmv/HomePilot/issues/new?template=persona-submission.yml) page on GitHub
3. Fill in the form: name, description, tags, content rating
4. Drag and drop your `.hpersona` file into the attachment field
5. Submit the issue — a maintainer will review it
6. Once approved (label: `persona-approved`), the pipeline runs automatically:
   - Validates the package (ZIP integrity, manifest schema, path traversal check)
   - Creates a GitHub Release with the `.hpersona` as a downloadable asset
   - Extracts preview images and card metadata
   - Updates `registry.json` on GitHub Pages
   - Comments on the issue with install instructions and closes it

**How to install a community persona:**

- **From the app**: Open HomePilot > **Shared with me** tab > browse > click **Install**
- **From the web**: Visit the [Community Gallery](https://ruslanmv.github.io/HomePilot/gallery.html) > download the `.hpersona` file > import into HomePilot
- **From a release**: Go to the GitHub Release page > download > drag into HomePilot

The gallery page supports search, tag filtering, content rating filters, and sorting — all running client-side with zero backend.

> See [docs/COMMUNITY_GALLERY.md](COMMUNITY_GALLERY.md) for the full architecture.

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

**160+ API endpoints** cover every operation — from chat and image generation to persona sessions, content policy enforcement, version history, and tool registration. Full OpenAPI docs ship at `/docs`.

**20+ ComfyUI workflows** handle image and video generation. To upgrade capabilities, swap a JSON file. No code changes needed.

**Everything is local.** No external telemetry. No cloud dependencies. Services bind to `127.0.0.1` by default. Your data, your models, your hardware.

---

## Tutorial: From Install to Your First Shared Persona

This step-by-step walkthrough takes you from a fresh clone to a published persona in the community gallery.

### Step 1 — Install HomePilot

```bash
# Clone the repository
git clone https://github.com/ruslanmv/homepilot
cd homepilot

# Copy environment config
cp .env.example .env

# Download models (pick your tier)
make download-recommended    # ~14GB — FLUX Schnell + SDXL

# Build and launch all services
make install
make run
```

Open `http://localhost:3000` in your browser. You should see the main interface.

### Step 2 — Create a Persona

1. Open the sidebar and go to **My Projects**
2. Click **New Project** > **Persona**
3. Walk through the creation wizard:
   - **Identity**: Name, role, personality description
   - **Appearance**: Generate an avatar, choose a style preset
   - **Voice**: Pick a voice persona and speed
   - **Tools**: Enable MCP tool access if desired
4. Click **Create** — your persona is live

### Step 3 — Have a Conversation

1. From My Projects, click your new persona card
2. Click **Start Session** (voice or text)
3. Talk to your persona — it remembers everything across sessions
4. The persona's long-term memory builds automatically: preferences, facts, emotional patterns

### Step 4 — Export the Persona

1. In **My Projects**, find your persona card
2. Click the **Export** button
3. HomePilot packages everything into a `.hpersona` file:
   - Blueprint (personality, appearance, agentic config)
   - Dependencies (tools, MCP servers, models)
   - Avatar images
   - Preview card for galleries

### Step 5 — Share with the Community

1. Go to [Submit a Persona](https://github.com/ruslanmv/HomePilot/issues/new?template=persona-submission.yml)
2. Fill in the form:
   - **Persona Name**: e.g., "Atlas"
   - **Short Description**: one line for the gallery card
   - **Tags**: select from professional, creative, educational, etc.
   - **Content Rating**: SFW or NSFW
   - **Package File**: drag your `.hpersona` file into the box
   - **Preview Image** (optional): drag a cover image
3. Check the agreement boxes and submit

A maintainer reviews your submission. Once they add the `persona-approved` label, the automated pipeline:
- Validates your package
- Creates a GitHub Release
- Updates the public registry
- Publishes to the [Community Gallery](https://ruslanmv.github.io/HomePilot/gallery.html)

### Step 6 — Install a Community Persona

Other users can now find and install your persona:

1. Open HomePilot > **Shared with me** tab
2. Browse the gallery — search by name, filter by tag
3. Click **Install** on any persona card
4. The 3-step wizard shows: persona preview, dependency check, and install confirmation
5. Click **Confirm** — the persona appears in My Projects, ready to use

Or browse the web gallery at [ruslanmv.github.io/HomePilot/gallery.html](https://ruslanmv.github.io/HomePilot/gallery.html) and download directly.

### Step 7 — Enable Agentic Mode (Optional)

To give your persona real-world tool access:

```bash
# Start HomePilot with MCP tool servers
AGENTIC=1 make start
```

This launches the MCP Gateway and all built-in tool servers. Your persona can now search the web, manage tasks, query knowledge bases, and coordinate with A2A agents.

---

### Access Points

| Service | URL |
| :--- | :--- |
| **HomePilot UI** | `http://localhost:3000` |
| **API Documentation** | `http://localhost:8000/docs` |
| **ComfyUI** | `http://localhost:8188` |
| **MCP Admin** | `http://localhost:4444/admin` |
| **Community Gallery** | [ruslanmv.github.io/HomePilot/gallery.html](https://ruslanmv.github.io/HomePilot/gallery.html) |

---

## Who Is This For?

**Content creators** who want a complete AI studio — text, image, video, export — in one place, without monthly subscriptions.

**Small teams** that need a shared AI platform with project management, version control, and content policy enforcement, running on their own infrastructure.

**Enterprises** evaluating AI for internal workflows, who need audit trails, configurable safety policies, and zero data exfiltration risk.

**Developers** building AI applications who want a production-ready reference architecture with 160+ endpoints, modular services, and extensible tool integration.

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
| **Community** | Isolated users | Public persona gallery with one-click install |
| **Data** | Sent to vendor servers | 100% local, self-hosted |
| **Cost** | Per-seat, per-month | One-time setup, your hardware |
| **Extensibility** | Closed ecosystem | Swap any service, add any tool, modify any workflow |

---

## The Bottom Line

HomePilot is not a wrapper around an API. It is a **complete AI operating environment** — conversation, creation, memory, identity, and action — running on your hardware, under your control.

Install it. Create a Persona. Share it with the world. Start a conversation that does not end when you close the browser.

```bash
git clone https://github.com/ruslanmv/homepilot && cd homepilot && make install && make run
```

---

<p align="center">
  <img src="../assets/homepilot-logo.svg" alt="HomePilot" width="300" /><br><br>
  <b>HomePilot</b> — Your AI. Your data. Your rules.<br>
  <a href="https://github.com/ruslanmv/homepilot">GitHub</a> · <a href="PERSONA.md">Persona Spec</a> · <a href="INTEGRATIONS.md">Integrations Guide</a> · <a href="https://ruslanmv.github.io/HomePilot/gallery.html">Community Gallery</a>
</p>
