# MeetingSense — changelog

What changed, when, and why — one entry per batch of
[`design/MEETINGSENSE_BATCHES.md`](design/MEETINGSENSE_BATCHES.md).

> **Written late, and worth saying so.** §0 of the batch plan asks each batch to finish with a
> changelog entry. HomePilot has no repository-wide changelog and never has, so nine batches
> closed without one rather than inventing a repo convention mid-feature. This file is the
> backfill, reconstructed from the commits; entries from MS9 onward are written as the batch
> lands. The rule now has a file to point at.
>
> The reconstruction is honest about its limits: each entry below is what the commit and the
> tests say, not what anybody remembers.

Every batch ships behind flags that default to off. With `MEETINGSENSE_ENABLED` unset, none of
this is reachable and no table is created.

---

## Fixes

### The LangGraph engine did nothing at all · `81fe3e2`

- `StateGraph(dict)` → `StateGraph(MeetingAgentState)`, and `_bind` now returns the node's
  **partial update** instead of the whole merged state.
- **This was a production bug, not a test bug.** LangGraph derives its channels from the state
  schema. A bare `dict` declares none, so every node ran, every node returned its update, and
  every update was dropped — the graph completed, the state came back exactly as it went in,
  and nothing raised. On any install with `langgraph` present and `MEETINGSENSE_AGENT` on, the
  agent produced no frames, no notes and no answers, silently.
- **It was red in CI for thirteen commits and I did not look.** MS23's headline acceptance test
  — the walker and LangGraph produce the same state — is correctly written and `pytest.skip`s
  when langgraph is absent. It is absent in this sandbox and present in CI, so it skipped on
  every local run and failed on every CI run. The local suite reported "1 skipped" throughout
  and I read past it. Reporting a batch's acceptance as met from a run where its acceptance
  test was skipped is the mistake here; the test was never the problem.
- Same shape as MS15's chromadb bug, and the second time in this programme: a behaviour that
  depends on which optional package the machine has. The difference is that the chromadb one
  only made tests lie, and this one made the feature not work.
- Verified by installing `langgraph` locally and reproducing all 35 CI failures exactly, then
  fixing until `tests/meetingsense` is **1058 passed, 0 skipped** — the zero matters, because
  the acceptance test now runs rather than skipping.

---

## W10 — Optional UI

### MS28 — finding a meeting again · `436173b`

- `meetingsense/catalog.ts` (every decision as a pure function), `MeetingFilter.tsx` in
  History, `MeetingLibrary.tsx` + `MeetingDetail.tsx` behind `MEETINGSENSE_CATALOG`, and
  `useMeetingCatalog.ts` so both surfaces share one fetch.
- **D5 was already decided, so the chip is the batch and the grid is the option.** "The catalog
  lives in History; a sidebar tab only if History gets crowded." The chip needs only the master
  flag; the tab is behind `_CATALOG`, which defaults off — a flag defaulting off *is* D5's
  condition made operable. Shipping the tab on would have overturned a recorded decision on a
  guess about a feature that has not finished its pilot.
- **A meeting is identified by the server, never by its title.** D5's note that the meeting
  message is the last message makes title-sniffing look viable; it is not, because the label is
  the *last* message and stops being the meeting's the moment anybody replies — which MS16
  exists to encourage. So the rows come from `GET /v1/meetingsense/meetings`.
- The tab needs **both** flags: MS0 made the sub-flags independent of the master, so
  `_CATALOG` alone would grow a nav item leading to a view of a feature that cannot run.
  Everything unknown is off.
- **The Teams grid and right-rail shapes are reused; the components are not.** Both are typed
  against `MeetingRoom` from `teams/types` — a *persona room*, with agenda items and
  per-persona speaking distribution. A MeetingSense meeting is a recording of real people. The
  two share the word and nothing else, and importing them would mean widening their types to
  cover both or handing them a lie.
- **Six mutation survivors, and the split was even.** Two were dead lines removed rather than
  kept — an empty-query fast path that `includes('')` already does, and a `.slice()` before a
  sort on an array `filter` had just created. Four were weak tests: the range boundary was
  never tested at exactly the boundary, the chip was only ever clicked while off, and — the one
  worth naming — the "refuses a non-numeric time" test passed for the wrong reason, because the
  fixture's timestamps made the bad subtraction come out *negative* and a different guard
  caught it. Its times are now chosen so the subtraction is positive.
- 65 vitest, 53 mutations each fail. Production build clean.

---

## W9 — Modes & voice

### MS27 — Coach, Practice, and the voice that reaches the call · `b63be99`

- `agent/coaching.py`, `agent/practice.py`, `agent/voice_out.py`, `VoiceSetup.tsx`, a mode badge
  on the pill and a sentence per mode in the consent sheet. Behind `MEETINGSENSE_MODES`.
- **The refusal is the batch.** The row asked for "an explicit test that Coach never receives
  screen OCR text", with the reason attached: §E.2's refusal is only real if enforced. It is
  enforced three ways — an allow-list in `context()`, a `scrub()` that drops anything carrying a
  slide's fingerprint, and a source test that fails if the module so much as mentions a
  keyframe. Three gates because the failure is silent, nothing looks wrong, and the people it
  affects are not in the room. **Verified by breaching it**: adding one keyframe read to
  `context` trips three independent tests.
- **Coach with no prep material says nothing at all.** Improvising from the transcript is the
  thing the mode is defined as not doing.
