# Teams Federation Design — HomePilot

> **Status:** Design draft (not yet implemented)
> **Scope:** Non-destructive, additive only — no existing features are modified
> **Goal:** Allow personas from one HomePilot instance to collaborate with personas from another in a shared virtual meeting room

---

## Overview

A new **Teams** tab in the main sidebar lets users create virtual meeting rooms where AI personas (and a single human participant) sit around a shared table. Each persona retains its own memory and personality, while the meeting room shares a unified context across all participants — like a real team meeting, but powered by AI.

In the future, meetings can be federated across multiple HomePilot instances on different computers, and even bridged to real Microsoft Teams / Zoom / Google Meet calls.

---

## Top 3 Solution Approaches

### Solution 1: Local Meeting Rooms (Recommended for Phase 1)

**Single-machine meetings where personas from the same HomePilot collaborate.**

```
┌─────────────────────────────────────────────────────────────┐
│  HomePilot Instance (PC-A)                                  │
│                                                             │
│  ┌─ Meeting Room ────────────────────────────────────────┐  │
│  │                                                       │  │
│  │   ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐            │  │
│  │   │Scarltt│  │ Max  │  │ Luna │  │ You  │            │  │
│  │   │Secrtry│  │Analst│  │Creatv│  │Human │            │  │
│  │   └──┬───┘  └──┬───┘  └──┬───┘  └──┬───┘            │  │
│  │      │         │         │         │                  │  │
│  │      └─────────┴─────────┴─────────┘                  │  │
│  │              Shared Meeting Context                    │  │
│  │         (all see same conversation + docs)             │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  Each persona has:           Meeting room has:              │
│   - Own memory (adaptive)     - Shared transcript           │
│   - Own personality           - Shared documents            │
│   - Own tools (MCP)           - Turn-based or parallel      │
│   - Own A2A connections       - Agenda & action items       │
└─────────────────────────────────────────────────────────────┘
```

**How it works:**
1. User creates a Meeting Room from the Teams tab
2. Drag personas from the sidebar list onto the "table" (a circular/oval layout)
3. The human types a message or topic → all personas respond in turn
4. Each persona's response passes through its own system prompt, memory, and tools
5. All participants see the full transcript (shared context window)

**Key data model:**
```
MeetingRoom {
  id: string
  name: string
  participant_ids: string[]        // persona project IDs
  human_seat: boolean              // always true (the user)
  turn_mode: "round-robin" | "free-form" | "moderated"
  shared_context: Message[]        // the meeting transcript
  agenda: string[]                 // optional discussion topics
  created_at: number
}
```

**Backend endpoints (all new, additive):**
- `POST /v1/teams/rooms` — create a meeting room
- `GET /v1/teams/rooms` — list rooms
- `GET /v1/teams/rooms/{id}` — get room details + transcript
- `POST /v1/teams/rooms/{id}/message` — send a message (human or trigger persona turn)
- `PUT /v1/teams/rooms/{id}/participants` — add/remove personas
- `DELETE /v1/teams/rooms/{id}` — delete room

**Frontend components (all new):**
- `TeamsView.tsx` — main tab content (room list + active room)
- `MeetingRoom.tsx` — the table view with persona avatars
- `MeetingTranscript.tsx` — shared conversation display

**Pros:** Simple, no networking, works offline, all personas have full tool access
**Cons:** Single machine only

---

### Solution 2: Federated Meeting Rooms (Phase 2)

**Cross-machine meetings where HomePilot instances link via WebSocket relay.**

