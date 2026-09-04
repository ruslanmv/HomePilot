"""Coach: talking points from prep material, and the screen it must never read (MS27, W9).

Coach is the mode with a **refusal in it**, and this file is where the refusal is enforced
rather than requested.

**What Coach may see.** The user's own uploaded prep material — the brief they wrote, the
questions they expect, the numbers they want to land — and the transcript of what has been
said. That is the whole list.

**What Coach must never see: anything read off the screen.** MeetingSense captures keyframes
and a vision model captions them, which is how it knows a slide said "Q3 revenue is flat". That
capability is for the user's *own* slides in Presenter, and pointing it at a Coach changes what
the feature is: a coach that can read the screen can read the other participants' documents,
their open tabs, their messages — in a meeting where nobody consented to that and the user
cannot see what was captured either. The design document refuses it, and a refusal in a design
document is a sentence until something enforces it.

So the enforcement is structural, not a prompt line:

- `context()` assembles from **an allow-list of two sources**, and there is no branch that
  reaches a keyframe. A test reads this module's source and fails if the words appear.
- `scrub()` runs over the assembled context anyway and drops any row that carries a slide's
  fingerprint, so a future caller that hands us a mixed list cannot smuggle one in.
- A test drives a meeting whose captions contain a distinctive string and asserts it never
  reaches the model.

Three gates for one rule is more than a rule usually gets. This one earns it: the failure is
silent, the user cannot see it happening, and the people it affects are not in the room.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from .. import store

log = logging.getLogger(__name__)

#: Artifact kind prep material is stored under.
PREP_KIND = "prep"

#: Most prep documents one meeting will hold. Past this the "prep material" is a library, and
#: a coach that has read a library has read nothing.
MAX_PREP = 10

#: Words of prep material one turn may carry. The coaching prompt is small on purpose — it
#: competes with nothing, because Coach speaks only to the user.
PREP_BUDGET_WORDS = 400

#: Keys that mean "this came off the screen". Any row carrying one is dropped by `scrub`,
#: whatever else it claims to be. Kept as data so the check is one list rather than a
#: condition repeated at each call site.
SCREEN_KEYS = ("caption", "keyframe_id", "hash", "url", "slide", "ocr", "image")

#: `kind` values that mean the same thing. MS15's rows carry one of these.
SCREEN_KINDS = ("slide", "keyframe", "screen", "ocr")


# ── prep material ───────────────────────────────────────────────────────────


def add_prep(meeting_id: str, title: str, text: str) -> Optional[Dict[str, Any]]:
    """Attach one piece of prep material. ``None`` if there was nothing to attach.

    Stored as text on the meeting rather than as a pointer into a project, because prep is the
    thing Coach is *restricted* to and a pointer is a restriction somebody else can widen. A
    document attached here is a document the user chose for this meeting.
    """
    body = (text or "").strip()
    name = (title or "").strip() or "Prep"
    if not body:
        return None
    if len(prep(meeting_id)) >= MAX_PREP:
        return None
    try:
        store.add_artifact(meeting_id, kind=PREP_KIND, target=name,
                           detail=json.dumps({"title": name, "text": body}))
    except Exception:  # noqa: BLE001 — an install with no tables holds no prep
        log.exception("meetingsense: could not attach prep to %s", meeting_id)
        return None
    return {"title": name, "words": len(body.split())}


def prep(meeting_id: str) -> List[Dict[str, Any]]:
    """Everything the user attached, oldest first. ``[]`` when they attached nothing."""
    try:
        rows = store.artifacts_for_meeting(meeting_id, kind=PREP_KIND)
    except Exception:  # noqa: BLE001
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            body = json.loads(row.get("detail") or "")
        except ValueError:
            continue
        if not isinstance(body, dict):
            continue
        text = (body.get("text") or "").strip()
        if not text:
            continue
        out.append({"title": (body.get("title") or "Prep").strip(), "text": text})
    return out


def drop_prep(meeting_id: str) -> int:
    """Forget every piece of prep on this meeting. Returns how many rows were cleared.

    A hard delete rather than a recorded withdrawal, which is the opposite of what MS24's
    approvals and MS26's queue do — and deliberately. Those are records of consent and of what
    was asked; this is the user's own document, and "remove my document" that leaves the
    document in the database is not a removal.
    """
    try:
        return store.delete_artifacts(meeting_id, kind=PREP_KIND)
    except Exception:  # noqa: BLE001
        log.exception("meetingsense: could not drop prep for %s", meeting_id)
        return 0


# ── the boundary ────────────────────────────────────────────────────────────


def from_screen(row: Any) -> bool:
    """Did this row come off the screen?

    Deliberately generous about what counts. A row is refused if it carries any key that only a
    captured frame carries, or names itself as one. Being wrong in this direction costs the
    coach a line of transcript; being wrong in the other direction is the failure the whole
    file exists to prevent, and nobody in the meeting would ever know it happened.
    """
    if not isinstance(row, dict):
        return False
    if str(row.get("kind") or "").strip().lower() in SCREEN_KINDS:
        return True
    return any(key in row for key in SCREEN_KEYS)


def scrub(rows: Sequence[Any]) -> List[Dict[str, Any]]:
    """Everything that did not come off the screen.

    The belt behind `context`'s allow-list. `context` never fetches a keyframe, so in the
    shipped path this removes nothing — which is exactly why it is here: the day a caller
    assembles rows somewhere else and passes them in, this is what stops it, and the day
    somebody edits `context` this is what still holds.
    """
    return [row for row in (rows or ()) if isinstance(row, dict) and not from_screen(row)]


def context(
    meeting_id: str,
    *,
    segments: Optional[Sequence[Dict[str, Any]]] = None,
    budget_words: int = PREP_BUDGET_WORDS,
) -> Dict[str, Any]:
    """What Coach is allowed to know. Two sources, named here and nowhere else.

    `segments` is injected rather than fetched so a caller can pass the live window; when it is
    ``None`` the transcript is read from the store. Either way it goes through `scrub`, because
    "the transcript" is a list somebody else built.
    """
    material = prep(meeting_id)[:MAX_PREP]
    spoken = segments if segments is not None else _transcript(meeting_id)
    return {"prep": _trim(material, budget_words), "said": scrub(spoken)}


def _transcript(meeting_id: str) -> List[Dict[str, Any]]:
    """The words. Only ever the words."""
    try:
        return list(store.get_segments(meeting_id))
    except Exception:  # noqa: BLE001
        return []


def _trim(material: Sequence[Dict[str, Any]], budget_words: int) -> List[Dict[str, Any]]:
    """Fit the prep to the budget, whole documents first, then truncating the last one.

    Truncating rather than dropping, because the first document a user attaches is usually
    their brief and half a brief is more use than none of it.
    """
    out: List[Dict[str, Any]] = []
    left = max(0, int(budget_words))
    for doc in material:
        if left <= 0:
            break
        words = (doc.get("text") or "").split()
        if len(words) <= left:
            out.append(dict(doc))
            left -= len(words)
            continue
        out.append({"title": doc.get("title"), "text": " ".join(words[:left]), "truncated": True})
        left = 0
    return out


# ── the coaching itself ─────────────────────────────────────────────────────


COACH_SYSTEM = """\
You are coaching the user privately during a meeting. Nobody else can hear you.