- Prep material has the only **real delete** in the store. MS24's approvals and MS26's queue
  record a withdrawal, because those are a history of consent; a user's own brief is not, and
  "take it out" that leaves it in the database has not done what it said.
- Practice runs **through `voice_call/`**, not beside it: their `create_session` does the
  entitlement check, their `barge_in` registry refuses stale turn ids, and MeetingSense keeps no
  turn state of its own — a second answer to "is the assistant still talking" would disagree
  with the first exactly when it mattered. The resume token is not echoed back into a meeting
  frame, per `create_session`'s own docstring.
- Voice out is **desktop only and says which "no" it is** — `browser` (wrong app, nothing to
  install would help) or `no_virtual_device` (right app, missing driver, here are the steps). It
  never falls back to the speakers: a rehearsal partner audible in the room but not in the call
  is a feature that appears to work and does not.
- The TTS tier stays `get_tts_provider`'s choice. A MeetingSense-specific voice selection would
  be a second place deciding what a user is entitled to.
- **Eleven mutation survivors, and they split cleanly.** Seven were a lifecycle I had simply not
  tested — prep attach/cap/budget/delete — which is what happens when a batch has one dramatic
  requirement and a quiet one beside it. Two were assertions weaker than the claims above them:
  the mode badge was asserted to be *inside* the live region when the claim was that it is
  *announced* (the meter is inside it too, and is `aria-hidden`), and the browser refusal was
  tested without `onCheck` wired, so it never showed that a browser is offered no retry that
  cannot work. Two were dead guards, removed rather than kept.
- 83 pytest + 23 vitest; 47 and 21 mutations each fail.
- **Five rows added to the manual matrix (17–21), and 18–20 are unreachable by any test**:
  whether audio arrives in somebody else's meeting is a question about two drivers and a
  conferencing app. The matrix is still entirely unsigned.

### MS26 — Participant and Presenter · `0be6c6a`

- `agent/mode_prompts.py`, `agent/participant.py`, `agent/presenter.py`, and **two new columns
  on `modes.py` rather than two branches in the graph** — `addressed` (answers to its own name)
  and `queues` (collects for the user), plus a per-mode `triggers` set deciding which of MS25's
  chips a mode offers.
- **`addressed` is not `proactive`**, and Participant is the first mode with one and not the
  other: being spoken to is a prompt, speaking unbidden is not. **`queues` and `addressed` are
  exclusive**, which is why Presenter has neither `addressed` nor a `question` chip — while the
  user is presenting, an assistant answering the floor out loud is the one thing the mode
  exists to prevent.
- Answering to your own name and drafting for the user's are opposites in one file. The line
  between them is a name, so names are declared at `start` and never guessed; with none
  declared nothing fires, a name matches as a whole word ("Ana" is not in "analysis"), and a
  one-letter name is refused.
- A mode's framing layers **above** `ASK_SYSTEM`, never in place of it: "cite the timestamp"
  and "never invent one" are not a Participant's to relax, and last position in a system prompt
  is the one a model weights hardest. With no mode set the prompt is byte-identical to MS13's.
- **A behaviour MS25 had, deliberately narrowed**: the `question` chip is now Participant's and
  above. Note-taker offers the note-taking chips and not the shoulder tap, which is what "says
  nothing unless asked" has to mean if it means anything.
- **Three real defects, all found by the e2e fixtures rather than by the units.** `chips.frame`
  dropped `draft` on the floor, so the whole drafting path worked and delivered nothing. A
  question naming the assistant was answered *and* chipped, putting two answers on screen for
  one question. And pacing compared the clock against a section's *end*, so the first minute of
  a ten-minute section read as "eight minutes ahead" — a section is a window, not an instant.
- **Twenty-four mutation survivors, and the lesson was the shape of the suite.** The e2e
  fixtures prove the modes *disagree*; they pass as long as the whole disagrees somewhere, and
  every part of MS26 has a rule no amount of end-to-end agreement would notice breaking.
  `test_modes_units.py` is those rules, one at a time — after which every survivor died.
- 91 tests over two files, 55 mutations each fail.

### MS25 — chips, and the order of ask-before-acting · `1919efc`

- `meetingsense/chips.py` (five deterministic triggers, no model), `ChipRow.tsx`, a `chip` /
  `chip_result` pair on the wire and a `chip_action` frame going the other way. Behind
  `MEETINGSENSE_MODES`, default off.
- **The negatives are the batch.** A chip interrupts, so it is tested twice: once for the
  sentence it exists to catch and once for the sentence that looks like it. `monday.com` is not
  a weekday, `example.com/2026-04-20/notes` is not a deadline, "so we're going with the second
  option?" is not a decision, "so Ana will send the terms?" is not a commitment, and "does that
  make sense?" is not a question aimed at anybody.
- **An id crosses the wire, never a chip.** The server keeps what it offered, so what runs is
  what was shown; a body on the wire would let the page rewrite the arguments between the offer
  and the acceptance. The addon never sends one and the server ignores one sent anyway.
- Three gates on `accept`: the chip has a proposal, the **runtime tool router** resolves the
  capability (never a second allow-list), and MS24's approval covers the **resolved tool id** —
  checked after the router has spoken, because approving a capability name approves whatever
  the catalog currently maps it to.
- **Eleven mutation survivors, and the two that mattered were both about unreachable code.** A
  broad `try/except` inside `detect` was swallowing the "not a segment" guard *and* would have
  swallowed a genuinely broken trigger; detection is pure, so the handler was removed and the
  caller's own guard is the only one. And a "chip is renderable" check inline in a closure could
  not be called at all, so it became `usable()` and is now tested with the chip no trigger
  builds.