```
┌─ PC-A (HomePilot) ────────┐    ┌─ PC-B (HomePilot) ────────┐
│                            │    │                            │
│  Scarlett (Secretary)      │    │  Dr. Chen (Researcher)     │
│  Max (Data Analyst)        │    │  Atlas (DevOps Engineer)   │
│  You (Human)               │    │  Friend (Human)            │
│                            │    │                            │
│  ┌─ Federation Agent ────┐ │    │ ┌─ Federation Agent ────┐  │
│  │ WebSocket client      │◄├────┤►│ WebSocket client      │  │
│  │ Relay: relay.local    │ │    │ │ Relay: relay.local    │  │
│  └───────────────────────┘ │    │ └───────────────────────┘  │
└────────────────────────────┘    └────────────────────────────┘
              │                                │
              └───────────┬────────────────────┘
                          ▼
              ┌─ Relay Server ─────────┐
              │ (lightweight, no LLM)  │
              │ Routes messages between│
              │ connected instances    │
              │ Stores shared context  │
              └────────────────────────┘
```

**How it works:**
1. Each HomePilot runs a **Federation Agent** (lightweight WebSocket client)
2. A simple **Relay Server** (can run on either PC or a third machine) routes messages
3. When PC-A's persona responds, the message is relayed to PC-B's shared context
4. Each persona still runs locally on its home machine (privacy preserved)
5. Only the transcript and turn signals cross the network — no model weights or memory

**New components:**
- `FederationAgent` — WebSocket client that syncs meeting context between instances
- `RelayServer` — minimal Node.js or Python server (new service, ~200 LOC)
- `PeerDiscovery` — mDNS/Bonjour for LAN auto-discovery, or manual URL entry

**Connection flow:**
```
1. PC-A creates a Meeting Room → gets a Room Code (e.g., "MEET-7X3K")
2. PC-B enters the Room Code in the Teams tab → connects via relay
3. Both sides see each other's personas appear at the table
4. Messages flow: Human types → local personas respond → relay → remote personas respond
```

**Pros:** True multi-machine collaboration, each persona runs on its own hardware
**Cons:** Requires network, relay server adds complexity, latency between turns

---

### Solution 3: External Meeting Bridge (Phase 3 — Future)

**Bridge virtual meetings to real Microsoft Teams, Zoom, or Google Meet.**

```
┌─ HomePilot ─────────────┐     ┌─ Microsoft Teams ──────────┐
│                          │     │                            │
│  Meeting Room            │     │  Real meeting with         │
│  (Scarlett + Max + You)  │     │  human participants        │
│                          │     │                            │
│  ┌─ Meeting Bridge ────┐ │     │ ┌─ Teams Bot API ────────┐ │
│  │ Transcription  ◄────┤─┤─────┤─┤ Audio → Text (STT)     │ │
│  │ TTS Response   ─────┤─┤─────┤─► Text → Audio (TTS)     │ │
│  │ Screen share   ─────┤─┤─────┤─► Visual content          │ │
│  └──────────────────────┘ │     │ └────────────────────────┘ │
└──────────────────────────┘     └────────────────────────────┘
```

**How it works:**
1. A **Meeting Bridge** service connects to Microsoft Teams / Zoom via their Bot APIs
2. External meeting audio is transcribed (STT) and fed into the HomePilot meeting room
3. Persona responses are converted to speech (TTS) and played back in the external meeting
4. Personas appear as bot participants in the real meeting

**Pros:** Integrates with real-world meetings, personas collaborate with real people
**Cons:** Requires external API keys, complex audio pipeline, Teams/Zoom bot registration

---

## Recommended Implementation Order

| Phase | What | Effort |
|-------|------|--------|
| **Phase 1** | Local Meeting Rooms (Solution 1) | Medium — new tab, room model, turn engine |
| **Phase 2** | Federation via relay (Solution 2) | Medium — WebSocket relay, peer discovery |
| **Phase 3** | External bridge (Solution 3) | Large — STT/TTS pipeline, bot API registration |

---

## UI Design: Teams Tab

### Sidebar Entry
```
  Chat        Ctrl+J
  Voice       Ctrl+V
  Project
  Imagine
  Edit
  Avatar
  Animate
  Studio
  Models
  ─────────
  Teams       ← NEW
  ─────────
  History
```

