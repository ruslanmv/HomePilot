"""What a persona knows about the meeting happening right now (batch MS18, wave W6).

Together mode is a person talking to a persona *while* a meeting is running, and the persona
being useful about it — "what did she just say the number was?", "draft a reply to that". The
whole feature is one block of text prepended to the system prompt, and everything hard about
it is what that block may not contain.

**The transcript is not it.** HomePilot's chat path passes `get_recent(cid, limit=6)` and drops
everything older; that limit is not touched by this batch and must not be. A three-hour meeting
is perhaps 30,000 words, and a block that grows with the meeting turns every question in the
second hour into a truncated prompt — which produces an answer confidently wrong about the part
that got cut. So this is **D9 tiers 1 and 2 only**: the last 90 seconds verbatim, the slide on
screen, the rolling notes, and the recap. Everything older reaches the persona through MS15's
retrieval, cited, when it is asked for.

**The budget is enforced, not requested.** 900 tokens, the same number MS13 answers under, and
the trim order is D9's priority made executable a second time: **verbatim first, then the notes
list, and the recap never.** The recap is the only tier that represents the parts of the meeting
nothing else can reach, and dropping it to make room for thirty seconds of detail trades the
summary of three hours for the last half-sentence.

**Off is byte-identical.** With no live meeting, or with the `together` flag down, this returns
``""`` and the prompt is character-for-character what it was before the batch. That is asserted
rather than assumed: a context provider that quietly changes every prompt on every install is
a change to every persona in the product.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from . import ask, export, store

log = logging.getLogger(__name__)

#: What the block is called in the prompt. A named block rather than loose prose so a persona
#: can be told about it once, and so a reader debugging a transcript can find it.
BLOCK_HEADER = "[LIVE MEETING CONTEXT]"

#: D9's budget, and deliberately the same constant MS13 answers under: two numbers for one
#: rule is one number that drifts.
TOKEN_BUDGET = ask.TOKEN_BUDGET

#: Tier 1's window, likewise shared with MS13.
VERBATIM_MS = ask.VERBATIM_MS

#: Most note items of each kind. The notes list is what gets trimmed second, and a cap here
#: means the trim loop starts from something bounded rather than from an hour of decisions.
MAX_ITEMS = 6

#: Told to the persona once, inside the block. Without it a model asked "what did she say?"
#: answers about the last thing in *its* window, which is the chat, not the meeting.
PREAMBLE = (
    "A meeting is being recorded right now. What follows is the only part of it you can see: "
    "a summary of everything so far, the current notes, and the last minute or two verbatim. "
    "You cannot see the rest of the transcript and must not claim to. Cite a timestamp only "
    "if it appears below."
)


def enabled(config: Any) -> bool:
    """Whether Together mode is on. Off by default, like every sub-flag."""
    return bool(getattr(config, "enabled", False)
                and getattr(getattr(config, "flags", None), "together", False))


def _items(items: Any, limit: int = MAX_ITEMS) -> List[str]:
    out: List[str] = []
    for item in (items or [])[:limit]:
        text = (item.get("text") or "").strip() if isinstance(item, dict) else str(item).strip()
        if not text:
            continue
        owner = f" — {item['owner']}" if isinstance(item, dict) and item.get("owner") else ""
        stamp = ""
        if isinstance(item, dict) and isinstance(item.get("t0"), (int, float)):
            stamp = f" [{export.clock(item['t0'])}]"
        out.append(f"  - {text}{owner}{stamp}")
    return out


def current_slide(keyframes: Sequence[Dict[str, Any]]) -> str:
    """The caption of the slide on screen now, or ``""``.

    The last captioned keyframe, because the strip's last entry is what is up — a later
    uncaptioned one is a slide the vision model has not answered about yet, and skipping back
    to the one before it is more use than saying nothing.
    """
    for frame in reversed(list(keyframes)):
        caption = (frame.get("caption") or "").strip()
        if caption:
            return f"{export.clock(frame.get('t_ms'))} {caption}"
    return ""


def _render(rows: Sequence[Dict[str, Any]]) -> List[str]:
    lines = []
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"  [{export.clock(row.get('t0_ms'))}] {export.speaker_label(row.get('speaker'))}: {text}")
    return lines


def assemble(
    *,
    recap: str = "",
    notes: Optional[Dict[str, Any]] = None,
    slide: str = "",
    verbatim_rows: Sequence[Dict[str, Any]] = (),
    elapsed_ms: int = 0,
    title: str = "",
    budget: int = TOKEN_BUDGET,
) -> str:
    """Build the block, trimming to the budget. Pure, so the trim order can be tested.

    Trim order, and it is the whole of D9's priority: **the verbatim tier is trimmed oldest
    first, then the notes list, and the recap never.** A model that has the recap and no
    verbatim can still answer "what has this meeting been about"; one with the verbatim and no
    recap knows the last thirty seconds of a three-hour call and nothing else.
    """
    body = dict(notes or {})
    verbatim = list(verbatim_rows)
    decisions = _items(body.get("decisions"))
    actions = _items([a for a in (body.get("actions") or []) if not _done(a)])
    questions = _items([q for q in (body.get("questions") or []) if not _done(q)])

    def render() -> str:
        parts: List[str] = [BLOCK_HEADER, PREAMBLE]
        header = title.strip() or "Meeting"
        parts.append(f"{header} · running {export.clock(elapsed_ms)}")
        if recap.strip():
            parts.append(f"So far:\n{recap.strip()}")
        if decisions:
            parts.append("Decisions:\n" + "\n".join(decisions))
        if questions:
            parts.append("Open questions:\n" + "\n".join(questions))
        if actions:
            parts.append("Actions:\n" + "\n".join(actions))
        if slide:
            parts.append(f"On screen now:\n  {slide}")
        rendered = _render(verbatim)
        if rendered:
            parts.append("The last minute or two:\n" + "\n".join(rendered))
        return "\n\n".join(parts)

    text = render()
    # Verbatim first, oldest line first: the newest is likeliest to be what a question asked
    # mid-meeting is about, and trimming from the end would strip the context nearest the ask.
    while ask.estimate_tokens(text) > budget and verbatim:
        verbatim.pop(0)
        text = render()
    # Then the notes lists, longest first, one item at a time from the end of each.
    while ask.estimate_tokens(text) > budget and (actions or questions or decisions):
        longest = max((actions, questions, decisions), key=len)
        longest.pop()
        text = render()
    # The recap is never trimmed. If the budget is still blown it is because a recap alone
    # exceeds it, which MS12 caps at 120 words and cannot.
    return text


def _done(item: Any) -> bool:
    return bool(isinstance(item, dict) and (item.get("resolved") or item.get("done")))


def build(meeting_id: str, *, now_ms: Optional[int] = None, budget: int = TOKEN_BUDGET) -> str:
    """The block for one meeting, read from the store. ``""`` when there is nothing to say."""
    try:
        meeting = store.get_meeting(meeting_id)
        if meeting is None:
            return ""
        segments = store.get_segments(meeting_id)
        keyframes = store.get_keyframes(meeting_id)
        notes = store.get_notes(meeting_id)
    except Exception:  # noqa: BLE001 — a prompt is never worth failing a chat over
        log.debug("meetingsense: could not read live context for %s", meeting_id, exc_info=True)
        return ""

    body = export.notes_body(notes) or {}
    recap = (body.get("recap") or body.get("summary") or "").strip()

    end_ms = now_ms
    if end_ms is None:
        ends = [int(s.get("t1_ms") or s.get("t0_ms") or 0) for s in segments]
        end_ms = max(ends) if ends else 0

    verbatim_rows = ask.verbatim(segments, now_ms=end_ms)
    if not (recap or verbatim_rows or body or keyframes):
        # A meeting that started ten seconds ago has nothing to say yet, and a block saying so
        # is a block that costs tokens to tell a persona nothing.
        return ""

    return assemble(
        recap=recap,
        notes=body,
        slide=current_slide(keyframes),
        verbatim_rows=verbatim_rows,
        elapsed_ms=end_ms,
        title=(meeting.get("title") or "").strip(),
        budget=budget,
    )


def for_conversation(conversation_id: str, *, config: Any = None) -> str:
    """The block for whatever meeting is live in this conversation. ``""`` when none is.

    The entry point `prompt_builder` calls, and the reason it is here rather than there: this
    file may import the store, the config and the session registry, and the prompt builder may
    not learn about any of them. Never raises — a chat that fails because a meeting was being
    recorded would be a worse bug than no context at all.
    """
    if not conversation_id:
        return ""
    try:
        from .config import load_config
        from . import session as session_mod

        cfg = config if config is not None else load_config()
        if not enabled(cfg):
            return ""
        live = session_mod.for_conversation(conversation_id)
        if live is None:
            return ""
        return build(live.meeting_id, now_ms=live.elapsed_ms)
    except Exception:  # noqa: BLE001
        log.debug("meetingsense: live context unavailable for %s", conversation_id, exc_info=True)
        return ""