- Two more were tests describing the wrong thing: the dismiss button was asserted to exist
  rather than to have a name a screen reader can use ("×" passes axe and reads as "times"
  three times in a row), and the hook re-implemented `mergeChip`'s own id guard — one
  implementation now, tested where it lives.
- 86 pytest + 31 vitest, 44 + 34 mutations each fail.

### CI — the vector store the tests were reading from · `a952e98`

- Not a batch. `tests/meetingsense/test_retrieval.py` had three tests asserting "this install
  has no vector store" **by not passing one**, and `retrieval._client()` falls back to the real
  Chroma client. `backend/requirements.txt` pins `chromadb>=0.4.0`, so those tests described a
  developer's laptop and failed in CI, where the deletion reached a real store and correctly
  reported `index_cleared: True`.
- Fixed as a category rather than three tests: `tests/meetingsense/conftest.py` makes "no store"
  the deterministic default for the suite, so the next test written the same way cannot fail in
  CI for a reason nobody connects to this one. Every test that wants a store already says so.
- The stub could hide a `_client` that had stopped calling `get_chroma_client` at all, so the
  real function is handed back through `unstubbed_client` and three tests exercise the fallback
  directly.
- **A marker would have read better and would not have worked.** `pytest_configure` runs only
  for the *initial* conftest files: under `pytest tests/meetingsense` this one is initial and a
  marker registers; under CI's `pytest -q` from `backend/` it is not, and the marker silently
  never registers. A fixture resolves identically under both.
- Verified by simulating CI locally — with `get_chroma_client` returning a working store, the
  suite is 882 passed either way; before the fix, two failed.

---

## W8 — Engine

### MS24 — two sub-agents, and what a meeting has approved · `feefa57`

- `agent/subagents.py`: **SlideReader** (a captioned keyframe → title, claim, ≤3 topics; a
  re-shown slide is a *return*, not a second reading) and **ActionExtractor** (a transcript
  window → proposed owners and deadlines, capped at five). Neither writes anything — `reflect`
  folds proposals in through MS12's `merge`, which never deletes.
- **The mode is server state.** `resolve_mode` reads it back from `ms_artifacts` on every turn;
  a `mode` arriving with a turn is a *default* for a meeting nobody has set, and when it
  disagrees with what is stored the stored one governs and the client is told. A per-turn mode
  on the wire is not a mode, it is an escalation.
- **Two gates, two questions.** A mode says whether tools may be used at all; a per-meeting
  approval says which. Both closed by default: `approved_tools=None` is a `Deps` nobody filled
  in, and `act` reads it exactly as it reads `[]`.
- **Nine mutation survivors, and every one was a real hole.** The two that mattered most:
  `test_re_approving_after_a_revoke_works` asserted on `approve`'s *return value*, which is
  computed — so a replay that made a revoke permanent passed the test and would have been wrong
  on the next turn; and the unreadable-store test asserted on the whole turn, where `perceive`'s
  own belt turns any failure into the floor, so it passed just as happily when `resolve_mode`
  crashed as when it decided. Both now assert on the thing that makes the claim.
- A third: the fenced-JSON test was killed by removing the fence handling entirely, because the
  bare-brace fallback found the same object. The fixture now has prose *after* the fence, which
  is what a model told "JSON only" actually returns, and a greedy scan swallows the sign-off.
- **One real defect, found while wiring:** `_merge_actions` imported `_key` with two dots from
  `agent/nodes/`, which resolves to `agent`, not `meetingsense`. Every extraction raised
  `ModuleNotFoundError` and was swallowed by the "a proposal is never worth the notes" guard —
  so the feature was silently doing nothing and the suite was green until a test looked at the
  merged frame.
- **A test I had written too wide, corrected rather than kept:** `TestMemoryStaysOutside`
  forbade any write under `agent/`, and MS24's approval log is a legitimate write — policy a
  person set, recorded by the code that set it. The claim is that *no node decides what is
  stored*, so the grep is scoped to `nodes/` + `graph.py` and is now backed by a behavioural
  test that a full Practice turn with every dependency wired writes nothing.
- 45 tests, 42 mutations each fail. `tests/meetingsense`: 793 passed, 1 skipped. Full backend
  baseline unchanged — 248 failed / 3163 passed on a clean tree, 248 failed / 3209 passed here.

### MS23 — the LangGraph engine · `622ca0d`

- Eight nodes (`perceive reflect decide answer coach act recall deliver`), one conditional edge,
  five modes, behind `MEETINGSENSE_AGENT` (default off).
- **The acceptance is the headline test**: the fixed loop and the graph are driven over the same
  recorded events with the same stubbed engine and compared frame for frame *and* on how they
  drive the engine (`run` count, `force` flags). A third test reads the source of
  `session._maybe_notes`, so the loop this suite copies cannot drift from the one that ships.
  That comparison is only possible because D8 kept memory outside the graph.
- **Two schedulers, one set of behaviour.** The topology is data; LangGraph executes it where
  installed and a twenty-line walker where not. `langgraph` is in `requirements.txt` but
  `langgraph_personas/graph_builder.py` imports it at module scope, which is why its whole suite
  is one of the eighteen that cannot be collected here — and a graph that cannot be imported
  cannot be tested.
- **A real gap the tests found:** a `slide` event routed to `answer` with nothing to answer. The
  caption is now the question, and an uncaptioned slide plans nothing.
