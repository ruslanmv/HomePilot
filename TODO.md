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
| **`teams-mcp-server`** (external repo) | `github.com/ruslanmv/teams-mcp-server` | Working, 23 tools (meeting chat, join, voice added) |

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
        "source": {"type": "external", "git": "https://github.com/ruslanmv/teams-mcp-server", "ref": "master"},
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

**Goal**: Connect `teams-mcp-server` tools to HomePilot's meeting room bridge,
so that a HomePilot meeting room can bi-directionally relay messages to/from
a Microsoft Teams channel or chat.

#### Existing Infrastructure

| What exists | Where | Notes |
|-------------|-------|-------|
| `MeetingBridge` abstract base class | `backend/app/teams/bridge/base.py` | 4 abstract methods: `connect()`, `disconnect()`, `incoming_events()`, `send_event()` |
| `MeetingEvent` dataclass | `backend/app/teams/bridge/types.py` | Fields: type, room_id, sender_id, sender_name, content, timestamp, external_ref, metadata |
| `EventType` literals | `backend/app/teams/bridge/types.py` | `meeting.message`, `meeting.join`, `meeting.leave`, `meeting.start`, `meeting.end` |
| Bridge `__init__.py` | `backend/app/teams/bridge/__init__.py` | Empty scaffold — just a docstring |
| Room model (JSON storage) | `backend/app/teams/rooms.py` | `create_room()` takes: name, description, participant_ids, turn_mode, agenda, topic, policy |
| Room messages | `backend/app/teams/rooms.py:add_message()` | Appends {id, sender_id, sender_name, content, role, tools_used, timestamp} |

#### Step 2.1 — Implement TeamsBridge

**File**: `backend/app/teams/bridge/teams_bridge.py` (NEW file)
**Action**: CREATE concrete implementation of `MeetingBridge`

```python
# backend/app/teams/bridge/teams_bridge.py
"""
Concrete MeetingBridge that relays messages between a HomePilot
meeting room and a Microsoft Teams channel/chat via the mcp-teams
server (port 9106).

Communication is via JSON-RPC 2.0 POST to http://localhost:9106/rpc.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator, Optional

import httpx

from .base import MeetingBridge
from .types import MeetingEvent

logger = logging.getLogger("homepilot.bridge.teams")

_DEFAULT_RPC = "http://localhost:9106/rpc"
_POLL_INTERVAL = 3.0  # seconds between polls for new messages


class TeamsBridge(MeetingBridge):
    """Bridge HomePilot meeting rooms ↔ Microsoft Teams channels/chats."""

    def __init__(
        self,
        room_id: str,
        target_id: str,                       # Teams channel or chat ID
        target_type: str = "channel",         # "channel" or "chat"
        sync_mode: str = "bidirectional",     # "bidirectional" | "outbound-only" | "inbound-only"
        rpc_url: str = _DEFAULT_RPC,
    ):
        self._room_id = room_id
        self._target_id = target_id
        self._target_type = target_type
        self._sync_mode = sync_mode
        self._rpc_url = rpc_url
        self._client: Optional[httpx.AsyncClient] = None
        self._last_seen_ts: float = time.time()
        self._connected = False

    # ── JSON-RPC helper ──────────────────────────────────────────────

    async def _rpc(self, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC 2.0 call to the mcp-teams server."""
        assert self._client is not None
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": method, "arguments": params or {}},
        }
        resp = await self._client.post(self._rpc_url, json=payload, timeout=15.0)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"RPC error: {body['error']}")
        return body.get("result", {})

    # ── MeetingBridge interface ──────────────────────────────────────

    async def connect(self) -> None:
        """Verify mcp-teams is running and user is authenticated."""
        self._client = httpx.AsyncClient()
        status = await self._rpc("teams.auth.status")
        if not status.get("authenticated"):
            raise RuntimeError(
                "Teams auth required. Run device code flow via the Setup Wizard first."
            )
        self._connected = True
        logger.info("TeamsBridge connected: room=%s target=%s", self._room_id, self._target_id)

    async def disconnect(self) -> None:
        self._connected = False
        if self._client:
            await self._client.aclose()
            self._client = None

    async def incoming_events(self) -> AsyncIterator[MeetingEvent]:
        """Poll Teams for new messages and yield them as MeetingEvents.

        Only active when sync_mode is "bidirectional" or "inbound-only".
        """
        if self._sync_mode == "outbound-only":
            return

        while self._connected:
            try:
                if self._target_type == "chat":
                    result = await self._rpc("teams.chats.list_recent", {"top": 10})
                else:
                    # For channels, use a hypothetical "teams.channels.messages" or
                    # poll "teams.chats.list_recent" filtered by channel context.
                    result = await self._rpc("teams.chats.list_recent", {"top": 10})

                for msg in result.get("messages", []):
                    msg_ts = msg.get("timestamp", 0)
                    if msg_ts > self._last_seen_ts:
                        self._last_seen_ts = msg_ts
                        yield MeetingEvent(
                            type="meeting.message",
                            room_id=self._room_id,
                            sender_id=msg.get("from", {}).get("id", "teams-user"),
                            sender_name=msg.get("from", {}).get("displayName", "Teams User"),
                            content=msg.get("body", {}).get("content", ""),
                            timestamp=msg_ts,
                            external_ref=msg.get("id"),
                            metadata={"source": "ms-teams", "target_id": self._target_id},
                        )
            except Exception as exc:
                logger.warning("TeamsBridge poll error: %s", exc)

            await asyncio.sleep(_POLL_INTERVAL)

    async def send_event(self, event: MeetingEvent) -> None:
        """Send a HomePilot meeting event to the Teams channel/chat.

        Only active when sync_mode is "bidirectional" or "outbound-only".
        """
        if self._sync_mode == "inbound-only":
            return
        if event.type != "meeting.message":
            return  # Only relay chat messages for now

        tool = (
            "teams.chats.send_message"
            if self._target_type == "chat"
            else "teams.channels.send_message"
        )
        await self._rpc(tool, {
            "chat_id" if self._target_type == "chat" else "channel_id": self._target_id,
            "content": f"**{event.sender_name}**: {event.content}",
        })
```

