# TODO: Teams Meeting Bridge — Link Personas to MS Teams / Zoom / Google Meet

## Status: STRATEGY PLAN (v1.0 — Additive, Non-Destructive)

> **Golden Rule 1.0**: Every change is additive. No existing file is deleted or
> rewritten. New files only. Existing interfaces are extended, never broken.
> If a function signature changes, the old signature still works.

---

## What We Have Today

| Component | Location | Status |
|-----------|----------|--------|
| **HomePilot Teams** (multi-persona meeting rooms) | `backend/app/teams/` | Fully implemented |
| **Meeting Bridge scaffold** (abstract base class) | `backend/app/teams/bridge/base.py` | Abstract only |
| **Bridge event types** (`MeetingEvent`) | `backend/app/teams/bridge/types.py` | Defined |
| **WebSocket relay** (federated meetings) | `services/teams-relay/` | Implemented |
| **Microsoft Graph MCP** (calendar + mail) | `agentic/integrations/mcp/microsoft_graph/` | Placeholder (port 9116) |
| **Google Calendar MCP** (events) | `agentic/integrations/mcp/google_calendar/` | Placeholder (port 9115) |
| **`teams-mcp-server`** (external repo) | `github.com/ruslanmv/teams-mcp-server` | Working, 13 tools |

## What We Need

A persona in a HomePilot meeting room should be able to:
1. **Read** the user's MS Teams chats, channels, and calendar
2. **Send** messages to Teams chats/channels on behalf of the user
3. **Get join links** for upcoming meetings
4. **Future**: Join a Teams/Zoom/Meet call as a bot participant

---

## Architecture Decision

**Option A**: Integrate `teams-mcp-server` as a community external MCP server (like `hp-news`)
**Option B**: Merge its tools into the existing `hp-microsoft-graph` server (port 9116)

**Decision: Option A** — separate MCP server at **port 9106**

Rationale:
- `hp-microsoft-graph` uses a different auth model (service-level OAuth2 with client secret)
- `teams-mcp-server` uses Device Code Flow (user-level, no secret needed)
- Separate concerns: calendar/mail vs. real-time chat/meetings
- Already has its own token encryption and refresh logic
- Follows the same pattern as `hp-news` (external community server)
- Non-destructive: doesn't touch existing Microsoft Graph server

---

## Implementation Plan

### Phase 1: Register as HomePilot Community Server (Day 1)

**Goal**: Make `teams-mcp-server` installable via persona import, discoverable by Forge.

#### Step 1.1 — Add to community persona generator

**File**: `community/sample/generate_community_personas.py`
**Action**: ADD a new persona entry (no existing entries modified)

```python
{
    "slug": "teams-assistant",
    "id": "teams_meeting_assistant",
    "name": "Teams Assistant",
    "role": "Meeting Coordinator",
    ...
    "tools": ["teams.auth.status", "teams.chats.list_recent", "teams.chats.send_message",
              "teams.teams.list_joined", "teams.channels.list", "teams.channels.send_message",
              "teams.meetings.list_today", "teams.meetings.list_range", "teams.meetings.get_join_link"],
    "mcp_server": {
        "name": "mcp-teams",
        "description": "Microsoft Teams integration — chats, channels, calendar, and meetings via Graph API",
        "default_port": 9106,
        "source": {"type": "external", "git": "https://github.com/ruslanmv/teams-mcp-server", "ref": "main"},
        "transport": "HTTP", "protocol": "MCP",
        "tools_provided": ["teams.auth.device_code_start", "teams.auth.device_code_poll",
                           "teams.auth.status", "teams.auth.logout",
                           "teams.chats.list_recent", "teams.chats.send_message",
                           "teams.teams.list_joined", "teams.channels.list",
                           "teams.channels.send_message", "teams.meetings.list_today",
                           "teams.meetings.list_range", "teams.meetings.get_join_link",
                           "teams.calls.join_meeting"],
    },
}
```

