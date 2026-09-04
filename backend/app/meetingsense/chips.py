"""Deterministic triggers, and the chips they produce (batch MS25, wave W9).

A chip is a small, dismissible offer on the meeting card: *"that looked like a decision"*,
*"there is a date in that sentence"*, *"the slide has a link"*. Nothing here asks a model.

**Why deterministic, when there is a notes engine right there.** A chip interrupts. It appears
while somebody is talking, and it appears *because* of what they just said, so a chip that is
wrong is not a bad summary the user can scroll past — it is the assistant visibly
misunderstanding the room, in front of the room. MS12's notes can afford to be occasionally
loose because they are read afterwards; a chip cannot. So every trigger here is a regular
expression with a written-down negative set, and the tests that matter are **the ones that must
not fire**.

That buys a specific trade, stated once so nobody has to rediscover it: these triggers *miss*.
"monday.com" is not a date and "we're going with the second option, I think" is not matched as a
decision. A trigger that misses costs the user a chip they might have liked. A trigger that
fires wrongly costs them trust in the whole card, and they only spend that once.

**Nothing here acts.** A chip may carry a *proposal* — "add this to the calendar" — and a
proposal is never executed on arrival. The user accepts it, and only then does it go through
`agentic/runtime_tool_router.py`, inside MS24's per-meeting approval. That is ask-before-acting
in the only form that means anything: the ask happens before the act, not alongside it.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

log = logging.getLogger(__name__)

#: The chip kinds. Closed, like the panel kinds and the graph's events: an unknown kind is a
#: chip the card cannot render, and a card that renders nothing is a silence nobody can debug.
KINDS = ("question", "decision", "action", "date", "link")

#: Chips one turn may produce. A turn that yields six of these has not found six moments; it
#: has found one sentence that tripped every trigger, and showing all six is how a card stops
#: being read at all.
MAX_PER_TURN = 3

#: Chips one meeting may produce. Beyond this the card is a list, and a list is what the notes
#: already are.
MAX_PER_MEETING = 40

# ── the shared negatives ────────────────────────────────────────────────────

#: A URL, stripped before every other trigger looks at the text. Without this, `monday.com`
#: reads as a weekday and `example.com/2026-04-20/` reads as a date — both from the same cause,
#: which is why the strip happens once here rather than being guarded five times.
_URL = re.compile(r"\b(?:https?://|www\.)\S+", re.I)

#: A bare host, for the same reason. `monday.com` and `friday.co.uk` are the whole point.
_HOST = re.compile(r"\b[\w-]+(?:\.[\w-]+)+\b")

#: Not a decision, not an action: the sentence is asking about one. Checked as a prefix as well
#: as a "?" because a transcript is punctuated by a speech model, and "so are we going with the
#: second option" arrives without its question mark about as often as with it.
_ASKING = re.compile(
    r"^\s*(?:so\s+|and\s+|but\s+|ok(?:ay)?,?\s+)*"
    r"(?:who|what|when|where|why|how|which|"
    r"do|does|did|are|is|was|were|will|would|should|shall|can|could|have|has|had)\b",
    re.I,
)

#: Negation anywhere before the marker kills it. "we have not decided" is the exact sentence a
#: decision chip must never fire on, because it is what people say *instead* of deciding.
_NOT = re.compile(r"\b(?:not|never|n't|cannot|can't|won't|wouldn't|shouldn't|didn't|"
                  r"haven't|hasn't|don't|doesn't|nothing|no\s+one|nobody)\b", re.I)


def _strip_urls(text: str) -> str:
    """Blank out anything that is an address, so no other trigger reads inside one."""
    return _HOST.sub(" ", _URL.sub(" ", text or ""))


def _asking(text: str) -> bool:
    """Is this sentence a question rather than a statement?"""
    body = (text or "").strip()
    return body.endswith("?") or bool(_ASKING.match(body))


# ── question aimed at me ────────────────────────────────────────────────────

#: Second person, with word boundaries — "young" is not "you" and "yourself" is.
_SECOND_PERSON = re.compile(r"\b(?:you|your|yours|you're|yourself)\b", re.I)

#: Questions that are shaped like questions and are not asking for anything. Every one of these
#: has a second-person pronoun and a question mark, which is exactly why they are listed: they
#: pass the rule and they must not fire. A chip on "does that make sense?" is the assistant
#: mistaking a verbal comma for a request.
_FILLER = (
    "does that make sense", "do you know what i mean", "you know what i mean",
    "do you follow", "are you with me", "you know", "right", "you see",
    "can you hear me", "can you see my screen", "are you there", "you good",
)


def _is_filler(text: str) -> bool:
    body = " ".join(re.findall(r"[^\W_]+", (text or "").lower()))
    return any(body == f or body.endswith(" " + f) or body == f + " right" for f in _FILLER)


def _question(segment: Dict[str, Any], *, names: Sequence[str] = ()) -> Optional[Dict[str, Any]]:
    """A question somebody else asked *this user*.

    Three conditions, and every one of them exists to stop a chip rather than to start one:

    - **Somebody else asked it.** MS4 fixes the channels — ``them`` is the call, ``me`` is this
      machine's microphone — so a question the user asked is a question they already know about.
    - **It is a question.** A "?" from the speech model, or an interrogative opening for the
      times it does not punctuate one.
    - **It is aimed at them**, by second person or by name. "What time is the release?" is a
      question to the room; a chip on it is the assistant volunteering.
    """
    text = (segment.get("text") or "").strip()
    if not text or (segment.get("speaker") or "") != "them":
        return None
    if not _asking(text):
        return None
    if _is_filler(text):
        return None
    aimed = bool(_SECOND_PERSON.search(text)) or _named(text, names)
    if not aimed:
        return None
    return {"kind": "question", "text": text, "t0": segment.get("t0_ms")}


def _named(text: str, names: Sequence[str]) -> bool:
    """Addressed by name — the user's, or a persona's."""
    for name in names:
        token = (name or "").strip()
        if len(token) < 2:
            continue
        if re.search(rf"\b{re.escape(token)}\b", text, re.I):
            return True
    return False


# ── decision ────────────────────────────────────────────────────────────────

_DECIDED = re.compile(
    r"\b(?:we(?:'ve| have)?\s+decided|we\s+agreed|it'?s\s+agreed|"
    r"let'?s\s+go\s+with|we(?:'ll| will|'re| are)\s+going\s+with|"
    r"the\s+decision\s+is|we(?:'re| are)\s+settled\s+on)\b",
    re.I,
)


def _decision(segment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A decision that was announced, not one that was wondered about.

    Two negatives carry this trigger. A question about deciding is not a decision — "should we
    go with the second option?" is the sentence a meeting says *before* deciding. And a negated
    marker is not a decision either: "we have not decided" is what people say instead.
    """
    text = (segment.get("text") or "").strip()
    if not text or _asking(text):
        return None
    match = _DECIDED.search(text)
    if not match:
        return None
    if _NOT.search(text[: match.start()]):
        return None
    return {"kind": "decision", "text": text, "t0": segment.get("t0_ms")}