**Key design decisions**:
- Uses `httpx.AsyncClient` for non-blocking RPC calls to port 9106
- Polls `teams.chats.list_recent` at 3-second intervals for inbound messages
- Tracks `_last_seen_ts` to avoid duplicate message delivery
- `sync_mode` controls direction: bidirectional (default), outbound-only, inbound-only
- All messages from HomePilot are prefixed with the sender's persona name

#### Step 2.2 — Bridge registry and factory

**File**: `backend/app/teams/bridge/__init__.py` (EXTEND)
**Action**: ADD bridge registry dict and async factory function

```python
# backend/app/teams/bridge/__init__.py
"""External meeting bridge scaffold (Phase 3)."""
from __future__ import annotations

import importlib
from typing import Any, Dict, Optional

from .base import MeetingBridge
from .types import MeetingEvent, EventType

__all__ = ["MeetingBridge", "MeetingEvent", "EventType", "create_bridge", "BRIDGE_REGISTRY"]

# Lazy registry — values are "module:ClassName" strings, imported on demand.
BRIDGE_REGISTRY: Dict[str, str] = {
    "ms-teams": "backend.app.teams.bridge.teams_bridge:TeamsBridge",
    # Future:
    # "zoom": "backend.app.teams.bridge.zoom_bridge:ZoomBridge",
    # "google-meet": "backend.app.teams.bridge.meet_bridge:MeetBridge",
}


def create_bridge(provider: str, **kwargs: Any) -> MeetingBridge:
    """Instantiate a bridge by provider name.

    Usage:
        bridge = create_bridge("ms-teams", room_id="...", target_id="...", sync_mode="bidirectional")
        await bridge.connect()
    """
    dotpath = BRIDGE_REGISTRY.get(provider)
    if not dotpath:
        raise ValueError(f"Unknown bridge provider: {provider!r}. Available: {list(BRIDGE_REGISTRY)}")
    module_path, cls_name = dotpath.rsplit(":", 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, cls_name)
    return cls(**kwargs)
```

#### Step 2.3 — Extend room model with optional bridge config

**File**: `backend/app/teams/rooms.py`
**Action**: ADD `external_bridge` as a new optional parameter to `create_room()`

```python
# ADDITIVE change — new optional parameter, old callers unaffected.
def create_room(
    name: str,
    description: str = "",
    participant_ids: Optional[List[str]] = None,
    turn_mode: str = "reactive",
    agenda: Optional[List[str]] = None,
    topic: Optional[str] = None,
    policy: Optional[Dict[str, Any]] = None,
    external_bridge: Optional[Dict[str, Any]] = None,  # NEW — Phase 2
) -> Dict[str, Any]:
    room: Dict[str, Any] = {
        # ... existing fields unchanged ...
    }
    if policy:
        room["policy"] = policy
    # NEW: persist bridge config if provided
    if external_bridge:
        room["external_bridge"] = external_bridge
    _write(room)
    return room
```

**Bridge config schema** (`external_bridge` dict):

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `provider` | string | yes | Bridge provider key (e.g. `"ms-teams"`, `"zoom"`) |
| `target_id` | string | yes | External channel/chat ID to bridge to |
| `target_type` | string | no | `"channel"` (default) or `"chat"` |
| `sync_mode` | string | no | `"bidirectional"` (default), `"outbound-only"`, `"inbound-only"` |

#### Step 2.4 — Bridge lifecycle in meeting orchestrator

**File**: `backend/app/teams/orchestrator.py` (EXTEND existing file)
**Action**: ADD bridge startup/shutdown hooks (additive)

When a room with `external_bridge` config starts a session:

```python
# Pseudo-code for orchestrator extension
async def _start_bridge_if_configured(room: dict) -> Optional[MeetingBridge]:
    bridge_cfg = room.get("external_bridge")
    if not bridge_cfg:
        return None
    from .bridge import create_bridge
    bridge = create_bridge(
        provider=bridge_cfg["provider"],
        room_id=room["id"],
        target_id=bridge_cfg["target_id"],
        target_type=bridge_cfg.get("target_type", "channel"),
        sync_mode=bridge_cfg.get("sync_mode", "bidirectional"),
    )
    await bridge.connect()
    return bridge

# On room message: if bridge exists, forward the event
async def _relay_to_bridge(bridge: MeetingBridge, msg: dict, room_id: str):
    event = MeetingEvent(
        type="meeting.message",
        room_id=room_id,
        sender_id=msg["sender_id"],
        sender_name=msg["sender_name"],
        content=msg["content"],
        timestamp=msg["timestamp"],
    )
    await bridge.send_event(event)

# Background task: consume incoming bridge events → inject into room
async def _bridge_inbound_loop(bridge: MeetingBridge, room_id: str):
    async for event in bridge.incoming_events():
        from .rooms import add_message
        add_message(
            room_id=room_id,
            sender_id=event.sender_id,
            sender_name=f"[Teams] {event.sender_name}",
            content=event.content,
            role="user",
        )
```

#### Step 2.5 — REST API endpoints for bridge management

**File**: `backend/app/main.py` (EXTEND)
**Action**: ADD new endpoints (additive, no existing routes changed)

```
POST   /v1/teams/rooms/{room_id}/bridge          — Attach a bridge to a room
GET    /v1/teams/rooms/{room_id}/bridge           — Get bridge status
DELETE /v1/teams/rooms/{room_id}/bridge           — Detach bridge from room
POST   /v1/teams/rooms/{room_id}/bridge/test      — Test bridge connectivity
```

#### Step 2.6 — Frontend: Bridge config in Room Settings

**File**: `frontend/src/ui/teams/RoomBridgePanel.tsx` (NEW file)
**Action**: CREATE panel component for configuring external bridge

```
┌─────────────────────────────────────────────┐
│  External Bridge                    [OFF ▾] │
├─────────────────────────────────────────────┤
│  Provider:  [Microsoft Teams ▾]             │
│  Target:    [Select channel...    ▾]        │
│  Mode:      ○ Bidirectional                 │
│             ○ Outbound only                 │
│             ○ Inbound only                  │
│                                             │
│  Status: ● Connected (14 msgs relayed)      │
│                            [Disconnect]     │
└─────────────────────────────────────────────┘
```

The channel selector calls `teams.teams.list_joined` → `teams.channels.list`
to populate the dropdown with the user's actual Teams channels.

---

### Phase 3: Persona Tool Binding + Device Code Auth UI (Day 3-4)

**Goal**: Any persona with `teams.*` tools can interact with Teams from chat.
Leverage HomePilot's **existing** MCP Setup Wizard infrastructure for the
device-code authentication flow.

#### Existing Setup Wizard Infrastructure

HomePilot already has a complete MCP server setup wizard:

| Component | File | Role |
|-----------|------|------|
| `McpSetupWizard` | `frontend/src/ui/mcp/McpSetupWizard.tsx` | Step-through drawer: instructions → credentials → connecting → success/error |
| `setupInstructions.ts` | `frontend/src/ui/mcp/setupInstructions.ts` | Per-server guides (`SERVER_GUIDES`) + generic fallbacks by auth type (`AUTH_TYPE_GUIDES`) |
| `RegistryDiscoverPanel` | `frontend/src/ui/mcp/RegistryDiscoverPanel.tsx` | Card states: `available` → `installing` → `needs_setup` → `running` |
| `McpServerDetailsDrawer` | `frontend/src/ui/mcp/McpServerDetailsDrawer.tsx` | "Complete Setup" button triggers wizard |
| Backend register route | `POST /v1/agentic/registry/{server_id}/register` | Accepts `{api_key}`, validates, discovers tools |

**How it works today**:
1. `server_catalog.yaml` has `requires_config: MS_TEAMS_AUTH` → card enters `needs_setup` state
2. `getSetupGuide(serverId, authType)` looks up `SERVER_GUIDES[serverId]` → falls back to `AUTH_TYPE_GUIDES[authType]`
3. If `needsCredentialInput(authType)` → shows credential input after instruction steps
4. If `needsOAuthFlow(authType)` → shows server URL for manual OAuth
5. On submit → `POST /v1/agentic/registry/{server_id}/register` with `{api_key: "..."}`

#### Step 3.1 — Add "Device Code" auth type support

**Insight**: The Teams MCP server uses **Device Code Flow** — the user doesn't paste
an API key. Instead, the server generates a one-time code, the user visits
`https://microsoft.com/devicelogin` in their browser, enters the code, and the
server polls Microsoft until auth completes. This is a **2-step interactive flow**
unlike the existing API Key or OAuth patterns.

**Solution**: Add a new auth type `"Device Code"` to the wizard, handled with
a custom per-server guide that calls the mcp-teams server's RPC endpoints directly.

##### Step 3.1a — Add `mcp-teams` to SERVER_GUIDES

**File**: `frontend/src/ui/mcp/setupInstructions.ts` (EXTEND — additive)
**Action**: ADD entry to `SERVER_GUIDES` dict

