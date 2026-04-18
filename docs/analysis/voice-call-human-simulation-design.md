# Voice-Call Human Simulation — Design Notes

**Status:** design document (additive, non-destructive). Describes how
HomePilot's voice-call feature simulates human phone behavior for each
persona without mutating the persona's base system prompt.

**Scope:** the two additive backend modules already on this branch —
`backend/app/voice_call/` (transport + turn loop) and
`backend/app/persona_call/` (per-turn behavioral composer) — plus the
thin frontend affordances in the chat and voice headers.

**Non-goals:** rewriting persona prompts, replacing the STT/TTS stack,
changing the chat endpoint contract, or shipping any destructive DB
migration.

---

## 1. Design constraints (from the user)

1. **Additive only.** New files or new optional parameters. No renames,
   no deletes, no behavior change when the feature flag is off.
2. **Keep each persona's core personality intact.** The composer
   produces a short *suffix* appended as an extra system message. It
   never replaces the persona's base system prompt.
3. **Only during a live call.** The suffix is composed inside the voice
   WebSocket turn loop. The normal chat endpoint never sees it.
4. **Not repetitive.** An anti-repetition ledger forbids the last few
   openers/acks the persona just said.
5. **Dynamic + situational.** Per-turn composition reads local clock,
   caller-state cues (driving, rushed), and phase in the call.

## 2. Research grounding

The composer's rules are drawn from four well-established strands of
conversation analysis. Citations are to canonical sources; nothing
here is novel research — we're just encoding the consensus:

- **Opening structure** — Schegloff (1968), "Sequencing in
  Conversational Openings": phone calls open with a summons/answer
  pair, an identification/recognition pair, a greeting pair, and a
  how-are-you pair. The phase machine reflects this ordering and lets
  the caller skip `how-are-you` when time-pressured.
- **Turn-taking** — Sacks, Schegloff, Jefferson (1974), "A simplest
  systematics for the organization of turn-taking for conversation":
  TRPs (transition-relevance places) are cued by clause boundaries
  and intonation. The backchannel emitter triggers on clause
  boundaries (comma, "and then", "so") with a minimum gap to avoid
  stepping on the speaker.
- **Backchannels** — Jefferson (1984), "Notes on a systematic
  deployment of the acknowledgment tokens 'Yeah' and 'Mm hm'": tokens
  cycle; repetition sounds robotic. The ledger rolls the last N and
  forbids them on the next turn.
- **Response timing** — Stivers et al. (2009), "Universals and
  cultural variation in turn-taking in conversation": cross-language
  modal response latency is ~200 ms. Anything over ~1 s reads as a
  trouble signal. Our filler scheduler emits a thinking-token after
  the configured threshold (default 600 ms) to fill the gap.

## 3. Architecture

```
chat UI ──▶ [emerald 📞 button] ──▶ sets mode=voice
voice UI ──▶ [red 📞⊘ button]   ──▶ onClose() ends the call

voice WS   ──▶ voice_call/ws.py
                │
                ├─ on transcript.final:
                │    ├─ persona_call.directive.compose(...)   (pure)
                │    │    ├─ context.compute_env       (clock + tz)
                │    │    ├─ context.classify_utterance (regex)
                │    │    ├─ state.advance_phase      (opening→topic→…)
                │    │    ├─ repeat.forbidden_tokens  (ledger)
                │    │    ├─ facets.for_persona_id    (per-persona style)
                │    │    └─ closing.compose_handshake
                │    │
                │    ├─ turn.run_turn(..., additional_system=suffix)
                │    │        └─ sent as an extra system msg to /chat
                │    │
                │    └─ persona_call.directive.record_persona_reply
                │         └─ rolls ledger for next turn
                │
                └─ during turn:
                     └─ latency.FillerScheduler
                          └─ emits "hmm…" if the model is slow
```

Two flags, both default-off, both checked every turn:

- `PERSONA_CALL_ENABLED` — compose directives, emit fillers/
  backchannels, persist ledger/phase rows.
- `PERSONA_CALL_APPLY` — actually append the suffix to the chat
  request. When false, the module runs in *shadow mode*: it computes
  directives and records phase state, but the LLM receives only the
  unmodified persona prompt. Useful for dogfooding without changing
  LLM output.

When both are false, `voice_call/ws.py` takes the original
unchanged path: `turn.run_turn(user_text, model, auth_bearer)` with
no `additional_system`. Zero behavior delta.

## 4. The per-turn composer

`persona_call.directive.compose(...)` returns a `ComposedDirective`
with two fields that matter at runtime:

- `system_suffix: str` — the text to append as an extra system
  message. Empty when nothing notable applies.
- `post_directives: list[str]` — machine-readable tags (e.g.
  `opening.skip_how_are_you`, `context.late_night_brevity`) used by
  tests and future introspection endpoints.

Crucially, the dataclass has **no `system_prompt` field**. A
structural test (`test_persona_call_never_overrides_system_prompt`)
asserts this. The point is to make it impossible to accidentally
rewrite a persona's voice — the composer only knows how to append a
suffix.

### 4.1 Phase machine

States: `opening → topic → pre_closing → closed`.

- `opening` — turn 1. Persona answers the summons. If the caller
  expresses a reason or time pressure in the first few turns, phase
  moves to `topic`. Otherwise it stays in `opening` until a
  reason-for-call regex matches.
- `topic` — the bulk of the call. No structural directives unless
  the local-context rules fire (late-night brevity, morning energy).
- `pre_closing` — caller or persona issues a closing-initiating token
  ("okay", "alright", "thanks for your time"). Composer tells the
  persona: *don't say "goodbye" yet — wait for the caller's
  closing*. This is the only enforced state override.
- `closed` — caller said bye. Composer tells the persona to produce
  a two-part terminal: a brief acknowledgment and a brief farewell.

State is persisted per session in the `persona_call_state` table
(phase, turn_index, caller_signal_json, ledger). All writes are
idempotent within a turn.

### 4.2 Anti-repetition ledger

`recent_acks` and `recent_openers` are small FIFO lists. When the
persona's last reply starts with or contains a known ack token
(`mm`, `mm-hm`, `uh-huh`, `gotcha`, …), we push it onto the
appropriate list and trim to the configured window (default 3).

On the next turn, `repeat.forbidden_tokens` pulls the current window
and adds a short line to the suffix like:

> You just used: **mm**, **mm-hm**. Pick a different backchannel
> this turn.

The `repeat.ledger` post-directive is emitted so tests can assert
the rule fired.

### 4.3 Local context rules

- **Late-night brevity** — if `local_hour` is within
  `[PERSONA_CALL_LATE_HOUR, PERSONA_CALL_LATE_HOUR_END)` (default
  22:00–06:00), suffix adds a "it's late — keep it short" frame.
- **Morning energy** — configurable optional frame (off by default).
- **Caller-state frames** — if `classify_utterance` flags
  `driving=True` or `time_pressured=True`, suffix adds a
  one-sentence-cap frame. If `transit=True`, suffix adds a
  "speak plainly, background noise is likely" frame.

Every frame is a single short sentence. The entire suffix rarely
exceeds ~400 characters. The persona's base prompt stays in full.

### 4.4 Closing handshake

Two-phase. When the caller produces a closing token while in `topic`,
we transition to `pre_closing` and emit:

> The caller is closing. Acknowledge warmly but **do not say
> 'goodbye'** yet — wait for the caller to end.

On the next turn, if the caller says "bye"/"see ya"/"talk later",
we transition to `closed` and emit a terminal directive. The
two-part shape ("okay, thanks — bye!") is the cross-cultural
default per Schegloff & Sacks (1973), "Opening up closings".

## 5. Prompt suffix shape

