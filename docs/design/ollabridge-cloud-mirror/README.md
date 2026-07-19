# HomePilot Cloud Mirror Through OllaBridge — Design

**Status:** design + Phase 1 implemented. Additive and non-destructive throughout.
**Rule of the whole effort:** *extend* the existing OllaBridge integration; never
replace it. The legacy provider plane and the new private mirror plane run in
parallel.

---

## 1. The two planes

| Plane | Who uses it | Endpoints | Change policy |
|---|---|---|---|
| **A — Legacy provider** | 3D Avatar Chatbot, OpenAI SDK/LangChain clients, existing HomePilot provider configs | `/v1/models`, `/v1/chat/completions`, `/v1/persona/context/*`, `/v1/embeddings`, `/ollama/v1/*`, `/v1/images/*`, `/v1/videos/*` | **Frozen.** No identifier, field, or auth mode changes. |
| **B — Private HomePilot mirror** | the authenticated HomePilot Cloud app only (owner-scoped) | `/v1/node/manifest` (local), `/v1/mirror/*` (cloud) | New, additive, feature-flagged. |

**HomePilot Local is the authoritative application and compute node.** The cloud
is a functional mirror + remote interface, not a second HomePilot install. Model
weights, persona memory, files, and GPU stay local unless the user explicitly
enables cloud backup.

```
                 HomePilot Local  (authoritative app + GPU)
                        ▲
                 OllaBridge Local  (secure transport + provider gateway)
                        ▲
                 OllaBridge Cloud  (identity, relay, owner-scoped routing)
                   ▲          ▲
       Legacy provider     Private mirror
                   │          │
            3D Avatar     HomePilot Cloud
            OpenAI SDK    (full remote UI)
```

## 2. What already exists (verified in this repo)

The document's "extend, don't replace" rule is grounded in code that is already
here:

- **Legacy `/v1/*` plane** — `backend/app/openai_compat_endpoint.py`. Personas
  exposed as OpenAI models (`persona:<alias>--<short>` via `_build_external_id`,
  `openai_compat_endpoint.py:140`); only personas with `shared_api.enabled` are
  listed (`:681`). This is Plane A and stays frozen.
- **Edition / sidecar / pairing** — `backend/app/ollabridge_local.py`:
  `/v1/edition`, `/v1/ollabridge/local/status`, `/v1/ollabridge/local/pair-url`,
  sidecar probe (`_probe_sidecar`, `:60`).
- **Compute provider abstraction** — `backend/app/compute/` (`base.py`,
  `local.py`, `ollabridge_cloud.py`, `routes.py`) — already does async cloud
  jobs for image/video and returns media artifacts after polling.
- **Capability / model / GPU sources the manifest reuses** —
  `providers.available_image_models()` / `available_video_models()`,
  `capabilities._check_torch_gpu()` (`capabilities.py:55`),
  `projects.list_all_projects()` (`projects.py:281`), the persona `shared_api`
  flag.

The manifest and mirror build **on top of** these; none are modified.

## 3. Four meanings of "mirror" (not filesystem copy)

1. **Interface mirror** — the cloud UI displays local resources.
2. **Execution mirror** — cloud actions run on HomePilot Local via the relay.
3. **Metadata mirror** — the cloud caches only a *description* (ids, names, types,
   capabilities, status, GPU, timestamps), never the databases.
4. **Data authority** — projects, persona memory, MCP credentials, model files,
   and generated assets stay local by default. No active second copy → no
   conflict resolution, privacy preserved.

## 4. Permission model — private mirror ≠ public publish

These are distinct and must not be conflated:

```json
{ "mirror_to_owner": true, "publish_provider_api": false,
  "share_with_org": false, "share_publicly": false }
```

- `mirror_to_owner` → visible in the owner's HomePilot Cloud UI (private mirror
  catalog).
- `publish_provider_api` → listed by the legacy `/v1/models` catalog (this is the
  existing `shared_api.enabled` flag — **unchanged**).

A private local persona appears in the owner's cloud UI but is **absent** from the
3D Avatar's `/v1/models` until the user enables provider publishing. The two
catalogs are separate by construction.

## 5. Stable resource identifiers

Display names aren't safe keys (two PCs may hold the same model). The cloud uses
canonical node URIs internally while legacy IDs stay valid forever:

```
hpnode://<node_id>/model/ollama/qwen3%3A14b
hpnode://<node_id>/persona/<project_id>
hpnode://<node_id>/workflow/<workflow_id>
```

External clients keep using `qwen3:14b`, `persona:...`, `flux-schnell`. IDs are
never renamed.

## 6. Remote operation protocol (no arbitrary proxy)

The relay can **never** request an arbitrary URL, port, path, or shell command.
HomePilot Local publishes *named* operations in its manifest:

- **RPC** (short control-plane): `projects.list`, `personas.get`, `models.status`,
  `services.health`, `settings.get_safe`, …
- **Jobs** (long-running): `chat.completions`, `images.generate`,
  `videos.generate`, `voice.synthesize`, `avatar.render`, `models.install`, …
  with `progress` → `completed`/`failed` events and relay-delivered artifacts.

Every mirror request is signed and carries owner identity, scopes, expiry, nonce,
and an idempotency key. Secrets (API keys, MCP OAuth tokens, DB creds, device
private keys) never appear in a manifest or an RPC response.

