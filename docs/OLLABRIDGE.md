# OllaBridge Integration

> Connect any OpenAI-compatible client to HomePilot personas through OllaBridge — a single API gateway.

<p align="center">
  <img src="../assets/ollabridge-architecture.svg" alt="OllaBridge Architecture" width="800" />
</p>

<p align="center">
  <img src="../assets/3d-avatar-pipeline.svg" alt="3D Avatar + HomePilot Pipeline" width="800" />
</p>

---

## Overview

HomePilot exposes its personas and personality agents as an **OpenAI-compatible API** (`/v1/chat/completions`), enabling external tools — including [OllaBridge](https://github.com/ruslanmv/ollabridge) and [3D Avatar Chatbot](https://github.com/ruslanmv/3D-Avatar-Chatbot) — to chat with HomePilot personas as if they were regular LLM models.

OllaBridge acts as a unified gateway: applications connect to one URL, and OllaBridge routes persona requests to HomePilot automatically.

---

## Architecture

### System Topology

```
                    ┌──────────────────────────────────┐
                    │        Client Applications       │
                    │                                  │
                    │  3D Avatar   Python   LangChain  │
                    │  Chatbot     SDK      Apps       │
                    └───────────┬──────────────────────┘
                                │
                         OpenAI SDK / HTTP
                                │
                    ┌───────────▼──────────────────────┐
                    │     OllaBridge Gateway (:11435)   │
                    │                                  │
                    │  ┌──────────┐  ┌──────────────┐  │
                    │  │  Router  │  │   Registry   │  │
                    │  │          │  │              │  │
                    │  │ persona: │  │ Track nodes: │  │
                    │  │ → HP     │  │  - local     │  │
                    │  │ default: │  │  - relay     │  │
                    │  │ → Ollama │  │  - homepilot │  │
                    │  └──────────┘  └──────────────┘  │
                    └──┬───────────────────┬───────────┘
                       │                   │
            ┌──────────▼────┐    ┌─────────▼──────────┐
            │  Local Ollama │    │    HomePilot (:8000)│
            │               │    │                    │
            │  deepseek-r1  │    │  ┌──────────────┐  │
            │  llama3       │    │  │ Persona      │  │
            │  mistral      │    │  │ Projects     │  │
            │               │    │  ├──────────────┤  │
            │               │    │  │ Personality  │  │
            │               │    │  │ Agents (15)  │  │
            │               │    │  ├──────────────┤  │
            │               │    │  │ LTM Memory   │  │
            │               │    │  ├──────────────┤  │
            │               │    │  │ MCP Tools    │  │
            │               │    │  └──────────────┘  │
            └───────────────┘    └────────────────────┘
```

### Request Flow

```
  Client Request                   OllaBridge                     HomePilot
  ─────────────                   ──────────                     ─────────
       │                               │                              │
       │  POST /v1/chat/completions    │                              │
       │  model="persona:proj-123"     │                              │
       │──────────────────────────────►│                              │
       │                               │                              │
       │                    Router detects "persona:" prefix          │
       │                    Selects HomePilot node                    │
       │                               │                              │
       │                               │  POST /v1/chat/completions  │
       │                               │  model="persona:proj-123"   │
       │                               │─────────────────────────────►│
       │                               │                              │
       │                               │              Resolve persona │
       │                               │              Build sys prompt│
       │                               │              Inject LTM      │
       │                               │              Call LLM        │
       │                               │              (+ MCP tools)   │
       │                               │                              │
       │                               │  OpenAI-format response     │
       │                               │◄─────────────────────────────│
       │                               │                              │
       │  OpenAI-format response       │                              │
       │◄──────────────────────────────│                              │
       │                               │                              │
```

### 3D Avatar Chatbot Integration

```
  ┌─────────────────────────────────────────────────────┐
  │              3D Avatar Chatbot (Browser)             │
  │                                                     │
  │  ┌────────────┐  ┌──────────┐  ┌────────────────┐  │
  │  │  3D Avatar │  │   Chat   │  │  Voice I/O     │  │
  │  │  Three.js  │  │  Panel   │  │  Web Speech    │  │
  │  └──────┬─────┘  └────┬─────┘  └───────┬────────┘  │
  │         │              │                │            │
  │         └──────┬───────┴────────┬───────┘            │
  │                │                │                    │
  │         ┌──────▼──────┐  ┌─────▼──────────┐         │
  │         │ LLMManager  │  │ Speech Service │         │
  │         │             │  │                │         │
  │         │ Provider:   │  │ STT → text     │         │
  │         │ ollabridge  │  │ TTS ← text     │         │
  │         └──────┬──────┘  └────────────────┘         │
  │                │                                    │
  └────────────────┼────────────────────────────────────┘
                   │
            POST /v1/chat/completions
            model="persona:my-therapist"
                   │
          ┌────────▼─────────┐
          │    OllaBridge    │
          │    Gateway       │
          │    (:11435)      │
          └────────┬─────────┘
                   │
          ┌────────▼─────────┐
          │    HomePilot     │
          │    Backend       │
          │    (:8000)       │
          │                  │
          │  Persona with:   │
          │  - Personality   │
          │  - Memory (LTM)  │
          │  - Avatar        │
          │  - MCP Tools     │
          └──────────────────┘
```

---

## HomePilot OpenAI-Compatible API

HomePilot exposes two endpoints that follow the OpenAI specification:

### `POST /v1/chat/completions`

Chat with a persona or personality agent.

**Model naming convention:**

| Model format | Routes to | Example |
|---|---|---|
| `persona:<project_id>` | Persona project (custom, with MCP tools) | `persona:abc-123` |
| `personality:<id>` | Built-in personality agent | `personality:therapist` |
| `<personality_id>` | Built-in personality (shorthand) | `therapist` |
| `default` | Plain LLM passthrough | `default` |

**Request:**

```json
{
  "model": "persona:my-project-id",
  "messages": [
    {"role": "user", "content": "Hello, how are you today?"}
  ],
  "temperature": 0.7,
  "max_tokens": 800
}
```

**Response (OpenAI-compatible):**

```json
{
  "id": "homepilot-a1b2c3d4e5f6",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "persona:my-project-id",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! I'm doing well..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0
  }
}
```

### `GET /v1/models`

List all available personas and personality agents.

**Response:**

```json
{
  "object": "list",
  "data": [
    {"id": "personality:assistant", "object": "model", "owned_by": "homepilot-personality"},
    {"id": "personality:therapist", "object": "model", "owned_by": "homepilot-personality"},
    {"id": "persona:proj-abc123", "object": "model", "owned_by": "homepilot-persona"}
  ]
}
```

---

## OllaBridge Configuration

### Enable HomePilot in OllaBridge

Set the following environment variables (or add to `.env`):

```env
HOMEPILOT_ENABLED=true
HOMEPILOT_BASE_URL=http://localhost:8000
HOMEPILOT_API_KEY=your-homepilot-api-key
HOMEPILOT_NODE_ID=homepilot
HOMEPILOT_NODE_TAGS=homepilot,persona
```

### What Happens on Startup

1. OllaBridge creates a `HomePilotConnector`
2. Discovers available personas from HomePilot `/v1/models`
3. Registers HomePilot as a node in the gateway registry
4. The router automatically sends `persona:*` and `personality:*` models to HomePilot

### Smart Routing

OllaBridge's router detects persona model names and routes them to HomePilot nodes:

```python
# Any model starting with "persona:" or "personality:" → HomePilot
model="persona:my-therapist"    # → routed to HomePilot
model="personality:storyteller" # → routed to HomePilot
model="deepseek-r1"            # → routed to local Ollama
```

---

## Usage Examples

### Python (OpenAI SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="sk-ollabridge-YOUR-KEY"
)