- **Four mutation survivors were all unreachable guards** — `act`'s tool check, `coach`'s
  permission check, note-taker's `recall=False`, and `MAX_STEPS`. Each was kept and is now
  tested by calling the node directly with the state the router would never build: that is what
  a second gate is *for*, and it is what holds when the first gate is edited.
- 41 tests, 19 mutations each fail.

---

## W7 — Capability

### MS22 — Forge registration, and the Teams decision · `dd92397`

- `hp-meetingsense` / 9107 registered in all four places that need it: the Forge seeder, the
  gateway list, the server catalog (marked `write_gated`) and the virtual servers
  (`hp-meetings-readonly`, `hp-meetings-all`). The read-only bundle's exclusion list is built
  from the server's own tool definitions in a test, so a fifth write tool cannot quietly
  appear in a suite named read-only.
- **Chief-of-Staff** asks `hp.ms.search` when a question is about meetings and puts the answers
  in their own bullet — meeting rows carry a citation and workspace hits do not.
- **Teams tier 2 is deferred, not built** — the second option the row offered. The `hp-teams`
  catalog entry already declares an *external* source, and a local server behind the same id
  would put two implementations behind one identifier.
- **Marking it only mattered because something now reads the mark.** The catalog loader
  dropped unknown keys, so `availability` and `unavailable_reason` were added to `ServerDef`,
  are always present in the API, and `install()` refuses with the reason. Without that the
  tile looked like every other one and failed on a timeout while starting a process for a
  module that is not there.
- **The tools were renamed `ms.*` → `hp.ms.*` here.** `test_agentic_health.py` requires every
  Forge tool prefix to start with `hp.`, which is what stops a virtual server's allow-list from
  admitting a namespace nobody registered. MS21 shipped the design document's `ms.` shorthand;
  a tested repo-wide invariant beats it, and the `ms` segment stays so the names still read.
  Caught by the full-suite baseline check, not by either batch's own tests.
- **The acceptance is not fully met and is not claimed to be.** `make test-mcp-servers` is
  red: `tests/test_mcp_servers.py` is entirely `async def` with no asyncio plugin configured
  and fails 164/164 on a clean tree. It is one of the 18 pre-existing failures and outside
  this batch.

### MS21 — the MCP server · `ed38c7f`

- `agentic/integrations/mcp/meetingsense_server.py` on **9107**, ten `hp.ms.*` tools, in
  `docker-compose.mcp.yml` and the Makefile (`start-`, `stop-`, `health-meetingsense`).
- **The transport is HTTP, not an in-process import** — a deliberate change from what the
  batch row implies. The MCP image contains `agentic/` and no `backend/`, so importing the
  meeting store would have worked from the Makefile and failed in every container. Four
  backend routes were added to make one transport possible: `GET /meetings`, `GET /search`,
  `GET /conversations/{id}/live`, `POST /{id}/notes`.
- **Reads open, four writes gated**, with `local-notes`' exact wording so an operator
  recognises the refusal and knows which variable to set.
- The tests run the **real backend router** behind an httpx ASGI transport rather than a stub:
  a tool naming a route the backend does not serve is the bug this batch can introduce, and a
  stub would answer it happily.
- **Two weak tests found by mutation:** the transcript cap was exercised on a two-segment
  fixture so it never bound, and an unknown mode was refused by the *backend's* 400 either
  way — the client-side check exists to hand the agent the list of modes, so the test now
  asserts the message rather than only the refusal.
- Written with sync tests. `test_mcp_servers.py` is entirely `async def` with no asyncio
  plugin configured and fails 164/164 on a clean tree — one of the 18 pre-existing failures,
  and a blocker for MS22's "make test-mcp-servers green".

---

## W6 — Together

### MS20 — the card on the avatar surface · `8640ad4`

- New `panel.py`: the same store rows become a `display` message of the existing `cards`
  kind — a third renderer, not a third source — and a `meeting_panel` frame on the avatar
  session asks for one.
- **A summary projection, never the transcript.** A 400-segment meeting arrives as what it is,
  what was decided, what is still open, what is on screen, and at most the last two lines so a
  live panel does not look frozen.
- **The row cap is read from `panels.MAX_ROWS`, not retyped**, so a change to the renderer's
  cap cannot leave this sending panels that get refused. Cards truncate from the end, so the
  header is dropped last and the first rows do not reshuffle as the meeting grows.
- A panel the channel refuses is dropped, not escalated: the meeting records either way, and a
  card that could not be drawn is not a reason to send an error into a live session.
- **The first-occurrence trap again**, twice: two mutations aimed at `_panel` matched identical
  guard lines in `_audio` and `_stop` and survived. Unique anchors, and both real behaviours
  now have tests.

### MS19 — the eighth activity · `3b7af51` (avatar) + `51bff81`

- `meeting.js` joins the 👥 launcher. It cannot obtain a stream: no `navigator`, no media
  call, no canvas — asserted by reading its own source. The recorder is handed the grant's
  streams through a new `startWithStreams`, because a recorder that opened its own capture
  inside that page would be a second consent story for the same screen.
- `meeting` is a **compound consent source**: screen then microphone, in that order. A part
  declined, or resolving with no stream, grants nothing.
- **Revoking stops the recorder synchronously**, asserted with no timers at all. If the test
  needed one, the guarantee would be "soon" rather than "now".
- **Two pre-existing tests updated rather than worked around.** `capture.test.js` pinned
  `SOURCES` exactly and B11's docstring says adding a consumer should be a registration —
  MS19 is the first to take that offer. `composition.test.js` caught `meeting.js` publishing a
  global `boot.js` never loaded, which is what it is for.
