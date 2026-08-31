# Avatar Director — HomePilot server lane (batch plan, spec v1.1 + addendum v1.2)

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
| new tool-approval flow for the embodied assistant (UC-12) | `backend/app/daypilot_bridge/` — **propose-only** mode: the persona proposes structured ops in `x_directives`, an Approval Center gates every external write | Reuse that contract verbatim. UC-12's "act = *confirm* unless the owner sets autonomous" is this, already built |
| new calendar/agenda source (UC-12) | `agentic/integrations/mcp/personal_assistant_server.py` exposes `hp_personal_plan_day`; the Forge seed catalog ships `hp-google-calendar` and Microsoft Graph mail/calendar | The agenda has a real source on day one; the server side of UC-12 is a `display` emitter, not a new integration |
| new store for focus streaks (UC-16) | `ltm.py` upserts on `(project_id, category, key)` | One more LTM **category**, same additive path as curiosity records |

Route prefix `/avatar/*` is free (`backend/app/avatar/router.py` mounts at `/v1`), so
`/avatar/session`, `/avatar/rtc` and `/avatar/vision/insight` stand as specified.
Documented fallback if that changes: `/companion/*`.

Config lands as a new `avatar:` block only: `enabled:false`, `vision.model`,
`vision.max_image_px:768`, `frames.retention:0`, `curiosity.session_budget:4`.

---

## Server batches

| Batch | Title | Depends on | Touches existing code |
|---|---|---|---|
| **B0** ✅ | Ground truth: `docs/PATHMAP.md`, `avatar_director/config.py` (`AVATAR_*` env keys, all off), `backend/tests/fixtures/protocol/`, `backend/tests/avatar/`, additive CI job | — | nothing |
| **B8** ✅ | Session gateway — `avatar_director/{protocol,session,safety}.py` + `register()`, contract tests driven by the shared fixtures | B0 | `backend/app/main.py`: one guarded `register(app)` block, matching the `voice_call` pattern |
| **B10** ✅ | Voice uplink — `avatar_director/rtc.py`, signalling over the B8 WS, mic → existing `voice_call` turn path | B8, client B9 | nothing new |
| **B15** | Vision — `avatar_director/vision.py`, `POST /avatar/vision/insight`, model adapter via the existing model runner | B8, client B11 | nothing |
| **B16** | Curiosity Engine — `avatar_director/curiosity.py`, interest records as new LTM categories | B8, client B9 | nothing |
| **B17** | MCP `avatar_control` tool server registered through Context Forge | client B9 | Context Forge tool-server registry: one new entry |
| **B19** | Privacy audit, retention proofs, docs; `avatar.enabled` stays **opt-in** | all | docs |

### Addendum v1.2 — server work (after B19, each behind its own flag)

| Batch | Title | Depends on | Touches existing code |
|---|---|---|---|
| **B20** | `display` message type + panel payload validation (agenda, cards, tool results) | B9, client B12 | nothing — new message type, ignored by older peers |
| **B21** | Embodied HomePilot server half: agenda assembly over `hp_personal_plan_day` / calendar servers, actions through the `daypilot_bridge` propose→approve path | B20 | nothing |
| **B22** | Focus streaks as a new LTM category, recalled next session | B16 | nothing |
| **B28** | Adult gates — `avatar_director/verification.py`, `redaction.py`, `adult_ack` / `adult_verify_request` | B8, B16 | nothing |

Client-side counterparts live in the client repo's plan: the Behavior Director itself,
`SessionAdapter`, capture/consent and the Together activities are B1–B7, B9 and B11–B14;
`PanelRenderer`, the five activity plugins, the clip engine, `ConsentFlow` and
`adult.profile` are B20–B29.

Addendum config, new keys only: `avatar.adult.enabled: false`,
`avatar.adult.provider: "owner-attest" | "<plugin>"`, `avatar.redaction.enabled: true`.

---

## Acceptance criteria per batch

**B0 · Ground truth — landed.** `backend/app/avatar_director/` exists with its config
block only; `register()` deliberately does not exist yet and a test asserts that, so the
package cannot quietly acquire a mount point between batches. 18 tests
(`pytest tests/avatar -q`), zero pre-existing files touched, `backend/app/main.py`
untouched. Config defaults proven off, including the two that carry weight: `adult.enabled`
is never implied by `avatar.enabled`, and a malformed numeric env value falls back to the
safe default instead of being coerced.

**B8 · Session gateway.** Build the mock server and the contract tests from
`tests/fixtures/protocol/*.json` **before** the real endpoints. WS auth reuses HomePilot's
existing auth/pairing; heartbeat 15 s; unknown message `type` ignored (forward
compatible). AC: every §6.9 message shape round-trips; `avatar.enabled=false` → no route
mounted and no import executed (asserted); the existing suite stays green.

**B8 · Session gateway — landed.** 40 tests (`pytest tests/avatar -q`). The protocol is a
pure module (`protocol.py`) so the contract tests need no socket, which is what let the mock
and the tests come first as the plan requires. `session.py` only moves bytes.

The half worth its own test is **"imports nothing"**: `register()` imports the transport
*inside* the enabled branch, and `test_registration.py` asserts against `sys.modules`
directly, because that claim is the one that quietly stops being true the first time someone
tidies an import to the top of a file. `backend/app/voice_call` guards itself the same way —
this follows the house pattern rather than inventing one.

