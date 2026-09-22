# Routines

Routines turn HomePilot from a purely reactive assistant into an optional,
user-owned automation layer. HomePilot remains the source of truth for schedule
definitions, execution, conversations, notifications, and history. Optional
clients such as the 3D Avatar only present the same HomePilot-owned result.

## Core model

Each routine answers four questions:

1. **What?** `news_digest`, `daily_briefing`, `reminder`, or
   `assistant_prompt`.
2. **Who / where?** HomePilot assistant, a Persona project, or a normal Project.
3. **When?** Daily, selected weekdays, or once, in an IANA timezone.
4. **How should it be delivered?** Notification, optional companion speech, and
   catch-up behavior.

Every successful run is saved as a native HomePilot conversation. This is an
intentional invariant: a notification is a pointer to a real conversation, not
a disposable blob of text.

## Ownership boundary

HomePilot owns:

- per-user routine definitions
- target context and schedule resolution
- timezone/DST handling
- action execution
- native conversation/session creation
- durable `routine_runs` history
- notifications and read/open state
- scheduler and catch-up behavior
- structured completion events

Companion clients own presentation only:

- voice input
- routine cards/status UI
- TTS playback
- avatar emotion/animation

A companion must not keep an independent routine database or browser timer.

## Targets

### Assistant

A fresh normal HomePilot conversation is created for the run.

### Persona

The target is a HomePilot project with `project_type: "persona"`. Scheduled
runs call the existing persona session factory with `force_new=True`, creating
a discrete session such as:

```text
Sofia
  Morning news · Sep 22
  Morning news · Sep 23
  Morning news · Sep 24
```

The sessions remain separate while continuing to use the persona project's
existing instructions, RAG context, and long-term memory.

### Project

A fresh conversation ID is created and the request is passed through the
existing project chat pipeline, preserving project instructions, files, RAG,
and agent/persona context.

## UI

The Routines tab supports:

- create/edit/remove
- enable/pause
- `Run with` selector grouped into HomePilot, Personas, and Projects
- daily/weekdays/custom-day schedules
- optional city/region for local news prioritization
- local timezone
- notification preference
- optional companion speech
- catch-up preference
- **Run now**
- latest-run status
- **Open latest**
- execution history

The editor always shows **Save as a conversation** as enabled because native
conversation persistence is part of the Routines contract.

## API

### Capabilities

`GET /v1/routines/capabilities`

The response reports whether the server supports manual execution only or has
automatic scheduling enabled:

```json
{
  "available": true,
  "version": 2,
  "execution": "manual",
  "scheduler_enabled": false,
  "target_types": ["assistant", "persona", "project"],
  "companion_compatible": true
}
```

### Definition CRUD

- `GET /v1/routines`
- `POST /v1/routines`
- `PATCH /v1/routines/{routine_id}`
- `DELETE /v1/routines/{routine_id}`

Delete is a soft delete.

Example:

```json
{
  "name": "Morning news",
  "enabled": true,
  "timezone": "Europe/Rome",
  "schedule": {
    "type": "daily",
    "time": "05:43"
  },
  "target": {
    "type": "persona",
    "project_id": "persona-project-sofia"
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
    "notification": true,
    "create_conversation": true,
    "speak_if_active": true,
    "catch_up": true
  }
}
```

### Manual execution

`POST /v1/routines/{routine_id}/run`

Manual execution is available even when the background scheduler is disabled.

### Run history

- `GET /v1/routines/runs`
- `GET /v1/routines/{routine_id}/runs`
- `PATCH /v1/routines/runs/{run_id}/seen?opened=true|false`

Runs use a unique `run_key` so scheduler retries cannot execute the same
scheduled occurrence twice.

### Completion stream

`GET /v1/routines/events?since={sequence}`

This authenticated SSE stream emits `routine.completed` events to active
HomePilot/companion clients. The stream is a low-latency transport only; SQLite
run history remains the durable recovery source.

Example event:

```json
{
  "type": "routine.completed",
  "run_id": "run-123",
  "routine": {
    "id": "routine-123",
    "name": "Morning news"
  },
  "target": {
    "type": "persona",
    "project_id": "persona-project-sofia"
  },
  "project_id": "persona-project-sofia",
  "conversation_id": "conv-456",
  "presentation": {
    "speech_text": "Buongiorno. Ecco le notizie principali...",
    "display_markdown": "## Morning news\n...",
    "sources": [],
    "avatar": {
      "emotion": "thinking",
      "intensity": 0.6
    }
  }
}
```

## News and briefing execution

`news_digest` is read-only:

1. when a News location is configured, try hp-news `news.search` for that city/region
2. otherwise (or if local search is unavailable), try hp-news `news.top`
3. fall back to `hp.web.search`
4. pass retrieved current information into hidden orchestration context
5. generate the final response through the selected assistant/persona/project
   chat pipeline
6. store the human-readable response as the native conversation

Raw tool JSON is not inserted as the visible user message.

`daily_briefing` reuses the existing Secretary Daily Briefing workflow hints
and current-information tools, while avoiding claims of calendar/email access
unless that context is actually available.

## Scheduler

Automatic scheduling is deliberately opt-in at the HomePilot server level.

```bash
ROUTINES_EXECUTION_ENABLED=true
```

Restart HomePilot after changing the flag.

When disabled:

- routine CRUD works
- **Run now** works
- history and notifications work
- no timed background routine fires

When enabled, the scheduler:

- uses `zoneinfo` / IANA timezone names
- handles DST without storing fixed UTC offsets
- wakes on a short configurable interval
- atomically claims each scheduled occurrence
- skips duplicate claims
- marks stale non-catch-up runs as `missed`
- executes catch-up-enabled routines after downtime

Optional settings:

```text
ROUTINES_SCHEDULER_INTERVAL_SECONDS=30
ROUTINES_ON_TIME_GRACE_SECONDS=90
```

## Notification behavior

A completed routine never forces the user away from their current HomePilot
screen. The global notification shows a preview and offers:

- **Open conversation**
- **Dismiss**

Opening restores the run's target project/persona context (when present), marks
the run opened, and uses HomePilot's existing conversation loader to display the
generated thread.

## Optional 3D Avatar integration

The avatar should probe HomePilot and consume the completion stream:

```text
HomePilot scheduler / Run now
        |
        v
safe action executor
        |
        v
native HomePilot conversation
        |
        +--> routine_runs (durable)
        |
        +--> HomePilot notification
        |
        +--> routine.completed SSE
                  |
                  v
          optional 3D Avatar
          display + TTS + emotion
```

The avatar must not implement another scheduler. `speech_text` is already
separated from `display_markdown`, so raw Markdown or internal emotion markers
do not need to be spoken.

## Safety boundary

The default action set is informational/read-only. Write-capable actions such as
sending messages, changing files, purchases, or smart-home control are not part
of this Routines executor and must continue to respect HomePilot's existing
authorization / ask-before-acting model.

## Compatibility

- Existing v1 routine rows are migrated additively with
  `target = assistant`.
- Existing delivery rows receive safe defaults when decoded.
- Routine deletion stays soft-delete.
- New frontend + scheduler-disabled backend remains manually executable.
- Optional hp-news absence falls back to `hp.web.search`.
- Optional companion absence does not affect normal HomePilot notifications.
