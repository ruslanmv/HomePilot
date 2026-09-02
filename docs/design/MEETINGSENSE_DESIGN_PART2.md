# MeetingSense — Part 2: Together mode, Meeting Catalog, Agent Engine, MCP, Helper modes

**Status:** design / analysis only — no code changed, nothing committed.
**Builds on:** `MEETINGSENSE_DESIGN.md` (Part 1: capture → transcript → slide keyframes → notes). Part 1 is the substrate; this part turns it into an experience.

---

## 0. The one-sentence product

> You start a meeting; HomePilot quietly listens and watches. While it runs you can talk to your persona about *what is happening right now*, ask it to jump into the conversation, or let it coach you. When it ends, the meeting lands in a catalog you can reopen weeks later and keep working from — and every past meeting is reachable by your personas and by any MCP client.

Four layers, each additive on Part 1:

```
 Part 1   Capture + Transcript + Slides + Notes          (substrate)
 Layer A  Together mode — live grounded chat, AI-in-the-room
 Layer B  Meeting Catalog — library, resume, cross-meeting memory
 Layer C  Meeting Agent Engine — LangGraph graph with tools (already a dependency)
 Layer D  MeetingSense MCP server — the meetings become a tool for everything else
 + Helper modes (Note-taker · Participant · Coach · Presenter)
```

---

## A. Together mode — the AI is *in* the meeting with you

### A.1 Live grounded chat (zero extra UI)

While a session runs, every normal chat turn in that conversation is grounded in the meeting. This needs no new endpoint — the existing chat pipeline gets one extra context block, injected only when a live `meeting_id` is attached to the conversation:

```
[LIVE MEETING CONTEXT — 00:14:32, source: Teams "Q3 planning"]
Current slide (14:05): "Timeline v3" — Oct launch, legal gate, budget TBD
Last 90 s of transcript:
  14:05 them: we still need legal sign-off before we can commit
  14:06 them: Marina, can you own that?
Running notes: decisions[1] actions[1] open_questions[1]
Instruction: answer using this context first; cite timestamps; if the user asks
"what did he mean", quote the exact segment.
```

- Implemented as a **context provider** hook in `prompt_builder.py` (personalities) — same seam personas already use to inject memory. Zero change when no meeting is live.
- Budget: last 90 s verbatim + rolling notes + current slide caption ≈ 600–900 tokens. Older material comes through retrieval (see B.3), not by stuffing the prompt.
- Latency target: the transcript is at most ~3 s behind reality (Part 1 partials), so "what did she just say?" works.

### A.2 Proactive nudges (opt-in, quiet by default)

The session watches for a few **deterministic triggers** and surfaces a small suggestion chip inside the MeetingCard — never a modal, never audio:

| Trigger | Detection | Chip |
|---|---|---|
| Question aimed at me | 2-channel: `them` segment ends with `?` and contains my name / "you" | "They asked you about X — suggested answer ▸" |
| Decision spoken | notes engine emits `add_decisions` | "Log decision? ▸" |
| Action assigned | notes engine emits `add_actions` with owner | "Create task in Notion/Todoist ▸" (via existing MCP servers) |
| Number / date said | regex on segment | "Add to calendar ▸" (google_calendar / microsoft_graph MCP) |
| Slide with a URL / code | vision caption + OCR | "Open / save link ▸" |

Chips are suggestions; the user taps to act. This keeps the AI *present* without being noisy.

### A.3 Putting the AI's voice into the room (three tiers)

| Tier | How | Requires | Realism |
|---|---|---|---|
| **1. Read-aloud** (default) | Persona drafts a reply; the user says it or pastes it into the meeting chat | nothing | ✔ always works |
| **2. Post to meeting chat** | Persona posts text into the Teams/Zoom chat via the **existing** `microsoft_graph` MCP server (9116) or a Zoom MCP (new, same `_common/server.py` template) | OAuth already handled by those servers | ✔ text only |
| **3. Speak into the call** | TTS (Piper/Kokoro from `voice/providers.py`) → rendered into a **virtual microphone** that Teams/Zoom select as input | Electron desktop + virtual audio device (VB-Cable on Windows, BlackHole on macOS) | ✔ voice, but needs one-time setup |