```typescript
// ADD to SERVER_GUIDES (after existing entries):
'hp-teams': {
  steps: [
    {
      title: 'Register an Azure AD App',
      description: 'Go to Azure Portal > App registrations > New registration. ' +
        'Enable "Mobile and desktop applications" with the redirect URI ' +
        'https://login.microsoftonline.com/common/oauth2/nativeclient. ' +
        'Grant Microsoft Graph permissions: Chat.Read, Chat.ReadWrite, ' +
        'ChannelMessage.Read.All, ChannelMessage.Send, Calendars.Read, ' +
        'OnlineMeetings.Read, Team.ReadBasic.All, User.Read.',
      link: {
        label: 'Open Azure App Registrations',
        url: 'https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade',
      },
    },
    {
      title: 'Start Device Code Login',
      description: 'Click "Start Login" below. A code will appear — ' +
        'open the Microsoft link and enter it to authorize HomePilot ' +
        'to access your Teams account. The wizard will automatically ' +
        'detect when you complete the sign-in.',
    },
  ],
  credentialLabel: 'Client ID (from Azure App Registration)',
  credentialPlaceholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
  credentialHint: 'The Application (client) ID from your Azure AD app registration.',
},
```

##### Step 3.1b — Add "Device Code" to AUTH_TYPE_GUIDES

**File**: `frontend/src/ui/mcp/setupInstructions.ts` (EXTEND)
**Action**: ADD new auth type fallback

```typescript
// ADD to AUTH_TYPE_GUIDES:
'Device Code': {
  steps: [
    {
      title: 'About Device Code Authentication',
      description: 'This server uses Microsoft Device Code Flow. ' +
        'You will be given a one-time code to enter at microsoft.com/devicelogin. ' +
        'No API key or secret is needed — you authenticate with your Microsoft account directly.',
    },
    {
      title: 'Start the flow',
      description: 'Click "Start Login" to begin. A code will appear — ' +
        'enter it at the Microsoft login page to authorize access.',
    },
  ],
  credentialLabel: 'Client ID',
  credentialPlaceholder: 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
  credentialHint: 'Optional — uses default HomePilot client ID if not provided.',
},
```

##### Step 3.1c — Update `needsCredentialInput` to include Device Code

**File**: `frontend/src/ui/mcp/setupInstructions.ts` (EXTEND)
**Action**: ADD `'Device Code'` to the list

```typescript
export function needsCredentialInput(authType: string): boolean {
  return ['API Key', 'API', 'OAuth2.1 & API Key', 'Device Code'].includes(authType)
}
```

#### Step 3.2 — Device Code Flow component

**File**: `frontend/src/ui/mcp/DeviceCodeFlow.tsx` (NEW file)
**Action**: CREATE a reusable component for device-code auth

This component is rendered **inside** `McpSetupWizard` when `auth_type === 'Device Code'`.
It replaces the simple credential input with a 2-phase interactive UI.

```
┌──────────────────────────────────────────────┐
│  🔐 Microsoft Device Code Login              │
│                                              │
│  Step 1: Enter your Client ID (optional)     │
│  ┌──────────────────────────────────────┐    │
│  │ xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx │    │
│  └──────────────────────────────────────┘    │
│                       [Start Login →]        │
│                                              │
│ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │
│                                              │
│  Step 2: Enter this code at Microsoft        │
│                                              │
│       ┌─────────────┐                        │
│       │  ABCD-EFGH  │  [Copy]               │
│       └─────────────┘                        │
│                                              │
│  → Open https://microsoft.com/devicelogin    │
│                                              │
│  ⏳ Waiting for you to complete sign-in...   │
│     ████████░░░░░░░░  polling (12s)          │
│                                              │
│  ✅ Authenticated as user@contoso.com        │
│     13 tools discovered                      │
└──────────────────────────────────────────────┘
```

**Technical flow**:

```typescript
// 1. User optionally enters Client ID, clicks "Start Login"
// 2. Component calls POST /rpc to mcp-teams:
//    { method: "tools/call", params: { name: "teams.auth.device_code_start",
//      arguments: { client_id: "..." } } }
// 3. Response: { user_code: "ABCD-EFGH", verification_uri: "https://...", expires_in: 900 }
// 4. Display the code + link
// 5. Poll every 5s: teams.auth.device_code_poll
// 6. On success → call POST /v1/agentic/registry/hp-teams/register to complete setup
// 7. Wizard transitions to "success" state
```

**Integration with McpSetupWizard**: Instead of creating a separate component,
the recommended approach is to extend `McpSetupWizard.tsx` with a new render
function `renderDeviceCodeFlow()` that is shown when `server.auth_type === 'Device Code'`.
This keeps the existing wizard's state machine (instructions → connecting → success/error)
and reuses its UI shell (header, progress indicator, footer nav).

```typescript
// ADD to McpSetupWizard.tsx — new conditional in the Body section:
//
// {showInstructions && isDeviceCode && renderDeviceCodeFlow()}
// {showInstructions && requiresOAuth && renderOAuthInfo()}
// {showInstructions && !requiresOAuth && !isDeviceCode && renderInstructionStep()}

const isDeviceCode = server.auth_type === 'Device Code'
```

#### Step 3.3 — Backend: Device code register endpoint

**File**: `backend/app/agentic/registry_routes.py` (EXTEND)
**Action**: ADD handling for Device Code auth type in the register endpoint

