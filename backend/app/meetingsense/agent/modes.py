"""What each helper mode is allowed to do (batches MS23 and MS24, wave W8).

**Modes are server policy objects, not client compositions.** That sentence is MS24's, and it
is the reason this file is data rather than a set of prompt fragments the client assembles. A
mode that a client composes is a mode a client can compose differently — and the difference
between Note-taker and Coach is not tone, it is whether the assistant may speak into a meeting
somebody else is running.

So a mode is an allow-list, evaluated here, and every node asks it rather than deciding for
itself. `hp.ms.set_mode` writes the name; this decides what the name means.

**Note-taker is the floor and the default.** It observes and writes notes. It does not answer
unprompted, does not coach, and does not call tools. That is also what makes MS23's acceptance
checkable: in Note-taker the graph runs `perceive → reflect → deliver`, which is exactly what
the fixed loop does, so "identical output" is a claim about one code path rather than a
coincidence between two.

Adding a mode is adding a row. Nothing here branches on a mode name outside this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple


@dataclass(frozen=True)
class Mode:
    """One mode's policy. Frozen: a policy a node could mutate is not a policy."""

    name: str
    label: str
    description: str
    #: Take rolling notes (MS12). Every mode does; it is what a recording is for.
    notes: bool = True
    #: Answer a direct question (MS13).
    answer: bool = False
    #: Speak without being asked. The line between an assistant and an interruption.
    proactive: bool = False
    #: Offer coaching — feedback on how the user is doing, not on what was said.
    coach: bool = False
    #: Call tools at all (MS24 gates *which*, per meeting).
    tools: bool = False
    #: Retrieve beyond the live window (MS15).
    recall: bool = True

    def allows(self) -> Dict[str, bool]:
        """The flat dict `perceive` puts in the state, resolved once per turn."""
        return {
            "notes": self.notes,
            "answer": self.answer,
            "proactive": self.proactive,
            "coach": self.coach,
            "tools": self.tools,
            "recall": self.recall,
        }


#: The five modes. Ordered from least to most capable, which is also the order a user should
#: have to opt into them.
MODES: Tuple[Mode, ...] = (
    Mode(
        name="note-taker",
        label="Note-taker",
        description="Listens and writes notes. Says nothing unless asked.",
        # Every other flag is off, and this is the mode MS23's acceptance is measured in: the
        # graph must produce what the fixed loop produces, and the fixed loop only takes notes.
        recall=False,
    ),
    Mode(
        name="participant",
        label="Participant",
        description="Answers when asked, using the meeting and everything recorded before it.",
        answer=True,
    ),
    Mode(
        name="presenter",
        label="Presenter",
        description="Answers, and watches the slides for what you have not covered yet.",
        answer=True,
        proactive=True,
    ),
    Mode(
        name="coach",
        label="Coach",
        description="Answers and offers feedback on how the conversation is going.",
        answer=True,
        coach=True,
    ),
    Mode(
        name="practice",
        label="Practice",
        description="A rehearsal partner: answers, coaches, and may use tools to look things up.",
        answer=True,
        coach=True,
        tools=True,
    ),
)

#: The floor. Also what an unknown name resolves to — see `resolve`.
DEFAULT = MODES[0]

_BY_NAME = {mode.name: mode for mode in MODES}


def names() -> Tuple[str, ...]:
    return tuple(mode.name for mode in MODES)


def resolve(name: str) -> Mode:
    """The mode with this name, or the default.

    **An unknown name falls back to the least capable mode, never the most.** A typo, a stale
    client, a mode a later wave removed — each of those should quiet the assistant down, not
    hand it tools. The refusal for a *deliberate* unknown mode belongs at the edge, which is
    where `hp.ms.set_mode` and `POST /{id}/notes` both put it.
    """
    return _BY_NAME.get((name or "").strip().lower(), DEFAULT)


def allows(name: str) -> Dict[str, bool]:
    return resolve(name).allows()


def as_dicts() -> list:
    """For `/status` and the mode chips — one place the UI reads what a mode does."""
    return [
        {"name": m.name, "label": m.label, "description": m.description, **m.allows()}
        for m in MODES
    ]