Tier 3 is what makes "insert the AI in the conversation" literal. UX rules: the persona speaks only when the user presses **Speak**, or in Participant mode when explicitly addressed by name and the user has armed it; a visible "🔊 persona is speaking" state is shown; barge-in stops it (reuse `voice_call/barge_in.py`). Others in the call should know an AI is present — the consent sheet says so.

---

## B. Meeting Catalog — the meeting outlives the session

### B.1 Data model (extends Part 1 tables)

```sql
ms_meetings   + tags TEXT, attendees_json, calendar_event_id, workspace_project_id,
              + status ('live'|'ended'|'archived'), pinned BOOL, last_opened_at
ms_threads    (id, meeting_id, conversation_id, created_at)   -- every "continue working" chat
ms_artifacts  (id, meeting_id, kind 'summary|actions|transcript_md|srt|slides_pdf', url)
ms_embeddings via existing vectordb: one collection per meeting + one global "meetings" collection
```

### B.2 The Library view (`frontend/src/ui/meetingsense/MeetingLibrary.tsx`)

A new entry in the left navigation: **Meetings**. Same visual grammar as `ProjectsView` / Sessions:

```
┌ Meetings ─────────────────────────────── [Search meetings, people, slides…] ┐
│ ● LIVE  Q3 planning · Teams · 00:14 · 3 slides           [Open] [Stop]      │
│                                                                              │
│ This week                                                                    │
│ ▸ Mon  Design review — Sofia, Marc   42 min · 12 slides · 4 actions (2 open) │
│ ▸ Mon  1:1 with Marina               25 min · 0 slides · 1 decision          │
│ Last week …                                                                  │
│                                                                              │
│ Filters: [Teams][Zoom][Meet]  [has open actions]  [has slides]  [tag ▾]      │
└──────────────────────────────────────────────────────────────────────────────┘
```

Opening a meeting → **MeetingDetail**: summary · timeline (slides on a time axis, click → transcript at that moment) · actions with checkboxes · full transcript with search · threads ("You discussed this on Aug 28 →") · export.

### B.3 "Continue working on it"

Three ways back in, all reusing existing conversation machinery:

1. **Reopen the original chat** — the conversation that hosted the live session still exists; the MeetingCard hydrates as a frozen card.
2. **New thread from this meeting** — creates a conversation with a compact **meeting brief** message (summary + open actions + slide list) and attaches `meeting_id`, so the persona has retrieval access to the full transcript via tool (`ms.search`, D.1). Recorded in `ms_threads`.
3. **Attach to a Project** — pushes `transcript_md` + slide captions into the project's knowledge base (`projects.py` upload path already exists). Now the project's persona knows the meeting forever.

Cross-meeting memory: the global "meetings" vector collection lets you ask *"what did we decide about pricing across the last three planning meetings?"* from any chat; the answer cites `meeting · timestamp`.

### B.4 Auto-metadata

- **Title/attendees**: if `google_calendar` or `microsoft_graph` MCP is connected, match the session start time to the current calendar event → title, attendees, link. Otherwise from the shared window title (Electron `desktopCapturer` source name: "Q3 planning | Microsoft Teams").
- **Source detection**: window title heuristics (Teams / Zoom / Meet / Webex) → icon + platform-specific tips.

---

## C. Meeting Agent Engine — when the simple loop isn't enough

Part 1's notes loop is a fixed pipeline. Helper modes and Together mode need **tool use and branching** (search the catalog, look at a slide again, draft a reply, post to chat, create a task). `langgraph>=0.2.0` is already in `backend/requirements.txt`, so the engine is a LangGraph graph, not a new dependency.

### C.1 Graph

```
                    ┌──────────────┐
  segment/slide ───►│   Perceive   │  normalise event, update working memory (rolling 10 min)
   event            └──────┬───────┘
                           ▼
                    ┌──────────────┐   every N s / on trigger
                    │   Reflect    │──► notes delta (decisions/actions/questions)
                    └──────┬───────┘
                           ▼
                 ┌────────────────────┐
   user chat ───►│  Decide (router)   │  mode + policy → which node, or "stay quiet"
   "ask" ───────►└─┬─────┬─────┬─────┬┘
                   ▼     ▼     ▼     ▼
              Answer  Coach  Act   Recall
              (LLM,   (mode- (tools: (vectordb:
              cited)  specific MCP    this + past
                      prompt) servers) meetings)
                   └─────┴─────┴─────┘
                           ▼
                    ┌──────────────┐
                    │   Deliver    │  chip · chat message · TTS (tier 3) · MCP post
                    └──────────────┘
```