- **A real bug the tests found:** `stop()` released the grant *after* revoking, so its own
  consent listener still saw a live grant, announced a second stop and counted a deliberate
  stop as a revocation.
- **A harness bug worth recording:** two mutations aimed at `startWithStreams` matched the
  identical guard lines in `start()` instead — `replace(…, 1)` takes the first occurrence —
  and survived, because `start()`'s own guard had no test. Both are covered now, and the
  borrowed path uses distinct local names so an anchor cannot land on the wrong function.

### MS18 — the live context provider · `188ee7a`

- New `live_context.py`, and one optional `conversation_id` argument on
  `build_system_prompt`. Every existing caller omits it and gets a byte-identical prompt;
  `orchestrator.py`'s chat path passes it.
- **D9 tiers 1 and 2 only**, capped at 900 tokens — the same constant MS13 answers under, so
  there is one number rather than two that drift. Trim order: verbatim oldest-first, then the
  notes lists, and the recap never.
- The block tells the persona what it cannot see. Without that, a model asked "what did she
  say?" answers about the last thing in its own window — the chat — and invents a timestamp.
- **Two weak tests found by mutation.** The budget was asserted against
  `live_context.TOKEN_BUDGET`, so raising that constant passed; it is now asserted against
  900. And nothing covered the orchestrator seam, so the wiring could be removed with the
  suite green — now checked by reading the call, which is the right weight for a one-keyword
  claim.
- A separate hazard worth recording: a mutation that replaced the notes-trim body with `pass`
  turned the loop infinite, timed out past the harness's own limit, and was left in the source
  by a restore that never ran. Every subsequent run hung until it was found. Mutations that can
  spin need their own timeout inside the harness, not around it.

---

## Carried work

### MS12-a — the notes engine, actually connected · 3c592f0

- MS12 shipped an engine that was complete, tested, and **constructed by nothing**. `start`
  echoed `notes: true` straight back, `MeetingSession` drove a `notes=` engine correctly, and
  no route ever built one — so for four batches no meeting on any install produced a `notes`
  frame, and every client was told notes were on.
- One `engine_factory(config)` in `notes_engine.py`, wired into both transports. Two call
  sites building one each would be two places for this to happen again.
- **`ready` now reports whether notes are running, not whether they were requested.** That is
  the half of the bug that hid the other half: a server answering with the client's own
  question can be wrong indefinitely without anybody noticing.
- The tests go through a **real socket** and a **real avatar bridge** rather than the session
  core, because MS12's suite tested the engine, MS3's tested the socket, and the gap was
  between them.

---

## W5 — Memory

### MS17 — naming a meeting without asking · `d3facbe`

- New `metadata.py`: the shared window's title (free, from `MediaStreamTrack.label`) and a
  calendar event via MCP, both applied after `ready` as a background task and reported as a
  `meta` frame. Schema 4 adds `attendees` and `link`.
- **A title the user gave always wins**, and **an empty answer is not an answer** — the two
  rules that stop auto-metadata from being worse than nothing. `"Zoom Meeting"` yields no
  title, because writing it in makes every Zoom call in History look identical.
- **Two real bugs the tests found.** Markers matched as substrings read "Cisco Webex Meetings"
  — and any shared document called "Meeting notes" — as a Meet call; they now match on word
  boundaries. And a regex counts `_` as a word character, so "Webex_Meetings" matched nothing
  until underscores were normalised for matching.
- The name is the **longest** surviving part of a window title, not the first: Teams titles a
  call `"<speaker> | <meeting> | Microsoft Teams"`, and the first part is whoever happened to
  be talking when recording started.
- Auto-metadata may write four columns and no others. It is fed by a calendar event and a
  window title, neither of which the user typed, and a path that can set any column is one bad
  MCP answer away from rewriting a meeting's conversation or its retention mode.

### MS16 — binding, resume and branching · `bd16c01`

- `ms_threads` and `ms_artifacts` (schema 3), a new `binding.py`, and three endpoints:
  `GET /conversations/{id}` to bring a card back, `POST /{id}/thread` to branch, and
  `POST /{id}/attach` to push the transcript into a project.
- **The origin thread is recorded when a meeting starts, not when it stops.** A meeting
  interrupted by a server restart should still bring its card back, and nothing on a chat
  message says which meeting produced it.
- **The conversation route is declared above `/{meeting_id}`.** FastAPI matches in declaration
  order; a path parameter first swallows "conversations" as a meeting id and 404s every
  hydration — a bug that looks like a missing feature.
- **The brief is not the summary message.** The summary is written where the reader has just
  been in the meeting; the brief opens a conversation whose reader may be a week late, so it
  leads with what is still open and ends by saying the transcript is searchable.
- **Attach goes through `process_and_add_file`**, the function the project upload button
  calls, which is why it needs no new job type — asserted, because "we reuse X" is the kind of
  claim that quietly stops being true.
- **A hole found by mutation, twice over:** a section whose items all render blank still
  printed its heading. MS14's note sections had the identical bug and its guard was copied
  without its test.

### MS15 — embeddings and cross-meeting retrieval · `bd16c01`

- New `retrieval.py`. On stop a meeting is embedded — after `final`, so nobody waits on it —
  into a Chroma namespace of its own, and `ms_search(query, meeting_id?, k)` returns rows
  carrying their own `<title> · hh:mm:ss` citation.
- `vectordb.py` gained a `namespace` parameter whose default produces the byte-identical
  collection name it always produced, and `collection_name()` is now the single place that
  name is built — two copies of a naming rule is how a delete stops matching its create.
