"""Presenter: the deck, the clock, and the questions that have to wait (batch MS26).

Presenter is the mode where the assistant's most important behaviour is **not** doing
something. The user is talking to a room. Anything said out loud lands on top of them, and a
question answered on their behalf mid-slide is worse than a question missed.

So the three jobs are: know where the deck is, say when the clock disagrees with it, and hold
the audience's questions until the user asks for them.

**The deck is attached, not inferred.** A deck is a list of sections the user wrote down
beforehand — titles and how long each is meant to take — stored in `ms_artifacts` so it
survives a reconnect and goes when the meeting is deleted. Inferring one from the slides that
have gone up would make "you are behind" a statement about a guess, and the first time it is
wrong the user turns the mode off.

**Pacing compares two things the server already knows**, the slide index and the elapsed time,
and says nothing unless they disagree by more than a threshold. A pacer that speaks every slide
is a clock, and the user has one.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Sequence

from .. import store

log = logging.getLogger(__name__)

#: Artifact kind the deck is stored under.
DECK_KIND = "deck"

#: Artifact kind a queued audience question is stored under.
QUEUE_KIND = "audience_question"

#: How far behind or ahead the deck has to be before it is worth saying, in milliseconds.
#: Two minutes: below that, every presenter drifts and being told about it is noise.
DRIFT_MS = 120_000

#: Most questions the queue will hold. Past this the queue is a transcript, and the meeting
#: already has one of those.
MAX_QUEUED = 20


# ── the deck ────────────────────────────────────────────────────────────────


def set_deck(meeting_id: str, sections: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach a deck. Returns the sections as stored.

    Each section is ``{"title": str, "minutes": number}``. A section with no title is dropped
    rather than stored blank — a pacing remark that names an empty string tells the user
    nothing and looks broken.
    """
    clean: List[Dict[str, Any]] = []
    for item in sections or ():
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        try:
            minutes = float(item.get("minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0.0
        clean.append({"title": title, "minutes": max(0.0, minutes)})
    if not clean:
        return []
    try:
        store.add_artifact(meeting_id, kind=DECK_KIND, detail=json.dumps(clean))
    except Exception:  # noqa: BLE001 — an install with no tables holds no deck
        log.exception("meetingsense: could not store the deck for %s", meeting_id)
        return []
    return clean


def deck(meeting_id: str) -> List[Dict[str, Any]]:
    """The deck attached to this meeting, or ``[]``. The last one attached wins."""
    try:
        rows = store.artifacts_for_meeting(meeting_id, kind=DECK_KIND)
    except Exception:  # noqa: BLE001
        return []
    for row in reversed(rows):
        try:
            body = json.loads(row.get("detail") or "")
        except ValueError:
            continue
        if isinstance(body, list) and body:
            return [s for s in body if isinstance(s, dict)]
    return []


def planned_ms(sections: Sequence[Dict[str, Any]]) -> List[int]:
    """Cumulative milliseconds by the *end* of each section."""
    out: List[int] = []
    total = 0
    for section in sections or ():
        total += int(round(float(section.get("minutes") or 0) * 60_000))
        out.append(total)
    return out


def pace(
    sections: Sequence[Dict[str, Any]],
    *,
    index: int,
    elapsed_ms: int,
    drift_ms: int = DRIFT_MS,
) -> Optional[str]:
    """One remark about the clock, or ``None`` — which is the usual answer.

    `index` is which section the user is on, zero-based; `elapsed_ms` is how long the meeting
    has been running.

    **A section is a window, not an instant.** It was meant to start when the previous one
    ended and to finish at its own planned time, and anywhere inside that window is on time.
    Comparing against the end alone makes the first minute of a ten-minute section read as
    "eight minutes ahead", which is the pacer telling a presenter who is exactly where they
    planned to be that they are early.

    So: behind by however far past the window's end the clock is, ahead by however far short
    of its start, and silent in between. Silent too when the deck is empty, when the index is
    off the end of it, and whenever the drift is under the threshold — every presenter drifts,
    and being told so is a clock.
    """
    plan = planned_ms(sections)
    if not plan or index < 0 or index >= len(plan):
        return None
    if plan[-1] <= 0:
        # A deck with no timings is a list of titles. Perfectly useful for saying where you
        # are, and no basis at all for saying whether you are late.
        return None
    starts_at = plan[index - 1] if index else 0
    ends_at = plan[index]
    now = int(elapsed_ms)
    if now > ends_at:
        drift = now - ends_at
    elif now < starts_at:
        drift = now - starts_at
    else:
        return None
    if abs(drift) < max(0, drift_ms):
        return None
    title = str((sections[index] or {}).get("title") or "").strip()
    minutes = abs(drift) // 60_000
    where = f"section {index + 1} of {len(plan)}"
    if title:
        where = f"{where}, {title!r}"
    if drift > 0:
        return f"{minutes} minutes behind on {where}."
    return f"{minutes} minutes ahead on {where}."


# ── the audience question queue ─────────────────────────────────────────────


def enqueue(meeting_id: str, question: str, *, t0: Optional[int] = None,
            asker: Optional[str] = None) -> bool:
    """Hold an audience question for later. ``True`` if it was held.

    **Held rather than answered.** That is the mode's one hard rule: interrupting a
    presentation to answer somebody in it is the failure this whole mode is arranged around.

    Deduped on the question text, because a question asked twice from the floor — which is what
    happens when the first asking was not heard — is one question.
    """
    body = (question or "").strip()
    if not body:
        return False
    existing = queued(meeting_id)
    if len(existing) >= MAX_QUEUED:
        return False
    seen = {q["text"].strip().lower() for q in existing}
    if body.lower() in seen:
        return False
    try:
        store.add_artifact(meeting_id, kind=QUEUE_KIND, target=asker or None,
                           detail=json.dumps({"text": body, "t0": t0}))
    except Exception:  # noqa: BLE001
        log.exception("meetingsense: could not queue a question for %s", meeting_id)
        return False
    return True


def queued(meeting_id: str) -> List[Dict[str, Any]]:
    """The questions waiting, oldest first. Answered ones are gone."""
    try:
        rows = store.artifacts_for_meeting(meeting_id, kind=QUEUE_KIND)
    except Exception:  # noqa: BLE001
        return []
    state: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        detail = row.get("detail") or ""
        if detail == "answered":
            # A withdrawal, recorded rather than deleted — the same rule MS24's revoke follows,
            # for the same reason: what was asked and when it was dealt with is what an
            # after-the-fact read of the meeting is for.
            key = (row.get("target") or "").strip()
            state.pop(key, None)
            continue
        try:
            body = json.loads(detail)
        except ValueError:
            continue
        if not isinstance(body, dict) or not (body.get("text") or "").strip():
            continue
        text = body["text"].strip()
        state[text.lower()] = {"text": text, "t0": body.get("t0"),
                               "asker": (row.get("target") or "") or None}
    return list(state.values())


def mark_answered(meeting_id: str, question: str) -> bool:
    """Take a question off the queue. ``True`` if one came off."""
    body = (question or "").strip().lower()
    if not body or body not in {q["text"].strip().lower() for q in queued(meeting_id)}:
        return False
    try:
        store.add_artifact(meeting_id, kind=QUEUE_KIND, target=body, detail="answered")
    except Exception:  # noqa: BLE001
        log.exception("meetingsense: could not clear a queued question for %s", meeting_id)
        return False
    return True