- **Working memory** = last 10 min verbatim + notes + slides (in-graph state). **Long memory** = vectordb + `ms_*` tables via the Recall node.
- **Policy** (`agentic/policy.py` ask-before-acting is reused): `Act` on external systems always produces a chip first unless the user pre-approved that tool for this meeting.
- **Sub-agents** only where they pay off: `SlideReader` (vision + OCR → structured slide), `ActionExtractor` (owner/due-date normalisation), `Coach` (mode-specific). Everything else is a single LLM call — deep agents are a tool, not a goal.
- Runs in-process as an asyncio task per session; fan-out to the WS from Part 1 is unchanged (`notes`, `chip`, `answer` frames — `chip` is the one new frame type).

### C.2 Where it lives

```
backend/app/meetingsense/agent/
├── graph.py        # LangGraph definition
├── state.py        # MeetingState (typed dict)
├── nodes/          # perceive.py reflect.py decide.py answer.py coach.py act.py recall.py deliver.py
├── tools.py        # wraps MCP tools via agentic/runtime_tool_router.py (existing)
└── modes.py        # mode → prompt + allowed nodes + trigger set
```

Part 1's `notes_engine.py` becomes the `Reflect` node; nothing is thrown away.

---

## D. MeetingSense MCP server — meetings as a capability

Following `agentic/integrations/mcp/knowledge_server.py` (`ToolDef` + `create_mcp_app`), add **`meetingsense_server.py` on port 9120**, registered in Context Forge by `seed_all.py` and listed in the suite manifest. Then every persona, the A2A agents, HomePilot's own agent graph *and external clients* (Claude Desktop, Cursor, another HomePilot) can use meetings.

### D.1 Tools

| Tool | Purpose |
|---|---|
| `ms.list_meetings(query?, from?, to?, tag?, has_open_actions?)` | catalog browse |
| `ms.get_meeting(id)` | summary, actions, slides, attendees |
| `ms.get_transcript(id, t0?, t1?, speaker?)` | ranged transcript |
| `ms.search(query, meeting_id?|all, k)` | vector + keyword search, returns `meeting·t0·text` |
| `ms.get_live_context(meeting_id)` | last 90 s + current slide + notes (what A.1 injects) |
| `ms.get_slide(meeting_id, t)` | keyframe url + caption + OCR text |
| `ms.update_action(id, status, owner?, due?)` | close the loop from anywhere |
| `ms.suggest(meeting_id, text)` | push a chip into the live card (agents talking *to* the meeting) |
| `ms.set_mode(meeting_id, mode)` | switch helper mode (policy-checked) |
| `ms.export(id, fmt)` | md / srt / json / slides pdf |

### D.2 Two directions

- **Consumers**: the Chief-of-Staff A2A agent can now do "brief me on everything decided this week"; the `executive_briefing_server` can pull `ms.list_meetings` into the morning brief.
- **Producers**: the meeting agent's `Act` node uses the *other* MCP servers (calendar, graph, notion, github, todoist-style) through the existing runtime tool router — meetings become the place where tasks originate.

Security: the server reads the same SQLite/vector store; auth via the same API-key/OAuth contract as the other local servers; `ms.suggest` and `ms.set_mode` are write-scoped and policy-gated.

---

## E. Helper modes

A mode is a bundle of: system prompt · trigger set · allowed graph nodes · delivery channel · what the recording pill says. The user picks it in the start popover; it can be switched live.

### E.1 Modes we design

