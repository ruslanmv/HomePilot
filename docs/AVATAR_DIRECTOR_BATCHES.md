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
| **B15** ✅ | Vision — `avatar_director/vision.py`, `POST /avatar/vision/insight`, model adapter via the existing model runner | B8, client B11 | `app/multimodal.py`: one optional `image_b64=` argument |
| **B16** ✅ | Curiosity Engine — `avatar_director/curiosity.py`, interest records as new LTM categories | B8, client B9 | `app/ltm.py`: one entry in `VALID_CATEGORIES` |
| **B17** ✅ | MCP `avatar_control` tool server registered through Context Forge | client B9 | Context Forge tool-server registry: one new entry |
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

**B15 · Vision — landed.** 46 tests across `test_vision.py` and
`test_vision_retention.py`.

**Retention is 0 because there is nowhere to put a frame.** Not a policy on top of a store —
there is no store. `vision.py` contains no `open(`, no `Path(`, no `tempfile`, no
`upload_path`, and a test asserts each of those absences against the file. The behavioural
half runs a real request against a stubbed model with `open`, `Path.write_bytes`,
`Path.write_text` and `os.replace` patched **process-wide** and the root logger captured:
the observation is deliberately broad, because checking that *this* module does not write
would prove nothing about the module it calls. A recognisable needle is baked into the test
frame, and the assertions are that neither disk nor logs ever saw it — including on the
error path, which is where a frame usually ends up in a log attached to a traceback somebody
added while debugging. Planting a cache, a log line and a debug dump fails five of them.

What is *not* claimed: that a hosted model provider stores nothing. That is somebody else's
disk, which is why §6.2's default is a local model.

**One touched file, and the reason.** `app.multimodal.analyze_image` resolves an image *from
disk*, which is precisely what must not happen here — so it gains one optional `image_b64=`
argument that skips resolution entirely. Every existing caller passes a URL and is
unaffected. The alternative was a second Ollama call in `vision.py`, which is sixty lines of
payload construction that would drift from the one that owns model resolution and the
prompts. The batch plan said "Touched: none"; this is the amendment, taken rather than
silently.

**The size cap is read, never decoded.** §6.13 caps input at 768 px and says the server
re-checks. Decoding a hostile 20000×20000 JPEG to discover it is too big *is* the attack, so
the dimensions come out of the JPEG SOFn / PNG IHDR header — a few dozen bytes, nothing
allocated. A test asserts a huge declaration costs no more than a small one. An oversize
frame is refused rather than resized: the client already caps at 512 (§6.2), so one arriving
over the server's limit means the client is wrong, compromised, or not the client.

**Intents are whitelist-checked with B10's splitter**, not a second parser with a second idea
of what is allowed. The vision prompt asks for §6.8's tag, `split_emote_tags` pulls it out
and drops anything outside §6.2, and at most one survives. The client checks again on
arrival — belt and braces, as §6.9 intends.

**`vision_ask` over the socket answers three refusals and nothing else.** Vision off →
`vision_unavailable`. No client capture consent → `vision_no_consent`, checked first,
because §6.14 makes consent a precondition of *asking*. Consent live → `vision_use_endpoint`,
because §6.9 sends the frame as a data-channel message and B10 shipped transcript mode
rather than WebRTC, so no bytes can reach the server that way. Accepting an ask that can
never be answered would be the worse choice. Consent itself arrives as `user_event`
`capture:start` / `capture:stop` — no new message type, because "something happened on the
client" is exactly what that type means.

The endpoint is mounted **only when a model is configured**. A route that answers every
request "not configured" looks like a feature to anything probing the API surface.

On p95: the wrapper's own cost — decode, size check, tag split — is measured at well under a
hundredth of the 3 s budget. The model's latency is the deployment's hardware and no test
here speaks for it, which the test says in as many words.

**B16 · Curiosity.** The uplink's `voice_state` and the client's `user:speaking` /
`user:silent` are the mute signals this batch needs; both exist as of B10. Scoring is pure functions (`+0.15` engaged / `−0.10` short-or-negative
/ `×0.98` daily decay / clamp [0,1]); the scheduler consumes events only. Hard mutes:
`user:speaking`, `attention ≥ 0.9`, meditation scenes, user opt-out. AC: unit tests for
scoring, decay, budget and every mute as a **negative assertion**; a seeded memory
produces a relevant proactive question at the next polite opening; exhausting the
per-session budget silences initiative for the rest of the session.

**B16 · Curiosity — landed, machine half.** 65 tests across `test_curiosity.py` and
`test_curiosity_etiquette.py`.

**Records live in the memory that already exists.** One new `interest` entry in
`ltm.VALID_CATEGORIES`, and `InterestStore` is a thin adapter over `app.ltm` — no table, no
migration, no cache. The store tests run against a **real sqlite database**, because "not a
parallel store" is a claim about the actual store and a mock would prove only that this
module can call a mock. One of them asserts the schema contains exactly one table and it is
not ours; another calls the existing `forget_all` and watches the interests go with it,
which is the property that makes this worth insisting on — a parallel store is a second
place a user's data hides from the delete button they already have. `build_ltm_context`
walks an explicit category list that `interest` is not on, so the addition changed no
existing behaviour, and there is a test for that too.

**Scoring is pure functions**, and a test reads their source to keep them that way: no
`time.`, no `self.`, no store, no logger. The deltas, the ×0.98 and the clamp are the
spec's, named rather than inlined so a reviewer can diff them. Decay is continuous in days
rather than a daily step — a step makes a topic touched at 23:59 and again at 00:01 lose a
whole day, which is how a companion quietly forgets something mentioned yesterday.

