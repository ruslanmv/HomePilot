# Routines

Routines turn HomePilot from a purely reactive assistant into an optional,
user-owned automation layer. HomePilot remains the source of truth for schedule
definitions, execution, conversations, notifications, and history. Optional
clients such as the 3D Avatar only present the same HomePilot-owned result.

## Core model

Each routine answers four questions:

1. **What task?** `news_digest`, `daily_briefing`, `reminder`, or
   `assistant_prompt` — a standing task the assistant carries out, shown in the UI as
   *Assistant task*. (The id keeps its original spelling so existing routines keep
   working.)
2. **Who / where?** HomePilot assistant, a Persona project, or a normal Project.
3. **When?** Daily, selected weekdays, or once, in an IANA timezone.
4. **How should it be delivered?** Notification, optional companion speech, and
   catch-up behavior.

Every successful run is saved as a native HomePilot conversation. This is an
intentional invariant: a notification is a pointer to a real conversation, not
a disposable blob of text.

### A routine is something HomePilot does, not something you said

This is the load-bearing distinction, and it decides how a run is stored.

A routine is a **standing task for the assistant**. When it comes due, HomePilot carries the
task out on its own and leaves the answer in a new conversation you can open, read and
continue — an Alexa routine that happens to also be a thread.

What it is *not* is a saved message from you. Routines used to work that way: the prepared
instruction was handed to the chat pipeline as the user's message, so every run opened its
conversation with a first-person line — *"Prepare my morning news briefing for today."* —
attributed to you, at 7am, while you were asleep. Three things were wrong with that:

* **the record lied about who said what**, and nothing downstream could tell — not the
  reader, not search, not memory, not a later summary of the thread;
* **your first real message landed second**, in a conversation that already misrepresented
  you, so the model's picture of you was wrong from its first turn;
* it made a routine look like a macro that replays typing, which is the wrong mental model
  for something that is supposed to act by itself.

So a routine's opening turn is stored with `role="system"` and reads as what it is:

```
Scheduled routine "Morning news" ran automatically at 07:04 on Sep 24.
Task: Prepare today's news briefing for the user from the current information supplied.
```

The chat surface renders that as a quiet marker line above the answer rather than as a chat
bubble, so a conversation that appeared by itself explains why it exists. Nothing about the
generated answer changes: conversation history is mapped role-for-role into the provider
call, so the model reads the same words it always did. **Only the attribution changes, and
the attribution was the bug.**

The rule is one flag, `system_initiated`, carried on the chat payload and honoured by both
persistence paths (`orchestrator.orchestrate` and `projects.run_project_chat`). It defaults
to `False`, so an ordinary message is still the user's.

### The conversation has to be readable by the person it was made for

`add_message` infers an owner when none is passed, and its last resort is the **default
user** — right for a single-user install typing into the app, wrong for anything that
creates a conversation on somebody's behalf. `get_messages` inner-joins
`conversation_owners`, so a conversation owned by the wrong user returns zero rows to the
person it belongs to, and *Open latest* opens a completely blank chat.

Both chat paths therefore **claim the conversation before writing to it**:

```python
if user_id:
    ensure_conversation_owner(cid, user_id)
```

Once, at the top, rather than threading `user_id=` through every `add_message` call —
there are fourteen on the chat path alone, and the next one added would silently
reintroduce the bug.

### The prompt and the record are different artifacts

Storing the routine's turn as `system` fixes the attribution and, on its own, breaks the
answer: a prompt whose every message is `system` is a shape many providers handle badly and
some openai-compatible endpoints reject outright.

So the turn is **re-roled on its way to the model and nowhere else**. What the model
receives is the familiar shape — the persona or project system prompt, then the task as a
user turn — while what is stored stays `system`, attributed to nobody. Only the final
history entry is eligible, and only when it is the system turn that same call just wrote.

| | Model sees | Storage keeps |
|---|---|---|
| Persona/project instructions | `system` | — |
| The routine's task | `user` | `system` |
| The answer | — | `assistant` |

### Opening a run's conversation

*Open* on a run loads that conversation and switches the app into chat. The order of those
two is load-bearing.

The chat surface resets the conversation whenever the **mode group** changes, so that a
transcript never bleeds into an image-edit or animate session
(`frontend/src/ui/lib/modeGroups.ts`). Routines is an `other` surface and chat is a `chat`
surface, so arriving in chat *from* Routines is a group change — and the reset runs after
the commit that changed the mode.

`loadConversation` used to switch mode after its fetch, which put `setMode`,
`setConversationId` and `setMessages` in a single commit. The reset then ran next and wiped
the messages that had just arrived: every routine's *Open* landed on an empty chat. It now
switches **before** fetching, so the reset happens while there is nothing to lose and the
loaded messages land last. A fetch cannot resolve before React flushes the effect, so this
is deterministic rather than a race.

The History list was unaffected only because it happened to call `setMode('chat')` itself
before loading; everything that relied on `loadConversation` alone was broken.

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

