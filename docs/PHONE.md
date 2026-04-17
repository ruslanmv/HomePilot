# PHONE.md — live voice-call simulation in HomePilot

**Audience.** Anyone who wants to understand why HomePilot's Phone
mode behaves the way it does — product, design, new engineers, and
curious users.

**Scope.** This is the "why" and "how it feels real" document. For
code layout and rollout mechanics see
[`docs/analysis/voice-call-human-simulation-design.md`](./analysis/voice-call-human-simulation-design.md).

Phone mode is a layer on top of HomePilot's existing chat — not a new
persona, not a new model, not a new voice engine. It is a small,
additive backend module (`backend/app/persona_call/`) and a thin UI
affordance (the emerald 📞 in the chat header). When you tap it,
HomePilot starts composing each reply as if the persona had just
picked up the phone.

Two principles the whole design bends toward:

1. **The persona stays itself.** Nothing rewrites a persona's base
   prompt. Phone behavior is appended as one short suffix per turn.
   Darkangel666 sounds like Darkangel666 on the phone; Atlas sounds
   like Atlas. They just both obey turn-taking.
2. **"Real" is measurable.** Every rule below is grounded in
   published conversation-analysis findings from the last fifty years.
   When the simulation feels off, we can point at which rule broke.

---

## 1. Scientific background

Phone conversations are one of the most studied objects in sociology
and linguistics. The results are remarkably consistent across
languages and decades. The four canonical findings we rely on are:

### 1.1 Openings are ritualized

**Schegloff, E. A. (1968). Sequencing in Conversational Openings.**
*American Anthropologist*, 70(6), 1075–1095.

Schegloff's landmark finding: every phone call opens with a fixed
sequence of adjacency pairs — *summons/answer*, *identification/
recognition*, *greeting/greeting*, and (optionally) *how-are-you/
how-are-you*. These pairs are not stylistic; they are the very thing
that turns two strangers on a wire into "on a call." Skipping one
causes audible trouble.

> **In HomePilot.** The phase machine in
> `persona_call/state.py` encodes `opening → topic → pre_closing →
> closed`. Turn 1 is a summons-answer ("Hello?" is fine; a five-
> bullet opener is not). The `opening.how_are_you_once` /
> `opening.skip_how_are_you` directives implement the optional
> fourth pair.

### 1.2 Turn-taking is clause-driven

**Sacks, H., Schegloff, E. A., & Jefferson, G. (1974). A Simplest
Systematics for the Organization of Turn-Taking for Conversation.**
*Language*, 50(4), 696–735.

Sacks/Schegloff/Jefferson (the "SSJ paper") showed that speakers
switch at *transition-relevance places* — clause boundaries marked by
syntax, intonation, and pragmatic completion. Not at silence. Silence
is a *last-resort* cue. A listener who waits for silence before
speaking reads as either shy or broken.

> **In HomePilot.** The backchannel emitter in
> `persona_call/backchannel.py` triggers on clause cues in the user's
> live transcript (conjunctions, commas, "so…", "and then…") rather
> than on absolute silence. The minimum-gap knob
> (`PERSONA_CALL_BC_MIN_GAP_MS`, default 1800 ms) keeps it from
> doubling up.

### 1.3 Acknowledgment tokens cycle

**Jefferson, G. (1984). Notes on a Systematic Deployment of the
Acknowledgment Tokens "Yeah" and "Mm hm."** *Papers in Linguistics*,
17(2), 197–216.

Jefferson's famous result: humans do not pick "mm-hm" vs "yeah" vs
"right" at random, but they *do* cycle them. Using "yeah" five times
in a row is one of the most distinctive signs of a non-native speaker
(or a chatbot). The choice carries weak meaning too — "mm-hm" is a
continuer ("keep going"), while "yeah" is more of a closure token
("I got it, next point").

> **In HomePilot.** The anti-repetition ledger in
> `persona_call/repeat.py` stores the last few acks and openers the
> persona just used. Next turn's directive explicitly forbids them:
> *"You just used: **mm**, **right**. Pick a different backchannel
> this turn."* Window sizes are tunable
> (`PERSONA_CALL_ACK_WINDOW`, default 5).

### 1.4 Response timing has a narrow normal range