```python
# The existing POST /v1/agentic/registry/{server_id}/register accepts {api_key: "..."}
# For Device Code, we extend it to also accept {auth_type: "device_code", client_id: "..."}
# The backend then:
#   1. Calls teams.auth.device_code_start via RPC
#   2. Returns the user_code + verification_uri to the frontend
#   3. A separate poll endpoint checks teams.auth.device_code_poll

# NEW endpoint (additive):
# POST /v1/agentic/registry/{server_id}/device-code/start  → returns {user_code, verification_uri}
# POST /v1/agentic/registry/{server_id}/device-code/poll   → returns {status: "pending"|"completed"}
```

#### Step 3.4 — Tool routing (no changes needed)

When mcp-teams tools are registered in Context Forge (done by `sync_service.py`
and the install pipeline), persona chat already routes `teams.*` tool calls to
`http://localhost:9106/rpc` via the standard tool invocation pipeline in
`backend/app/projects.py`.

**Verification**: After mcp-teams install + setup wizard completion:
1. `sync_service._get_mcp_servers()` picks up hp-teams from `community/external/registry.json`
2. `sync_homepilot()` queries port 9106 `/rpc` → `tools/list` → registers 13 tools in Forge
3. Persona with `teams.*` tools in equipment → LLM can invoke them → routed to port 9106

#### Step 3.5 — Update server_catalog.yaml auth type

**File**: `agentic/forge/templates/server_catalog.yaml`
**Action**: CHANGE `requires_config: MS_TEAMS_AUTH` to use the new auth type

```yaml
  - id: hp-teams
    port: 9106
    label: "Microsoft Teams"
    description: "Teams chats, channels, calendar, and meetings via Graph API"
    category: communication
    icon: message-circle
    requires_config: MS_TEAMS_AUTH
    auth_type: "Device Code"          # NEW — drives wizard behavior
    source:
      type: external
      git: https://github.com/ruslanmv/teams-mcp-server
      ref: main
```

---

### Phase 4: Zoom & Google Meet (Future)

**Goal**: Same bridge + wizard pattern, different providers. Each gets its own
MCP server, bridge implementation, and setup wizard entry.

#### Step 4.1 — Zoom MCP Server (`mcp-zoom`)

**Port**: 9107
**Repo**: `github.com/ruslanmv/zoom-mcp-server` (to be created)

**Tool namespace**: `zoom.*`

| Tool | Description |
|------|-------------|
| `zoom.auth.oauth_start` | Start OAuth2 PKCE flow for Zoom |
| `zoom.auth.oauth_callback` | Complete OAuth2 callback |
| `zoom.auth.status` | Check current auth state |
| `zoom.meetings.list_upcoming` | List scheduled meetings |
| `zoom.meetings.create` | Create a new meeting |
| `zoom.meetings.get_join_link` | Get join URL for a meeting |
| `zoom.meetings.participants` | List participants in a live meeting |
| `zoom.chat.send_message` | Send a message in Zoom Team Chat |
| `zoom.chat.list_channels` | List Zoom chat channels |

**Auth model**: Zoom Server-to-Server OAuth (for bot/service accounts) or
Zoom OAuth2 PKCE (for user-level access). The wizard uses the same
`Device Code` or `OAuth2.1` pattern depending on deployment choice.

**Server catalog entry**:
```yaml
  - id: hp-zoom
    port: 9107
    label: "Zoom"
    description: "Zoom meetings, chat channels, and video calls"
    category: communication
    icon: video
    requires_config: ZOOM_AUTH
    auth_type: "OAuth2.1"
    source:
      type: external
      git: https://github.com/ruslanmv/zoom-mcp-server
      ref: main
```

**Setup wizard entry** (`setupInstructions.ts`):
```typescript
'hp-zoom': {
  steps: [
    {
      title: 'Create a Zoom App',
      description: 'Go to the Zoom App Marketplace and create a Server-to-Server ' +
        'or OAuth2 app. Enable scopes: meeting:read, meeting:write, chat_message:read, ' +
        'chat_message:write.',
      link: { label: 'Open Zoom Marketplace', url: 'https://marketplace.zoom.us/' },
    },
    {
      title: 'Copy credentials',
      description: 'Copy the Client ID and Client Secret from your Zoom app settings.',
    },
    {
      title: 'Paste below',
      description: 'Enter your Zoom credentials to connect.',
    },
  ],
  credentialLabel: 'Client ID : Client Secret',
  credentialPlaceholder: 'client_id:client_secret',
},
```

**Bridge**: `backend/app/teams/bridge/zoom_bridge.py` — same pattern as `TeamsBridge`:
```python
class ZoomBridge(MeetingBridge):
    """Bridge HomePilot meeting rooms ↔ Zoom channels."""
    # Same pattern: connect() checks auth, incoming_events() polls chat,
    # send_event() posts messages via zoom.chat.send_message
```

#### Step 4.2 — Google Meet MCP Server

**Option A**: Extend existing `hp-google-calendar` (port 9115) with Meet tools
**Option B**: Create `mcp-google-meet` as separate server (port 9108)