# Chat with a HomePilot persona
response = client.chat.completions.create(
    model="persona:my-therapist-project",
    messages=[{"role": "user", "content": "I've been feeling stressed lately."}]
)

print(response.choices[0].message.content)
```

### Node.js

```javascript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:11435/v1",
  apiKey: "sk-ollabridge-YOUR-KEY",
});

const response = await client.chat.completions.create({
  model: "personality:storyteller",
  messages: [{ role: "user", content: "Tell me a story about a brave knight." }],
});
```

### cURL

```bash
curl -X POST http://localhost:11435/v1/chat/completions \
  -H "Authorization: Bearer sk-ollabridge-YOUR-KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "personality:therapist",
    "messages": [{"role": "user", "content": "How can I manage anxiety?"}]
  }'
```

### 3D Avatar Chatbot

In the 3D Avatar Chatbot settings:

1. Select **OllaBridge** as the provider
2. Set **Base URL** to `http://localhost:11435`
3. Enter your **API Key**
4. Click **Fetch Models** to discover available personas
5. Select a persona model (e.g., `persona:my-therapist`)

The 3D avatar will speak with the selected persona's personality, memory, and tool capabilities.

---

## Built-in Personality Agents

HomePilot ships with 15 personality agents accessible via OllaBridge:

| Personality ID | Category | Description |
|---|---|---|
| `assistant` | General | Proactive home AI assistant |
| `therapist` | Wellness | Empathetic therapeutic companion |
| `storyteller` | General | Narrative-driven storyteller |
| `meditation` | Wellness | Calm, reflective guide |
| `motivation` | Wellness | Encouraging motivational coach |
| `argumentative` | General | Devil's advocate debater |
| `conspiracy` | General | Speculative thinker |
| `fan-service` | General | Entertaining personality |
| `kids-trivia` | Kids | Educational trivia for children |
| `kids-story` | Kids | Beginner-friendly stories |
| `interview` | General | Structured Q&A interviewer |
| `romantic` | Adult | Affectionate companion |
| `sexy` | Adult | Adult content personality |
| `unhinged` | Adult | Unrestricted personality |
| `custom` | General | User-defined personality |

