"""Embodied HomePilot — the morning brief (spec v1.1 §6.15, batch B21).

This is a **presentation batch over tools that already exist**. `hp_personal_plan_day`, the
seeded `hp-google-calendar` server and the Microsoft Graph server already fetch the day;
`daypilot_bridge` already carries proposals to an Approval Center. Nothing here fetches
anything and nothing here acts. It composes: given the day, produce a panel to look at, a
sentence to hear, and — at most — one thing to say yes to.

## The single worst mistake available in this plan

…would be a second approval path. HomePilot already has one: the persona proposes, DayPilot
validates and drafts, the user approves in the Approval Center, and the *executor* runs the
action. An assistant activity that called a calendar API "just for the easy cases" would
have built a second door into the same house, with a different lock, maintained by nobody.

So this module is structurally incapable of it, not merely disciplined about it:

  * it takes **no executor, no client, no session** — its constructor arguments are data;
  * its output type is :class:`Proposal`, which has an ``as_directive`` and no ``run``;
  * every capability passes through :func:`gate`, the one door, which knows two tables and
    refuses everything absent from both — an unknown capability is not a capability.

A negative test reads this file for the network and subprocess machinery a bypass would
need and fails if any of it appears. That test is the actual guarantee; this paragraph is
just the reason it exists.

## Two namespaces, one door

There are two kinds of thing she could be said to "do", and conflating them is how a gesture
ends up needing approval and a calendar write does not:

  * **Avatar tools** (``play_animation``, ``vision_insight``) — graded by ``safety.py``.
    Playing a clip is *autonomous*; it is output, not action.
  * **DayPilot capabilities** (``calendar.create``, ``email.send``) — real-world writes.
    Every one is *confirm*, always, because every one of them changes something outside
    this process.

:func:`gate` reads both tables and returns a level. :func:`propose` refuses to build a
proposal for anything it grades *autonomous*, because a proposal is a question, and asking
permission to blink is how an assistant becomes exhausting.

## One proposal per brief

``MAX_PROPOSALS_PER_BRIEF`` is 1. A brief that proposes five things is a to-do list you have
to decline four times before breakfast, and the fifth decline is where a user stops reading
the panel at all. The rest are *deferred*, not dropped — they are returned on the brief so a
caller can offer them when asked, and so a test can prove nothing vanished.

Pure module: no FastAPI, no I/O, no clock of its own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import safety
from .panels import DEFAULT_MAX_KB, MAX_ROWS, build

log = logging.getLogger("avatar_director.assistant")

#: How many things one brief may ask permission for. See the module header.
MAX_PROPOSALS_PER_BRIEF = 1

#: How many agenda items the *spoken* summary names. The panel carries all of them; she
#: points at it rather than reading it out, which is the difference between an assistant
#: with a body and a speaker puck with a face. §6.15's UX gate, made into a number.
SPOKEN_ITEM_LIMIT = 2

#: A spoken brief longer than this has stopped being a greeting.
SPEECH_CHAR_BUDGET = 320

#: The gesture she plays while the panel is up. A *name* from ``protocol.EMOTE_WHITELIST``,
#: resolved to a clip by the KB on the client — never a filename, per §6.4. Autonomous: it
#: is output, and it needs no permission. It is also the whole of the UX gate that this file
#: can express: she points at the screen, and the sentence is short because the screen is
#: doing the work.
POINT_INTENT = "point"

#: Levels this module understands, mirroring ``safety.SafetyLevel``.
CONFIRM = "confirm"
AUTONOMOUS = "autonomous"
READ_ONLY = "read-only"


class AssistantError(Exception):
    """A refusal with a code, in the shape :mod:`panels` established."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ── the one door ─────────────────────────────────────────────────────────────


def capabilities() -> frozenset:
    """The DayPilot capabilities a proposal may target.

    Read from ``daypilot_bridge`` rather than copied, so the two lists cannot drift. Copying
    it would produce exactly the failure mode this batch is about: a second, staler statement
    of what may be approved.
    """
    from ..daypilot_bridge import bridge  # noqa: PLC0415 — lazy, like every optional half

    return bridge.CAPABILITIES


