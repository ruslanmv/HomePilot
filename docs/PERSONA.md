<p align="center">
  <img src="../assets/persona-logo.svg" alt="Persona" width="320" />
</p>

<p align="center">
  <b>PERSONA</b><br>
  <em>A new primitive for human-AI interaction.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Status-Shipped-brightgreen?style=for-the-badge" alt="Shipped" />
  <img src="https://img.shields.io/badge/Architecture-Project--Backed-blue?style=for-the-badge" alt="Project-Backed" />
  <img src="https://img.shields.io/badge/Memory-Persistent-purple?style=for-the-badge" alt="Persistent Memory" />
  <img src="https://img.shields.io/badge/Tools-Extensible-orange?style=for-the-badge" alt="Extensible Tools" />
</p>

---

## The Problem

Every AI product today gives you a stateless text box. You type, it answers, it forgets. Switch tabs, close the browser, come back tomorrow — you start from zero. The assistant has no face, no name, no memory of who you are. It is a function call with a chat skin.

This is not how relationships work. This is not how trust is built. And this is not how AI will be used in the decade ahead.

---

## What Is a Persona?

A **Persona** is a persistent AI identity that represents *who the assistant is* — not just what it answers.

It is the atomic unit that connects everything a modern AI assistant needs into a single, continuous entity:

```
Identity + Voice + Appearance + Memory + Sessions = Persona
```

A Persona sits above individual conversations and below the user:

```
                   ┌─────────────┐
                   │    User     │
                   └──────┬──────┘
                          │ owns
                   ┌──────┴──────┐
                   │   Persona   │   ← one consistent identity
                   └──────┬──────┘
                          │ hosts
              ┌───────────┼───────────┐
              │           │           │
        ┌─────┴────┐ ┌───┴────┐ ┌────┴─────┐
        │ Session 1 │ │Session 2│ │Session N │
        │  (voice)  │ │ (text)  │ │ (voice)  │
        └──────────┘ └────────┘ └──────────┘
```

Think of it as: **a named, visual, voice-enabled assistant with a defined personality, behavior, and memory scope that you can talk to over time.**

---

## Core Characteristics

### 1. Identity — Who the assistant is

A Persona defines:

- **Name & Role** — e.g. *"Scarlett — Personal Secretary"*
- **Personality & Behavior** — tone, warmth, initiative, response style
- **Safety & Maturity** — family-safe or adult-gated content boundaries

This identity is **stable across sessions**. The assistant does not reset its character when you close the browser. It knows who it is the same way you know who you are.

### 2. Appearance — How the assistant looks

A Persona has:

- **One authoritative avatar** — always renderable, deterministically shown when asked
- **Multiple generated portraits** — outfit variations, expressions, styles
- **Wardrobe system** — generate and manage outfit variations from character prompts

Because appearance is first-class:
- *"Show me your photo"* always works — in voice mode, chat mode, or any session
- The Persona feels **present** rather than abstract
- Visual identity reinforces the relationship between user and assistant

### 3. Voice — How you talk to it

A Persona integrates directly into Voice Mode:

- Appears in the personality selector — no new screens, no extra complexity
- Uses the Persona's system prompt, tone, and style
- Renders the Persona's avatar during spoken responses
- Supports hands-free continuous conversation

Voice configuration is independent of identity — any voice (Ara, Eve, Leo, Rex, Sal, Gork) can be paired with any Persona, with adjustable speed (0.5x-2.0x).

### 4. Sessions — How conversations are organized

A Persona supports **many sessions over time**:

| Capability | Detail |
| :--- | :--- |
| **Multi-session** | Each Persona hosts unlimited voice and text sessions |
| **Resumable** | Continue any previous session exactly where you left off |
| **Non-destructive** | Closing voice mode does not delete history |
| **Mode-agnostic** | Sessions can be voice or text, independently |
| **Browsable** | Review, continue, or start new sessions from a session hub |