Two stubs refuse rather than lie: `vision_ask` answers `vision_unavailable` until B15 (a
client waiting forever on a reply that will never come is worse than a no), and
`adult_verify_request` answers `adult_unavailable` — a placeholder that answered "verified"
would be exactly the failure §16.2 forbids.

**Client B9 · landed, in the other repo.** The 3D-Avatar-Chatbot side of this protocol now
exists (`src/behavior/adapters/SessionAdapter.js`), so both peers are written against
`tests/fixtures/protocol/` and the fixtures have a second reader — a change to one repo's copy
turns the other repo's contract test red, which is the whole point of keeping them
byte-identical.

Two things settled there that the server batches inherit. Intents sent over this socket are
held to the client's own §6.2 whitelist and §6.5 gates, so nothing a server sends can name a
clip or bypass the NSFW rules — B16's curiosity and B17's tools should be written on that
assumption rather than expecting the client to trust them. And the client treats heartbeat
silence, not `onclose`, as the evidence a link is dead, because a stranded socket never
closes; the 15 s `ping` in `session.py` is load-bearing for that, not decorative.

**B10 · Voice uplink.** One `RTCPeerConnection` per session, signalled over the WS; mic
audio upstream only, no downstream video. This is an **integration** — a second ASR
implementation fails review. AC: mic → ASR → persona reply → client gesture, end to end;
VAD drives `user:speaking`/`user:silent`; declining mic leaves every other channel working.

**B10 · Voice uplink — landed.** 34 tests. The integration reuses three things and
implements none of them: `voice_call.turn.run_turn` for the turn, `voice_call.barge_in` for
cancellation, and `app.voice.providers.get_stt_provider` as the only ASR a media terminus may
call. `rtc.py` is a pure module like `protocol.py`, so every contract test above drives it
directly with an injected turn runner — which is the same claim in another form: an uplink
that had to know how a turn is run could not be handed a fake one.

**Two media modes, and the default is the one without WebRTC.** `voice.media = "transcript"`
means the client's own recogniser — which it already has, and which already handles Quest
via MediaRecorder — sends final text up. That is not a shortcut around WebRTC; it is the
shape `voice_call` was built for, and browsers having a recogniser is why. `webrtc` mode
terminates media server-side and needs a terminus object; B10 deliberately does **not** add
`aiortc` to `requirements.txt`, because whether a deployment wants the server holding audio
is a deployment's decision. With no terminus a WebRTC offer is refused as
`voice_media_unavailable`, naming transcript mode as the alternative — B8's refuse-rather-
than-lie rule, applied again.

**The tag split is not tidiness.** A `say` goes to the client's `speakText`, not through the
chat tag parser, so an `[[emote:…]]` left in the string is *read aloud*. `split_emote_tags`
strips it and turns it into an `intent`, whitelist-checked; a non-whitelisted name is dropped
from the gestures and still stripped from the speech.

Everything the uplink produces is marked `source: "voice"` — deliberately not `"user"`, since
§6.5 blocks NSFW for any intent whose source is not the user and a tag written by a model is
a model's tag whichever way the sentence reached it. The turn also carries
`X-HomePilot-Source: voice` into chat.

Barge-in is the one place where being an integration is visible in the behaviour: a second
final transcript while a reply is still coming cancels the first through `voice_call`'s
registry and **discards the reply that arrives anyway**, because answering a question the
user has already replaced is worse than not answering it.

**B15 · Vision.** Server re-checks the 768 px cap, runs the configured model, returns
`{text, intents[]}` with intents whitelist-checked server-side. AC: p95 ≤3 s local;
**retention test proves nothing is written to disk or logs**; cancelling client-side
consent mid-flight aborts the ask.

**B16 · Curiosity.** The uplink's `voice_state` and the client's `user:speaking` /
`user:silent` are the mute signals this batch needs; both exist as of B10. Scoring is pure functions (`+0.15` engaged / `−0.10` short-or-negative
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

**B20/B21 · Embodied assistant.** The server sends `display` panels; the client renders
them as a canvas texture on the virtual screen. Every action the persona proposes goes
through the existing propose-only bridge and its Approval Center — **a second approval path
is the one thing this batch must not build.** AC: "good morning" produces panel + spoken
summary + exactly one *confirm*-level tool call; a negative test proves no tool can be
invoked outside the persona safety layer; `assistant.panelMaxKb` is enforced server-side,
with oversized payloads rejected rather than silently truncated.

**B28 · Adult gates (server first, always).** `verification.py` answers
`adult_verify_request` with a signed, expiring, session-scoped `adult_ack` — the **only**
path by which `adultVerified` can become true anywhere in the system. Owner attestation is
the self-host default and **refuses to load on a multi-user instance**; distribution builds
must configure a real provider through `avatar.adult.provider`. `redaction.py` runs on every
memory write while `mode=='adult'`: warmth signals may persist ("prefers slow pacing"),
explicit detail may not. AC: the §16.7 invariants are written as tests **before** the
feature — no client path sets `adultVerified`; curiosity, vision and MCP sources can never
select nsfw content; redaction fixtures pass; with `avatar.adult.enabled=false` the tier is
invisible in the UI and unactivatable over MCP or the session channel.

**Definition of done, every batch:** `pytest` green including the pre-existing suites;
`avatar.enabled=false` proven inert; only the files listed for that batch touched;
rollback = revert the PR or delete `backend/app/avatar_director/`.

---

*Companion to the client-side plan; spec v1.1 §§4B, 5.P6–P12, 6.9–6.14 and addendum v1.2
§§13–17.*