def gate(capability: str) -> str:
    """The safety level for anything she might do. The only classifier in this module.

    Two tables, checked in order, and no third answer. A name in neither is refused: an
    unknown capability is not a capability, and grading it *confirm* "to be safe" would let
    a typo become a real-world action that the user then approves.
    """
    name = (capability or "").strip()
    if not name:
        raise AssistantError("capability_missing", "a proposal needs a capability")
    if name in capabilities():
        # Every real-world write is confirm. There is no autonomous branch here on purpose.
        return CONFIRM
    if name in safety.TOOL_SAFETY:
        return safety.level_for(name)
    raise AssistantError("capability_unknown", f"{name!r} is in neither safety table")


# ── what a proposal is, and what it is not ───────────────────────────────────


@dataclass(frozen=True)
class Proposal:
    """One thing the persona would like to do, expressed as a question.

    It carries no way to answer itself. There is no ``run``, no ``execute``, no ``client`` —
    the only thing it can become is a directive on the bridge, which DayPilot validates
    again and drafts behind its Approval Center. Two independent validations of the same
    untrusted model output is the contract, not belt-and-braces.
    """

    capability: str
    summary: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    level: str = CONFIRM

    def as_directive(self) -> Dict[str, Any]:
        """The bridge's wire shape. Deliberately the *only* rendering of a proposal."""
        directive: Dict[str, Any] = {
            "type": "daypilot.action.propose",
            "capability": self.capability,
            "summary": self.summary,
        }
        if self.arguments:
            directive["arguments"] = dict(self.arguments)
        return directive


def propose(capability: str, summary: str, arguments: Optional[Dict[str, Any]] = None) -> Proposal:
    """Build one proposal, or refuse.

    Refuses an *autonomous* capability by design: those are things she just does, and turning
    one into a question would train the user to approve without reading — which is how a real
    approval gets waved through later.
    """
    level = gate(capability)
    if level != CONFIRM:
        raise AssistantError(
            "not_a_proposal",
            f"{capability!r} is {level}; only confirm-level capabilities become proposals",
        )
    text = (summary or "").strip()
    if not text:
        raise AssistantError("summary_missing", f"{capability!r} needs a summary the user can read")
    return Proposal(capability=capability, summary=text, arguments=dict(arguments or {}), level=level)


# ── the brief ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Brief:
    """Everything a "good morning" produces: something to look at, something to hear, and
    at most one thing to say yes to."""

    panel: Dict[str, Any]
    speech: str
    intent: str
    proposals: Tuple[Proposal, ...] = ()
    deferred: Tuple[Proposal, ...] = ()

    @property
    def confirm_count(self) -> int:
        """How many confirmations this brief asks for. The acceptance criterion, as a number."""
        return sum(1 for p in self.proposals if p.level == CONFIRM)

    def directives(self) -> List[Dict[str, Any]]:
        """The bridge block for this turn. Deferred proposals are not in it — they were not
        offered, so they must not arrive at the Approval Center."""
        return [p.as_directive() for p in self.proposals]

    def messages(self) -> List[Dict[str, Any]]:
        """The protocol frames a client receives, in the order they are sent.

        Panel first, then speech. A sentence about a screen that is not up yet is the
        narrating-into-space failure the UX gate is looking for.
        """
        from .protocol import ProtocolHandler  # noqa: PLC0415 — lazy, like every optional half

        # Built through the handler rather than by hand, so `intent` still has to clear
        # EMOTE_WHITELIST. A brief that names a gesture the client cannot resolve should
        # fail here, in a test, rather than arrive as an intent nobody plays.
        emit = ProtocolHandler()
        frames = [dict(self.panel)]
        if self.intent:
            frames.append(emit.intent(self.intent, 0.5, source="assistant"))
        if self.speech:
            frames.append(emit.say(self.speech, source="assistant"))
        return frames


def _row(item: Any) -> Optional[Dict[str, Any]]:
    """One agenda entry, normalised. Untrusted input: an item that will not read is skipped
    rather than fatal, because one malformed calendar entry must not cost the whole morning."""
    if isinstance(item, str):
        text = item.strip()
        return {"key": "", "value": text} if text else None
    if not isinstance(item, dict):
        return None
    when = str(item.get("when") or item.get("time") or item.get("start") or "").strip()
    what = str(item.get("what") or item.get("title") or item.get("summary") or "").strip()
    if not what:
        return None
    return {"key": when, "value": what}