- **One collection filtered by `meeting_id`, not one per meeting**, which is a deliberate
  deviation from the batch row: both queries a per-meeting collection would serve are the
  global one with and without a filter, the delete runs filtered either way, and the second
  copy would double every index for no capability.
- **Both retrievers run, interleaved by rank.** Embeddings find the passage worded differently
  from the question; keyword finds the exact token somebody asked about. Interleaved rather
  than merged, because a cosine distance and a length-normalised term count share no scale.
- **Delete now clears three stores.** A meeting left in the index answers questions after the
  user deleted it.
- **Two weak tests, found by mutation:** the over-fetch before the verbatim filter and the
  time-order sort both survived their mutants, because in each fixture the retriever's scores
  happened to agree with the property under test. Rewritten so rank and time disagree.

---

## W3 — Eyes

### MS11 — desktop system audio · `e3e7937`

- `desktop/meetingsense-audio.js` + a `setDisplayMediaRequestHandler` registered from
  `bootstrap`, `preload.js` exposing `meetingSenseAudio()`, and a popover notice built from the
  shell's own answer. Flag off by default (`MEETINGSENSE_DESKTOP_AUDIO`, or
  `meetingSenseDesktopAudio` in the desktop store).
- **Windows only on Electron 33**, and the popover says so *before* recording starts. macOS has
  no public API for capturing system output; the hint names the virtual-audio-device workaround
  rather than stopping at "unsupported", because a user who believes the call is being recorded
  and finds out afterwards that it was not has lost the meeting.
- **"Off" and "not possible here" are two different messages.** Off on Windows is advice the
  user can act on; the same sentence on macOS would be advice that does not help, so it is not
  shown there.
- **Off means nothing is registered.** A display-media handler changes what every screen share
  in the app does, ScreenSense's included, so the flag-off build is byte-for-byte the old
  behaviour — asserted, not assumed.
- The module deliberately does not `require("electron")`: everything is injected, so the
  platform table is unit-tested in Node. "Manual QA on two machines" is not a test that runs in
  CI, and the decisions around loopback are exactly what a manual pass covers worst.

### MS10 — slides in the card · `8023b3d`

- `SlideStrip.tsx`: a strip under the transcript, and a lightbox joining a slide's caption to
  the transcript spoken while it was up. `mergeSlide` and `segmentsDuring` in `meetingState`,
  because the join is the claim of the batch and a renderer is the wrong place to test an
  interval boundary.
- **The join is half-open at the next slide.** A segment whose `t0` equals the next slide's
  timestamp belongs to the next slide — the words began as it went up — and a closed interval
  would file the opening sentence of every slide under the one before it. Attribution is by
  where a segment *starts*, so a sentence spanning a change appears once.
- **The server now announces a keyframe twice**: when it is taken, and again when the caption
  lands. The strip upserts on `id`. Without the first frame an install with no vision model
  has an empty strip for a meeting full of slides, and a slide that appears three seconds
  late looks like a slide that was missed.
- **A defect a test of my own found:** `mergeSlide` spread the incoming frame over the stored
  one, so a `caption: null` arriving out of order across a reconnect would erase a caption
  already on screen. Fields are now only overwritten by a value that says something.

### MS9 — the keyframe scheduler, and captions · `0e0281f`

- **Client** (`homepilot-meetingsense.js`, mirrored): a 500 ms sampler → 64×36 gray → dHash and
  a changed-pixel ratio; motion gate > 35 % *against the last capture*, 1.5 s stability, an 8 s
  floor, a 5 min heartbeat, and a rolling-hour cap. Keyframe → JPEG → `/upload` → `keyframe`
  frame. `start({ watch: true })` also keeps the shared **video** track when the share carried
  no audio, which it previously stopped.
- **Server** (`keyframes.py`): `analyze_image` with a prompt written for a slide, a dHash
  reused **within one meeting** so a re-shown slide is captioned once, refusal and length
  filtering, and every failure swallowed. Captioning runs as a task beside the frame loop;
  `stop` waits up to 8 s and cancels the rest.
- **The rule is change *plus stillness*, not change.** A slide flip, a scroll and a video all
  move most of the frame; only one of them then stops. That single observation is what the
  1.5 s window buys, and it is why the heartbeat requires stillness too.
- **Keyframes use the transcript's clock**, not `Date.now()` — MS10 joins slide to speech on
  that number, and two clocks would put the join a sentence out.