**Recommended**: Option A — extend `hp-google-calendar`. Google Meet events are
already Google Calendar events with `conferenceData`. This avoids a separate
auth flow since `hp-google-calendar` already has Google OAuth scaffolded.

**New tools to add** (additive — existing calendar tools unchanged):

| Tool | Description |
|------|-------------|
| `calendar.meet.create` | Create a calendar event with Google Meet auto-attached |
| `calendar.meet.get_join_link` | Extract Meet URL from a calendar event |
| `calendar.meet.list_upcoming` | List events that have Meet links |

**Auth**: Reuses existing `GOOGLE_OAUTH` from `hp-google-calendar`. No new auth
flow needed. The setup wizard already handles Google OAuth via the existing
`requires_config: GOOGLE_OAUTH` entry.

**Bridge**: `backend/app/teams/bridge/meet_bridge.py`:
```python
class MeetBridge(MeetingBridge):
    """Bridge HomePilot meeting rooms ↔ Google Meet.

    Note: Google Meet doesn't have a real-time chat API like Teams/Zoom.
    The bridge focuses on meeting lifecycle (start/join/end) rather than
    message relay. Chat bridging would require Meet's upcoming Chat API.
    """
    # connect() → verify Google OAuth token
    # send_event() → create Meet meeting or post to associated Chat space
    # incoming_events() → limited to meeting start/end from Calendar webhooks
```

#### Step 4.3 — Bridge registry update

**File**: `backend/app/teams/bridge/__init__.py`
**Action**: ADD new providers to registry as they're implemented

```python
BRIDGE_REGISTRY: Dict[str, str] = {
    "ms-teams": "backend.app.teams.bridge.teams_bridge:TeamsBridge",
    "zoom": "backend.app.teams.bridge.zoom_bridge:ZoomBridge",
    "google-meet": "backend.app.teams.bridge.meet_bridge:MeetBridge",
}
```

#### Step 4.4 — Community personas for Zoom & Meet

Same pattern as Marcus Chen (Teams) — create community personas that declare
their MCP server dependency:

- **Zoom persona**: "Zoom Coordinator" — manages meetings, sends join links
- **Meet persona**: "Meet Scheduler" — creates Google Meet events, manages calendar

---

### Appendix A: Setup Wizard Extension Pattern

**For any future community MCP server that needs custom auth/setup steps**,
the pattern is fully additive — 3 touches, zero existing code modified:

#### 1. Declare `requires_config` in `server_catalog.yaml`

```yaml
  - id: hp-your-server
    port: 91XX
    requires_config: YOUR_AUTH_KEY   # ← triggers needs_setup card state
    auth_type: "API Key"             # ← or "Device Code", "OAuth2.1", etc.
```

#### 2. Add per-server guide in `setupInstructions.ts`

```typescript
// ADD to SERVER_GUIDES dict (fully additive):
'hp-your-server': {
  steps: [
    { title: 'Step 1', description: '...', link: { label: '...', url: '...' } },
    { title: 'Step 2', description: '...' },
  ],
  credentialLabel: 'API Key',
  credentialPlaceholder: 'your-key-format...',
},
```

#### 3. (If new auth type) Add to `AUTH_TYPE_GUIDES`

Only needed if the server uses an auth type not already handled:

| Existing types | Wizard behavior |
|----------------|----------------|
| `Open` | No setup needed, auto-ready |
| `API Key` / `API` | Show instructions → credential input → POST register |
| `OAuth2.1` / `OAuth` | Show info + server URL, OAuth handled by server |
| `OAuth2.1 & API Key` | Credential input (API key) or OAuth fallback |
| **`Device Code`** (NEW) | Interactive 2-step: start flow → show code → poll until done |

If adding a truly new auth pattern (e.g., SAML, WebAuthn), add:
1. A handler in `AUTH_TYPE_GUIDES`
2. A `needsXxxFlow()` helper function
3. A `renderXxxFlow()` function in `McpSetupWizard.tsx`

---

### Appendix B: Port Allocation

| Port | Server | Status |
|------|--------|--------|
| 9101-9105 | Core MCP servers | Active |
| 9106 | hp-teams (MS Teams) | Phase 1 ✅ |
| 9107 | hp-zoom (Zoom) | Phase 4 (future) |
| 9108 | hp-google-meet (or extend 9115) | Phase 4 (future) |
| 9110-9113 | Local tool servers | Active |
| 9114-9117 | Communication servers | Active |
| 9118-9119 | Developer servers | Active |
| 9120 | hp-inventory | Active |
| 9200+ | Community servers | Allocated dynamically |

---

## File Change Summary (Non-Destructive Audit — All Phases)