One example (persona: default assistant, local 22:15, caller says
"I'm driving, quick question"):

```
[additional system — phone call context, this turn only]
- It is 22:15 locally. It is late; keep replies brief.
- The caller says they are driving. Keep it to one short sentence
  this turn. Do not ask clarifying questions.
- You recently used: "mm", "mm-hm". Pick a different backchannel
  this turn.
```

Delivered as one extra `role: system` message on the OpenAI/Ollama
chat call, appended *after* the persona's full system prompt. The
persona's voice, goals, and knowledge stay exactly as written.

## 6. Event model (server → client)

Three new event types, all optional, all namespaced:

- `assistant.backchannel` — emitted from the turn loop when the
  backchannel emitter decides a "mm-hm" would be natural. Client
  plays it as a short TTS clip (or skips if muted). Never blocks the
  reply.
- `assistant.filler` — emitted by the filler scheduler if the LLM
  takes longer than the configured threshold. Fires exactly once per
  slow turn. Token chosen from the persona's `thinking_tokens`.
- `safety.notice` — reserved; already sketched in the voice_call
  envelope protocol. No wiring yet.

The existing `transcript.final` event for the assistant reply is
unchanged. Clients that don't handle the new event types simply
ignore them (forward-compatible by design).

## 7. Evaluation plan

Manual: pair-test a handful of scripts with one composer user and
one control user on the same persona. Score for naturalness,
repetition, and whether the persona "sounds like themselves". Goal
is no regression on the third axis.

Automated: the `backend/tests/test_persona_call.py` suite covers the
seven rules end-to-end without reloading `app.main`. Twelve tests.
Each test is anchored to one rule from the research digest, so a
failing test points straight at the broken rule.

## 8. Recommended defaults

| Flag / knob                        | Default | Notes                           |
|------------------------------------|---------|---------------------------------|
| `PERSONA_CALL_ENABLED`             | `false` | Off in prod until dogfooded     |
| `PERSONA_CALL_APPLY`               | `false` | Shadow mode flips to true later |
| `PERSONA_CALL_LATE_HOUR`           | `22`    | Local hour (24h)                |
| `PERSONA_CALL_LATE_HOUR_END`       | `6`     | Local hour (24h)                |
| `PERSONA_CALL_FILLER_AFTER_MS`     | `600`   | Thinking-token latency trigger  |
| `PERSONA_CALL_BACKCHANNEL_MIN_GAP` | `1500`  | ms between backchannels         |
| `PERSONA_CALL_LEDGER_WINDOW`       | `3`     | forbidden tokens per turn       |
| `PERSONA_CALL_REASON_FALLBACK_TURN`| `3`     | promote to `topic` by turn N    |

## 9. Rollout

1. **Shadow mode.** Flip `PERSONA_CALL_ENABLED=true`,
   `PERSONA_CALL_APPLY=false`. Record directives + phase state to
   the DB. Sample a few sessions by hand and see whether the
   composer's decisions match what we'd want to have said. Zero
   user-visible change.
2. **Internal flip.** Flip `PERSONA_CALL_APPLY=true` for a small set
   of internal users. Watch the three new event types. Listen for
   repetition, rushed endings, or persona drift.
3. **Public rollout.** Default both flags to `true`. Keep the
   shadow-mode path alive for debugging.

At every stage, both flags can be flipped off instantly and the
voice-call loop reverts to the exact code path it had before
persona_call existed. The feature is designed to be deletable.

## 10. What is explicitly *not* in this design

- No persona-prompt editor changes.
- No change to the persona selection UI.
- No change to the chat endpoint's request/response contract.
- No new STT provider, no new TTS voice, no new model.
- No destructive migration — two new tables, both additive, both
  safe to drop.
- No changes to the existing `voice_call` transport protocol other
  than the three optional new event types.

The whole feature is one import, one optional kwarg on
`turn.run_turn`, and one `async with` block in the WS loop. Nothing
else moved.