**Stivers, T., Enfield, N. J., Brown, P., Englert, C., Hayashi, M.,
Heinemann, T., … Levinson, S. C. (2009). Universals and cultural
variation in turn-taking in conversation.** *PNAS*, 106(26),
10587–10592.

Across ten languages on five continents, modal response latency
between a question and its answer is ~200 ms, and anything beyond
~700 ms reads as a *trouble signal* — the listener infers hesitation,
disagreement, or distraction. Above ~1 s, the speaker typically
repairs (reformulates, adds tag questions, prompts for response).

> **In HomePilot.** The filler scheduler in
> `persona_call/latency.py` wraps every turn. If the LLM takes
> longer than `PERSONA_CALL_FILLER_AFTER_MS` (default 600 ms), we
> emit exactly one thinking token — "hmm", "one sec", "let me see"
> — from the persona's own voice. The reply that eventually arrives
> then continues the thought naturally. Result: the caller never
> gets more than ~600 ms of dead air.

### 1.5 Closings are never one move

**Schegloff, E. A., & Sacks, H. (1973). Opening up Closings.**
*Semiotica*, 8(4), 289–327.

Closings take 3–6 turns to negotiate: a pre-closing ("okay…",
"alright then"), an acknowledgment, sometimes a small topic re-open
("oh, one more thing"), then mirrored terminal exchanges ("bye",
"bye"). Collapsing this to a single "goodbye" from the assistant
reads as cold or rushed — the single clearest tell that you are
talking to a machine.

> **In HomePilot.** `persona_call/closing.py` implements a
> state-machine-enforced two-phase handshake: `topic → pre_closing →
> closed`. In `pre_closing` the directive hard-forbids the persona
> from saying "goodbye" until the caller says it first. This is the
> **one place** the composer overrides rather than suggests.

### 1.6 Further influences (not cited line-by-line, but guiding)

- **Clark, H. H. (1996). *Using Language*.** Cambridge University
  Press. The idea that dialogue is a *joint activity* requiring
  continuous coordination, which motivates backchannels as a separate
  stream rather than as assistant replies.
- **Pomerantz, A. (1984). Agreeing and disagreeing with assessments:
  Some features of preferred/dispreferred turn shapes.** In J. M.
  Atkinson & J. Heritage (eds.), *Structures of Social Action*.
  Motivates not answering "yes or no?" style compressions when the
  caller is driving or rushed — dispreferred seconds need room.
- **Schegloff, E. A. (2000). Overlapping talk and the organization of
  turn-taking for conversation.** *Language in Society*, 29(1),
  1–63. Justifies the minimum-gap knob on the backchannel emitter
  and the bias against emitting continuers during a caller's in-
  progress clause.
- **OpenAI Realtime prompting guide (2024/2025).** An engineering
  document, not research, but the empirical observation that the
  dominant robotic tell is *lexical repetition of openers and
  acknowledgments* matches Jefferson (1984) exactly and reinforces
  the ledger design.

---

## 2. How the science maps onto the real app

Everything in § 1 is encoded as a single small module per rule.
Nothing is left to prompt magic.

| Scientific rule (§ 1)                    | Module                                        | Default knob                                     |
|------------------------------------------|-----------------------------------------------|--------------------------------------------------|
| Opening is a fixed sequence              | `persona_call/state.py` phase machine         | `PERSONA_CALL_REASON_FALLBACK_TURN=3`            |
| "How are you" is optional                | `persona_call/directive.py` (opening framing) | `PERSONA_CALL_HAY_LATE_HOUR=21`                  |
| Turn-taking at clause boundaries         | `persona_call/backchannel.py`                 | `PERSONA_CALL_BC_CLAUSES=2`                      |
| Acknowledgment tokens cycle              | `persona_call/repeat.py`                      | `PERSONA_CALL_ACK_WINDOW=5`                      |
| 700 ms trouble threshold                 | `persona_call/latency.py` (filler scheduler)  | `PERSONA_CALL_FILLER_AFTER_MS=600`               |
| Closings are never one move              | `persona_call/closing.py`                     | (none — always on when the module is on)         |
| Late-night brevity (ergonomics, not CA)  | `persona_call/context.py` + composer          | `PERSONA_CALL_LATE_HOUR=22`, `..._END=6`         |
| Caller mobility (driving / transit)      | `persona_call/context.py::classify_utterance` | n/a — regex                                      |