| Phase | File | Action | Existing Code Affected? |
|-------|------|--------|------------------------|
| 1 | `community/sample/generate_community_personas.py` | ADD persona entry | No — append to list |
| 1 | `agentic/forge/templates/server_catalog.yaml` | ADD optional server | No — append to list |
| 1 | `agentic/forge/templates/gateways.yaml` | ADD reference entry | No — append to list |
| 2 | `backend/app/teams/bridge/teams_bridge.py` | **CREATE** new file | No — new file |
| 2 | `backend/app/teams/bridge/__init__.py` | ADD registry + factory | No — additive imports |
| 2 | `backend/app/teams/rooms.py` | ADD optional `external_bridge` param | No — old callers unaffected |
| 2 | `backend/app/teams/orchestrator.py` | ADD bridge hooks | No — additive functions |
| 2 | `backend/app/main.py` | ADD 4 bridge endpoints | No — new routes only |
| 2 | `frontend/src/ui/teams/RoomBridgePanel.tsx` | **CREATE** new file | No — new file |
| 3 | `frontend/src/ui/mcp/setupInstructions.ts` | ADD `'hp-teams'` to `SERVER_GUIDES`, ADD `'Device Code'` to `AUTH_TYPE_GUIDES` | No — append to dicts |
| 3 | `frontend/src/ui/mcp/McpSetupWizard.tsx` | ADD `renderDeviceCodeFlow()` + conditional | No — additive branch |
| 3 | `frontend/src/ui/mcp/DeviceCodeFlow.tsx` | **CREATE** new file (optional extraction) | No — new file |
| 3 | `backend/app/agentic/registry_routes.py` | ADD 2 device-code endpoints | No — new routes |
| 3 | `agentic/forge/templates/server_catalog.yaml` | ADD `auth_type` field to hp-teams | No — new field |
| 4 | `backend/app/teams/bridge/zoom_bridge.py` | **CREATE** new file | No — new file |
| 4 | `backend/app/teams/bridge/meet_bridge.py` | **CREATE** new file | No — new file |
| 4 | `backend/app/teams/bridge/__init__.py` | ADD zoom + meet to registry | No — dict append |

**Zero existing files deleted or rewritten. Zero function signatures broken.**

---

## Testing Checklist

### Phase 1 (Server Registration)
- [ ] `teams-mcp-server` starts on port 9106 and responds to `/health`
- [ ] `POST /rpc` with `tools/list` returns 13 tools
- [ ] `POST /rpc` with `tools/call` + `teams.auth.status` returns auth state
- [ ] HomePilot `sync_homepilot()` discovers mcp-teams tools
- [ ] Persona with `teams.*` tools shows them in Equipment section

### Phase 2 (Bridge Integration)
- [ ] `TeamsBridge` connects successfully when mcp-teams is authenticated
- [ ] `TeamsBridge.send_event()` delivers messages to Teams channel
- [ ] `TeamsBridge.incoming_events()` yields new messages from Teams
- [ ] Room with `external_bridge` config persists and loads correctly
- [ ] Bridge start/stop lifecycle works in orchestrator
- [ ] REST endpoints return correct bridge status
- [ ] `RoomBridgePanel` displays and configures bridge settings
- [ ] Bidirectional, outbound-only, inbound-only modes all work

### Phase 3 (Auth + Tool Binding)
- [ ] `hp-teams` entry in `SERVER_GUIDES` renders correct setup steps
- [ ] Device code flow: start → show code → user completes → success
- [ ] `needsCredentialInput('Device Code')` returns `true`
- [ ] Device code poll endpoint correctly proxies to mcp-teams
- [ ] After auth, all 13 tools are discovered and registered
- [ ] Persona chat correctly routes `teams.*` tool calls to port 9106
- [ ] Existing setup wizard flows (API Key, OAuth) still work unchanged

### Phase 4 (Zoom + Meet)
- [ ] `zoom-mcp-server` starts on port 9107
- [ ] `ZoomBridge` connects and relays messages
- [ ] Google Meet tools work via extended `hp-google-calendar`
- [ ] `MeetBridge` creates meetings with Meet links
- [ ] All bridge providers available in Room Settings dropdown
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
# Microsoft Teams MCP Server (Phase 1)
TEAMS_MCP_HOST=0.0.0.0
TEAMS_MCP_PORT=9106
MS_TENANT_ID=common
MS_CLIENT_ID=<your-entra-app-client-id>
TEAMS_MCP_TOKEN_KEY=<fernet-key-for-token-encryption>

