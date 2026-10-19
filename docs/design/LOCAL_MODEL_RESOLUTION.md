# Local model resolution — use the models that are actually there

Status: phases 1, 2 and the Expert part of 3 implemented in HomePilot on
16 Oct 2026 (`backend/app/model_resolver.py`, `model_resolver_routes.py`,
`frontend/src/ui/components/ModelDownloadCard.tsx`, `OllamaHealthBanner.tsx`,
`lib/modelResolution.ts`; tests in `backend/tests/test_model_resolver.py` and
`frontend/src/test/modelDownloadCard.test.tsx`). The OllaBridge changes in
§3.6 and the image resolver in §3.7 are still open. Scope: HomePilot backend +
frontend, the Expert service, and OllaBridge (local edition). Companion to
`docs/design/ollabridge-cloud-mirror/README.md`.

## 1. The problem, as observed on a real machine

Symptoms seen in one session on a Windows 11 laptop running HomePilot and
OllaBridge inside WSL 2:

| Where | What the user saw |
|---|---|
| HomePilot chat | `HTTP 502 … Ollama at http://localhost:11434 has no models pulled. Run ollama pull deepseek-r1:latest …` |
| HomePilot UI banner | "Ollama unavailable … Switch to vLLM / Fetch models" (vLLM is not installed) |
| OllaBridge banner | `Model: deepseek-r1` followed by `Ollama not reachable at http://localhost:11434`, `local catalog … models_loaded=0` |
| HomePilot backend log | ComfyUI warmup submits `ckpt_name: 'sdxl'` although the checkpoint list is `[]` |

The machine **does** have a model. Ollama for Windows is running (pid 16696)
with `deepseek-r1:latest` (qwen3 family, 8.2B, 5.2 GB, tools + thinking). It
listens on `127.0.0.1:11434` only. WSL runs in NAT mode (gateway
`172.20.16.1`), so `localhost:11434` inside WSL is an empty socket and the
Windows listener is not reachable from Linux at any address.

Every component then fails in its own way because each one hard-codes a URL
and a model name, probes once, and has no shared notion of "which runtimes are
reachable and what they hold".

### 1.1 How each component picks a model today

HomePilot backend (`backend/app`):