This eliminates the *"lost conversation"* problem. Your history with a Persona is always there.

### 5. Long-Term Memory — What it remembers

A Persona accumulates persistent memory across all sessions:

- **Facts about the user** — name, preferences, dislikes, important dates
- **Emotional patterns** — how you respond, what you care about
- **Relationship context** — history summaries, recurring topics
- **Preferences** — communication style, depth, formality

Memory is:
- **Persistent** — survives restarts, browser clears, device switches
- **Cross-session** — shared across every conversation with this Persona
- **Compact** — stored as summaries and facts, not raw logs

This is what transforms a chatbot into a **long-term assistant** — a secretary, a companion, a coach that improves over months and years.

### 6. Project-Backed Architecture

Under the hood, a Persona is implemented as a **Persona Project**:

- Stored in HomePilot's existing Projects system
- Uses the same database, storage paths, and API surface
- No parallel or duplicated "persona database"
- Fully additive — no breaking changes to the existing architecture

This keeps the system maintainable, upgrade-safe, and production-ready.

---

## What a Persona Is Not

| Not this | Why |
| :--- | :--- |
| A chat thread | A Persona hosts many threads. A thread is disposable; a Persona is not. |
| A prompt template | A template has no memory, no face, no sessions. |
| A voice skin | A voice is an output modality. A Persona is an identity. |
| An image gallery | Images serve the identity. The identity is not defined by images. |

A Persona is the **unifying layer** that connects prompt + voice + appearance + memory + sessions into a single coherent entity.

---

## Linked vs. Unlinked Mode

Personas can operate in two modes:

| | Linked (Backend) | Unlinked (Client) |
| :--- | :--- | :--- |
| **Memory** | Persistent across sessions | Ephemeral — resets each time |
| **Knowledge / RAG** | Full document access | None |
| **Tools** | Backend tools available | Limited |
| **Photos** | Managed by backend | Cached client-side |
| **Speed** | Richer context (slightly slower) | Fast, minimal context |

**Linked mode** routes conversations through the backend where the Persona's full project context — memory, documents, tools, photos — is attached. **Unlinked mode** assembles the prompt client-side for lightweight, fast conversations.

---

## Tool Integrations — A Persona That Acts

A Persona is not limited to conversation. Through HomePilot's MCP (Model Context Protocol) gateway, every Persona gains access to **real-world tools** — turning identity + memory into identity + memory + action.

### How It Works

```
User  →  Persona  →  MCP Gateway  →  Tool Server  →  External Service
                                                        (Email, WhatsApp,
                                                         Calendar, Search...)
```

When a Persona is in **Linked mode**, it can discover and invoke tools at runtime. The Persona's identity and memory inform *how* it uses those tools — a "Personal Secretary" Persona sends emails with your preferred sign-off; a "Chief of Staff" Persona prioritizes your calendar based on what it knows about your week.

### Built-in Tool Servers

These ship with HomePilot and launch automatically with `make start`:

| Tool Server | Port | Capabilities |
| :--- | :--- | :--- |
| **Personal Assistant** | 9101 | Task management, reminders, scheduling |
| **Knowledge** | 9102 | Document search, RAG queries, knowledge base |
| **Decision Copilot** | 9103 | Pro/con analysis, decision frameworks, risk assessment |
| **Executive Briefing** | 9104 | Summarization, daily digests, status reports |
| **Web Search** | 9105 | Real-time web research (SearXNG or Tavily) |

### External Service Connectors

Personas can connect to external services through additional MCP tool servers. Each connector is a standalone server that the Persona discovers and uses through the gateway:

| Connector | Use Case | Example |
| :--- | :--- | :--- |
| **Email (SMTP/IMAP)** | Send and read emails on your behalf | *"Scarlett, draft a reply to the client email from this morning"* |
| **WhatsApp** | Send messages, read incoming threads | *"Send my wife a message that I'll be 20 minutes late"* |
| **Calendar (CalDAV/Google)** | Create events, check availability, send invites | *"Block 2 hours tomorrow for the proposal review"* |
| **Slack** | Post messages, read channels, manage threads | *"Post the weekly update to #engineering"* |
| **GitHub** | Create issues, review PRs, check CI status | *"Open an issue for the login bug I described yesterday"* |
| **Home Automation** | Control smart devices, scenes, routines | *"Turn off the office lights and set thermostat to 68"* |
| **File System** | Read, write, organize local files | *"Save this summary as a PDF in my reports folder"* |
| **Database** | Query, insert, update structured data | *"How many orders came in this week?"* |

### Adding Your Own Tool Server

Any MCP-compatible tool server can be registered with the gateway:

```bash
# Register a custom tool server
curl -X POST http://localhost:4444/api/servers \
  -d '{"name": "my-crm", "url": "http://localhost:9200", "description": "CRM integration"}'
```

Or register via the API:

```
POST /v1/agentic/register/tool
```

Once registered, every Persona in Linked mode automatically discovers and can use the new tool. No per-Persona configuration needed.

### Safety: Ask-Before-Acting

All tool invocations follow HomePilot's **safety-first execution model**:

- **Level 0 — Read-only:** Persona can search, query, and read without confirmation
- **Level 1 — Confirm:** Persona describes the action and waits for user approval before executing
- **Level 2 — Autonomous:** Persona acts independently within configured boundaries

The default is Level 1. You control the autonomy per tool, per Persona, or globally.

---

## Current Feature Status

| Capability | Status |
| :--- | :--- |
| Stable identity & role | Shipped |
| Selectable avatar (always renderable) | Shipped |
| Voice mode integration | Shipped |
| Text + voice sessions | Shipped |
| Session resume & history | Shipped |
| Deterministic photo rendering | Shipped |
| Wardrobe / outfit system | Shipped |
| Optional project linkage | Shipped |
| Persistent long-term memory | Shipped |
| Non-destructive, additive architecture | Shipped |
| MCP tool gateway integration | Shipped |
| 5 built-in tool servers | Shipped |
| Ask-before-acting safety model | Shipped |
| External service connectors (Email, WhatsApp, Calendar, Slack, GitHub) | Ready |
| Custom tool server registration | Shipped |

---

## Voice Personas (Voice Configuration)

Voice personas control **how the AI sounds** and are independent of identity. Any voice can be paired with any Persona.

| Voice | Style | Character |
| :--- | :--- | :--- |
| **Ara** *(default)* | Upbeat female | Slightly faster, higher pitch |
| **Eve** | Soothing female | Calm, neutral pace |
| **Leo** | British male | Measured, slightly lower pitch |
| **Rex** | Calm male | Steady, deep tone |
| **Sal** | Smooth male | Neutral, versatile |
| **Gork** | Lazy male | Slow, relaxed delivery |

Speed control: 0.5x to 2.0x via the settings slider. The multiplier preserves each voice's character at any speed.

---

## Built-in Personalities

HomePilot ships with **15 built-in personality agents** that can be used standalone or combined with a Persona project.

### General

| Personality | Description |
| :--- | :--- |
| **Assistant** *(default)* | Helpful, concise, conversational. Good all-rounder. |
| **Custom** | Write your own instructions (up to 1,500 characters). |
| **Storyteller** | Vivid narrator — descriptive language, imagination-first. |
| **HomePilot "Doc"** | Medical-consultant tone. Professional and analytical. |
| **Conspiracy** | Tinfoil-hat mode. Questions everything, connects unrelated dots. |

### Kids & Family

| Personality | Description |
| :--- | :--- |
| **Kids Story Time** | Simple, magical, child-friendly storytelling. |
| **Kids Trivia Game** | Fun trivia host for kids — easy questions, encouragement. |

### Wellness