#### Step 1.2 — Add to server catalog (optional servers)

**File**: `agentic/forge/templates/server_catalog.yaml`
**Action**: ADD entry under `optional:` section (after hp-slack)

```yaml
  - id: hp-teams
    port: 9106
    description: "Microsoft Teams chats, channels, calendar, and meetings"
    category: communication
    is_core: false
    module: null  # external server, not a built-in module
    source:
      type: external
      git: https://github.com/ruslanmv/teams-mcp-server
      ref: main
```

#### Step 1.3 — Add to gateways.yaml (reference)

**File**: `agentic/forge/templates/gateways.yaml`
**Action**: ADD entry under Communication section

```yaml
  - name: hp-teams
    url: "http://localhost:9106/rpc"
    transport: "SSE"
    description: "Microsoft Teams MCP server (chats, channels, meetings)"
```

---

### Phase 2: Bridge Integration (Day 2-3)

**Goal**: Connect `teams-mcp-server` tools to HomePilot's meeting room bridge.

#### Step 2.1 — Implement TeamsBridge

**File**: `backend/app/teams/bridge/teams_bridge.py` (NEW file)
**Action**: CREATE concrete implementation of `MeetingBridge`

```python
class TeamsBridge(MeetingBridge):
    """Bridge HomePilot meeting rooms to Microsoft Teams channels."""

    def __init__(self, teams_mcp_url: str = "http://localhost:9106/rpc"):
        self._rpc_url = teams_mcp_url

    async def connect(self) -> None:
        # Call teams.auth.status to verify auth
        # If not authed, initiate device_code flow
        ...

    async def incoming_events(self) -> AsyncIterator[MeetingEvent]:
        # Poll teams.chats.list_recent for new messages
        # Convert to MeetingEvent
        ...

    async def send_event(self, event: MeetingEvent) -> None:
        # Call teams.chats.send_message or teams.channels.send_message
        ...
```

#### Step 2.2 — Add bridge registry

**File**: `backend/app/teams/bridge/__init__.py` (EXTEND)
**Action**: ADD bridge factory function

```python
BRIDGE_REGISTRY = {
    "ms-teams": "backend.app.teams.bridge.teams_bridge:TeamsBridge",
    # Future: "zoom": "backend.app.teams.bridge.zoom_bridge:ZoomBridge",
    # Future: "google-meet": "backend.app.teams.bridge.meet_bridge:MeetBridge",
}
```

#### Step 2.3 — Add bridge field to room model

**File**: `backend/app/teams/rooms.py`
**Action**: EXTEND room schema (additive — new optional field)

```python
# ADD to room creation payload (optional, backward-compatible):
"external_bridge": {
    "provider": "ms-teams",       # which bridge to use
    "target_id": "channel_id",    # Teams channel/chat ID to bridge
    "sync_mode": "bidirectional", # or "outbound-only", "inbound-only"
}
```

---

### Phase 3: Persona ↔ Meeting Tool Binding (Day 3-4)

**Goal**: Any persona with `teams.*` tools can interact with Teams from chat.

#### Step 3.1 — Tool routing in persona chat

**File**: `backend/app/projects.py`
**Action**: EXTEND the tool-call detection to recognize `teams.*` tool names

When a persona has `teams.*` tools in its equipment and the user says
"check my Teams messages" or "send this to the marketing channel",
the LLM generates a tool call → routed to `http://localhost:9106/rpc`.

No code change needed if tools are registered in Forge correctly —
the existing tool invocation pipeline handles it.

#### Step 3.2 — Auth flow UI component

**File**: `frontend/src/ui/components/TeamsAuthFlow.tsx` (NEW file)
**Action**: CREATE React component for device code auth

```tsx
// Shows: "Go to https://microsoft.com/devicelogin and enter code: XXXXX"
// Polls teams.auth.device_code_poll until authenticated
// Stores success state in persona project settings
```

#### Step 3.3 — Add "Connect to Teams" button in persona settings

