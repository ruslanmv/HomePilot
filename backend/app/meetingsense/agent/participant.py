"""Participant: answering to your own name, and drafting for somebody else's (batch MS26).

Two behaviours that look similar and are opposites, which is why they are in one file where the
difference can be stated once.

**Addressed by name → answer.** Somebody says "Ana, what did we decide about pricing?" and Ana
is this assistant. That is not speaking unbidden; it is a question that arrived down the
microphone instead of down the socket, and answering it is the whole of what a participant is
for. It routes through MS13's `answer` like every other question, so the budget, the tiers and
the citation rule are the ones that were argued once.

**The user is asked → draft, never answer.** Somebody says "Ruslan, what did we decide about
pricing?" and Ruslan is the *user*. Answering that out loud is the assistant talking over the
person it works for, in a meeting where the other people believe they are talking to a human.
So it drafts a reply and hands it over; the user says it, edits it, or ignores it.

The line between the two is a name, so the names matter and are never guessed. A meeting
declares them at `start`; with none declared, nothing here fires — which is the narrow
behaviour and the right default, because the failure mode of guessing is answering to somebody
else's name in front of them.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable, Dict, Optional, Sequence

from .. import chips as chips_mod
from . import mode_prompts

log = logging.getLogger(__name__)

#: The transcript channel other people are on. MS4 fixed this: 0/`them` is the call, 1/`me` is
#: this machine's microphone. A question on `me` is the user asking, and the socket is where
#: that belongs.
THEM = "them"


def _mentions(text: str, names: Sequence[str]) -> Optional[str]:
    """The first of ``names`` this text addresses, or None. Word boundaries, always."""
    for name in names or ():
        token = (name or "").strip()
        if len(token) < 2:
            # A one-letter name matches most sentences. Refusing it is not a limitation, it is
            # the difference between a name and a coincidence.
            continue
        if re.search(rf"\b{re.escape(token)}\b", text or "", re.I):
            return token
    return None


def addressed(
    segment: Dict[str, Any],
    *,
    assistant_names: Sequence[str] = (),
) -> Optional[Dict[str, Any]]:
    """Somebody in the call asked *the assistant* something, by name.

    Three conditions, and each one is here to stop a reply rather than to start one: the call
    said it (not the user), it is a question, and it names the assistant. Drop any one and the
    assistant starts talking in somebody else's meeting.
    """
    text = (segment or {}).get("text") or ""
    if (segment or {}).get("speaker") != THEM:
        return None
    if not chips_mod._asking(text):
        return None
    name = _mentions(text, assistant_names)
    if not name:
        return None
    return {"question": text.strip(), "name": name, "t0": (segment or {}).get("t0_ms")}


def aimed_at_user(
    segment: Dict[str, Any],
    *,
    user_names: Sequence[str] = (),
    assistant_names: Sequence[str] = (),
) -> Optional[Dict[str, Any]]:
    """Somebody in the call asked *the user* something.

    Reuses MS25's `question` trigger for what counts as a question aimed at the user — second
    person, or the user's own name — rather than writing a second one. Two definitions of "was
    that aimed at me" would drift, and the one that drifted would be the one nobody was
    reading.

    **A question that names the assistant is not aimed at the user**, even when it also uses
    second person: "Ana, can you tell us what you think?" is Ana's to answer, and drafting a
    reply for the user as well would put two answers on screen for one question.
    """
    text = (segment or {}).get("text") or ""
    if _mentions(text, assistant_names):
        return None
    found = chips_mod._question(segment or {}, names=user_names)
    if not found:
        return None
    return {"question": found["text"], "t0": found.get("t0")}


async def draft(
    question: str,
    *,
    answer: Callable[..., Awaitable[Dict[str, Any]]],
    meeting_id: str,
) -> str:
    """A reply the user could give, or ``""``.

    Built on MS13's `answer` rather than on a fresh prompt over the raw transcript: a draft is
    only worth offering if it is grounded in what the meeting actually said, and MS13 is the
    thing that knows how to ground an answer in a meeting. The framing that turns an answer
    into a first-person draft is `mode_prompts.DRAFT_SYSTEM`.

    Never raises, and returns ``""`` far more often than not — see `usable_draft`. A draft the
    user has to rewrite is slower than answering themselves.
    """
    if not (question or "").strip():
        return ""
    try:
        frame = await answer(meeting_id, question, mode="draft")
    except Exception:  # noqa: BLE001 — a draft is never worth the meeting
        log.exception("meetingsense: draft failed")
        return ""
    text = (frame or {}).get("text") if isinstance(frame, dict) else None
    return mode_prompts.usable_draft(text)


def attach_draft(chip: Dict[str, Any], text: str) -> Dict[str, Any]:
    """Put a draft on a `question` chip. Returns a new chip; the original is untouched.

    A field on the chip rather than a frame of its own, because a draft with no question beside
    it is a sentence with no reason to exist — and because the reader dismisses one thing.
    """
    body = (text or "").strip()
    if not body or (chip or {}).get("kind") != "question":
        return chip
    return dict(chip, draft=body)
