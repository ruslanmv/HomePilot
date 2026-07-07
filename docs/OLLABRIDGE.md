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

## OllaBridge Link — Use Your Home GPU From Anywhere

OllaBridge Link lets a HomePilot running on a machine with a **high-end GPU**
serve its models to the HomePilot **web** and **mobile** apps, from anywhere.
You browse and run those models remotely; the heavy inference stays on your own
hardware. The app never talks to your PC directly — it asks **OllaBridge Cloud**,
which relays the request to whichever of *your* machines is online (no public IP
or port forwarding needed).

### Two links, two variants

| Variant | Link | Role | Purpose |
|---|---|---|---|
| **A — Account link** | web/mobile app ↔ OllaBridge Cloud | *consumer* | lets the app **see** your machines and route inference to them |
| **B — Machine link** | remote HomePilot Local (GPU PC) ↔ OllaBridge Cloud | *provider* | makes that PC's **GPU + models** available to your account |

Once both exist the connection is transitive — **Web → (A) → your Cloud account → (B) → your GPU node:**

```
                         OllaBridge Cloud (relay + identity)
                                     ▲   ▲
              Variant A: account     │   │   Variant B: machine
              link (sign in)         │   │   link (device code)
                                     │   │
        ┌────────────────────────────┘   └────────────────────────────┐
        │                                                              │
 ┌──────┴───────┐                                              ┌───────┴────────┐
 │  HomePilot   │                                              │  HomePilot     │
 │  Web / Phone │  ── "run llama3 on my node" ──▶  Cloud  ──▶  │  Local (GPU PC)│
 │  (consumer)  │  ◀──────── streamed reply ─────  relay  ◀──  │  (provider)    │
 └──────────────┘                                              └────────────────┘
        you, anywhere                                          your home/office GPU
```

The app sends a completion request to the Cloud; the Cloud recognises you
(Variant A), finds your online machine (Variant B), forwards the job, and
streams the answer back.

### The simplest path

**Variant A — link this device (usually zero extra steps).** If you signed in
with **“Continue with OllaBridge”** on the login screen, the app is *already
linked* (the account token is stored and reused). Otherwise open
**Settings → OllaBridge Link → This device → Link account** and enter your
OllaBridge email + password.

**Variant B — add a GPU machine (one-time device-code pairing).** The standard
"TV login" flow (OAuth 2.0 Device Authorization Grant, RFC 8628):

```
  GPU PC (HomePilot Local)                 You, in any browser
  ────────────────────────                 ───────────────────
  1. Connector shows a code:  ABCD-1234    3. Open  <cloud>/link
  2. Polls the Cloud …          ───────▶   4. Type  ABCD-1234  → Confirm
  6. Poll returns "approved" ✔             5. Cloud binds the PC to your account
```

From the app: **Settings → OllaBridge Link → Your GPU machines → Add a machine**
opens the pairing page. After it's approved once, the machine reconnects on its
own every boot. (See **Device Pairing (Auth Mode)** below for the underlying
endpoints.)

### What you get after linking

- Machines listed in **Settings → OllaBridge Link → Your GPU machines** (name,
  GPU, VRAM, online state) — from Cloud `GET /v1/devices`.
- Their models appear in **Models** under a dedicated **“OllaBridge”** provider,
  in every Model Type tab (chat, multimodal, image, edit, video, enhance, LoRA,
  Add-ons); own-node models are badged **GPU node** — from Cloud
  `GET /ollama/v1/models`.
- On a chat/multimodal model, **Use for Chat** points the chat provider at the
  relay; HomePilot attaches your account token as the request credential
  (`provider_api_key`), so the relay resolves you and runs the job on your GPU.

Everything is **additive and opt-in**: without an OllaBridge link, HomePilot
uses its local providers (Ollama, ComfyUI, …) exactly as before.

---

## Two HomePilot editions