### Room List View (no active meeting)
```
┌─────────────────────────────────────────────┐
│  Teams                          [+ New Room] │
│                                              │
│  ┌─ Morning Standup ────────────────────┐   │
│  │  👤 Scarlett, Max, Luna  · 3 personas │   │
│  │  Last active: 2 hours ago            │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  ┌─ Research Planning ──────────────────┐   │
│  │  👤 Dr. Chen, Atlas      · 2 personas │   │
│  │  Last active: yesterday              │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  ┌─ Creative Brainstorm ────────────────┐   │
│  │  👤 Luna, Nova           · 2 personas │   │
│  │  Last active: 3 days ago             │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

### Active Meeting Room View
```
┌──────────────────────────────────────────────────────────────────┐
│  Morning Standup                    [Agenda] [Settings] [Leave]  │
│─────────────────────────────────────────────────────────────────│
│                                                                  │
│              ┌──────────┐                                        │
│              │ Scarlett  │  ← speaking indicator (glow)          │
│              │  (avatar) │                                        │
│              └──────────┘                                        │
│                                                                  │
│     ┌──────────┐              ┌──────────┐                      │
│     │   Max    │              │   Luna   │                      │
│     │ (avatar) │              │ (avatar) │                      │
│     └──────────┘              └──────────┘                      │
│                                                                  │
│              ┌──────────┐                                        │
│              │   You    │  ← human seat                         │
│              │ (avatar) │                                        │
│              └──────────┘                                        │
│                                                                  │
│─────────────────────────────────────────────────────────────────│
│ Transcript                                                       │
│                                                                  │
│  You: Let's discuss the Q1 priorities.                           │
│                                                                  │
│  Scarlett: I've reviewed the calendar. We have 3 key deadlines   │
│  this week: the proposal draft, the client meeting prep, and     │
│  the budget review.                                              │
│                                                                  │
│  Max: Looking at the data, the proposal should take priority —   │
│  the conversion rate analysis shows...                           │
│                                                                  │
│  Luna: From a creative standpoint, I'd suggest we also...        │
│                                                                  │
│─────────────────────────────────────────────────────────────────│
│  [Type a message...]                              [Send] [Mic]   │
└──────────────────────────────────────────────────────────────────┘
```

### Drag-and-Drop Persona Selection
```
┌──────────────────────────┐  ┌────────────────────────────────┐
│  Available Personas      │  │  Meeting Table                 │
│                          │  │                                │
│  ┌─ Scarlett ──────┐     │  │      ┌──────┐                 │
│  │ Secretary       │ ──drag──►    │Scarltt│                 │
│  └─────────────────┘     │  │      └──────┘                 │
│  ┌─ Max ───────────┐     │  │                                │
│  │ Data Analyst    │     │  │  ┌──────┐      ┌──────┐       │
│  └─────────────────┘     │  │  │ Max  │      │ Luna │       │
│  ┌─ Luna ──────────┐     │  │  └──────┘      └──────┘       │
│  │ Creative Dir    │     │  │                                │
│  └─────────────────┘     │  │      ┌──────┐                 │
│  ┌─ Dr. Chen ─────┐     │  │      │ You  │                 │
│  │ Researcher      │     │  │      └──────┘                 │
│  └─────────────────┘     │  │                                │
│                          │  │  Drop a persona to add them    │
└──────────────────────────┘  └────────────────────────────────┘
```

---

## Data Flow: How a Meeting Turn Works

```
Human types: "What should we focus on this week?"
         │
         ▼