## 7. Node Manifest (Phase 1 — implemented)

HomePilot Local exposes a **localhost-only** manifest that OllaBridge Local reads
and republishes (owner-scoped) to the cloud:

```
GET /v1/node/manifest            # full, revisioned
GET /v1/node/manifest/revision   # cheap {revision, hash} for delta polling
```

Schema `homepilot.node.manifest/v1`: `node_id`, versions, `manifest_revision`,
`hardware` (GPU/VRAM/RAM/disk), `services` (homepilot/ollama/comfyui/voice/
avatar/mcp status), `capabilities[]`, and `resources` (chat_models, personas with
both permission flags, image_models, video_models, workflows). Built entirely
from the existing sources in §2 — see `backend/app/node_manifest.py`.

Guarantees enforced by the implementation:
- **Localhost-only** — remote callers get 403 (the manifest can carry more than
  the public catalog, so it must not be internet-reachable directly).
- **Feature-flagged** — `OLLABRIDGE_NODE_MANIFEST_ENABLED` (default off); disabling
  it removes the endpoint and changes nothing else.
- **No secrets** — only ids, names, types, status, and the two permission flags.
- **Revisioned** — content hash → monotonic `manifest_revision`, so the cloud can
  sync with `manifest.full` / `manifest.delta` and detect continuity loss.

## 8. Implementation phases

| Phase | Delivers | Repo(s) | State |
|---|---|---|---|
| **0** | Freeze compatibility: contract tests + JSON fixtures for the 3D-Avatar / `/v1` behavior | HomePilot | **done** (`test_ollabridge_contract.py`) |
| **1** | **Node manifest** (`/v1/node/manifest`), localhost-only, feature-flagged | HomePilot | **done** (`node_manifest.py`) |
| **2** | **Read-only mirror RPC** (`/v1/node/rpc`): services, models, personas, projects, workflows, safe settings | HomePilot | **done** (`node_rpc.py`) |
| **3** | **Durable jobs + artifacts** (`/v1/node/jobs`, `/v1/node/artifacts`): chat/image/video ops with progress; owner-scoped, expiring artifacts | HomePilot | **done** (`node_jobs.py`, `node_artifacts.py`) — image/video adapters await a live sidecar ComfyUI URL |
| **2–3 cloud+daemon** | Owner-scoped `/v1/mirror/nodes/*` relay routes; daemon maps `homepilot.mirror.*` op-codes → node endpoints | ollabridge-cloud | **done** (`api/mirror.py`, `connector/bridge.py`) |
| 4 | Full ops (projects/persona edit, voice, avatar, files, MCP) — per-scope | all | design |
| 5 | Media optimization (chunked/resume/WebRTC, direct-browser media) | all | design |
| 6 | Optional encrypted backup/sync — a **separate** product feature | all | design |

### End-to-end path (now complete for read RPC + jobs)

```
HomePilot Cloud ──► POST /v1/mirror/nodes/{id}/rpc|jobs        (ollabridge-cloud api/mirror.py)
   owner check ──► RelayHub.request(node, homepilot.mirror.*)  (relay_hub.py)
              ──► OllaBridge Local daemon _dispatch_mirror      (connector/bridge.py)
              ──► HomePilot /v1/node/rpc | /v1/node/jobs        (HomePilot node_rpc/node_jobs)
              ──► local capability/persona data · GPU jobs
```

Every hop is additive, feature-flagged, and owner-scoped. Turning any flag
off collapses that hop back to prior behavior with no effect on the legacy
provider plane.

## 9. Feature flags (all independently reversible)

```env
OLLABRIDGE_LEGACY_PROVIDER_ENABLED=true   # Plane A — must stay independently on
OLLABRIDGE_NODE_MANIFEST_ENABLED=false    # Phase 1 (this change)
OLLABRIDGE_NODE_GEN_ENABLED=true
HOMEPILOT_MIRROR_ENABLED=false            # Plane B master switch
HOMEPILOT_MIRROR_RPC_ENABLED=false
HOMEPILOT_MIRROR_JOBS_ENABLED=false
HOMEPILOT_MIRROR_PROJECTS_ENABLED=false
HOMEPILOT_MIRROR_FILES_ENABLED=false
HOMEPILOT_MIRROR_MCP_ENABLED=false
HOMEPILOT_CLOUD_FALLBACK_ENABLED=true
```

**Disabling the mirror must never disable `/v1/models` or `/v1/chat/completions`.**

## 10. Acceptance (whole effort)

- Legacy: 3D Avatar connects, fetches published personas, chats with local memory
  + MCP + attachments + avatar directives; existing IDs and auth modes unchanged.
- Mirror: owner sees their online PCs, GPU/service health, local models (no weight
  copy), owner-authorized personas/projects; cloud chat + image/video run on the
  local GPU with progress; local memory/files stay local; offline nodes shown
  honestly.
- Security: no cross-user node access; unpublished personas absent from the legacy
  catalog; no arbitrary port/shell; artifact URLs owner-scoped + expiring; no
  secrets in manifests.
- Rollback: flag-off restores current behavior; legacy APIs keep working;
  HomePilot Local works with OllaBridge stopped; 3D Avatar works without any
  mirror endpoint.
