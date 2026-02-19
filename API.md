# HomePilot — API Reference

> **160+ endpoints** across chat, media, studio, personas, agentic AI, and community.
>
> Full interactive documentation (Swagger UI) is available at `http://localhost:8000/docs` after launch.

---

## Core

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

---

## Conversations & Memory

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/conversations` | GET | List all conversations |
| `/conversations/{id}/messages` | GET | Retrieve conversation history |
| `/conversations/{id}` | DELETE | Delete a conversation |
| `/conversations/{id}/search` | GET | Full-text search within a conversation |

---

## Projects & Knowledge Base

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

---

## Persona System

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

---

## Image Enhancement (v1)

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

---

## Edit Sessions (v1)

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/v1/edit-sessions/{id}` | GET | Get edit session state |
| `/v1/edit-sessions/{id}` | DELETE | Delete edit session |
| `/v1/edit-sessions/{id}/image` | POST | Upload source image |
| `/v1/edit-sessions/{id}/message` | POST | Send edit instruction |
| `/v1/edit-sessions/{id}/select` | POST | Select result variant |
| `/v1/edit-sessions/{id}/revert` | POST | Revert to previous state |

---

## Story Mode

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

---

## Creator Studio (65+ endpoints)

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

---

## Agentic AI

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

---

## Community Gallery

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/community/status` | GET | Check if gallery is configured and reachable |
| `/community/registry` | GET | Cached persona registry with search/filter support |
| `/community/card/{id}/{ver}` | GET | Persona card metadata proxy |
| `/community/preview/{id}/{ver}` | GET | Persona preview image proxy |
| `/community/download/{id}/{ver}` | GET | `.hpersona` package download proxy |

---

## API Keys & Configuration

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/settings/api-keys` | GET | List configured API keys |
| `/settings/api-keys` | POST | Add API key for a provider |
| `/settings/api-keys/{provider}` | DELETE | Remove API key |
| `/settings/api-keys/test` | POST | Test API key connectivity |
| `/video-presets` | GET | Video generation presets |
| `/image-presets` | GET | Image generation presets |

---

## Model Management

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/models/health` | GET | Model service health |
| `/civitai/search` | POST | Search Civitai model registry |
| `/models/install` | POST | Install model from Civitai |
| `/models/delete` | POST | Remove installed model |
