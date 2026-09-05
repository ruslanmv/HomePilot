"""What each mode tells the model about its own role (batch MS26, wave W9).

MS23 made a mode a policy object — an allow-list of what it *may* do. That is half of what a
mode is. The other half is what it should *sound like*, and this is that half: a short framing
paragraph per mode, kept in a file of strings for the reason `prompts.py` gives — a prompt is a
thing people edit, argue about and tune after a bad meeting, and a file of strings is easier to
argue with than strings buried in control flow.

**A mode prompt is layered onto MS13's system prompt, never in place of it.** `ASK_SYSTEM`
carries the rules that are not about tone: cite the timestamp, never invent one, say the
meeting does not cover it rather than guessing. Those are the difference between an assistant
and a liability, and they are not a Participant's business to relax. So the framing goes first
and the base rules go last, which is both the safer composition — the final word in a system
prompt is the one a model weights hardest — and the honest one: a mode decides the register,
not the standard of evidence.

Note-taker has **no prompt at all**, and that is not an oversight. It never answers, so a
prompt for it would be dead text that a later reader would assume was live — and MS23's
acceptance is that Note-taker's output is identical to the fixed loop's, which a mode-specific
prompt would quietly end.
"""

from __future__ import annotations

from typing import Dict, Optional

#: mode name → the framing paragraph. A mode absent from here is a mode with no framing, which
#: is the correct state for one that never speaks.
PROMPTS: Dict[str, str] = {
    "participant": """\
You are taking part in this meeting as an assistant the user has brought with them.

- When somebody addresses you by name, answer them. Briefly — one or two sentences. You are a
  participant, not the speaker.
- When somebody asks the *user* a question, do not answer it. Draft what the user might say and
  offer it to them; they decide whether to use it.
- Say nothing at all if you have nothing that helps. A participant who comments on everything
  is one the others stop listening to.""",

    "presenter": """\
The user is presenting. You are watching their deck and the room.

- Your job is the deck's progress and the room's questions, not the content of every slide.
- When a new slide goes up, say the one thing that is most useful given what has already been
  said, or say nothing. Most slides need nothing.
- Never answer an audience question while the user is presenting. Questions are queued for
  them; interrupting a presentation is the one thing you must not do.""",

    "coach": """\
You are coaching the user through this meeting.

- Comment on how the conversation is going, never on what was said. Whether somebody has not
  spoken, whether a point went unanswered, whether the time is going where the user wanted it.
- Address the user, never the room. Nobody else can hear you.
- One observation at a time, and only when it is worth the interruption.""",

    # Not a mode. See `framing`.
    "draft": None,  # replaced below, once DRAFT_SYSTEM is defined
    "practice": """\
This is a rehearsal. The user is practising, and you are playing the other side.

- Stay in the role the user set up. Ask the questions that role would ask.
- Push where a real counterpart would push. A rehearsal that agrees with everything teaches
  nothing.
- Break character only if the user asks you to.""",
}


def framing(mode: str) -> str:
    """The framing paragraph for a mode, or ``""``.

    ``"draft"`` is in here alongside the mode names and is not a mode: it is the framing a
    Participant uses when the question was aimed at the *user*. Keyed the same way because it
    composes the same way — over `ASK_SYSTEM`, never in place of it — and giving it a second
    mechanism would mean two things to check when the base rules change.
    """
    return PROMPTS.get((mode or "").strip().lower(), "")


def system_for(mode: str, base: str) -> str:
    """The system prompt for one mode: framing first, base rules last.

    **The base is never dropped and never reordered.** A mode that could replace it could
    replace "never invent a timestamp", and the whole reason a meeting assistant is trusted at
    all is that its citations are real. The framing goes above so the base rules read as the
    conditions the role is exercised under, rather than as suggestions the role may override.
    """
    head = framing(mode)
    if not head:
        return base
    return f"{head}\n\n{base}"


#: What a Participant offers when somebody asks the *user* a question. A draft, in the user's
#: voice, that they can use or ignore — not an answer, and not spoken to the room.
DRAFT_SYSTEM = """\
Somebody in a meeting has asked the user a question. Draft a reply for the user to give.

- Write it as the user would say it out loud, in the first person. One or two sentences.
- Use only what the meeting has already covered. If the meeting does not support an answer,
  reply with exactly: PASS
- No preamble, no "you could say". Just the words.
- PASS is the right answer more often than not. A draft the user has to rewrite is worse than
  no draft."""

#: The literal a draft returns when it has nothing. Checked exactly rather than fuzzily: a
#: model that writes "I'll pass on this one" has produced a draft, not declined to.
PASS = "PASS"


PROMPTS["draft"] = DRAFT_SYSTEM


def usable_draft(text: Optional[str]) -> str:
    """The draft, or ``""`` when the model declined or wandered.

    Declining is the common case and the right default — see `DRAFT_SYSTEM`. A blank answer,
    a `PASS`, or a paragraph are all "no draft": the first two by the model's own account, and
    the third because a draft the user has to edit down is slower than answering themselves.
    """
    body = (text or "").strip() if isinstance(text, str) else ""
    if not body or body.upper().strip(" .!") == PASS:
        return ""
    if len(body.split()) > 60:
        return ""
    return body