**The scheduler consumes events only**, asserted by reading it for `Timer`, `Thread`,
`sleep`, `create_task` and `asyncio`. It is fed `ctx` and `user_event` — what the session
already reports — and asked whether now is a moment. It returns a *subject*, never a
sentence: §6.12 leaves the wording to the persona LLM, and keeping generation out means no
code path can phrase something into existence past a mute.

**Every mute is a negative assertion.** All four of §6.12's, each with the event fired, an
initiative requested, and a failure if anything comes back — plus the edges (just under the
attention threshold she may; the non-silent scenes are not silenced; opting back in works)
because a mute with no edge is a mute nobody can reason about. Mutes are checked *before*
the budget, so a muted session does not spend budget it was never going to use. Turning off
any one mute fails between three and six tests.

**Three bugs the tests and the replay found**, worth listing because none was arithmetic:

1. `user:silent` both clears the speaking flag and is the companion profile's commonest
   opening. Written as an if/elif chain, the first reading swallowed it and the most
   frequent polite moment in the whole system never arrived.
2. Argmax over a set that does not change between openings picks the same topic every time.
   The first replay had her ask about the aquarium at 0:15, 2:30, 7:10 and 15:00. The
   scheduler now remembers what it asked and falls silent rather than repeating itself.
3. She opened the evening fifteen seconds in with "Mum's scan results are due this week" —
   the highest-curiosity thread, correct by every other rule, and a terrible thing to be
   greeted with. `curiosity.min_session_age_ms` (120 s) is the answer, and it exists because
   the replay showed it rather than because the spec asked.

**The human half is not done.** `python -m app.avatar_director.curiosity_review` replays a
twenty-minute session and prints every moment she would have spoken, the opening that
licensed it, and what the user was doing at the time. A test can prove she was never *muted*
when she spoke; whether the moment *felt* right is a judgement about tone and timing that
belongs to a person. Current output is four initiatives — 2:30, 7:10, 15:00, 16:30 — on four
different topics, none during the film, the phone call or the meditation.

**Open — a reviewer has not yet sat the session.** The AC asks for a person to run the
twenty minutes and report. That has not happened, and no test in this repo stands in for it.
A reviewer's verdict belongs here, signed.

**B17 · MCP tools.** `search_animations`/`get_animation` read-only;
`play_animation`/`queue_sequence`/`set_mood`/`set_scene` autonomous; anything touching
capture or vision `confirm` **and** requires an active client consent state. AC: an MCP
client runs a 3-clip queued sequence on the live avatar; no live session → clean error;
killing the tool server has zero effect on local avatar behaviour.

**B17 · MCP tools — landed.** 40 tests. Nine tools, one per row of §6.14's safety table, and
the bridge implements exactly that set — a tool without a row would run at the default level
by accident rather than by decision, and a row without a tool is a promise nothing keeps.
Both directions are asserted.

**Paths.** The plan named `backend/app/avatar_director/tool_servers/avatar_control/`. The
repository's actual convention is `agentic/integrations/mcp/<name>/app.py` plus a
`<name>_server.py` entry point — where the other twenty-odd `hp-*` servers live, and what
`sync_service._CORE_SERVERS` points at. Following the repository over the plan, as with
`avatar_director` vs `avatar`. The registry entry is one line: `hp-avatar-control`, port 9121.

**Tools name intents, never clips.** §6.14's bridge invariant, and the decision everything
else follows from. `play_animation` sends an *intent*; the client's Tier-1 selector chooses
which of the thirty-one dance clips that becomes, against the live mood and anti-repeat,
exactly as a parsed `[[emote:…]]` tag would. A test confirms a real clip id cannot be
smuggled through the intent field. Intents carry `source: "tool"` — not `"user"` — so §6.5's
NSFW gate holds against them.

**Capture needs two yeses.** `confirm` (the operator, through Context Forge) *and* a live
capture consent on the client. Approved-but-no-consent is a refusal with nothing sent, and
revoking mid-session closes the door again; both are negative assertions. Turning off the
client-consent check fails three tests; the confirm check, one.

**"Killing the server changes nothing locally"** is an architectural claim, checked as one
rather than by killing a process a test runner does not have. The bridge holds no avatar
state (asserted against its own `vars`), decides no timing (no `sleep`, `delay`, `duration`
or `wait` in the class), and reaches the session through exactly one method — established by
asking which methods' source mentions the outbox rather than by counting the word. The MCP
process itself is one `httpx` call per tool with no state at all. It is a caller, not a
component.

**One writer on the socket.** `control.py` is pure — importing it pulls in neither FastAPI
nor `httpx` nor the session module, asserted in a subprocess. Tool calls queue on the
handler's `outbox` and the transport drains it four times a second, so a queued gesture does
not wait fifteen seconds for the next heartbeat.

**The catalogue reads the client's manifest and does not copy it.** `AVATAR_KB_MANIFEST`
names the file; the knowledge base is authored in the client repository alongside the assets
it describes, and a copy here would give two answers to "what can she do". With no manifest
the two read-only tools refuse **by name** — a search that quietly returned nothing would
read as "she can't dance". Search is substring over descriptions, tags and intents,
deliberately *not* a second copy of the client's TF-IDF selector: searching a catalogue and
choosing a clip for a moment are different jobs.

**The standalone client-side server stays documented, not written.** `mcp-server/README.md`
in the client repository specifies it exactly — the same nine tools, the three rules it may
not relax — and says why it is a specification rather than code. Its only use is an install
with no HomePilot at all, and writing an unused optional layer to demonstrate that the layer
is optional is the wrong trade. All three acceptance criteria are met by the registered path.

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
