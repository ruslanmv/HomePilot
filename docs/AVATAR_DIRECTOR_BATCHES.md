# Avatar Director — HomePilot server lane (batch plan, spec v1.1)

**Status:** planning artifact. No product code changes.
**Full cross-repo plan:** `ruslanmv/3D-Avatar-Chatbot` → `docs/BEHAVIOR_DIRECTOR_BATCHES.md`
(authoritative; this file is the HomePilot-scoped extract).
**Rule for every batch:** additive only — new package, new tests, one guarded
registration line. `avatar.enabled=false` (the default) means nothing mounts and nothing
imports.

---

## Naming decisions (frozen in B0 — read before writing code)

| Spec says | HomePilot reality | Use instead |
|---|---|---|
| `services/avatar/` | `backend/app/avatar/` is **taken** — 18 modules of StyleGAN / hybrid avatar *image generation*; `services/` at repo root holds only `teams-relay` | **`backend/app/avatar_director/`** |
| new motion command format | `backend/app/embodiment/{motion_dsl,planner}.py` already defines `CommandType`, `MotionPlan`, `MotionPlanBuilder` | Reuse `embodiment.motion_dsl`; do not fork a second DSL |
| new memory store for interests | `backend/app/ltm.py` — long-term persona memory, its own golden rule is "ADDITIVE ONLY" | New **categories inside LTM**, no parallel store |
| new ASR / streaming voice path | `backend/app/voice_call/{ws,barge_in,turn_stream}.py` + `backend/app/voice/` | Feed the existing voice-call path; mark turns `source:"voice"` |
| new MCP tool-server registry | `backend/app/agentic/` (`server_manager`, `mcp_installer`, `forge_http`, `server_config`) + `agentic/forge/` seed & templates | Register `avatar_control` through the existing Context Forge registry |

Route prefix `/avatar/*` is free (`backend/app/avatar/router.py` mounts at `/v1`), so
`/avatar/session`, `/avatar/rtc` and `/avatar/vision/insight` stand as specified.
Documented fallback if that changes: `/companion/*`.

Config lands as a new `avatar:` block only: `enabled:false`, `vision.model`,
`vision.max_image_px:768`, `frames.retention:0`, `curiosity.session_budget:4`.

---

## Server batches

| Batch | Title | Depends on | Touches existing code |
|---|---|---|---|
| **B0** | Ground truth: `docs/`, `avatar:` config block, shared protocol fixtures, additive CI job | — | nothing |
| **B8** | Session gateway — `avatar_director/{__init__,session,safety}.py`, mock server, contract tests | B0 | `backend/app/main.py`: one guarded `register_avatar(app, config)` |
| **B10** | Voice uplink — `avatar_director/rtc.py`, signalling over the B8 WS, mic → existing `voice_call` ASR path | B8, client B9 | nothing new |
| **B15** | Vision — `avatar_director/vision.py`, `POST /avatar/vision/insight`, model adapter via the existing model runner | B8, client B11 | nothing |
| **B16** | Curiosity Engine — `avatar_director/curiosity.py`, interest records as new LTM categories | B8, client B9 | nothing |
| **B17** | MCP `avatar_control` tool server registered through Context Forge | client B9 | Context Forge tool-server registry: one new entry |
| **B19** | Privacy audit, retention proofs, docs; `avatar.enabled` stays **opt-in** | all | docs |

Client-side counterparts (`SessionAdapter`, capture/consent, Together activities, the
Behavior Director itself) are batches B1–B7, B9, B11–B14 in the client repo's plan.

---

## Acceptance criteria per batch

**B8 · Session gateway.** Build the mock server and the contract tests from
`tests/fixtures/protocol/*.json` **before** the real endpoints. WS auth reuses HomePilot's
existing auth/pairing; heartbeat 15 s; unknown message `type` ignored (forward
compatible). AC: every §6.9 message shape round-trips; `avatar.enabled=false` → no route
mounted and no import executed (asserted); the existing suite stays green.

**B10 · Voice uplink.** One `RTCPeerConnection` per session, signalled over the WS; mic
audio upstream only, no downstream video. This is an **integration** — a second ASR
implementation fails review. AC: mic → ASR → persona reply → client gesture, end to end;
VAD drives `user:speaking`/`user:silent`; declining mic leaves every other channel working.

**B15 · Vision.** Server re-checks the 768 px cap, runs the configured model, returns
`{text, intents[]}` with intents whitelist-checked server-side. AC: p95 ≤3 s local;
**retention test proves nothing is written to disk or logs**; cancelling client-side
consent mid-flight aborts the ask.

**B16 · Curiosity.** Scoring is pure functions (`+0.15` engaged / `−0.10` short-or-negative
/ `×0.98` daily decay / clamp [0,1]); the scheduler consumes events only. Hard mutes:
`user:speaking`, `attention ≥ 0.9`, meditation scenes, user opt-out. AC: unit tests for
scoring, decay, budget and every mute as a **negative assertion**; a seeded memory
produces a relevant proactive question at the next polite opening; exhausting the
per-session budget silences initiative for the rest of the session.

**B17 · MCP tools.** `search_animations`/`get_animation` read-only;
`play_animation`/`queue_sequence`/`set_mood`/`set_scene` autonomous; anything touching
capture or vision `confirm` **and** requires an active client consent state. AC: an MCP
client runs a 3-clip queued sequence on the live avatar; no live session → clean error;
killing the tool server has zero effect on local avatar behaviour.

**Definition of done, every batch:** `pytest` green including the pre-existing suites;
`avatar.enabled=false` proven inert; only the files listed for that batch touched;
rollback = revert the PR or delete `backend/app/avatar_director/`.

---

*Companion to the client-side plan; spec v1.1 §§4B, 5.P6–P12, 6.9–6.14.*
