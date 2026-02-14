# Persona & Personality System

HomePilot ships with **15 built-in personality agents** and supports **custom Personas** you can create yourself. Personalities shape how the AI talks, thinks, and behaves during Voice Mode conversations.

---

## Quick Start

1. Open **Voice Mode** (microphone icon in the sidebar).
2. Click the **settings cog** or the personality label in the bottom voice bar.
3. Pick a personality from the dropdown — the AI switches character immediately.
4. Start talking. The selected personality stays active for the entire session.

---

## Built-in Personalities

Personalities are grouped into categories. Each one carries its own system prompt, conversation style, and tone.

### General

| Personality | Description |
| :--- | :--- |
| **Assistant** *(default)* | Helpful, concise, conversational. Good all-rounder. |
| **Custom** | Write your own instructions (up to 1 500 characters). |
| **Storyteller** | Vivid narrator — descriptive language, imagination-first. |
| **HomePilot "Doc"** | Medical-consultant tone. Professional and analytical (AI disclaimer included). |
| **Conspiracy** | Tinfoil-hat mode. Questions everything, connects unrelated dots. |

### Kids & Family

| Personality | Description |
| :--- | :--- |
| **Kids Story Time** | Simple, magical, child-friendly storytelling. |
| **Kids Trivia Game** | Fun trivia host for kids — easy questions, lots of encouragement. |

### Wellness

| Personality | Description |
| :--- | :--- |
| **Therapist** | Empathetic listener using Rogerian + CBT + Motivational Interviewing techniques. |
| **Meditation** | Slow, calm meditation guide focused on breath and relaxation. |
| **Motivation** | High-energy motivational speaker — shouts encouragement, pushes for greatness. |

### Adult (18+)