┌─ Meeting Engine (backend) ──────────────────────────────────────┐
│                                                                  │
│  1. Add human message to shared_context                          │
│                                                                  │
│  2. For each persona (in turn order):                            │
│     a. Build prompt = persona.system_prompt                      │
│                      + persona.memory (private, from memory DB)  │
│                      + shared_context (all meeting messages)     │
│                      + available MCP tools                       │
│                                                                  │
│     b. Call LLM → get response                                   │
│                                                                  │
│     c. If persona uses tools (MCP/A2A), execute them             │
│        - Scarlett checks calendar via hp-google-calendar          │
│        - Max queries data via hp-knowledge                       │
│        - Luna generates a mood board via generate_images          │
│                                                                  │
│     d. Add persona response to shared_context                    │
│     e. Update persona's private memory                           │
│                                                                  │
│  3. Stream all responses to frontend                             │
└──────────────────────────────────────────────────────────────────┘
```

---

## Federation Protocol (Phase 2)

```
┌─ PC-A ──────────────────────┐        ┌─ PC-B ──────────────────────┐
│                              │        │                              │
│  FederationAgent             │        │  FederationAgent             │
│  ├─ connect(relay_url)       │        │  ├─ connect(relay_url)       │
│  ├─ join_room(room_code)     │        │  ├─ join_room(room_code)     │
│  ├─ send_message(msg)        │◄──────►│  ├─ send_message(msg)        │
│  ├─ on_message(callback)     │   WS   │  ├─ on_message(callback)     │
│  └─ sync_participants()      │        │  └─ sync_participants()      │
│                              │        │                              │
└──────────────────────────────┘        └──────────────────────────────┘

Message format:
{
  "type": "meeting.message",
  "room_code": "MEET-7X3K",
  "sender": {
    "instance_id": "hp-abc123",     // HomePilot instance
    "persona_id": "scarlett-001",   // or "human"
    "display_name": "Scarlett",
    "avatar_url": "data:image/..."  // small thumbnail
  },
  "content": "I've checked the calendar...",
  "tools_used": ["hp.gcal.list_events"],
  "timestamp": 1740000000
}
```

---

## Compatibility with MCP Tools and A2A Agents

Each persona in a meeting retains full access to its configured tools:

| Persona | MCP Tools Available | A2A Agents |
|---------|-------------------|------------|
| Scarlett (Secretary) | hp-personal-assistant, hp-google-calendar, hp-gmail | everyday-assistant |
| Max (Data Analyst) | hp-knowledge, hp-web-search, Discover: GitHub MCP | chief-of-staff |
| Luna (Creative Dir) | generate_images, generate_videos | - |
| You (Human) | Can trigger any tool via natural language | Can delegate to any agent |

When a persona is dragged into a meeting, its full tool set comes with it. The meeting engine ensures each persona only uses tools it has been granted (via its project's `agentic.tool_source` policy).

---

## .hpersona Compatibility

Meeting room configurations can be exported and shared:

```json
{
  "kind": "homepilot.meeting_room",
  "name": "Morning Standup",
  "participants": [
    { "persona_hpersona": "scarlett-v2.hpersona", "seat": 1 },
    { "persona_hpersona": "max-analyst.hpersona", "seat": 2 },
    { "persona_hpersona": "luna-creative.hpersona", "seat": 3 }
  ],
  "turn_mode": "round-robin",
  "agenda_template": ["Status updates", "Blockers", "Action items"]
}
```

When imported, the system checks for each persona's `.hpersona` availability and prompts to install missing ones (including their MCP server dependencies).

---

## Files That Would Be Created (Phase 1)

| File | Purpose |
|------|---------|
| `frontend/src/ui/TeamsView.tsx` | Main Teams tab — room list + active room |
| `frontend/src/ui/teams/MeetingRoom.tsx` | Table view with draggable persona avatars |
| `frontend/src/ui/teams/MeetingTranscript.tsx` | Shared conversation display |
| `frontend/src/ui/teams/PersonaDragList.tsx` | Left panel: available personas to drag |
| `frontend/src/ui/teams/useTeamsRooms.ts` | Hook for room CRUD operations |
| `backend/app/teams/rooms.py` | Room storage (JSON-file based, like projects) |
| `backend/app/teams/meeting_engine.py` | Turn engine: orchestrates persona responses |
| `backend/app/teams/routes.py` | FastAPI router for /v1/teams/* endpoints |
| `backend/app/teams/__init__.py` | Module init |
