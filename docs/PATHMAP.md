# PATHMAP — Avatar Director spec paths → this repository

Spec v1.1 §0.6: *when the repo layout differs from the paths assumed in the spec, keep the
role and adapt the path; record the mapping here so later phases stay consistent.*

This is the HomePilot half of that record. The client half lives in
`ruslanmv/3D-Avatar-Chatbot` at `docs/PATHMAP.md`; the two are read together.

Frozen in **B0**. Every later batch reads this file before writing code, and appends to it
in the same PR that introduces a new mapping.

---

## 1. Server path map

| Spec says | This repository | Why |
|---|---|---|
| `services/avatar/` | **`backend/app/avatar_director/`** | `backend/app/avatar/` is taken — 18 modules of StyleGAN / hybrid avatar *image* generation. Repo-root `services/` holds only `teams-relay`, and every mounted service lives under `backend/app/` |
| `services/avatar/session.py` | `backend/app/avatar_director/session.py` (B8) | — |
| `services/avatar/rtc.py` | `backend/app/avatar_director/rtc.py` (B10) | Signalling only; the audio path feeds `app.voice_call` |
| `services/avatar/vision.py` | `backend/app/avatar_director/vision.py` (B15) | Model access through the existing model runner |
| `services/avatar/curiosity.py` | `backend/app/avatar_director/curiosity.py` (B16) | Records are new **categories** in `app.ltm`, not a new store |
| `services/avatar/kb_search.py`, `kb_store.py` | `backend/app/avatar_director/kb_search.py`, `kb_store.py` (B8+) | KB synced from the client repo |
| `services/avatar/safety.py` | `backend/app/avatar_director/safety.py` (B8) | Maps tools to HomePilot's read-only / confirm / autonomous levels |
| `services/avatar/verification.py`, `redaction.py` | `backend/app/avatar_director/{verification,redaction}.py` (B28) | Addendum §16.2, §16.5 |
| `context_forge/tool_servers/avatar_control/` | registered through `backend/app/agentic/` (`server_manager`, `mcp_installer`, `server_config`) and the seeds in `agentic/forge/` | The Context Forge registry already exists; `avatar_control` is one new entry beside the built-ins |
| `avatar:` config section | `backend/app/avatar_director/config.py`, `AVATAR_*` environment variables | HomePilot's config is env-var based (`backend/app/config.py` reads `os.getenv` at import). Same idiom, new keys only, `config.py` untouched |
| `tests/avatar/` | `backend/tests/avatar/` | `pytest -q` runs with `working-directory: backend` |
| `tests/fixtures/protocol/` | `backend/tests/fixtures/protocol/` | Byte-identical to the client copy; `CHECKSUMS.txt` is the proof |
| route prefix `/avatar/*` | unchanged — `/avatar/session`, `/avatar/rtc`, `/avatar/vision/insight` | Free: `backend/app/avatar/router.py` mounts at `/v1`. Documented fallback if that ever changes: `/companion/*` |

### Subsystems to reuse, never to re-implement

| Need | Already in the tree | Rule |
|---|---|---|
| Motion command format | `backend/app/embodiment/motion_dsl.py`, `planner.py` (`CommandType`, `MotionPlan`, `MotionPlanBuilder`) | Reuse; do not fork a second DSL |
| Long-term persona memory | `backend/app/ltm.py` — upserts on `(project_id, category, key)`, its own golden rule is "ADDITIVE ONLY" | Curiosity interests and focus streaks are new **categories**; no parallel store, no new tables beyond LTM's additive path |
| Streaming voice, barge-in, turn handling | `backend/app/voice_call/{ws,barge_in,turn_stream}.py`, `backend/app/voice/` | The mic track feeds this path; turns are marked `source:"voice"`. A second ASR implementation fails review |
| Tool approval for the embodied assistant | `backend/app/daypilot_bridge/` — propose-only mode: the persona proposes structured ops in `x_directives`, an Approval Center gates every external write | This *is* "act = confirm unless the owner sets autonomous". B21 renders proposals and confirms through it; a second approval path fails review |
| Agenda / day plan source | `agentic/integrations/mcp/personal_assistant_server.py` (`hp_personal_plan_day`), seeded `hp-google-calendar` and Microsoft Graph servers in `agentic/forge/templates/` | B21 is presentation over tools that already exist |
| MCP registration | `backend/app/agentic/` + `agentic/forge/` | `avatar_control` registers here (B17) |

---

## 2. Configuration

The spec's `avatar:` block, expressed as environment variables. All defaults are the safe
ones; nothing here is enabled by installing the package.

| Key (spec) | Environment variable | Default |
|---|---|---|
| `avatar.enabled` | `AVATAR_ENABLED` | `false` — the §1 kill switch: no routes mounted, nothing runs |
| `avatar.vision.model` | `AVATAR_VISION_MODEL` | `""` |
| `avatar.vision.max_image_px` | `AVATAR_VISION_MAX_IMAGE_PX` | `768` — re-checked server-side (§6.13) |
| `avatar.frames.retention` | `AVATAR_FRAMES_RETENTION` | `0` — frames are never stored |
| `avatar.curiosity.session_budget` | `AVATAR_CURIOSITY_SESSION_BUDGET` | `4` (§6.12) |
| `avatar.adult.enabled` | `AVATAR_ADULT_ENABLED` | `false` — a second, independent gate, never implied by `AVATAR_ENABLED` |
| `avatar.adult.provider` | `AVATAR_ADULT_PROVIDER` | `owner-attest` (addendum §16.2) |
| `avatar.redaction.enabled` | `AVATAR_REDACTION_ENABLED` | `true` (addendum §16.5) |

A malformed numeric value falls back to the default rather than being coerced — a typo in
an environment file must never silently widen a privacy limit. Tested in
`backend/tests/avatar/test_config_defaults.py`.

---

## 3. The one existing file any batch may touch

Spec v1.1 §7 allows exactly one server-side registration:

```python
# backend/app/main.py — beside the existing include_router calls:
from app.avatar_director import register as register_avatar
register_avatar(app, config)   # mounts nothing when avatar.enabled is false
```

That line lands in **B8**, not B0. Today `backend/app/avatar_director` exports only its
config; `register` does not exist yet, and a test asserts that, so the package cannot
quietly acquire a mount point between batches.

Plus one new entry in the Context Forge tool-server registry in B17. Anything else is a
spec violation: stop and flag it.

---

## 4. Running the checks

```bash
cd backend && pytest tests/avatar -q      # config defaults + protocol fixtures
```

The config tests deliberately need no FastAPI, no database and no network:
`app.avatar_director.config` is a pure module, so "the flags ship off" is checkable by
anyone in seconds rather than only inside a full environment.

---

## 5. Open mappings

Recorded when the batch that needs them lands.

| Batch | To decide |
|---|---|
| B8 | Which existing auth/pairing dependency the WS handshake reuses, and where `register()` is called from in `backend/app/main.py` |
| B10 | The exact seam in `voice_call` the mic track feeds, and how a turn is marked `source:"voice"` |
| B15 | Which model-runner entry point serves the VLM, and the local p95 measured on reference hardware |
| B16 | The LTM category names for interest records, and the decay job's home |
| B21 | The `x_directives` shapes the assistant renders as panels |