# Zoom MCP Server (Phase 4 — future)
ZOOM_MCP_PORT=9107
ZOOM_CLIENT_ID=<your-zoom-client-id>
ZOOM_CLIENT_SECRET=<your-zoom-client-secret>
```

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Azure AD app registration required | Certain | Medium | Setup wizard documents every step, provide defaults |
| Token expiration during long meetings | Low | Low | Auto-refresh built into teams-mcp-server |
| Rate limiting on Graph API | Low | Low | Built-in retry logic in GraphClient |
| Port conflict with other services | Very Low | Low | 9106-9108 reserved in port allocation table |
| Breaking existing Teams rooms | None | N/A | All changes are additive, bridge is optional |
| Device code flow timeout (900s) | Low | Low | Show countdown timer, allow restart |
| Bridge poll latency (3s intervals) | Low | Low | Configurable `_POLL_INTERVAL`, acceptable for chat |
| Zoom API deprecation | Very Low | Medium | Modular bridge pattern allows easy replacement |
| Google Meet chat API unavailable | Medium | Low | Bridge limited to meeting lifecycle, not chat relay |

---

## Phase 2.5: Live Meeting Bridge — COMPLETE

> **Built**: `session_01CQnRTUVEvENRF3114ijbvw` (March 2026)
> **Wired**: `session_012K2m2W36PS49BXM25CPJsA` (March 2026)
> **Branch**: `claude/apply-teams-mcp-upgrades-fp5Mw`

### What Was Built & Wired

Phase 2.5 implements the "Join Meeting" flow — paste a Teams meeting link,
select personas, and the bridge reads the live meeting chat in real-time.
Personas auto-react to incoming messages and post responses back to Teams.

#### teams-mcp-server (pushed to `claude/apply-teams-mcp-upgrades-fp5Mw`)

| File | Type | Purpose |
|------|------|---------|
| `src/teams_mcp/tools/tools_meeting_chat.py` | NEW | 4 tools: `teams.meeting_chat.resolve`, `.read`, `.post`, `.members` |
| `src/teams_mcp/tools/tools_meeting_join.py` | NEW | 3 tools: `teams.meeting.connect`, `.status`, `.disconnect` |
| `src/teams_mcp/tools/tools_voice.py` | NEW | 3 tools: `teams.voice.toggle`, `.status`, `.configure` (default: chat-only, STT off) |
| `src/teams_mcp/tools/__init__.py` | MODIFIED | Registered all 3 new tool modules in `ALL_TOOLS` (13 → 23 tools) |
| `src/teams_mcp/auth/scopes.py` | MODIFIED | Added `ChatMessage.Read`, `ChatMember.Read`, `OnlineMeetings.Read` |
| `tests/test_meeting_tools.py` | NEW | 26 unit tests: registration, URL parsing, sessions, voice, scopes, schemas |
| `tests/conftest.py` | NEW | Test config (dummy Fernet key for CI) |
| `.github/workflows/test.yml` | NEW | GitHub Actions CI (Python 3.10 + 3.12 matrix) |
| `Makefile` | NEW | `make install`, `make test`, `make lint` |

#### HomePilot (pushed to `claude/apply-teams-mcp-upgrades-fp5Mw`)

| File | Type | Purpose |
|------|------|---------|
| `backend/app/teams/bridge/teams_bridge.py` | NEW | `TeamsBridge` — connects to live Teams meetings via teams-mcp-server RPC |
| `backend/app/teams/bridge/chat_poller.py` | NEW | `ChatPoller` — background asyncio task polling Teams chat |
| `backend/app/teams/bridge/manager.py` | NEW | `BridgeManager` — singleton lifecycle manager |
| `backend/app/teams/bridge_routes.py` | NEW + P1a | REST API + `_on_bridge_messages` callback wiring |
| `backend/app/teams/orchestrator.py` | MODIFIED (P1b) | Bridge forwarding after persona message generation |
| `frontend/src/ui/teams/MeetingRoom.tsx` | MODIFIED (P1c) | `useBridge` hook + `BridgeStatusPanel` in right rail |
| `frontend/src/ui/teams/JoinMeetingWizard.tsx` | NEW | 3-step wizard: paste link → personas → settings |
| `frontend/src/ui/teams/BridgeStatusPanel.tsx` | NEW | Status panel with voice toggle + disconnect |
| `frontend/src/ui/teams/useBridge.ts` | NEW | React hook for bridge operations |

#### Completed Tasks

- [x] **P0**: Push teams-mcp-server changes (meeting chat, join, voice tools)
- [x] **P1a**: Wire auto-reactions — bridge callback triggers orchestrator
- [x] **P1b**: Wire response forwarding — persona messages posted back to Teams
- [x] **P1c**: Render BridgeStatusPanel in MeetingRoom right rail
- [x] **P2**: STT pipeline — whisper, deepgram, azure_speech backends + transcribe_chunk tool
- [x] **P3**: ACS scaffold — join/leave/status tools for Azure Communication Services

#### Remaining (manual / Azure infra)

- [ ] Azure Entra app registration (Azure Portal — add API permissions, grant consent)
- [ ] ACS resource provisioning (Azure Portal — for real-time audio capture)
- [ ] Wire `azure-communication-calling` SDK into ACS client (currently scaffold)

### Architecture: Data Flow

```
Teams Meeting (chat + audio)
    │
    ▼  Microsoft Graph API
teams-mcp-server :9106  (27 tools, 58 tests, CI)
    ├── meeting chat tools      resolve / read / post / members    ✅
    ├── meeting session tools   connect / status / disconnect      ✅
    ├── voice / STT tools       toggle / status / configure / transcribe_chunk  ✅
    ├── ACS tools (scaffold)    join / status / leave              ✅
    │
    ▼  JSON-RPC /rpc
HomePilot Backend
    ├── TeamsBridge + ChatPoller    polls chat every 5s             ✅
    ├── BridgeManager              lifecycle + reaction callback   ✅
    ├── bridge_routes.py           REST API + auto-reactions       ✅
    ├── Orchestrator                auto-triggered + forwarding    ✅
    │
    ▼  WebSocket / REST
HomePilot Frontend
    ├── JoinMeetingWizard          paste link → personas → config  ✅
    ├── BridgeStatusPanel          status + voice + disconnect     ✅
    └── useBridge hook             connect / disconnect / poll     ✅
```