These are hidden by default. See [Enabling Adult Content](#enabling-adult-content) below.

| Personality | Description |
| :--- | :--- |
| **Unhinged** | Chaotic, unpredictable, no guardrails. Dark humor and strong language. |
| **Scarlett** | Confident, direct, bold. Explicit language. |
| **Romantic** | Hopeless romantic — passionate and affectionate. |
| **Debater** | Devil's advocate. Challenges every point with strong opinions. |
| **Fan Service** | Fully NSFW intimate companion. |

---

## Custom Instructions

When you select the **Custom** personality:

1. A text area appears in the Voice Settings panel.
2. Type your behavioural instructions (max 1 500 characters).
3. Click **Save**.
4. The AI follows your instructions on the next turn.

Your custom prompt is stored locally in the browser (`localStorage`) and persists across sessions.

---

## User-Created Personas

Personas go beyond built-in personalities — they are **project-backed characters** with their own identity, photos, and optional tool access.

### Creating a Persona

1. Go to **Settings & Projects** in the main app.
2. Create a new **Persona** project.
3. Fill in the persona details: name, role, tone, visual style, and character description.
4. Optionally upload reference photos with outfit labels.

### Using a Persona in Voice Mode

1. Open **Voice Mode → System Settings** (gear icon).
2. Toggle **Enable Personas** on.
3. Your Personas now appear in the personality dropdown under the **Personas** category.
4. Select one — the AI adopts that character's identity, tone, and style.

### Linked vs. Unlinked Mode

Personas can run in two modes, configured in System Settings:

| | Linked (Backend) | Unlinked (Client) |
| :--- | :--- | :--- |
| **Memory** | Persists across sessions | Ephemeral — resets each time |
| **RAG / Knowledge** | Full document access | None |
| **Tools** | Backend tools available | Limited |
| **Photos** | Managed by backend | Cached client-side only |
| **Speed** | Slower (richer context) | Fast (minimal context) |

**Linked mode** sends conversations through the backend where the persona's full project context (memory, documents, tools, photos) is attached. **Unlinked mode** assembles the prompt client-side for faster, lighter conversations.

Toggle this with **Link to Project** in System Settings (only visible when Personas are enabled).

---

## Voice Personas (Voices)

Voice personas control **how the AI sounds** and are independent of personality. You can mix any voice with any personality.

| Voice | Style | Notes |
| :--- | :--- | :--- |
| **Ara** *(default)* | Upbeat female | Slightly faster, higher pitch |
| **Eve** | Soothing female | Calm, neutral pace |
| **Leo** | British male | Measured, slightly lower pitch |
| **Rex** | Calm male | Steady, deep tone |
| **Sal** | Smooth male | Neutral, versatile |
| **Gork** | Lazy male | Slow, relaxed delivery |

Select a voice from the **Voice grid** in the settings panel. The voice is matched to your browser's available TTS voices automatically.

### Speed Control

Use the **speed slider** (0.5x – 2.0x) to adjust speech rate. The slider multiplies the voice persona's base rate, so each voice retains its character even at different speeds.

---

## Enabling Adult Content

Adult personalities (18+) are hidden behind a two-step gate:

1. Open **System Settings** in Voice Mode (gear icon).
2. Toggle **Enable 18+ Personalities**.
3. An age-verification dialog appears — confirm you are 18 or older.
4. Adult personalities now appear in the dropdown.

Disabling the toggle hides them again. If the current personality is an adult one, it falls back to **Assistant**.

---

## How Personalities Affect the AI

When you select a personality, HomePilot builds a **system prompt** that instructs the AI to stay in character. The prompt includes:

- **Behavioural instructions** — tone, depth, initiative level.
- **Conversation dynamics** — speak/listen ratio, emotional mirroring, intensity.
- **Voice brevity wrapper** — keeps responses short and natural for spoken delivery (1–2 sentences).
- **Safety rules** — content boundaries, disclaimers where needed.

For built-in personalities, these prompts are defined both in the frontend and in the backend's **personality agent framework** (`backend/app/personalities/`), which provides a production-grade, validated definition for each agent.

For Personas (user-created), the prompt additionally includes:

- Character identity (name, role, age context).
- Photo catalogue with outfit descriptions.
- Self-awareness rules ("You ARE this character").

---

## Architecture Reference

```
frontend/src/ui/voice/
├── personalities.ts          # 15 built-in personality definitions
├── personalityGating.ts      # Adult gating, persona toggle, localStorage helpers
├── voices.ts                 # 6 voice persona definitions
├── VoiceSettingsPanel.tsx     # Settings panel UI (voice grid, personality selector, speed)
├── PersonalityList.tsx        # Category-grouped personality dropdown
├── SettingsModal.tsx          # System settings (adult gate, persona toggle, linked mode)
└── useVoiceController.ts     # Voice state machine (listen → think → speak)

backend/app/personalities/
├── types.py                  # PersonalityAgent Pydantic model
├── registry.py               # Thread-safe personality registry
└── *.py                      # Individual personality agent modules
```

### localStorage Keys

| Key | Purpose |
| :--- | :--- |
| `homepilot_personality_id` | Currently selected personality |
| `homepilot_voice_id` | Currently selected voice persona |
| `homepilot_speech_speed` | Speech rate multiplier |
| `homepilot_adult_content_enabled` | 18+ content toggle |
| `homepilot_adult_age_confirmed` | Age verification flag |
| `homepilot_voice_personas_enabled` | Personas in Voice toggle |
| `homepilot_voice_linked_to_project` | Linked mode toggle |
| `homepilot_voice_persona_cache` | Cached persona project data |
| `homepilot_custom_personality_prompt` | Custom personality text |

---

## FAQ

**Can I use a personality outside Voice Mode?**
Personalities are currently Voice Mode–only. Chat mode uses a separate system prompt (with optional Fun Mode).

**Do personalities affect image generation?**
Backend personality agents include an `image_style_hint` field. When generating images through a persona conversation, this hint influences the visual style.

**Can I create my own built-in personality?**
Yes — add a new module under `backend/app/personalities/` following the `PersonalityAgent` schema and it will be auto-discovered by the registry.

**What happens if my browser has no matching TTS voice?**
The voice system falls back to the browser's default voice. You can also manually pick a system voice in System Settings → System Voice.