**File**: `frontend/src/ui/PersonaEditor.tsx`
**Action**: EXTEND Equipment section (additive)

When persona has `teams.*` tools → show a "Connect to Microsoft Teams" button
that triggers the device code auth flow.

---

### Phase 4: Zoom & Google Meet (Future)

**Goal**: Same pattern, different providers.

#### Step 4.1 — Zoom MCP Server

Create `mcp-zoom` following the same pattern as `teams-mcp-server`:
- Port: 9107
- Tools: `zoom.meetings.list`, `zoom.meetings.create`, `zoom.meetings.join_link`
- Auth: Zoom OAuth2 with Server-to-Server or User-level tokens

#### Step 4.2 — Google Meet MCP Server

Create `mcp-google-meet` or extend `hp-google-calendar` (port 9115):
- Tools: `meet.create`, `meet.join_link`, `meet.list_upcoming`
- Auth: Google OAuth2 (already scaffolded in hp-google-calendar)

#### Step 4.3 — Implement ZoomBridge and MeetBridge

Same pattern as `TeamsBridge` — concrete implementations of `MeetingBridge`.

---

## File Change Summary (Non-Destructive Audit)

| File | Action | Existing Code Affected? |
|------|--------|------------------------|
| `community/sample/generate_community_personas.py` | ADD persona entry | No — append to list |
| `agentic/forge/templates/server_catalog.yaml` | ADD optional server | No — append to list |
| `agentic/forge/templates/gateways.yaml` | ADD reference entry | No — append to list |
| `backend/app/teams/bridge/teams_bridge.py` | CREATE new file | No — new file |
| `backend/app/teams/bridge/__init__.py` | ADD registry dict | No — additive import |
| `backend/app/teams/rooms.py` | ADD optional field | No — new optional field |
| `frontend/src/ui/components/TeamsAuthFlow.tsx` | CREATE new file | No — new file |
| `frontend/src/ui/PersonaEditor.tsx` | ADD connect button | No — additive UI |

**Zero existing files deleted or rewritten. Zero function signatures broken.**

---

## Testing Checklist

- [ ] `teams-mcp-server` starts on port 9106 and responds to `/health`
- [ ] `POST /rpc` with `tools/list` returns 13 tools
- [ ] `POST /rpc` with `tools/call` + `teams.auth.status` returns auth state
- [ ] HomePilot `sync_homepilot()` discovers mcp-teams tools
- [ ] Persona with `teams.*` tools shows them in Equipment section
- [ ] Device code auth flow completes successfully
- [ ] `teams.chats.list_recent` returns real chats after auth
- [ ] `teams.meetings.list_today` returns calendar events
- [ ] Bridge: messages sent from HomePilot room appear in Teams channel
- [ ] Bridge: messages from Teams channel appear in HomePilot room
- [ ] Existing tests still pass (no regression)

---

## Dependencies

```
# teams-mcp-server requirements (already in its pyproject.toml)
fastapi>=0.110
uvicorn[standard]>=0.27
httpx>=0.27
cryptography>=42.0
python-dateutil>=2.9
pydantic>=2.6
pydantic-settings>=2.2
```

## Environment Variables (New — all optional)

```bash
# Microsoft Teams MCP Server
TEAMS_MCP_HOST=0.0.0.0
TEAMS_MCP_PORT=9106
MS_TENANT_ID=common
MS_CLIENT_ID=<your-entra-app-client-id>
TEAMS_MCP_TOKEN_KEY=<fernet-key-for-token-encryption>
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Azure AD app registration required | Certain | Medium | Document in setup guide, provide defaults |
| Token expiration during long meetings | Low | Low | Auto-refresh built into teams-mcp-server |
| Rate limiting on Graph API | Low | Low | Built-in retry logic in GraphClient |
| Port conflict with other services | Very Low | Low | 9106 is unallocated in HomePilot |
| Breaking existing Teams rooms | None | N/A | All changes are additive, bridge is optional |