| Mode | Who talks | What the AI does | Delivery |
|---|---|---|---|
| **Note-taker** (default) | nobody | Part 1: transcript, slides, notes, summary | card only |
| **Participant** | the persona, when addressed | Answers questions the room asks *it* ("HomePilot, what was last quarter's number?") using Recall + project KB; proposes answers to questions aimed at the user as chips | chip → user approves → tier 1/2/3 |
| **Coach** | the user | Real-time talking points for *the user's own* answers, grounded in material the user uploaded beforehand (CV, prep notes, product docs); flags filler/rambling; "you haven't answered the second part" | subtle chips, optional earpiece TTS |
| **Presenter** | the user | Speaker notes for the current slide (from the deck the user attached), time-per-slide pacing, captures audience questions into a queue, drafts answers for Q&A | side rail |
| **Practice** (offline) | user ↔ persona | Persona plays interviewer / examiner / customer using a job description or syllabus; full transcript + scored feedback afterwards | normal voice call (reuses `voice_call/`) |

Coach honesty note: interview coaching is a legitimate, existing product category, but HomePilot's Coach is designed as *preparation and delivery support*, not a covert answer feed. Chips show talking points from **the user's own material**, the pill shows "Coach" so the user never forgets it is on, and the consent sheet recommends checking the interviewer's policy on assistive tools. We explicitly do **not** build a hands-free "whisper the answer" loop for Coach.

### E.2 What we do not build

The request included answering oral-exam questions and reading test questions off the screen to answer them live. We are not designing that mode. It is academic-dishonesty tooling, and the same pipeline that makes it possible (screen OCR → LLM → covert answer) is precisely what the consent, visible-indicator and mode-policy design above exists to prevent. Concretely:

- No mode reads on-screen questions and returns answers without the user's own chat turn.
- Modes are server-side policy objects; a client can't compose "Coach + screen OCR + auto-answer" into a new one.
- The `Practice` mode covers the honest version of that need: run a mock oral exam or timed quiz *before* the real one, with the persona grading and explaining.

---

## F. Real-time budget

| Stage | Target | How |
|---|---|---|
| Audio → partial text | ≤ 3 s | 8 s hard-cut chunks, faster-whisper small on GPU (~0.2× RT) |
| Segment → working memory | < 50 ms | in-process |
| Chip decision (deterministic triggers) | < 100 ms | regex/2-channel heuristics, no LLM |
| Grounded chat answer | 2–6 s | one LLM call, ≤ 1 k context tokens + retrieval |
| Notes refresh | every 60 s | background, never blocks transcript |
| Slide caption | 3–10 s after change | vision model, async; transcript keeps flowing |
| TTS into call (tier 3) | first audio < 1 s | Piper streaming |

---

## G. Delivery plan (continues Part 1's phases)

| Phase | Scope | Depends on |
|---|---|---|
| **5 — Together (A)** | live context provider in `prompt_builder`, chips, tier 1/2 delivery (read-aloud, post-to-chat via graph MCP) | Part 1 phases 1–3 |
| **6 — Catalog (B)** | tables, Library + Detail views, "new thread from meeting", attach-to-project, calendar auto-metadata, exports | 5 |
| **7 — MCP server (D)** | `meetingsense_server.py` (9120), Forge registration, suite manifest, `ms.*` tools | 6 |
| **8 — Agent engine (C)** | LangGraph graph replaces the fixed notes loop; Recall over past meetings; Act via runtime tool router | 7 |
| **9 — Modes (E)** | Participant, Coach, Presenter, Practice; tier 3 voice-in-call for desktop | 8 |

Each phase is flag-gated (`MEETINGSENSE_TOGETHER`, `MEETINGSENSE_CATALOG`, `MEETINGSENSE_MCP`, `MEETINGSENSE_AGENT`, `MEETINGSENSE_MODES`) and off by default; the Part 1 recorder keeps working if every later flag stays off.

---

## H. Files touched vs. added (all phases)

**Added:** `backend/app/meetingsense/**` (incl. `agent/`), `agentic/integrations/mcp/meetingsense_server.py`, `frontend/src/ui/meetingsense/**` (Popover, Pill, Card, Library, Detail, SlideStrip, ConsentSheet), `frontend/public/js/homepilot-meetingsense.js`, docs.

**Touched, additively:** `main.py` (+router include), `config.py` (+flags), `prompt_builder.py` (+one optional context provider), `desktop/main.js` + `preload.js` (+loopback handler, +virtual-mic output), `seed_all.py` + suite manifest (+one server), left nav (+"Meetings" entry behind flag), `index.html` (+1 script).

No existing endpoint, table column, or chat path is modified.