---

## Persona Capabilities

When a persona project has agentic capabilities enabled, OllaBridge requests route through HomePilot's agent loop, giving the persona access to:

- **MCP Tools** — Gmail, Google Calendar, GitHub, Slack, Notion, and more
- **Web Search** — SearXNG or Tavily integration
- **Knowledge Base** — RAG over uploaded documents
- **Image Generation** — ComfyUI workflows (FLUX, SDXL)
- **Long-Term Memory** — Persistent per-persona memory across sessions

All of this is transparent to the client — the OpenAI-compatible response format stays the same.

---

## Deployment

### Docker Compose (Recommended)

Add OllaBridge configuration to your HomePilot `.env`:

```env
# HomePilot backend
DEFAULT_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434

# OllaBridge gateway (separate service or same host)
HOMEPILOT_ENABLED=true
HOMEPILOT_BASE_URL=http://backend:8000
HOMEPILOT_API_KEY=your-api-key
```

### Service Topology

```
Docker Compose
├── frontend        (:3000)  React UI
├── backend         (:8000)  FastAPI — personas, chat, media
├── ollama          (:11434) Local LLM runtime
├── comfyui         (:8188)  Image/video generation
├── ollabridge      (:11435) API gateway
├── mcp-*           (9101+)  Tool servers
└── 3d-avatar       (:8080)  3D Avatar Chatbot (optional)
```

### Health Checks

```bash
# HomePilot backend
curl http://localhost:8000/health

# OllaBridge gateway
curl http://localhost:11435/health

# List personas via OllaBridge
curl -H "Authorization: Bearer sk-ollabridge-..." \
  http://localhost:11435/v1/models
```

---

## Device Pairing (Auth Mode)

OllaBridge supports a **pairing** auth mode alongside the standard API key method. Pairing lets clients (like 3D Avatar Chatbot) connect without manually copying API keys.

### How It Works

```
┌──────────────────┐         ┌──────────────────────┐
│  OllaBridge CLI   │         │   3D Avatar Client   │
│                  │         │                      │
│  Displays code:  │         │  User enters code    │
│  ┌────────────┐  │         │  in Settings panel   │
│  │  847291    │  │ ──────> │  ┌────────────────┐  │
│  └────────────┘  │  code   │  │ 847291  [Pair] │  │
│                  │         │  └────────────────┘  │
│  Validates code  │ <────── │                      │
│  Returns token   │  POST   │  Stores mtx_* token  │
│                  │ /pair   │  for future requests  │
└──────────────────┘         └──────────────────────┘
```

### Setup

1. Start OllaBridge in pairing mode:
   ```bash
   ollabridge start --auth-mode pairing
   ```

2. A 6-digit pairing code appears in the console dashboard.

3. In the 3D Avatar Chatbot settings, select OllaBridge, enter the code in the "Pair with code" field, and click **Pair**.

4. The client receives a persistent `mtx_*` token stored automatically. All future requests use this token.

### Auth Modes

| Mode | Description |
|------|-------------|
| `required` | Static API keys (default, backwards-compatible) |
| `local-trust` | Skip auth for loopback clients (127.0.0.1) |
| `pairing` | Device code exchange + static keys both accepted |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/pair/info` | GET | Check if pairing is available |
| `/pair` | POST | Exchange code for token (`{code, label}`) |
| `/pair/devices` | GET | List paired devices |
| `/pair/revoke` | POST | Revoke a device (`{device_id}`) |

> **Note**: Standard API key authentication (`Authorization: Bearer <key>`) continues to work in all modes. Pairing is an additional option, not a replacement.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| No persona models in `/v1/models` | Verify `HOMEPILOT_ENABLED=true` and HomePilot backend is running |
| 404 on persona chat | Check the persona project ID exists in HomePilot |
| 502 LLM backend error | Ensure the LLM provider (Ollama/vLLM) is running and accessible |
| Auth failures | Verify `HOMEPILOT_API_KEY` matches HomePilot's `require_api_key` |
| Streaming not supported | Persona endpoints currently return non-streaming responses only |

---

## Related Documentation

- [Persona System](PERSONA.md) — Persona architecture, `.hpersona` packages, memory
- [Memory](MEMORY.md) — Long-term memory engines (Adaptive & Basic)
- [Integrations](INTEGRATIONS.md) — MCP servers, third-party services
- [API Reference](../API.md) — Full endpoint documentation