| Personality | Description |
| :--- | :--- |
| **Therapist** | Empathetic listener using Rogerian + CBT + MI techniques. |
| **Meditation** | Slow, calm meditation guide focused on breath and relaxation. |
| **Motivation** | High-energy motivational speaker. |

### Adult (18+)

Hidden by default. Enable via System Settings with age verification.

| Personality | Description |
| :--- | :--- |
| **Unhinged** | Chaotic, unpredictable, no guardrails. |
| **Scarlett** | Confident, direct, bold. |
| **Romantic** | Hopeless romantic — passionate and affectionate. |
| **Debater** | Devil's advocate. Challenges every point. |
| **Fan Service** | NSFW intimate companion. |

---

## How Personalities Affect the AI

When you select a personality, HomePilot builds a **system prompt** that includes:

- **Behavioral instructions** — tone, depth, initiative level
- **Conversation dynamics** — speak/listen ratio, emotional mirroring, intensity
- **Voice brevity wrapper** — keeps responses short and natural for spoken delivery
- **Safety rules** — content boundaries, disclaimers where needed

For user-created Personas, the prompt additionally includes:
- Character identity (name, role, age context)
- Photo catalogue with outfit descriptions
- Self-awareness rules ("You ARE this character")

---

## Architecture

```
frontend/src/ui/voice/
  personalities.ts          # 15 built-in personality definitions
  personalityGating.ts      # Adult gating, persona toggle, localStorage
  voices.ts                 # 6 voice persona definitions
  VoiceSettingsPanel.tsx     # Voice grid, personality selector, speed
  PersonalityList.tsx        # Category-grouped personality dropdown
  SettingsModal.tsx          # System settings (adult gate, persona toggle)
  useVoiceController.ts     # Voice state machine (listen > think > speak)

backend/app/personalities/
  types.py                  # PersonalityAgent Pydantic model
  registry.py               # Thread-safe personality registry
  *.py                      # Individual personality agent modules
```

### localStorage Keys

| Key | Purpose |
| :--- | :--- |
| `homepilot_personality_id` | Selected personality |
| `homepilot_voice_id` | Selected voice persona |
| `homepilot_speech_speed` | Speech rate multiplier |
| `homepilot_adult_content_enabled` | 18+ content toggle |
| `homepilot_adult_age_confirmed` | Age verification flag |
| `homepilot_voice_personas_enabled` | Personas in Voice toggle |
| `homepilot_voice_linked_to_project` | Linked mode toggle |
| `homepilot_voice_persona_cache` | Cached persona project data |
| `homepilot_custom_personality_prompt` | Custom personality text |

---

## FAQ

**Can I use a Persona outside Voice Mode?**
Yes. Personas work in both text chat and voice mode. Sessions can be either modality.

**Do Personas affect image generation?**
Yes. Backend personality agents include an `image_style_hint` field that influences visual style during persona conversations.

**Can I create my own built-in personality?**
Yes. Add a new module under `backend/app/personalities/` following the `PersonalityAgent` schema. It will be auto-discovered by the registry.

**What happens if my browser has no matching TTS voice?**
The system falls back to the browser's default voice. You can also manually select a system voice in System Settings.

---

## Why This Matters

With this design, HomePilot Personas can realistically become:

- A **personal secretary** that reads your email, manages your calendar, and drafts replies in your voice
- A **daily companion** that remembers yesterday's conversation and asks how the meeting went
- A **operations manager** that posts Slack updates, files GitHub issues, and summarizes your week
- A **coach or mentor** that tracks your progress over months and adjusts its approach
- A **creative collaborator** that maintains context across projects, generates assets, and exports deliverables
- A **home automation controller** that knows your routines and manages your smart devices

The difference between a chatbot and a Persona is the difference between a tool you use and an assistant that works for you.

---

<p align="center">
  <b>Persona</b> — Identity is the new interface.<br>
  <sub>Memory is the new context. Tools are the new hands.</sub>
</p>