The single most important distinction. HomePilot ships in two editions with
**different roles**, and the app adapts its UI and behavior to which one it is:

| | **HomePilot Web** | **HomePilot Local** |
|---|---|---|
| Where | Hugging Face Space / any hosted deploy | installed on your PC (desktop app) |
| Role | **consumer / client** | **consumer + provider** |
| Runs | frontend + backend | frontend + backend + ComfyUI/Ollama + **OllaBridge Local sidecar** |
| GPU | none of its own | your GPU, shareable |
| To OllaBridge Cloud | signs in, *uses* linked machines | *pairs* and *provides* its GPU |
| Must **not** | run a provider sidecar, or pretend the Space is your GPU | — |

> **The rule:** *HomePilot Web does not provide your GPU. HomePilot Local
> provides your GPU through OllaBridge Local. OllaBridge Cloud connects them.*

```
  HomePilot Web (consumer)            OllaBridge Cloud            HomePilot Local (provider)
  Hugging Face Space          identity · relay · registry        installed on your PC
        │                         · policy · pairing                    │
        │                               │                               ├─ HomePilot backend
        └────── uses your linked PC ────┼──── your GPU node ◄───────────┼─ ComfyUI / Ollama / GPU
                                        │                               └─ OllaBridge Local sidecar
                                        └───────────────────────────────────┘  (dials out :11435)
```

### Edition detection

Resolved by the backend at startup and exposed to the frontend:

- Explicit **`HOMEPILOT_EDITION=web|local`** always wins.
- Otherwise: a Space env var (`SPACE_ID` / `HF_SPACE_ID` / `SPACE_HOST`) ⇒ **web**;
  else ⇒ **local**.

```bash
GET /v1/edition
→ { "edition": "web", "is_web": true, "is_local": false,
    "can_provide_gpu": false, "cloud_url": "https://ruslanmv-ollabridge.hf.space" }
```

The UI **fails safe to web** while loading, so provider/GPU controls never leak
onto the hosted app.

---

## The OllaBridge Local sidecar (provider side)

HomePilot Local turns your PC into a private GPU node by running the official
**[OllaBridge](https://github.com/ruslanmv/ollabridge)** package (`ollabridge`,
v0.1.5+, MIT) as a **sidecar**. HomePilot does **not** reimplement pairing,
relay, or sharing — it delegates to OllaBridge, which already does all of it.

What the sidecar provides:

- An OpenAI-compatible gateway + **dashboard at `http://localhost:11435/ui`**.
- A **node agent** that **dials OUT** to the Cloud relay
  (`wss://…/relay/connect`) — no port forwarding, no VPN, no inbound ports.
- **Device-code pairing** built in (`ollabridge-node cloud-pair`).
- **Per-model sharing controls** (This PC / Cloud / per-app), **owner-only and
  opt-in** by default.
- (v0.1.5) **GPU generation over the tunnel** — advertise ComfyUI image/video
  models and run routed jobs, opt-in via `OLLABRIDGE_NODE_GEN_ENABLED`. This is
  what makes **all Model Types** (not just chat) show up remotely.
- (v0.1.5) **Self-healing** Cloud connection (auto-reconnect with backoff).

### HomePilot's status/probe endpoints

The backend surfaces the sidecar state so the UI can show it. On the **web**
edition these answer honestly with `available:false` (there is no sidecar).

```bash
GET  /v1/ollabridge/local/status
→ { "edition":"local", "available":true, "installed":true, "running":true,
    "cloud_url":"…", "local_url":"http://…:11435", "models": 7,
    "share_scope":"owner_only" }

GET  /v1/ollabridge/local/pair-url   → { "pair_url": "<cloud>/link", … }
POST /v1/ollabridge/local/start|stop → lifecycle is owned by the desktop shell
```

### Desktop install behavior (Docker)

The desktop app (`desktop/docker-manager.js`) runs both containers on a shared
`homepilot-local` network:

1. `homepilot-desktop` — with `HOMEPILOT_EDITION=local` and
   `OLLABRIDGE_LOCAL_URL=http://ollabridge-local:11435`.
2. `ollabridge-local` — image `ruslanmv/ollabridge:latest`, `ollabridge start`
   on **:11435 bound to `127.0.0.1` only**, GPU shared, config persisted to the
   `ollabridge-local-data` volume, wired to HomePilot's services.

It is **installed + running by default**, but **best-effort and non-fatal** — if
Docker or the image is unavailable, HomePilot Local runs exactly as before.
Disable it entirely with the desktop store flag `ollabridgeSidecar = false`.

### Security model — installed ≠ paired ≠ shared

Three independent states; each requires explicit user action to advance:

| State | Meaning | Default |
|---|---|---|
| **Installed** | the sidecar exists / runs on the PC | yes (opt-out) |
| **Paired** | the PC is linked to your OllaBridge account | **no** — user approves |
| **Shared** | specific models are reachable via the relay | **no** — user approves |

After pairing, the safe default is **share scope = my account only**;
org/community sharing stays off. This mirrors OllaBridge's local-first, no-
telemetry-by-default posture.

---

## Configuration reference

| Variable | Side | Default | Purpose |
|---|---|---|---|
| `HOMEPILOT_EDITION` | HomePilot | auto (`web` if Space, else `local`) | Force the edition |
| `OLLABRIDGE_CLOUD_URL` | HomePilot + sidecar | `https://ruslanmv-ollabridge.hf.space` | Canonical Cloud base URL |
| `OLLABRIDGE_CLOUD_TOKEN` | HomePilot | — | Token for cloud-compute (consumer burst) |
| `OLLABRIDGE_LOCAL_URL` | HomePilot | `http://127.0.0.1:11435` | Where to probe the sidecar |
| `OLLABRIDGE_NODE_GEN_ENABLED` | sidecar | `false` | Advertise GPU + run ComfyUI image/video jobs |
| `OLLABRIDGE_COMFYUI_URL` | sidecar | `http://127.0.0.1:8188` | ComfyUI endpoint for generation |
| `OLLABRIDGE_COMFYUI_WORKFLOWS_DIR` | sidecar | (bundled) | Workflow templates (flux/sdxl/ltx/wan) |
| `OLLABRIDGE_HOMEPILOT_URL` | sidecar | `http://127.0.0.1:8001` | HomePilot backend the node serves |
| `VITE_OLLABRIDGE_CLOUD_URL` | web build | (default above) | Frontend Cloud URL override |

**Canonical production Cloud URL:** `https://ruslanmv-ollabridge.hf.space`
(override per-deployment with the env vars above).

---

## Production readiness checklist

- [ ] **Cloud**: `SHARING_TIERS_ENABLED=true` (enables `/v1/devices`), a strong
      `JWT_SECRET` + `TOKEN_PEPPER`, and a **persistent** `DATABASE_URL` (the
      default HF Space DB is ephemeral — users don't survive a rebuild).
- [ ] **Cloud**: `/v1/auth/me` reachable; promote the shared-secret HS256 JWT to
      asymmetric signing + JWKS before adding third-party relying parties.
- [ ] **Web**: served over HTTPS so the `homepilot_session` cookie is `Secure`
      (`HOMEPILOT_COOKIE_SECURE=auto` handles this); `edition` reports `web`.
- [ ] **Local**: `edition` reports `local`; sidecar reachable at
      `OLLABRIDGE_LOCAL_URL`; pairing persists across restarts (volume mounted).
- [ ] **Local**: device-code pairing tested end-to-end; sharing defaults to
      owner-only; GPU generation only advertised when intentionally enabled.
- [ ] **Both**: sign-in → link → see device → run a remote job verified on a
      real GPU machine (the desktop sidecar path needs a real Electron+Docker run).

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