You are given the user's own prep material and what has been said so far. Reply with a JSON
object:

  {"say": "..." }   one short observation, or omit the key entirely

Rules:
- Draw every talking point from the prep material. If the prep does not raise it, it is not a
  talking point — you are not here to have opinions of your own about their meeting.
- Prefer what they meant to cover and have not. That is the observation only you can make.
- One sentence. You are speaking over somebody else's meeting.
- Omit "say" if there is nothing worth the interruption. That is the usual answer."""


async def observe(
    meeting_id: str,
    *,
    call: Optional[Callable[..., Awaitable[str]]] = None,
    segments: Optional[Sequence[Dict[str, Any]]] = None,
    elapsed_ms: int = 0,
) -> str:
    """One coaching observation, or ``""``. Never raises.

    **Silent with no prep material.** Coach without prep is a coach with nothing to draw a
    talking point from, and the alternative — improvising from the transcript — is the thing
    this mode is defined as not doing.
    """
    if call is None:
        return ""
    body = context(meeting_id, segments=segments)
    if not body["prep"]:
        return ""

    prompt = _render(body, elapsed_ms=elapsed_ms)
    try:
        raw = await call([{"role": "system", "content": COACH_SYSTEM},
                          {"role": "user", "content": prompt}], temperature=0.2)
    except Exception:  # noqa: BLE001 — coaching is never worth the meeting
        log.exception("meetingsense: coaching failed for %s", meeting_id)
        return ""

    from .subagents import _json_object

    parsed = _json_object(raw)
    if not parsed:
        return ""
    return str(parsed.get("say") or "").strip()


def _render(body: Dict[str, Any], *, elapsed_ms: int) -> str:
    """The user message. Prep first, because it is what the observation must come from."""
    parts = ["Your prep material:"]
    for doc in body["prep"]:
        parts.append(f"— {doc.get('title')}\n{doc.get('text')}")
    said = body["said"]
    if said:
        lines = "\n".join(
            f"{s.get('speaker') or '?'}: {(s.get('text') or '').strip()}"
            for s in said if (s.get("text") or "").strip()
        )
        parts.append(f"\nWhat has been said:\n{lines}")
    parts.append(f"\nThe meeting has been running {int(elapsed_ms) // 60_000} minutes.")
    return "\n".join(parts)