- **Start from a template** — ten ready-made routines, behind one dropdown (see below)
- create/edit/remove
- enable/pause
- searchable `Run with` picker grouped into HomePilot, Personas, and Projects
- daily/weekdays/custom-day schedules
- optional city/region for local news prioritization
- local timezone
- notification preference
- optional companion speech
- catch-up preference

### The shape of the form

The creation form reads top to bottom as **name → task → context → schedule → delivery →
create**, and the only optional thing in it — templates — sits in the header as a single
button rather than in the flow.

That ordering is a correction. The first version opened with a section of nine template
cards, then asked for a name, then offered *another* grid of four cards for the action type:
thirteen large targets to read before the first field of the thing the user actually came to
create. Two problems came out of that, and both are fixed here rather than restyled:

* **Optional work looked compulsory.** A shortcut that occupies the first screen is not read
  as a shortcut. It is one dropdown now, and the menu stays shut until asked for. Once a
  template is applied the button names it and a single line under the header says so —
  no second card repeating what the fields below already show.
* **The same question was asked twice.** Templates are named *Morning news*, *Start my day*,
  *Daily reminder*; the action cards were named *Today's news*, *Daily briefing*, *Reminder*.
  Choosing "Morning news" and then being asked to choose "Today's news" reads as the form
  not having listened. So the four action types stopped being a card grid and became
  suggestions under one **What should HomePilot do?** field — which is what they always
  were. `news_digest` and `daily_briefing` take no free text, so for those the field shows
  what will happen instead of an input bound to nothing.

The names for those four live in one place (`taskKindLabel`), shared by the field and the
routine list's badge, so the list cannot drift into calling something "Today's news" beside
a field that calls it "News".

`Run with` is a searchable picker rather than a native `<select>`: on an install with a few
dozen personas and projects, a dropdown of every one of them stops being usable, and there
is no recency data to shortlist honestly — so it offers search over a grouped, scrolling
list instead.

### Templates

The hardest question on the form is *what should HomePilot do?* — a writing task, and a good
answer looks nothing like the one-line placeholder most people type. So the header offers
worked examples (`frontend/src/ui/routines/presets.ts`), grouped **Popular · Work ·
Personal** and searchable.

Picking one fills in name, schedule and task, and closes. Nothing stays expanded, and the
form beneath is ordinary and fully editable — a template is a shortcut that fills the form,
not a mode the routine is now in. Editing an existing routine offers no templates at all:
overwriting name, schedule and task in one click is helpful on a blank form and destructive
on a routine that has been running for a month.

| Template | Group | Action | Default schedule | Best run with |
|---|---|---|---|---|
| Morning news | Popular | `news_digest` | Daily 07:00 | HomePilot |
| Start my day | Popular | `daily_briefing` | Weekdays 08:00 | HomePilot |
| Evening wind-down | Popular | `assistant_prompt` | Daily 21:30 | HomePilot |
| Stand-up prep | Work | `assistant_prompt` | Weekdays 08:45 | a Project |
| Sunday reset | Work | `assistant_prompt` | Sundays 18:00 | a Project |
| Field watch | Work | `assistant_prompt` | Weekdays 17:00 | HomePilot |
| Daily reminder | Personal | `reminder` | Daily 09:00 | HomePilot |
| Move of the day | Personal | `assistant_prompt` | Daily 12:30 | HomePilot |
| Bedtime story | Personal | `assistant_prompt` | Daily 19:45 | a Persona |
| Language practice | Personal | `assistant_prompt` | Daily 08:15 | a Persona |

Four rules hold the list together, and each is asserted by a test:

* **Nothing in it can fail on a fresh install.** Every template uses an action HomePilot
  ships with — the model itself, hp-news, or the default web search. The obvious missing
  candidates are email triage and a calendar look-ahead, which the Secretary workflows
  (`secretary_email_triage`, `secretary_meeting_prep`) already implement but which need
  credentials. A picker whose first row errors because a connector is absent teaches people
  that templates do not work, and they stop opening it.
* **Every task is written as a task** — imperative, addressed to the assistant, never in the
  user's voice. This is the same rule the executor enforces when it stores a routine's
  opening turn as `system`. A first-person template would put the fabricated user turn back
  into every routine created from it, typed in by the product rather than by the code.
* **Each task says what to do when there is nothing to report.** Left unsaid, a small local
  model fills the silence, and a stand-up that invents progress is worse than one that says
  the notes were empty.
* **A template fills in what it is entitled to decide** — name, schedule, task — and nothing
  else. Timezone and delivery keep the form's values, so picking a template never quietly
  undoes a preference set two fields above it. The target is never set either: a template
  cannot know your project ids, so where it wants to run is shown as advice beside the
  `Run with` picker.

Templates are gated on the action types `/v1/routines/capabilities` reports, so a build that
drops an action stops offering templates that need it.
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

Raw tool JSON never reaches the conversation — it goes into hidden orchestration context,
not into a visible turn.

Each action returns an **`instruction`**: an imperative task addressed to the assistant
("Prepare today's news briefing for the user"), never a first-person line in the user's
voice ("Give me my daily briefing"). The phrasing is part of the contract rather than a
style preference — a first-person instruction is what made the forged turn read as normal,
and it also cues the model to answer as though someone had just spoken to it, which nobody
had.

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
