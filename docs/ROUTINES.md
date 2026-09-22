# Routines

Routines are user-owned schedule definitions for HomePilot. They are designed so
HomePilot remains the source of truth while optional clients (including the
3D Avatar Chatbot) can display and manage the same definitions.

## Ownership boundary

HomePilot owns:

- routine persistence
- user ownership and permissions
- timezone and schedule definitions
- action parameters
- delivery preferences
- future execution history / scheduler state

Companion clients own presentation only:

- voice input
- cards / status UI
- TTS playback
- avatar emotion / animation

A companion must not keep an independent routine database or timer.

## V1 scope

V1 is intentionally definition-only. It adds CRUD and the HomePilot Routines
tab, but it does **not** start a background scheduler or execute actions.

This makes the first release inert by default: adding the tab cannot cause
emails, notifications, web requests, speech, or other actions to happen in the
background.

Supported action definitions:

- `news_digest`
- `daily_briefing`
- `reminder`
- `assistant_prompt`

Supported schedule definitions:

- `daily`
- `weekly`
- `once`

## API

### Capability probe

`GET /v1/routines/capabilities`

The probe is intentionally public and contains no personal data. A client can
use it to decide whether to show optional routine controls.

### List

`GET /v1/routines`

Returns routines owned by the current HomePilot user. Logged-in installs use
the normal bearer/cookie identity. Legacy single-user installs fall back to
their default user. Anonymous ownership is never guessed on multi-user installs.

### Create

`POST /v1/routines`

Example:

```json
{
  "name": "Morning news",
  "enabled": true,
  "timezone": "Europe/Rome",
  "schedule": {
    "type": "daily",
    "time": "08:00",
    "days": []
  },
  "action": {
    "type": "news_digest",
    "parameters": {
      "scope": ["local", "national", "world"],
      "max_items": 6
    }
  },
  "delivery": {
    "in_app": true,
    "speak_if_active": true,
    "catch_up": true
  }
}
```

### Update

`PATCH /v1/routines/{id}`

Partial update. Example:

```json
{
  "enabled": false
}
```

### Remove

`DELETE /v1/routines/{id}`

Removal is a soft delete. The row is archived rather than destroyed, leaving a
safe path for a future Undo UI and audit tooling.

## Optional 3D Avatar usage

The avatar should treat routines as a HomePilot capability:

```text
User voice/text
      |
      v
3D Avatar / OllaBridge
      |
      v
HomePilot routine API / conversational intent
      |
      v
HomePilot-owned routine
```

For a lightweight UI, the avatar can:

1. probe `/v1/routines/capabilities`
2. list `/v1/routines`
3. show today's/active routines
4. send create/update/delete intents back to HomePilot

It should not schedule timers in browser JavaScript.

## Execution phase

A later execution layer should be additive and independently switchable:

```text
routine definitions (this module)
        |
        v
due-time calculator
        |
        v
idempotent run claim
        |
        v
safe action executor
        |
        +-- news_digest -> hp-news preferred, hp.web.search fallback
        +-- reminder -> in-app event
        +-- daily_briefing -> secretary briefing workflow
        +-- assistant_prompt -> approved informational prompt
```

Write-capable actions (sending messages, changing files, purchases, smart-home
control, etc.) should remain outside the default routine action set and respect
HomePilot's ask-before-acting permission model.

## Non-destructive rules

- New code lives under `backend/app/routines/` and
  `frontend/src/ui/routines/`.
- Existing chat, voice, avatar and project stores are untouched.
- The main backend only mounts one new router.
- The main frontend only imports the view, adds one `Mode`, one sidebar item,
  and one render branch.
- Deleting a routine archives it.
- No background work starts in V1.