- `config.py:37-52` — `DEFAULT_PROVIDER=ollama` outside Docker,
  `OLLAMA_BASE_URL=http://localhost:11434`, `OLLAMA_MODEL=""` ("backend can
  auto-pick").
- `llm.py:512-565` — `chat_ollama` auto-picks per request from `/api/tags`
  through `pick_chat_model` (priority list at `llm.py:288`), with no cache.
  Good behaviour, but only at the one configured URL, and **a configured name
  wins without being checked** (`llm.py:321-335`: `if cfg: return cfg`). On a
  404 it lists the installed models (`llm.py:637-650`) and gives up. Server
  down and zero models produce the same message ("none were found. Run
  'ollama pull llama3:8b'"), which is wrong when the server is down.
- `llm.py:830-841` — `stream_chat` has **no auto-pick** and sends `model: ""`.
- `llm.py:373-374`, `config.py:48` — the `openai_compat` path (OllaBridge on
  `11435/v1`) uses `LLM_MODEL`, default `"local-model"`, with no listing.
- `orchestrator.py:2107-2113` — every LLM failure becomes an **HTTP 200** whose
  text is `"LLM error (ollama): …"`, rendered as a normal assistant bubble and
  saved into the conversation history. Only transport failures get an error
  flag and a retry button.
- `main.py:1647` — `GET /auto-detect` probes `OLLAMA_BASE_URL`, `LLM_BASE_URL`
  and ComfyUI, with its **own copy** of the priority list
  (`CHAT_MODEL_PRIORITY`, `VISION_PRIORITY`, no `qwen3`). Returns
  `modelChat: ""` when nothing answers.
- Hard-coded `llama3:8b` / `llama3` fallbacks that never consult any list:
  `teams/llm_adapter.py:61`, `crewai_llm.py:48`, `story_mode.py:1168,1304,1492`,
  `game_mode.py:644`, `main.py:5337`, `interactive/llm_router.py:99-102,150`,
  `voice_call/ws.py:291-296`, `orchestrator.py:506,539`
  (`DEFAULT_REFINE_MODEL`), `node_jobs.py:183`, `routines/service.py:108`,
  `studio/routes.py:1341-1406` (own fallback chain, exact-string check that
  misses `llama3` vs `llama3:latest`).
- Three different vision preference orders: `llm._VISION_MODEL_PRIORITY`,
  `/auto-detect` `VISION_PRIORITY` and `multimodal.VISION_PREFERENCE`
  (moondream first in two, last in the third).
- `openai_compat_endpoint._resolve_chat_backend` (`:319-356`) — the one
  existing resolver that goes `runtime.env` → env → installed list. It is only
  used by the persona endpoint, and shares the "configured wins" gap.
- `frontend/src/ui/App.tsx:3771-3815` — auto-detect runs on boot only while
  `localStorage.homepilot_model_chat` is unset. It stops for good once **any**
  name is saved, including a wrong one, and never notices a saved model that
  has disappeared. Two paths save wrong names: reopening Settings fills the
  chat model with `'local-model'` (`App.tsx:4148`), and the legacy key
  `homepilot_ollama_model` defaults to `'llama3:8b'` (`App.tsx:3286`), which
  Meetings (`meetingsense/api.ts:57-66`) and Teams
  (`TeamsSettingsDrawer.tsx:55`) send explicitly on a fresh install.
- `SettingsPanel.tsx:962-1010` — the Chat Model dropdown shows a saved model
  that is missing from the list as "X (current)" with no warning, and ignores
  the `error` field the backend sends when Ollama is down.
- `frontend/src/ui/OllamaHealthBanner.tsx` — one static message with a remedy
  that does not apply to most installs ("Switch to vLLM").
- Status surfaces: `/health/detailed` lists installed models and `/providers`
  reports the configured one, but **no endpoint reports the mismatch**;
  `/compute/status` says "Connected — Using this PC" with zero models.
- `meetingsense/notes_engine.py:483-524` — passes `OLLAMA_MODEL` through to
  `chat_ollama`; summaries and analysis do the same. They inherit whatever
  `chat_ollama` does, which is fine once `chat_ollama` is fixed.
- `multimodal.py` — `pick_vision_model` with the same per-request `/api/tags`
  pattern.
- `warmup.py:59-110` — maps `IMAGE_MODEL=sdxl` to an installed checkpoint by
  architecture, but when **nothing** is installed it returns the raw token and
  still submits the workflow, producing the validation error in the log.
- `ollabridge_local.py:60-118` — probes the OllaBridge sidecar for a model
  count, for status display only.

Expert service (`expert/backend/app/expert/providers.py:24-70`):

- Own URL (`EXPERT_OLLAMA_URL`) and own defaults (`deepseek-r1:latest`,
  `llama3.2:3b`). `_resolve_local_model` already falls back to a pulled model
  with a stem match (`EXPERT_LOCAL_AUTO_FALLBACK`, default on). It only hard
  fails when the list is empty, which is exactly the WSL case. This is the
  pattern to generalise, not to replace.

OllaBridge (`src/ollabridge`):

- `api/main.py:891` — `model = req.model or runtime_settings.default_model or
  settings.DEFAULT_MODEL`. The name is never checked against anything.
- `api/main.py:393-405`, `core/router.py:27-67` — the local node is registered
  with `models=[]` and `healthy=True` and nothing ever marks it unhealthy, so
  it is always chosen, Ollama up or down.
- `providers/ollama_client.py:59-67` — a 404 ("model not found") is retried
  three times and surfaces as a **500** with httpx's text. Ollama's own
  "try pulling it first" is lost. A connect failure becomes a 502
  `ollama_unreachable`.
- `addons/providers/router.py:134-176` — name heuristic: `deepseek-r1` matches
  the `deepseek-cheap` cloud provider whenever a DeepSeek key exists, so a
  local model name can silently go to the cloud.
- `addons/local_catalog/*` — scans `/api/tags` + `/api/show` every 60 s,
  scores models (`scoring.py`), writes `~/.ollabridge/local_models.yaml` and
  **writes `local-best` / `local-fast` / `local-private` aliases to
  `~/.ollabridge/local_aliases.yaml`, which nothing reads**
  (`provider_loader.py:50-57` loads only `model_aliases.yaml`).
- `api/ollama_setup_routes.py:429-482` — the setup wizard already probes
  fallback URLs (127.0.0.1, WSL host, Docker host) and suggests models with
  sizes. None of that reaches the request path or `runtime_settings`.
- `addons/local_catalog/routes.py:90-91` — `/local/*` builds its client from
  the env URL, not the URL saved in the UI, so "Pull" and "Test" can target a
  different Ollama than the scheduler.
- `cli/main.py:341-374` — `--model` only feeds the banner and `ensure_model`,
  never the server; `--no-setup` flips `LOCAL_RUNTIME_ENABLED` after
  `runtime_settings` has already captured the default.

### 1.2 Root causes

1. **Discovery is a single hard-coded URL.** Nobody looks for Ollama anywhere
   but `localhost`, although every WSL and Docker user has it one hop away.
2. **No shared resolver.** Six places pick a model with four different rules
   and two copies of the priority list.
3. **Configured names are requirements, not preferences.** `deepseek-r1`,
   `llama3.2:3b`, `sdxl` fail hard instead of mapping to what exists.
4. **State is captured once.** The frontend stops re-detecting as soon as any
   model name is saved (even `local-model`), OllaBridge's
   `runtime_settings.json` pins the first default forever, and the local node's
   `healthy=True` is never revisited.
5. **Errors are not actionable.** Raw 500/502 JSON or an HTTP 200 "LLM error"
   bubble reaches the chat box; the banner suggests a provider that is not
   installed; the pull button that exists in OllaBridge is not offered where
   the error appears.
6. **The default name is inconsistent.** `make start` and `make run` print
   `llama3:8b`, `.env.example` and `docker-compose.yml` set `llama3:8b`,
   `make download-chat` pulls `llama3.2:3b`, the Expert service wants
   `deepseek-r1:latest`, and OllaBridge wants `deepseek-r1`. A user who follows
   the printed advice still ends up with a mismatch somewhere.

## 2. Goals and non-goals

Goals:

- G1 Find every reachable local runtime, not just `localhost`.
- G2 One resolver: configured model if installed, else the best installed
  model for the role, else an explicit "no model" state with a remedy.
- G3 Every consumer (chat, streaming, meetings, multimodal, teams, Expert,
  auto-detect, health) uses that resolver. No fatal hard-coded names.
- G4 Re-evaluate when the world changes: new pull, Ollama started, URL
  changed. Caches expire; a 404 invalidates.
- G5 The UI shows the effective model and why ("auto, from Windows Ollama"),
  and offers the real fix (pull / connect / start) with progress.
- G6 OllaBridge treats `DEFAULT_MODEL` as a preference, makes `local-best`
  real, and answers "model missing" with a structured error or a fallback the
  client can see in a header.

Non-goals:

- Downloading gigabytes without consent. The resolver may **offer** a pull,
  never start one on its own.
- Scanning the LAN. Candidate hosts are loopback, the WSL/Docker host
  gateway and explicitly configured URLs only.
- Changing cloud routing policy. Provider selection stays as it is; this
  design only stops local names from falling into the cloud by accident.

## 3. Design

### 3.1 Runtime discovery (both products)

A small, dependency-free module probes a fixed candidate list in parallel
(1.5 s connect timeout) and returns the reachable runtimes with their model
lists:

```
candidates (in order):
  1. explicit env     OLLAMA_BASE_URL / EXPERT_OLLAMA_URL / OllaBridge runtime_settings
  2. loopback         http://127.0.0.1:11434, http://localhost:11434
  3. WSL host         http://<default-route gateway>:11434   (ip route show default)
                      http://<resolv.conf nameserver>:11434  (older WSL)
  4. Docker host      http://host.docker.internal:11434, http://172.17.0.1:11434
  5. HomePilot only   OllaBridge sidecar  OLLABRIDGE_LOCAL_URL + /v1/models
```

Ranking: the configured URL wins if it answers; otherwise the first runtime
that answers **with at least one model**; otherwise the first that answers at
all. The result is cached 30 s, refreshed in the background every 60 s with
exponential backoff while nothing answers, and invalidated immediately on a
connection error or a 404 from the active runtime.

WSL-specific hint: when the process runs under WSL (`/proc/version` contains
"microsoft") and the gateway refuses the connection, the remedy says so
explicitly: "Ollama on Windows listens on 127.0.0.1 only. Enable WSL mirrored
networking or set OLLAMA_HOST=0.0.0.0 on Windows" (see §6).

### 3.2 The resolver (HomePilot: `backend/app/model_resolver.py`)

```python
Role = Literal["chat", "fast", "vision", "embed", "image"]

@dataclass
class Resolution:
    role: Role
    model: str                 # "" when none
    runtime_url: str           # "" when no runtime
    source: Literal["configured", "fallback", "none"]
    reason: str                # human sentence for logs/UI
    installed: list[ModelInfo] # name, family, params, caps, size, modified_at
    alternatives: list[str]
    remedy: Remedy | None      # kind: pull|connect|start|wsl_bridge, command, suggested[]

async def resolve(role: Role, configured: str = "") -> Resolution
async def invalidate(reason: str) -> None
```

Algorithm for `chat` (others differ only in the filter and priority list):

1. `installed = discovery.active().models` (normalised from `/api/tags`:
   `details.family`, `parameter_size`, `capabilities`).
2. Exact match of `configured` → `source=configured`.
3. Stem match (`deepseek-r1` ↔ `deepseek-r1:latest`, `:Q4_K_M` variants) →
   `source=configured`, reason notes the tag.
4. Role filter: chat excludes embedding-only and vision-only models (reuse
   `is_text_chat_model`, `VISION_MODEL_PATTERNS`); `fast` prefers ≤ 4B;
   `vision` requires a vision family; `image` uses `scan_installed_models`.
5. Priority list — one copy, moved here from `llm.py:288` and
   `main.py:1727/1757`. Ties break on most recent `modified_at`.
6. Nothing left → `source=none` with a remedy:
   - runtime alive, zero models → `pull`, suggested list with sizes
     (`llama3.2:3b` 2.0 GB, `qwen2.5:7b` 4.7 GB, `deepseek-r1:8b` 4.9 GB).
   - no runtime → `start` (binary found on PATH) or `connect`
     (nothing found) or `wsl_bridge` (WSL and a Windows host detected).

`"auto"` (or empty) is a first-class value for the configured model. The UI
stores `auto`; the backend resolves per request and reports what it used.

### 3.3 Consumers

| Consumer | Change |
|---|---|
| `llm.chat_ollama` / `stream_chat` (`llm.py:512, 832`) | `model = (await resolve("chat", model or OLLAMA_MODEL)).model` in **both** paths (streaming has none today); on 404 call `invalidate()` and resolve once more before failing; use `resolution.runtime_url` instead of `OLLAMA_BASE_URL`; distinct errors for "server down" and "no models". |
| `llm.chat_openai_compat` (`llm.py:355-390`) | treat `LLM_MODEL="local-model"` as `auto`: list the gateway's `/v1/models` through the same discovery and resolve against it. |
| `openai_compat_endpoint._resolve_chat_backend` (`:319-356`) | seed for the resolver: it already reads `runtime.env` → env → installed. Move that logic into `model_resolver` and call it from here. |
| `multimodal.py` | `resolve("vision", configured)`; delete the two extra vision orders. |
| `meetingsense/notes_engine.py:446-543` | `resolve_target` → resolver; `classify_model_failure` (`:57-89`) must classify a 404 as `model_missing`, not log a traceback per notes window; record `resolution.reason` in job metadata so a fallback is visible. |
| Hard-coded `llama3:8b` sites (list in §1.1) | one sweep: `resolve("chat")` for quality paths, `resolve("fast")` for Game Mode's fast path, prompt refinement and routines. No literal model names remain outside the priority table. |
| `studio/routes.py` outline / continuation | drop the private fallback chain; use the resolver (stem-aware, so `llama3` matches `llama3:latest`). |
| `orchestrator.py:2107-2113` | map a `no_local_model` resolution to the structured 503 of §3.4 instead of a 200 text bubble, and do not store it in the conversation history. |
| Teams / personas / voice / interactive | same entry point. |
| `GET /auto-detect` (`main.py:1647`) | built on `resolve()` for chat/vision/image; adds `reason`, `runtime_url`, `remedy`. |
| `GET /health` | add `models.resolution` (effective chat/vision model, runtime, source). |
| `warmup.py:84` | when `scan_installed_models` is empty: log "no checkpoints installed — skipping warmup" and return; never submit a workflow that cannot validate. |
| Expert `providers.py` | keep `_resolve_local_model`; add the same discovery candidate list before declaring "no models pulled"; make the error a structured 503 (see 3.4). The service is deliberately isolated, so copy the 60-line discovery helper rather than import HomePilot. |

### 3.4 API contract

New endpoints (HomePilot backend):

```
GET  /v1/models/resolution          → { chat, fast, vision, image, runtimes[], fingerprint }
POST /v1/models/refresh             → re-probe now (used by the UI "Retry" button)
POST /v1/models/pull {name}         → proxy Ollama /api/pull as SSE progress
GET  /v1/models/pull/{name}         → progress for reconnects
```

When the active runtime is the OllaBridge sidecar, `pull` delegates to
OllaBridge's existing `POST /admin/ollama-setup/pull` and polls
`GET /pull/{model}`.

Structured error, returned by every LLM consumer instead of a raw 500/502:

```json
{
  "code": "no_local_model",
  "role": "chat",
  "runtime": { "url": "http://localhost:11434", "reachable": false, "wsl_host": "172.20.16.1" },
  "remedy": {
    "kind": "wsl_bridge",
    "message": "Ollama on Windows is listening on 127.0.0.1 only …",
    "command": "ollama pull llama3.2:3b",
    "suggested": [{ "name": "llama3.2:3b", "size_gb": 2.0 }]
  }
}
```

HTTP 503, never 500, so the frontend can distinguish "nothing to answer with"
from a bug.

### 3.5 Frontend

1. **Reconcile on every load.** Call `/v1/models/resolution` (cheap, cached).
   If the saved chat model is empty or not in `installed`, switch the setting
   to `auto` and show a one-line toast. Replace the once-only auto-detect gate
   with "run when unresolved or when `fingerprint` changed" (fingerprint =
   runtime URL + sorted installed names, kept in `localStorage`).
2. **Replace `OllamaHealthBanner` with a `LocalModelBanner`** driven by
   `remedy.kind`:
   - `wsl_bridge` / `connect` / `start`: explain, "Retry", "Open setup guide".
   - `pull`: suggested models with sizes, a "Pull" button with a progress bar
     (SSE), auto-dismiss when the resolution becomes non-empty.
   - fallback active: a small badge next to the model name,
     "Using deepseek-r1:latest (auto)".
   - "Switch to vLLM" only when `/auto-detect` actually found a vLLM.
3. **Model picker** (`SettingsPanel.tsx:962-1010`): "Auto (recommended)"
   first, installed models grouped by runtime with family and size, greyed
   "Pull…" rows for the suggested ones, a visible warning instead of
   "X (current)" when the saved model is not installed, and the backend's
   `error` field shown when the list is empty.
4. **Remove the wrong defaults**: no `'local-model'` fill when Settings reopens
   (`App.tsx:4148`); the legacy `homepilot_ollama_model` key defaults to
   `auto`, not `'llama3:8b'` (`App.tsx:3286`). Meetings
   (`meetingsense/api.ts:57-66`) and Teams (`TeamsSettingsDrawer.tsx:55`) keep
   reading the legacy key for installs that only have it (a test pins this),
   which is harmless now: a saved name that is not installed is mapped to an
   installed model by the backend instead of failing. `fetchMeetingModels`
   should stop adding a not-installed selection to the list (open).
5. **Error rendering**: a `no_local_model` response renders the banner's
   content inline in the chat with a retry, instead of a normal-looking
   assistant bubble or a raw JSON string.

### 3.6 OllaBridge changes (local edition)

In order of value:

1. **Validate and fall back in `chat_completions`** (`api/main.py:891`).
   After computing `model`, look it up in the local catalog (rows with
   `setup_status` not in `removed|not_installed|pulling` and
   `capabilities.supports_chat`), falling back to a cached
   `ollama_client.list_models()`. If it is not installed and no provider
   *declares* it (alias or exact id, not the name heuristic), use the
   `local-best` candidate and set `X-OllaBridge-Resolved-Model` and
   `X-OllaBridge-Resolution: fallback`. Config `OBRIDGE_MODEL_FALLBACK=auto|off`,
   default `auto` for `AUTH_MODE=local-trust`. With nothing installed return
   503 `{"error":{"code":"no_local_models","remedy":{...}}}` instead of the
   retried 500, reusing the wizard's suggested list.
2. **Load `local_aliases.yaml`** into the registry next to `model_aliases.yaml`
   (`provider_loader.load_aliases` merge, provider id `local` = the local
   node) and reload it after each catalog sync through the existing reload
   hook (`api/main.py:598-647`). `local-best`, `local-fast`, `local-private`
   then work as documented.
3. **Runtime discovery** for `runtime_settings.ollama_base_url()`: when unset
   or unreachable, probe the wizard's fallback list
   (`ollama_setup_routes.py:429-482` already has WSL host and Docker host).
   Show the discovered URL on the Local Runtimes page with "Use this"; in
   `local-trust` mode adopt it automatically and log it.
4. **Make local node health real**: feed `core/reachability.OLLAMA` into
   `router.choose_node` and pass `require_model=True` when the catalog knows
   the installed set, so a down Ollama does not shadow an available provider.
5. **Fix `/local/*` to use `rts.ollama_base_url()`** (`routes.py:90-91`), make
   `--model` set the server default, and move the `--no-setup` flag before
   `runtime_settings` is imported.
6. **Stop the name-heuristic hijack**: a bare Ollama-style tag that is
   installed locally is served locally even when a cloud provider's kind
   appears in the name.
7. **Banner and `/v1/models`**: print the *resolved* model and runtime URL, or
   "No local models — open the dashboard → Local Runtimes → Pull"; add
   `recommended: true` to the top-N rows and an `X-OllaBridge-Default-Model`
   header with the effective default.

### 3.7 The same idea for ComfyUI checkpoints

`IMAGE_MODEL=sdxl` is a preference too. `_resolve_warmup_checkpoint` already
maps a token to an installed checkpoint by architecture; generalise it into
`resolve("image")`, use it at generation time as well as warmup, skip warmup
when nothing is installed, and let the image model picker read
`scan_installed_models` with a "Download…" row for catalog entries.

## 4. Rollout

| Phase | Content | Files |
|---|---|---|
| 0 — today, no code | Make Windows Ollama reachable from WSL (§6); reset the saved chat model to auto; stop stale processes on 3000/8010. | — |
| 1 — backend resolver | `model_resolver.py`, discovery, consumers in §3.3, structured 503, warmup skip, `/v1/models/resolution|refresh|pull`; one default name everywhere (`llama3.2:3b`, the one `make download-chat` pulls) in `make start`/`run` text, `.env.example:38`, `infra/docker-compose.yml:23` and the Expert fast model. | `backend/app/model_resolver.py` (new), `llm.py`, `openai_compat_endpoint.py`, `multimodal.py`, `main.py` (`/auto-detect`, `/health`), `orchestrator.py`, `meetingsense/notes_engine.py`, `warmup.py`, the hard-coded sites in §1.1, `expert/backend/app/expert/providers.py`, `Makefile`, `.env.example`, `infra/docker-compose.yml` |
| 2 — frontend | reconcile on load, `LocalModelBanner`, picker with Auto, inline error card, pull progress. | `App.tsx`, `OllamaHealthBanner.tsx` → `LocalModelBanner.tsx`, settings model picker |
| 3 — OllaBridge | items 1–7 of §3.6. | `api/main.py`, `providers/ollama_client.py`, `addons/providers/services/provider_loader.py`, `addons/local_catalog/routes.py`, `core/router.py`, `core/runtime_settings.py`, `cli/main.py` |
| 4 — images | `resolve("image")` at generation time, picker. | `warmup.py`, `providers.py`, image routes |

Phases 1 and 3 are independent and can ship separately. Phase 2 depends on 1.

## 5. Tests

- Resolver unit tests with a fake `/api/tags` (extend
  `backend/tests/test_model_selection.py`): configured present; stem match;
  configured missing → priority fallback; embedding-only list → none with
  `pull` remedy; no runtime → `connect`/`wsl_bridge` remedy; 404 invalidates
  and re-resolves once; streaming and non-streaming resolve identically.
- A grep guard in CI: no `llama3:8b` / `llama3` / `local-model` literal outside
  `model_resolver.py` and the docs.
- Discovery tests: candidate order, parallel probe with one slow host, WSL
  gateway detection from a fake `ip route` output.
- Contract test: chat with nothing installed returns 503 `no_local_model`,
  not 500/502; meetings job records `resolution.reason`.
- Frontend: banner states by `remedy.kind`; picker shows Auto first;
  reconcile switches a stale saved model to auto.
- OllaBridge: `local-best` alias resolves after a sync; missing model →
  fallback header; nothing installed → 503 with remedy; `FakeOllama` in
  `tests/enterprise/test_ollama_runtime_url.py` already fakes `/api/tags`
  and `/api/chat`.

## 6. Making this machine work today (Phase 0)

Option A — **WSL mirrored networking** (recommended: no exposure beyond
loopback, no firewall change, discovery then finds Ollama at `127.0.0.1`):

```
%USERPROFILE%\.wslconfig
[wsl2]
networkingMode=mirrored
```

then `wsl --shutdown`, reopen the shell, and check:

```bash
curl -s http://127.0.0.1:11434/api/tags | head -c 200
```

Caveats: ports bound to `0.0.0.0` inside WSL become visible on Windows
localhost too (the stale 3000/8010 listeners already in the log will then
collide with Windows apps on those ports); Docker Desktop ≥ 4.26 supports
mirrored mode.

Option B — bind Ollama on Windows to all interfaces: user environment variable
`OLLAMA_HOST=0.0.0.0:11434`, restart the Ollama app, add an inbound firewall
rule for TCP 11434 scoped to the WSL subnet, and point `OLLAMA_BASE_URL` at the
gateway (`ip route show default`). The gateway address changes across reboots
in NAT mode, and Ollama is then reachable from the LAN unless the firewall rule
is tight.

Option C — install Ollama inside WSL and pull the model again (5 GB; the GPU is
already usable in WSL as the ComfyUI log shows).

After any option: in HomePilot set the chat model to Auto (or clear
`homepilot_model_chat` in the browser's localStorage) so auto-detect runs again
until Phase 2 removes that gate. OllaBridge's `DEFAULT_MODEL=deepseek-r1`
already matches `deepseek-r1:latest`, because Ollama treats a missing tag as
`:latest`.

## 7. Risks and open decisions

- **Silent fallback may pick a weak model** (a 1B tag ahead of nothing). The
  badge and the log line make it visible; the priority list keeps known good
  families first. Decision needed: silent fallback (proposed) or a one-time
  confirmation in the UI.
- **Probe latency in the request path.** Mitigated by the 30 s cache and the
  background refresh; a cold resolve costs at most one 1.5 s probe round.
- **Firewall-dropped gateway probes** time out rather than refuse; the
  parallel probe keeps the total bounded.
- **Auto-adopting a discovered URL** is limited to loopback, the WSL gateway
  and the Docker host, and in OllaBridge to `local-trust` mode. Anything else
  requires a click.
- **Auto-pull on first boot**: proposed *no*; offer the pull with its size and
  let the user click. `make download-minimal` remains the batch route.