The composer `persona_call/directive.py::compose()` assembles the
active rules into one `ComposedDirective`:

```
ComposedDirective
├── system_suffix      (short text, appended as an extra system msg)
└── post_directives    (list[str] — machine tags for tests + logs)
```

The suffix is **never** a persona prompt replacement. A structural
test (`test_persona_call_never_overrides_system_prompt`) asserts
the dataclass has no `system_prompt` field; the only attachment
point into the chat request is the new optional `additional_system`
parameter on `voice_call/turn.py::run_turn`.

## 3. The per-turn loop — what actually happens when you talk

When you tap the emerald 📞 button in the chat header, `App.tsx`
switches `mode` to `voice`, which mounts `VoiceModeGrok`. The voice
controller opens a WebSocket against
`/v1/voice-call/ws/{session_id}` (see
`backend/app/voice_call/ws.py`). The red 📞⊘ button in the voice
header tears the session down cleanly.

Every user utterance becomes a `transcript.final` event, and the
server runs this loop (`voice_call/ws.py` lines 192–302):

```
1.  STT finalizes the user's turn → transcript.final
2.  persona_call.context.compute_env(tz, now)                # clock + tz
    persona_call.context.classify_utterance(text)            # regex signals
3.  persona_call.directive.compose(session, persona, env, text)
    ├─ advance phase (opening/topic/pre_closing/closed)
    ├─ build suffix from active rules
    └─ return ComposedDirective(system_suffix, post_directives)
4.  async with persona_call.latency.FillerScheduler(...):
        reply = await turn.run_turn(
            user_text=...,
            model=...,
            auth_bearer=...,
            additional_system=composed.system_suffix,   # <- suffix only
        )
    (if the LLM doesn't return within 600 ms, the scheduler has
     already emitted one "hmm…" event to the client in the persona's
     voice.)
5.  Send reply to client as transcript.final (role: assistant).
6.  persona_call.directive.record_persona_reply(reply)
    └─ rolls the anti-repetition ledger for next turn
```

Steps 2, 3, 4's filler scheduler, and step 6 are the persona_call
contribution. Remove them and the loop is byte-identical to the
plain voice-call MVP.

## 4. What makes it feel real

Eight observable differences between "chatbot on speakerphone" and
"persona on the phone," each mapped to a rule from § 1:

| Feeling                                                 | Mechanism                                                                              |
|---------------------------------------------------------|----------------------------------------------------------------------------------------|
| "It picked up like a person would."                     | Phase machine; turn 1 is a short recognition, not a pitch (§ 1.1).                     |
| "It doesn't ask how I am when I'm clearly in a rush."   | `context.classify_utterance` → `time_pressured=True` → `opening.skip_how_are_you`.     |
| "It never goes silent on me."                           | `latency.FillerScheduler` emits a persona filler inside 600 ms (§ 1.4).                |
| "It's actually listening — it acknowledges as I talk."  | `backchannel.should_emit` fires on clause boundaries (§ 1.2), not on silence.          |
| "It doesn't keep saying 'mm-hm' like a robot."          | `repeat.forbidden_tokens` forbids the last N used tokens (§ 1.3).                      |
| "It ends calls gracefully."                             | `closing.compose_handshake` — two-phase, state-enforced (§ 1.5).                       |
| "At 11 pm it keeps things short."                       | Late-night brevity frame from `context` + `PERSONA_CALL_LATE_HOUR=22`.                 |
| "It still sounds like *Atlas*, not a generic assistant." | Persona base prompt is untouched; only a short suffix is appended.                     |

## 5. The per-turn suffix — an example

Persona: default assistant. Local time: 22:15. Caller has just said:
*"Quick question — I'm driving, can I ask something fast?"* The
persona's previous two replies started with "mm" and "mm-hm."

The suffix appended to this one turn looks like:

```
[phone-call context — this turn only]
- You are on a live phone call. Keep replies to 1–3 short sentences.
  Never use bullet points, stage directions, or emoji — this is spoken.
- It is 22:15 locally. It is late; keep replies brief and offer to
  continue tomorrow if a topic needs more than a minute.
- The caller is driving and is time-pressured. One short sentence
  this turn. Do not ask clarifying questions.
- You recently used: "mm", "mm-hm". Pick a different backchannel
  this turn.
```