# ── action ──────────────────────────────────────────────────────────────────

#: A named owner and a commitment. Narrow on purpose — the same trade MS24's extractor makes,
#: for the same reason: an install with no model gets the commitments that were phrased plainly
#: and misses the rest, which beats a regular expression guessing at intent.
_COMMITTED = re.compile(
    r"(?:^|(?<=[\s,;]))(?P<who>I|[A-Z][a-z]+)"
    r"(?:'ll|\s+(?:will|am\s+going\s+to|is\s+going\s+to|are\s+going\s+to))\s+(?P<what>\w+)",
)

#: Owners that are not owners. "We will see" and "It will be fine" are not commitments, and
#: "Someone will do it" is the sentence that means nobody will.
_NOT_AN_OWNER = {"we", "it", "someone", "somebody", "anyone", "anybody", "everyone",
                 "everybody", "nobody", "they", "there", "that", "this", "who"}

#: Verbs that make a sentence a prediction rather than a promise. "I will see", "I will try".
_NOT_A_COMMITMENT = {"see", "try", "think", "guess", "hope", "probably", "maybe", "be", "have"}


def _action(segment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Somebody said they would do something, by name and in the plain form."""
    text = (segment.get("text") or "").strip()
    if not text or _asking(text):
        return None
    for match in _COMMITTED.finditer(text):
        who = match.group("who")
        if who.lower() in _NOT_AN_OWNER:
            continue
        if match.group("what").lower() in _NOT_A_COMMITMENT:
            continue
        # Negation before the owner, *and* inside the commitment itself: "Ana will not send"
        # puts its "not" between the auxiliary and the verb, where a prefix check cannot see it.
        if _NOT.search(text[: match.start()]) or _NOT.search(match.group(0)):
            continue
        owner = "me" if who == "I" else who
        return {"kind": "action", "text": text, "t0": segment.get("t0_ms"), "owner": owner}
    return None


# ── date ────────────────────────────────────────────────────────────────────

_WEEKDAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday"
_MONTHS = ("january|february|march|april|may|june|july|august|september|october|november|"
           "december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec")

_DATE = re.compile(
    rf"\b(?:\d{{4}}-\d{{2}}-\d{{2}}"                      # 2026-04-20
    rf"|(?:next|this|last)\s+(?:{_WEEKDAYS})"             # next Tuesday
    rf"|(?:on|by|before|after|until)\s+(?:{_WEEKDAYS})"   # by Friday
    rf"|(?:{_MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?"        # March 3
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS})"  # 3rd of March
    rf")\b",
    re.I,
)


def _date(segment: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A date somebody said out loud.

    The URLs come out first, and that one line is most of this trigger's correctness:
    ``monday.com`` is a company, ``example.com/2026-04-20/notes`` is a permalink, and both read
    as dates to any pattern that has not been shown the address.

    A bare weekday is deliberately *not* a date. "Friday" alone is as often a description of
    the week as a deadline; "by Friday" and "next Friday" are the forms people use when they
    mean a day, and requiring the preposition is what keeps "it's been a long Friday" quiet.
    """
    text = (segment.get("text") or "").strip()
    if not text:
        return None
    match = _DATE.search(_strip_urls(text))
    if not match:
        return None
    return {"kind": "date", "text": text, "t0": segment.get("t0_ms"),
            "when": match.group(0).strip()}


# ── a link on a slide ───────────────────────────────────────────────────────

#: A scheme or a `www.`, and nothing else. A bare host would make `node.js` and `report.pdf`
#: into links, and a slide deck is full of both. This misses `monday.com` written plainly on a
#: slide, which is a real miss and the right one: a link chip that opens `report.pdf` in a
#: browser is worse than no link chip.
_SLIDE_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"'\])]+", re.I)