- **Three test holes that mutation testing found**, each of which had let a wrong
  implementation pass: a capture sequence that started at t = 0 could not tell a rolling hour
  from a calendar bucket (the bucket's cost is at its edge); a vision stub that never suspended
  was finished by any incidental `await` inside `stop`, so the drain could be deleted; and an
  `ok: False` answer with empty text was rejected by the *length* check, so the `ok` check
  itself was doing nothing.
- `hash = NULL` matches nothing in SQL but `hash = ''` matches every other empty one, so the
  guard against an empty hash is load-bearing in a way the SQL alone is not.

---

## W4 — Brain

### MS13 — asking about a meeting · `27e75d9`

- `ask.py`: the `ask` frame on the live socket and `POST /v1/meetingsense/{id}/ask` for ended
  meetings, both through one function. Three tiers — verbatim last 90 s, MS12's recap, top-k
  keyword retrieval (k ≤ 12) — with the verbatim window excluded from retrieval.
- **Trim order is D9's priority made executable:** retrieval first, verbatim second, the recap
  never.
- The frame reports the citations the answer *actually used* from what it was offered, so an
  invented timestamp is never presented as real.
- **The headline test passed for the wrong reason:** the two-hour fixture's segments did not
  match the question, so the prompt was small because retrieval found nothing — it passed with
  the budget *and* `k` removed.
- **A real scoring bug its own test caught:** normalising by *distinct* words made a segment
  repeating one word score highest in the meeting.

### MS14 — a self-sufficient summary, and deleting a meeting · `f537783`

- The summary message carries the recap, decisions, actions with owners and citations, open
  questions and a slide timeline, with thumbnails in `media.images` capped at 8. The chat path
  passes six messages, so this one *is* the meeting as far as a persona is concerned.
- **Per D4 nothing is enqueued.** Two tests hold it: one patches the jobs functions and asserts
  none fired, one greps the module for the word.
- `retention.py` + `DELETE /v1/meetingsense/{id}`: rows and owned files, reporting counts.
  **Retention does not modify deletion** — whatever was kept is removed.
- `session.stop()` forces the last notes window, or the final minute of every meeting is
  missing from its summary.
- **Two weak tests found by mutation:** a symlink does not separate `is_relative_to` from a
  string prefix check (a sibling directory named like the root does), and an empty list never
  reaches a section whose items all render blank.

### MS12 — rolling notes and the recap · `1e90e18`

- `notes_engine.py` + `prompts.py`. Trigger is a floor, not a schedule: 60 s **or** 400 words,
  and nothing pending is never due.
- **Deltas, not rewrites.** The merge happens server-side and never deletes; resolving marks a
  question so the card can strike it through.
- **D9 tier 2 is one signature:** `recap_messages()` takes the previous recap as a string, not
  a meeting id, so it cannot reach the transcript. The 120-word cap is enforced in code, not
  requested in the prompt.
- A citation the transcript cannot support is dropped while the observation is kept.
- **Found an MS6 bug:** `to_markdown` read `notes["json"]` while `store.get_notes()` returns
  the parsed object under `notes["notes"]`, so the Markdown export had been silently omitting
  its notes section. The MS6 test hand-built a shape the store never produces and passed over
  it.

---

## W2 — Reach

### MS8 — through OllaBridge · `27b6e15`, ollabridge `48520da`

- `/v1/meetingsense/status` gains **`remote_ok`** (`enabled AND ready AND flags.remote`) — one
  boolean rather than two flags for a client to combine, because the flags do not imply each
  other and a client guessing would offer a control the server refuses.
- With `MEETINGSENSE_REMOTE` off, avatar-session meeting frames are refused **per frame**, not
  only at start. The local WebSocket is untouched by the flag.
- In `ruslanmv/ollabridge`: the proxy's "it is a pipe" claim is asserted **in bytes** — up,
  down, a whole meeting in order, and over the cloud `sig`/`ev` relay — plus a test forbidding
  meeting vocabulary anywhere in the proxy. `/health` advertises `meetings`.
- **A test that could not fail:** the first audio fixture happened to be byte-identical to
  `json.dumps` output, so a mutant that re-serialised every relayed frame passed the whole
  suite. The fixtures now carry spacing `json.dumps` cannot reproduce.

### MS7 — the avatar-session transport · `75d7294`, 3D-Avatar-Chatbot `303b722`

- `meeting_start`, `meeting_audio`, `meeting_stop` and server `meeting` added to the avatar
  protocol's type sets. **`PROTOCOL_VERSION` stays 1** — §6.9's silent-ignore rule is what
  makes that safe, and a bump would have broken the avatar, voice and panels too.
- New `meetingsense/avatar_bridge.py`: a `Transport` over the handler's outbox, and a bridge
  that reuses MS2's core, MS3's `audio.py` and MS3's own `_handle_audio`. The two transports
  cannot answer differently because there is only one thing answering.
- The handler *queues* meeting frames rather than answering them: `handle()` is synchronous by
  design, and a meeting transcribes audio.
- **Cross-repo:** `backend/tests/fixtures/protocol/` is byte-identical to the copy in
  `ruslanmv/3D-Avatar-Chatbot`, held by `CHECKSUMS.txt`. Adding four frames turned that repo's
  contract test red until the same files landed there — the mechanism working, not an obstacle.
- **A parity test that failed for the right reason:** the two transports differed by one
  millisecond of `elapsed`. Fixed by injecting the clock, not by scrubbing the field.

---

## Carried work

### MS1-a — real timings from a remote endpoint · `97fc3e4`

- `OpenAICompatSTTProvider.transcribe_segments` asks for `response_format=verbose_json`;
  `supports_segments` is now true for that provider. Every install with `STT_BASE_URL` set had
  been producing `t1: None` on every segment.
- **A second call site, not a modified one.** `transcribe()` still sends the default format —
  changing it would alter a return value the voice call shares.
- `verbose_json` is documented, not guaranteed: every degraded shape falls back to one honest
  span rather than raising. **A segment the server did not time is skipped, never given
  `t0: 0`** — these get cited in notes.

---

## W1 — Recorder (local)

### MS6 — the live card, the pill, consent and export · `657f592`

- `frontend/src/ui/meetingsense/`: `meetingState.ts`, `MeetingCard.tsx`, `RecordingPill.tsx`,
  `ConsentSheet.tsx`, `useMeetingSense.ts`. Backend `export.py`, `finalize.py`,
  `GET /v1/meetingsense/{id}` and `/export?fmt=md|srt|json`.
- **Stop keeps recording.** Pressing it starts a ten-second undo countdown and only then sends
  `stop` — the seconds spent deciding are usually seconds somebody else was still talking.
- Segments keyed by `id` so a resume replay is invisible; a provisional line is the same
  element as the segment replacing it; new lines scroll into view only when the reader is
  already at the bottom.
- Export handles `t1: None`, which is *every* segment on a remote-STT install.
- **A finding that shrank the work:** HomePilot has no `conversations` table — History labels a
  conversation with its last message's content. So D5's auto-title needed no schema change; the
  meeting message is that last message and the title leads it.

### MS4-a — reconnect, level meter, backpressure · `63dffcd`

- Reconnect on 1-2-4-8 s backoff capped at 15 s, sending `resume` with the **highest** `seq`
  seen. `ms:reconnecting` / `ms:resumed`.
- `levels` (RMS per channel, polled) and backpressure shedding by **how much speech a chunk
  carries** rather than by age, reporting `behind_ms`.
- **Three test defects, all mine:** shed tests that put the near-silent chunk first (so
  dropping by age gave the same answer), a "gives up" test that never asserted the pill stops
  saying *reconnecting*, and leaked `addEventListener`s that counted each event once per prior
  test.

### MS3-a — resume on reconnect · `ada9408`

- A dropped socket **suspends** for `MEETINGSENSE_RESUME_GRACE_S` (default 120) instead of
  ending. `0` reproduces the old behaviour exactly, and a test pins that.
- Store gains `ms_meetings.suspended_at` and `ms_segments.seq`, added by `ALTER` when missing —
  without it a database created by MS2 would fail mid-meeting on its first resume.
- **A deliberate deviation from D10:** the server *does* replay. "The client already has it" is
  false for exactly the frames in flight when the socket died.
- **A test that could not fail:** `pytest.approx` on a Unix timestamp has a relative tolerance
  of roughly ±1700 s. Now on an injected clock.

### MS5 — the entry point · `1ee3227`

- The ScreenSense button gains a popover when MeetingSense is enabled, and is untouched when it
  is not — asserted as `outerHTML` byte-identical before and after.
- Every disabled control names its cause and its fix, with a stable id per state; a test greps
  the module for generic "unavailable" prose. axe-core over the healthy *and* degraded trees.
- **"Ask once" needed care:** ScreenSense's own click handler is still on that button, so one
  click would have both asked a question and opened the popover. Suppressed in the capture
  phase and re-fired by the popover's own button.

### MS4 — the audio capture addon · `6ee54ab`

- Mirrored addon pair, own `getDisplayMedia`/`getUserMedia`, separate gain nodes into a channel
  merger (**ch0 = call, ch1 = mic**, never summed), AudioWorklet → 16 kHz PCM16 20 ms frames,
  energy VAD with a 350 ms close over a 1 s floor and an 8 s hard cut.
- **Only the hard cut carries the 200 ms overlap.** The first draft carried it from every close
  and measured 140 ms: one ring buffer was doing two jobs, and the silence that closed an
  utterance displaced the frames the overlap was made of.
- **Outside the batch's scope:** `vitest.config.ts` had been excluding **17 test files and 124
  tests** — every `.test.js` and `.test.jsx`, the whole phone/call primitives suite included.
  They had never run in CI. The glob was widened; all 124 pass unchanged.

### MS3 — the local WebSocket transport · `15b2b24`

- `WS /v1/meetingsense/session` plus `audio.py`. Refuses flag-off the way the voice route does
  (accept, say why, close 1008) so a client can tell "disabled" from "server down".
- PCM16 gets a RIFF header server-side: headerless PCM named `.wav` has 44 bytes of speech read
  as a header, producing a garbled transcript rather than an error.
- A stereo frame is two transcriptions, one assembler each.
- **Two tests that hung instead of failing.** A test waiting on a frame the server never sends
  blocks forever; a CI timeout is a worse diagnosis than a red assertion. The helper now
  provokes a `pong` end-marker.

### MS2 — store, assembler, transport-agnostic core · `82c8ff4`

- `store.py`, `transcript.py`, `session.py`. **`session.py` never imports FastAPI** — it knows
  about a `Transport`, which is `send` and `close` and nothing else.
- The assembler trims the **head of the later** span, never the tail of the earlier one: text
  already sent must not change. The comparison window is over *emitted* words.
- **Mutation testing found real redundancy:** deleting the `dedupe()` call changed nothing,
  because `push()` hand-rolled the same rule. Now one implementation.

---

## W0 — Foundation

### MS1 — the STT capability layer · `3b8e1a8`

- The one sanctioned exception to additive-only, spent. `WHISPER_DEVICE`/`WHISPER_COMPUTE`, the
  **resolved** device read back off the loaded model, `transcribe_segments()` concrete on the
  ABC, and a provider cache keyed on config.
- **A claim of mine that was wrong:** faster-whisper does *not* default to CPU — `device`
  defaults to `"auto"`. The real problem is that `auto` falls back to CPU *silently*, which is
  why the resolved device is reported.
- Carried out: **MS1-a** (real remote timings) and **MS1-b** (measure the real-time factor).

### MS0 — skeleton and flags · `6ad44e7`

- `backend/app/meetingsense/{__init__,config,routes}.py`, the master flag and six sub-flags
  (none implied by the master), and `GET /v1/meetingsense/status` — always mounted, always 200,
  never leaking the STT endpoint.
- Probes run through a wrapper that turns any escape into a reported unknown: a status endpoint
  that 500s because an optional package moved has failed at its one job.