def summarise(rows: Sequence[Dict[str, Any]], *, greeting: str = "Morning.") -> str:
    """The spoken half. Short, and it defers to the panel.

    She names at most ``SPOKEN_ITEM_LIMIT`` things and says how many more there are, because
    the panel is already showing all of them and reading a list aloud is what a speaker does.
    """
    head = (greeting or "").strip()
    if not rows:
        return f"{head} Nothing on the calendar today." if head else "Nothing on the calendar today."

    named = [r["value"] for r in rows[:SPOKEN_ITEM_LIMIT] if r.get("value")]
    rest = len(rows) - len(named)
    body = " and ".join(named) if len(named) < 3 else ", ".join(named)
    tail = f", and {rest} more on the screen." if rest > 0 else "."
    sentence = f"{head} You've got {body}{tail}".strip()
    if len(sentence) > SPEECH_CHAR_BUDGET:
        sentence = f"{head} {len(rows)} things today — they're on the screen.".strip()
    return sentence


def compose(
    agenda: Sequence[Any],
    *,
    title: str = "Today",
    greeting: str = "Morning.",
    actions: Sequence[Dict[str, Any]] = (),
    max_kb: int = DEFAULT_MAX_KB,
    max_proposals: int = MAX_PROPOSALS_PER_BRIEF,
) -> Brief:
    """Compose a brief from a day that has already been fetched.

    ``agenda`` is whatever ``hp_personal_plan_day`` or a calendar server returned; ``actions``
    are candidate proposals as ``{"capability", "summary", "arguments"}``. Candidates that do
    not pass :func:`gate` are dropped with a log line rather than raising — one bad suggestion
    from a model must not cost the user their morning — but a candidate that *does* pass and
    lands beyond ``max_proposals`` is deferred, and returned, and therefore still countable.
    """
    rows: List[Dict[str, Any]] = []
    for item in agenda or ():
        row = _row(item)
        if row is not None:
            rows.append(row)

    limit = MAX_ROWS["agenda"]
    shown = rows[:limit]
    if len(rows) > limit:
        # The panel refuses more rows than it can draw, and this is the caller that knows
        # what to do about it: say the number out loud rather than send a panel that fails.
        log.info("agenda has %d rows; the panel shows %d", len(rows), limit)

    data: Dict[str, Any] = {"title": title, "items": shown}
    if len(rows) > limit:
        data["footer"] = f"{len(rows) - limit} more not shown"
    panel = build("agenda", data, max_kb=max_kb)

    accepted: List[Proposal] = []
    for candidate in actions or ():
        if not isinstance(candidate, dict):
            continue
        try:
            accepted.append(
                propose(
                    str(candidate.get("capability") or ""),
                    str(candidate.get("summary") or ""),
                    candidate.get("arguments") if isinstance(candidate.get("arguments"), dict) else None,
                )
            )
        except AssistantError as error:
            log.info("assistant candidate refused — %s", error)

    keep = max(0, int(max_proposals))
    offered = tuple(accepted[:keep])
    deferred = tuple(accepted[keep:])

    speech = summarise(rows, greeting=greeting)
    if offered:
        speech = f"{speech} {offered[0].summary.rstrip('.')}?".strip()

    return Brief(
        panel=panel,
        speech=speech,
        intent=POINT_INTENT,
        proposals=offered,
        deferred=deferred,
    )


def good_morning(agenda: Sequence[Any], **kwargs: Any) -> Brief:
    """The named entry point the e2e test drives. A brief is a brief; this exists so the
    acceptance criterion reads the way it was written."""
    kwargs.setdefault("greeting", "Morning.")
    kwargs.setdefault("title", "Today")
    return compose(agenda, **kwargs)


__all__ = [
    "AssistantError",
    "Brief",
    "Proposal",
    "MAX_PROPOSALS_PER_BRIEF",
    "SPOKEN_ITEM_LIMIT",
    "SPEECH_CHAR_BUDGET",
    "POINT_INTENT",
    "capabilities",
    "compose",
    "gate",
    "good_morning",
    "propose",
    "summarise",
]