def _link(keyframe: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A URL that was **on the screen**, never one that was spoken.

    The batch row says "URL on a slide", and the distinction is not pedantry: a link somebody
    read out is a link the listener already has, while a link on a slide that nobody read out
    is the one people photograph the screen for.
    """
    caption = str((keyframe or {}).get("caption") or "")
    match = _SLIDE_URL.search(caption)
    if not match:
        return None
    url = match.group(0).rstrip(".,;:")
    return {"kind": "link", "text": url, "t0": keyframe.get("t_ms"), "url": url}


# ── what a chip may offer to do ─────────────────────────────────────────────

#: kind → the capability the runtime tool router is asked to resolve, and the button's words.
#: A capability, not a tool id: MS23 already decided that a second resolver is a second
#: allow-list, and one that disagrees with Forge's is a security control that is wrong half the
#: time. `question` and `decision` are absent on purpose — there is nothing to *do* about a
#: question except answer it, and the card already has a way to ask.
PROPOSALS: Dict[str, Dict[str, str]] = {
    "action": {"capability": "tasks.create", "label": "Add to tasks"},
    "date": {"capability": "calendar.create_event", "label": "Add to calendar"},
    "link": {"capability": "web.fetch", "label": "Summarise this page"},
}


def _proposal(chip: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The offer a chip carries, or None. **Never executed here** — see `accept`."""
    spec = PROPOSALS.get(chip["kind"])
    if not spec:
        return None
    args: Dict[str, Any] = {"text": chip["text"]}
    if chip.get("when"):
        args["when"] = chip["when"]
    if chip.get("url"):
        args["url"] = chip["url"]
    if chip.get("owner"):
        args["owner"] = chip["owner"]
    return {"capability": spec["capability"], "label": spec["label"], "args": args}


# ── assembling a turn's chips ───────────────────────────────────────────────


def usable(chip: Optional[Dict[str, Any]]) -> bool:
    """Is this something the card can render?

    A closed kind and some text. Module level rather than inline in `detect` so it can be
    called with the chip a trigger will never build — which is the only way a guard against a
    future trigger is testable at all.
    """
    if not isinstance(chip, dict):
        return False
    if chip.get("kind") not in KINDS:
        return False
    return bool((chip.get("text") or "").strip())


def key(chip: Dict[str, Any]) -> str:
    """How two chips are judged to be the same offer.

    MS12's normalisation — case- and punctuation-insensitive — scoped by kind, because the same
    sentence can legitimately be both a decision and a date and those are two different offers.
    """
    body = " ".join(re.findall(r"[^\W_]+", (chip.get("text") or "").lower()))
    return f"{chip.get('kind')}:{body}"


def chip_id(meeting_id: str, chip: Dict[str, Any]) -> str:
    """A stable id, derived from the offer rather than from a counter.

    Derived, so the same offer arriving twice — a resume replaying segments, two clients on one
    meeting — is the same chip on both cards rather than two chips on one.
    """
    digest = hashlib.sha256(f"{meeting_id}\x00{key(chip)}".encode()).hexdigest()
    return f"chip_{digest[:16]}"


def detect(
    segments: Iterable[Dict[str, Any]] = (),
    *,
    keyframe: Optional[Dict[str, Any]] = None,
    names: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    """Every trigger, over one turn's input. Pure: no store, no clock, no model.

    A segment may produce more than one chip — "Ana will send the terms by Friday" is genuinely
    an action *and* a date — but the turn is capped, because a turn that produces six chips has
    found one sentence that tripped every trigger rather than six moments worth interrupting for.
    """
    out: List[Dict[str, Any]] = []
    seen: set = set()

    def add(chip: Optional[Dict[str, Any]]) -> None:
        if not usable(chip):
            return
        k = key(chip)
        if k in seen:
            return
        seen.add(k)
        proposal = _proposal(chip)
        if proposal:
            chip = dict(chip, proposal=proposal)
        out.append(chip)

    for segment in segments or ():
        # Junk is skipped here rather than caught below. There is no `try` around this loop on
        # purpose: detection is pure — no clock, no store, no model — so the only exception it
        # can raise is a programming error, and a swallowed one would be a trigger that
        # silently stopped firing with a green suite. The caller (`session._maybe_chips`) holds
        # the guard that keeps a chip from ever costing a meeting.
        if not isinstance(segment, dict):
            continue
        add(_question(segment, names=names))
        add(_decision(segment))
        add(_action(segment))
        add(_date(segment))

    if isinstance(keyframe, dict) and keyframe:
        add(_link(keyframe))

    return out[:MAX_PER_TURN]


def frame(meeting_id: str, chip: Dict[str, Any]) -> Dict[str, Any]:
    """One chip, as it goes down the wire.

    `proposal` is present and `accepted` is false. The card renders a button; nothing has run.
    """
    body = {"type": "chip", "id": chip_id(meeting_id, chip), "kind": chip["kind"],
            "text": chip["text"], "t0": chip.get("t0")}
    for extra in ("owner", "when", "url", "proposal"):
        if chip.get(extra) is not None:
            body[extra] = chip[extra]
    return body


# ── accepting a proposal ────────────────────────────────────────────────────

#: The artifact kind an accepted chip is recorded under, so a meeting's record shows what was
#: offered *and* acted on. Refusals are recorded too — see `accept`.
ACCEPT_KIND = "chip_action"


async def accept(
    meeting_id: str,
    chip: Dict[str, Any],
    *,
    router: Any,
    tool_source: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a chip's proposal, now that somebody has said yes. Never raises.

    This is the whole of ask-before-acting, and the order is the point: the chip was shown
    without running anything, the user accepted, and only then is a tool resolved. A chip that
    ran its proposal in order to show a nicer label would be acting-before-asking with an ask
    drawn on top.

    **Three gates, all of which can say no.**

    1. The chip has a proposal at all. A `question` chip has nothing to run.
    2. The **runtime tool router** resolves the capability inside the project's allow-list —
       `agentic/runtime_tool_router.py`, not a second resolver here. MS23 settled that: a
       second allow-list that disagrees with the one Forge enforces is a security control that
       is wrong half the time.
    3. MS24's **per-meeting approval** covers the tool the router picked. The mode said tools
       may be used; this says *this* tool, for *this* meeting. A capability the user approved
       in one meeting is not approved in the next one.

    Gate 3 is checked on the **resolved tool id**, after the router has spoken, because that is
    the thing that will actually be invoked. Checking the capability instead would approve a
    name and run whatever the catalog currently maps it to.
    """
    from .agent import subagents

    proposal = (chip or {}).get("proposal") or {}
    capability = str(proposal.get("capability") or "")
    if not capability:
        return {"ok": False, "reason": "this chip has nothing to run"}

    try:
        decision = await router.resolve(capability, tool_source)
    except Exception as error:  # noqa: BLE001 — a chip is never worth the meeting
        log.exception("meetingsense: chip routing failed")
        return {"ok": False, "reason": f"could not resolve {capability}: {error}"}

    tool_id = getattr(decision, "resolved_tool_id", None)
    if not tool_id:
        # The router's own words, forwarded rather than paraphrased: it knows whether the
        # project has no tools, no matching tool, or no tool source at all, and the user is
        # owed the difference.
        return {"ok": False, "reason": getattr(decision, "reason", "no tool available"),
                "mode": getattr(decision, "mode", None)}

    if tool_id not in set(subagents.approved(meeting_id)):
        _record(meeting_id, chip, tool_id, "refused")
        return {"ok": False, "needs_approval": tool_id,
                "reason": f"{tool_id} is not approved for this meeting"}

    try:
        output = await router.invoke(tool_id, proposal.get("args") or {})
    except Exception as error:  # noqa: BLE001
        log.exception("meetingsense: chip action %s failed", tool_id)
        _record(meeting_id, chip, tool_id, "failed")
        return {"ok": False, "tool": tool_id, "reason": f"{tool_id} failed: {error}"}

    _record(meeting_id, chip, tool_id, "ran")
    return {"ok": True, "tool": tool_id, "output": output}


def _record(meeting_id: str, chip: Dict[str, Any], tool_id: str, outcome: str) -> None:
    """Write what happened to the artifact log. Never raises.

    A refusal is recorded as well as a run, for the reason MS24 records a refused tool call: an
    action that vanishes silently is one nobody can approve, because nobody knows it was wanted.
    """
    from . import store  # noqa: F401

    try:
        store.add_artifact(meeting_id, kind=ACCEPT_KIND, target=tool_id,
                           detail=f"{outcome}:{chip_id(meeting_id, chip)}")
    except Exception:  # noqa: BLE001 — an install with no tables has nothing to record to
        log.exception("meetingsense: could not record chip action")


def router_bridge() -> Optional[Any]:
    """The agentic runtime tool router, or None if this install has no agentic stack.

    Built the way MS9's `vision_bridge` is built, and for the same reason: MeetingSense reads
    another subsystem's capability at the edge and holds no opinion about it. `None` means chip
    proposals cannot run on this install — the chips still appear and still say what they
    found, which is most of their value.
    """
    try:
        from ..agentic.routes import _tool_router  # noqa: PLC0415

        return _tool_router()
    except Exception:  # noqa: BLE001 — an install without the agentic stack has no router
        log.debug("meetingsense: no runtime tool router available", exc_info=True)
        return None