The persona's own base system prompt still runs first, in full.
The composer never touches it. If you flip
`PERSONA_CALL_APPLY=false`, the suffix is still computed and stored
in `persona_call_directives` for review, but it is not sent to the
LLM — so we can audit "would have said X" against real calls for a
week before flipping the switch.

## 6. Running it yourself

Both flags default **off** in production. Turn them on locally:

```
# backend/.env (or shell env)
PERSONA_CALL_ENABLED=true     # master flag — loads the module
PERSONA_CALL_APPLY=true       # actually send the suffix to the LLM
                              # (set false for shadow mode)
```

Optional knobs — all have safe defaults (see `persona_call/config.py`):

```
PERSONA_CALL_FILLER_AFTER_MS=600     # § 1.4 trouble threshold
PERSONA_CALL_BC_CLAUSES=2            # backchannels after N clause cues
PERSONA_CALL_BC_MIN_GAP_MS=1800      # cooldown between backchannels
PERSONA_CALL_BC_VOL_DB=-6.0          # backchannel TTS volume
PERSONA_CALL_HAY_LATE_HOUR=21        # skip "how are you" at/after
PERSONA_CALL_LATE_HOUR=22            # enter late-night brevity
PERSONA_CALL_LATE_HOUR_END=6         # exit late-night brevity
PERSONA_CALL_ACK_WINDOW=5            # ack ledger depth
PERSONA_CALL_OPENER_WINDOW=3         # opener ledger depth
PERSONA_CALL_REASON_FALLBACK_TURN=3  # promote opening→topic by turn N
```

Start the app normally, open the chat, tap the emerald 📞 in the
top-right, and talk. Tap the red 📞⊘ in the voice header to end.

## 7. How we know it works — tests

`backend/tests/test_persona_call.py` anchors one test group per
research rule (twelve tests total, all green in 3.77 s):

1. **Flag-off invariant** — every `/v1/persona-call/*` path 404s.
2. **Phase machine** — opening/topic/pre_closing/closed (§ 1.1).
3. **Anti-repetition ledger** — tokens rolled + forbidden (§ 1.3).
4. **Late-night brevity** — fires at 22:00, not 21:59 (§ 1.4-ish).
5. **Closing handshake** — two-phase, state-enforced (§ 1.5).
6. **Backchannel cadence** — clause-triggered, rate-limited (§ 1.2).
7. **Filler latency** — fires >600 ms, not at 50 ms (§ 1.4).
8. **Persona-prompt invariance** — suffix-only, structurally
   guaranteed.

Any regression lands on a named rule, not a vague "it feels worse."

## 8. What the simulation is *not*

- **Not a voice clone.** We don't swap out the persona's TTS voice
  for a "phone-ier" one. The existing Piper/Web-Speech pipeline
  plays the reply as-is.
- **Not a fake telephone effect.** No 300–3400 Hz bandpass, no line
  noise, no ringback tone. The realism is conversational, not sonic.
  (Sonic effects are easy to add later; they are a separate choice.)
- **Not a persona rewrite.** Zero persona files are modified by
  turning Phone mode on. The feature is purely additive.
- **Not a replacement for the chat endpoint.** The suffix is an
  `additional_system` parameter; `/v1/chat/completions` still gets
  the persona's full base prompt first and the suffix second.
- **Not streaming.** The current chat path is non-streaming, so the
  filler-under-wait technique replaces token-level streaming. When
  streaming lands, the filler scheduler becomes a redundancy rather
  than a necessity.

## 9. Further reading

If you want to go deeper into the conversation-analysis findings that
drive this module:

- Sidnell, J., & Stivers, T. (eds.) (2013). *The Handbook of
  Conversation Analysis*. Wiley-Blackwell. — The modern reference
  volume; chapters 1, 3, 11, and 13 cover every rule cited above.
- Levinson, S. C. (1983). *Pragmatics*. Cambridge University Press.
  Chapter 6 is still the clearest textbook treatment of turn-taking
  and adjacency pairs.
- Liddicoat, A. J. (2021). *An Introduction to Conversation
  Analysis* (3rd ed.). Bloomsbury. — A short, readable modern intro
  that cites all the papers in § 1.

For the implementation companion document — architecture, data
contracts, rollout plan — see
[`docs/analysis/voice-call-human-simulation-design.md`](./analysis/voice-call-human-simulation-design.md).
