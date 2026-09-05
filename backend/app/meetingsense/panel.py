"""The meeting card on the avatar surface (batch MS20, wave W6).

The card already exists twice over — `MeetingCard.tsx` in the web UI, and the summary message
in History. This adds a third *renderer*, not a third source: the same store rows become a
`display` panel of the existing `cards` kind, drawn by the avatar client's own panel renderer.

**A panel is a screen, not a document.** B20's channel caps a panel at 64 KB and a `cards`
panel at twelve rows, and those limits are the whole design of this module. A four-hundred
segment meeting has to arrive as something a person can read across a room in a glance, so what
is sent is a **summary projection**: what the meeting is, what was decided, what is still open,
what is on screen. The transcript is never rows — a panel is not where anybody reads a
transcript, and the web card, the export and MS13's `ask` are all better at it.

**The limits are read, never copied.** `MAX_CARDS` comes from `panels.MAX_ROWS`, so a panel
that the renderer's cap changes cannot silently start being refused: two numbers for one rule
is one number that drifts.

**What survives a trim is fixed, and it is not the newest thing.** The header card — what the
meeting is and how long it has run — is what makes every other row make sense, so it is built
first and dropped last. The transcript preview goes first, because it is the row this panel is
worst at and everything else is best at.

Pure with respect to the wire: this builds a payload and hands it to `panels.build`, which is
the one place that decides whether a panel is legal.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from . import export, store

log = logging.getLogger(__name__)


def max_cards() -> int:
    """The row cap, read from the panel channel rather than restated here."""
    try:
        from ..avatar_director.panels import MAX_ROWS

        return int(MAX_ROWS.get("cards", 12))
    except Exception:  # noqa: BLE001 — a missing director is not a broken meeting
        return 12


#: Transcript lines in the preview card, when there is room for one at all. Two, because the
#: card is a glance: the point is "it is still going and here is the shape of it", and a
#: reader who wants the words has the web card open.
PREVIEW_LINES = 2

#: Longest a card's body may be before it is cut at a word. A panel row that wraps to six
#: lines is a row nobody reads.
MAX_BODY = 180


def _clip(text: str, limit: int = MAX_BODY) -> str:
    body = " ".join((text or "").split())
    if len(body) <= limit:
        return body
    cut = body[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip(" ,;:") + "…"


def _done(item: Any) -> bool:
    return bool(isinstance(item, dict) and (item.get("resolved") or item.get("done")))


def _line(item: Any) -> str:
    if isinstance(item, dict):
        text = (item.get("text") or "").strip()
        owner = item.get("owner")
        return f"{text} — {owner}" if owner and text else text
    return str(item or "").strip()


def project(
    meeting: Dict[str, Any],
    segments: Sequence[Dict[str, Any]] = (),
    keyframes: Sequence[Dict[str, Any]] = (),
    notes: Any = None,
    *,
    live: bool = False,
    elapsed_ms: Optional[int] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """The `cards` payload for one meeting. Always inside the row cap.

    Cards are built in the order they matter and truncated from the end, so what a reader sees
    when a meeting is busy is the same first three rows they saw when it was quiet — a panel
    whose contents reshuffle as the meeting grows is one nobody can glance at.
    """
    cap = max_cards() if limit is None else max(1, int(limit))
    body = export.notes_body(notes) or {}
    cards: List[Dict[str, Any]] = []

    # 1. What this is. Built first and dropped last: every other row means less without it.
    started = meeting.get("started_at")
    ended = meeting.get("ended_at")
    if elapsed_ms is None:
        elapsed_ms = int((float(ended) - float(started)) * 1000) if (started and ended) else 0
    facts = [export.clock(elapsed_ms)]
    if meeting.get("source"):
        facts.append(str(meeting["source"]))
    facts.append(f"{len(segments)} segment{'' if len(segments) == 1 else 's'}")
    if keyframes:
        facts.append(f"{len(keyframes)} slide{'' if len(keyframes) == 1 else 's'}")
    cards.append({
        "title": (meeting.get("title") or "Meeting").strip() or "Meeting",
        "body": " · ".join(facts),
        "badge": "recording" if live else "ended",
    })

    # 2. The recap — the one row that stands in for everything not shown.
    recap = (body.get("recap") or body.get("summary") or "").strip()
    if recap:
        cards.append({"title": "So far", "body": _clip(recap)})

    # 3. Decisions, then what is still open. Resolved items are left out: a list that mixes
    #    them is a list the reader has to re-check, which is the opposite of a glance.
    for label, items in (
        ("Decided", body.get("decisions")),
        ("Still open", [q for q in (body.get("questions") or []) if not _done(q)]),
        ("Actions", [a for a in (body.get("actions") or []) if not _done(a)]),
    ):
        for item in items or []:
            text = _line(item)
            if text:
                cards.append({"title": label, "body": _clip(text)})

    # 4. What is on screen now. Late, because it is the row most likely to be stale by the
    #    time anybody reads the panel.
    for frame in reversed(list(keyframes)):
        caption = (frame.get("caption") or "").strip()
        if caption:
            cards.append({"title": "On screen", "body": _clip(caption)})
            break

    # 5. The last thing said, and only that. **The transcript is never rows** — a panel is not
    #    where a transcript is read, and the web card, the export and `ask` are all better at
    #    it. This is here so a live panel does not look frozen.
    spoken = [s for s in segments if (s.get("text") or "").strip()][-PREVIEW_LINES:]
    for segment in spoken:
        cards.append({
            "title": export.speaker_label(segment.get("speaker")),
            "body": _clip(segment["text"]),
            "stamp": export.clock(segment.get("t0_ms")),
        })

    return {
        "title": (meeting.get("title") or "Meeting").strip() or "Meeting",
        # Truncated from the end, so the header and the recap are the last things to go.
        "cards": cards[:cap],
        "meeting_id": meeting.get("id"),
    }


def display(
    meeting_id: str,
    *,
    live: bool = False,
    elapsed_ms: Optional[int] = None,
    max_kb: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """One `display` message for a meeting, or ``None``. Never raises.

    ``panels.build`` is what decides whether a panel is legal, and it is called rather than
    reimplemented: a second size check here would be a second answer to one question.
    """
    try:
        from ..avatar_director import panels

        meeting = store.get_meeting(meeting_id)
        if meeting is None:
            return None
        data = project(
            meeting,
            store.get_segments(meeting_id),
            store.get_keyframes(meeting_id),
            store.get_notes(meeting_id),
            live=live,
            elapsed_ms=elapsed_ms,
        )
        kwargs = {"max_kb": max_kb} if max_kb is not None else {}
        return panels.build("cards", data, **kwargs)
    except Exception:  # noqa: BLE001 — a panel is never worth the meeting
        log.exception("meetingsense: could not build a panel for %s", meeting_id)
        return None
