# DayPilot bridge (propose-only)

HomePilot owns the agents; **DayPilot connects to them and manages their work.**
DayPilot talks to a HomePilot persona over the OpenAI-compatible
`POST /v1/chat/completions` endpoint in **propose-only** mode. The persona
reasons with its full identity and memory but never performs external writes —
it *proposes* structured operations, and DayPilot validates and approves them.

Implemented in `backend/app/daypilot_bridge/` and wired into
`backend/app/openai_compat_endpoint.py`.

## Request headers

| Header | Value | Meaning |
| --- | --- | --- |
| `X-Client-Type` | `daypilot` | Identifies the bridge client (activates bridge fields). |
| `X-HomePilot-Tool-Mode` | `propose` | Only mode used in production. Unknown values fall back to `propose`. |
| `X-HomePilot-Session-ID` | opaque id | DayPilot's external session id, echoed back for correlation. |
| `X-HomePilot-Bridge-Version` | `1` | Protocol version. |

The bridge is *active* when `X-Client-Type: daypilot` **or** any bridge header is
present. In propose mode HomePilot appends a **separate** system message telling
the persona it cannot act on the outside world itself and how to propose actions.
The persona's own system prompt is never modified.

## How a persona proposes an action

The persona replies normally, then — only when it intends a concrete action or
wants to track work — appends one machine block at the very end:

```
[[DAYPILOT_DIRECTIVES]]{"directives":[
  {"type":"task.create","title":"Draft the Q3 report","priority":"high"},
  {"type":"daypilot.action.propose","capability":"email.send","summary":"Email Bob the update","arguments":{"to":"bob@acme.com"}}
]}[[/DAYPILOT_DIRECTIVES]]
```

HomePilot parses that block, **strips it from the visible reply**, validates it
defensively (model output is untrusted), and returns the result. Malformed JSON
or unknown directive types are dropped while the plain-text reply is preserved.

**Allowed directive types:** `task.create`, `task.update`, `task.complete`,
`task.block`, `progress.report`, `delegate.request`, `daypilot.action.propose`,
`artifact.attach`.

**Capabilities** (only for `daypilot.action.propose`; each still becomes a draft
+ Approval on DayPilot): `email.send`, `calendar.create`, `calendar.update`,
`calendar.cancel`, `coding.run`, `github.change`, `message.send`,
`document.generate`, `finance.change`, `hr.change`, `system.change`.

Bounds: at most 12 directives/turn; titles ≤ 200 chars; text ≤ 4000 chars.

## Response fields

For a bridge client the response carries two extra fields alongside the standard
OpenAI-compatible body:

```jsonc
{
  "choices": [ ... ],                 // visible reply, machine block removed
  "x_directives": {
    "version": 1,
    "tool_mode": "propose",
    "items": [ /* validated directives */ ]
  },
  "x_homepilot": {
    "bridge_version": 1,
    "tool_mode": "propose",
    "session_id": "<echoed>",
    "project_id": "<persona project id or null>",
    "model": "persona:<id>",
    "directive_count": 2
  }
}
```

Both fields are present on every bridge turn — even when the persona proposed
nothing (`items: []`) — so DayPilot can always correlate the turn.

## Capability discovery

`GET /v1/integrations/daypilot/capabilities` returns a static document listing
the supported tool modes, directive types, capabilities, limits, and header
names — so DayPilot can feature-detect a bridge-aware HomePilot without a chat
round-trip.

## Account identity (multi-account security)

`GET /v1/integrations/daypilot/identity` reports which HomePilot account a
DayPilot connection is bound to, so a user's agents can never blend with
another's:

```jsonc
{ "bridge_version": 1, "account_ref": "user:42", "account_label": "Ana", "authenticated": true, "scope": "account" }
```

- A request carrying a **specific user's token** (Bearer JWT or the
  `homepilot_session` cookie) resolves to that user — `scope: "account"`, and
  DayPilot syncs only that account's agents.
- The **shared instance key** resolves to `scope: "shared"` (`account_ref:
  "shared"`) — published personas with no single owner.

No secret is ever returned. DayPilot records `account_ref` on the connection and
stamps every synced agent with it; if the bound account changes, DayPilot
re-scopes rather than mixing accounts. Cloud (`homepilot.ruslanmv.com`) and local
installs use the same endpoint, so a cloud connection is bound to the cloud
account automatically.

## Guarantees

- HomePilot never sends email, changes files, schedules events, or completes
  tasks on DayPilot's behalf — it only proposes.
- The persona's stored system prompt and memory are untouched by the bridge.
- Non-bridge clients (VR, plain OpenAI SDKs) see no bridge fields and no
  behavior change.
