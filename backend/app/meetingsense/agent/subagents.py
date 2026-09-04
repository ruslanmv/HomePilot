"""Two sub-agents, and what a meeting has approved (batch MS24, wave W8).

MS23 built a graph whose nodes each do one thing badly-defined jobs would blur. This adds the
two jobs that are genuinely separate from the main loop, and the policy that decides what
either of them may reach.

**SlideReader** turns a captioned keyframe into something the notes can carry: a title, the
claim, and whether it repeats a slide already seen. It is a sub-agent rather than a branch in
`reflect` because it reads *one* artefact and produces *one* record, and mixing that into the
rolling-notes prompt is how a notes engine starts hallucinating slides that were never shown.

**ActionExtractor** pulls owners and deadlines out of a window of transcript. Separate for the
opposite reason: it is the one job here that benefits from being wrong cheaply. An extractor
that proposes six actions and has four rejected is useful; a notes engine that does the same is
a notes engine nobody trusts.

Neither writes anything. They return proposals; `reflect` merges what it accepts, and MS12's
`merge` — which never deletes — is still the only thing that changes the notes.

**Per-meeting tool pre-approval.** A mode says whether tools may be used at all; this says
*which*, for *this meeting*. Two questions, deliberately not one: "I am rehearsing a talk" is a
mode, and "you may search the web during it" is a consent, and collapsing them means a user who
picks Practice has silently agreed to whatever tools the install happens to have.

Approvals live in `ms_artifacts`, so they are per meeting, survive a reconnect, and are visible
to the same delete that removes everything else about the meeting.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from .. import store
from . import modes as modes_mod

log = logging.getLogger(__name__)

#: The artifact kind approvals are recorded under.
APPROVAL_KIND = "tool_approval"

#: Actions one window may propose. An extractor that returns twenty has not understood the
#: window; capping it keeps a bad answer cheap rather than making it authoritative.
MAX_ACTIONS = 5

_OWNER = re.compile(r"\b([A-Z][a-z]+)\s+(?:will|to|should|is going to|can)\b")


# ── SlideReader ─────────────────────────────────────────────────────────────


SLIDE_SYSTEM = """\
You are given one slide's caption from a meeting. Return JSON only:

{"title": "...", "claim": "...", "topics": ["..."]}

- "title" is the slide's heading, or "" if it has none.
- "claim" is the one thing the slide asserts, in under fifteen words. Not a description of the
  layout — "revenue is flat since June", not "a line chart with a downward trend".
- "topics" is at most three short subjects, for matching this slide against what was said.

Say nothing outside the JSON."""


async def read_slide(
    keyframe: Dict[str, Any],
    *,
    call: Optional[Callable[..., Awaitable[str]]] = None,
    seen_hashes: Sequence[str] = (),
) -> Optional[Dict[str, Any]]:
    """One captioned keyframe → a record the notes can carry, or ``None``.

    Returns ``None`` for an uncaptioned slide rather than asking the model about a picture it
    cannot see, and for a repeat rather than describing the same slide twice — MS9 already
    decided that a re-shown slide is the same slide, and this is the same dHash saying so.
    """
    caption = str((keyframe or {}).get("caption") or "").strip()
    if not caption:
        return None

    digest = (keyframe or {}).get("hash")
    if digest and digest in set(seen_hashes):
        # A slide back on screen. Recorded as a return rather than a new reading, so a
        # timeline can show it went up twice without the notes claiming two slides.
        return {"t_ms": keyframe.get("t_ms"), "hash": digest, "repeat": True,
                "title": "", "claim": "", "topics": []}

    if call is None:
        # No model: the caption is already a sentence a person wrote or a vision model
        # produced, and passing it through unchanged is more use than nothing.
        return {"t_ms": keyframe.get("t_ms"), "hash": digest, "repeat": False,
                "title": "", "claim": caption, "topics": []}

    try:
        raw = await call([{"role": "system", "content": SLIDE_SYSTEM},
                          {"role": "user", "content": caption}], temperature=0.1)
    except Exception:  # noqa: BLE001 — a slide reading is never worth the meeting
        log.exception("meetingsense: slide reader failed")
        return None

    body = _json_object(raw)
    if body is None:
        return None
    topics = [str(t).strip() for t in (body.get("topics") or []) if str(t).strip()][:3]
    return {
        "t_ms": keyframe.get("t_ms"),
        "hash": digest,
        "repeat": False,
        "title": str(body.get("title") or "").strip(),
        "claim": str(body.get("claim") or "").strip(),
        "topics": topics,
    }


# ── ActionExtractor ─────────────────────────────────────────────────────────


ACTION_SYSTEM = """\
You are given a window of meeting transcript. Return JSON only:

{"actions": [{"text": "...", "owner": "...", "due": "...", "t0": 0}]}

- "text" is what someone committed to do, as they said it, in under twelve words.
- "owner" is the person who committed, or "" if nobody was named. Never guess.
- "due" is a date or a phrase like "by Friday", or "" if none was said.
- "t0" is the millisecond timestamp of the line it came from — copy it, never invent it.

Only things somebody actually committed to. A topic that was discussed is not an action, and a
question about who should do something is not an action either. Return {"actions": []} rather
than filling the list. Say nothing outside the JSON."""


async def extract_actions(
    window: Sequence[Dict[str, Any]],
    *,
    call: Optional[Callable[..., Awaitable[str]]] = None,
) -> List[Dict[str, Any]]:
    """A window of transcript → proposed actions. Always a list, possibly empty.

    **Proposals, not notes.** Nothing here writes: `reflect` merges what it accepts through
    MS12's `merge`, which never deletes and dedupes on the item text. An extractor that wrote
    directly would be a second author of the same record.
    """
    rows = [s for s in (window or []) if (s.get("text") or "").strip()]
    if not rows:
        return []
    if call is None:
        return _heuristic_actions(rows)

    transcript = "\n".join(
        f"[{int(s.get('t0_ms') or 0)}] {s.get('speaker') or '?'}: {(s.get('text') or '').strip()}"
        for s in rows
    )
    try:
        raw = await call([{"role": "system", "content": ACTION_SYSTEM},
                          {"role": "user", "content": transcript}], temperature=0.1)
    except Exception:  # noqa: BLE001
        log.exception("meetingsense: action extractor failed")
        return []

    body = _json_object(raw) or {}
    valid_t0 = {int(s.get("t0_ms") or 0) for s in rows}
    out: List[Dict[str, Any]] = []
    for item in (body.get("actions") or [])[:MAX_ACTIONS]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        action: Dict[str, Any] = {"text": text}
        owner = str(item.get("owner") or "").strip()
        if owner:
            action["owner"] = owner
        due = str(item.get("due") or "").strip()
        if due:
            action["due"] = due
        stamp = item.get("t0")
        # A `t0` the model invented is worse than none — MS12 decided that, and this obeys it:
        # an uncitable action keeps its text and loses its timestamp.
        if isinstance(stamp, (int, float)) and int(stamp) in valid_t0:
            action["t0"] = int(stamp)
        out.append(action)
    return out


def _heuristic_actions(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """What to propose with no model at all.

    Deliberately narrow: "Ana will send the terms" and nothing cleverer. An install with no
    model gets the actions that were phrased unmistakably, and misses the rest — which is a
    better trade than a regular expression guessing at intent.
    """
    out: List[Dict[str, Any]] = []
    for row in rows:
        text = (row.get("text") or "").strip()
        match = _OWNER.search(text)
        if not match:
            continue
        out.append({"text": text[:120], "owner": match.group(1), "t0": int(row.get("t0_ms") or 0)})
        if len(out) >= MAX_ACTIONS:
            break
    return out


def _json_object(raw: Any) -> Optional[Dict[str, Any]]:
    """The object out of whatever the model said, or None. MS12's tolerance, reused in spirit."""
    if isinstance(raw, dict):
        return raw
    text = (raw or "").strip() if isinstance(raw, str) else ""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        bare = re.search(r"\{.*\}", text, re.S)
        candidate = bare.group(0) if bare else text
    try:
        body = json.loads(candidate)
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


# ── the mode a meeting is actually in ───────────────────────────────────────

#: The artifact kind `hp.ms.set_mode` and `POST /{id}/notes` both write.
MODE_KIND = "mode"


def _artifacts(meeting_id: str, kind: str) -> Optional[List[Dict[str, Any]]]:
    """The rows of one kind, or ``None`` when the store could not be read at all.

    "Nothing was ever set" and "we cannot tell what was set" are different answers, and only
    the second one has to fail closed. Collapsing them — which is what a bare
    ``except: return []`` does — turns a broken store into a store that silently agrees with
    whatever the caller asked for.
    """
    try:
        return list(store.artifacts_for_meeting(meeting_id, kind=kind))
    except Exception:  # noqa: BLE001 — an install with no tables reads as unreadable
        log.exception("meetingsense: cannot read %s artifacts for %s", kind, meeting_id)
        return None


def current_mode(meeting_id: str) -> Optional[str]:
    """The mode this meeting was last set to, or ``None`` if it never was.

    Read from the artifact log rather than held in memory: a mode has to survive a reconnect,
    a server restart and a second client attaching to the same meeting, and the one place all
    three of those already agree is the store.

    An unreadable store also reads as ``None`` here, because a plain reader has nothing better
    to say. `resolve_mode` is the one that has to tell the two apart.
    """
    rows = _artifacts(meeting_id, MODE_KIND) or []
    for row in reversed(rows):
        target = (row.get("target") or "").strip().lower()
        if target:
            return target
    return None


def resolve_mode(meeting_id: str, requested: str = "") -> Dict[str, Any]:
    """Which mode governs this turn, and whether a client tried to say otherwise.

    **A stored mode wins.** That is the whole of "modes are server policy objects, not client
    compositions": the mode is set once, through `hp.ms.set_mode` or `POST /{id}/notes`, and
    every turn afterwards reads it. A per-turn `mode` on the wire would let a client put a
    meeting into Practice for one request — which is not a mode, it is an escalation.

    A `requested` value is a **default**, used only when nothing has been set. When it
    disagrees with what is stored, the stored one governs and the disagreement is reported, so
    a client that thinks it is driving finds out rather than quietly not being.
    """
    asked = (requested or "").strip().lower()
    rows = _artifacts(meeting_id, MODE_KIND) if meeting_id else []
    if rows is None:
        # **Unreadable is the floor, never the ceiling.** We cannot check what the server said,
        # so the one thing we must not do is take the client's word for it: a store outage
        # would otherwise be the cheapest way to get a meeting into Practice.
        floor = modes_mod.DEFAULT.name
        return {"mode": floor, "source": "unreadable", "overridden": bool(asked and asked != floor),
                "requested": asked or None}
    stored = ""
    for row in reversed(rows):
        target = (row.get("target") or "").strip().lower()
        if target:
            stored = target
            break
    if stored:
        conflict = bool(asked and asked != stored)
        return {"mode": stored, "source": "store", "overridden": conflict,
                "requested": asked or None}
    return {"mode": asked or "", "source": "default" if asked else "none", "overridden": False,
            "requested": asked or None}


# ── per-meeting tool pre-approval ───────────────────────────────────────────


def approve(meeting_id: str, tools: Sequence[str]) -> List[str]:
    """Record which tools this meeting may use. Returns the full approved set.

    Additive: approving `hp.web.search` after approving `hp.notes.read` leaves both. Revoking
    is `revoke`, and it is a separate call because "also allow this" and "stop allowing that"
    are different intentions and a set-replacing API turns the first into the second whenever
    a client forgets to send the old list.
    """
    wanted = [str(t).strip() for t in (tools or []) if str(t).strip()]
    if not wanted:
        return approved(meeting_id)
    current = set(approved(meeting_id))
    added = [t for t in wanted if t not in current]
    for tool in added:
        store.add_artifact(meeting_id, kind=APPROVAL_KIND, target=tool)
    return sorted(current | set(added))


def revoke(meeting_id: str, tools: Sequence[str]) -> List[str]:
    """Withdraw approval. Returns what is left.

    Recorded as a withdrawal rather than by deleting the approval row: a meeting's record of
    what it was allowed to do, and when that changed, is the thing an audit reads.
    """
    dropping = {str(t).strip() for t in (tools or []) if str(t).strip()}
    if not dropping:
        return approved(meeting_id)
    for tool in sorted(dropping):
        store.add_artifact(meeting_id, kind=APPROVAL_KIND, target=tool, detail="revoked")
    return approved(meeting_id)


def approved(meeting_id: str) -> List[str]:
    """The tools this meeting may use, right now.

    Replayed from the artifact log in order, so the last statement about a tool wins. A
    meeting with no approvals returns ``[]``, and `act` reads that as "approve nothing" —
    **the default is refusal**, which is the only default a consent can safely have.
    """
    rows = _artifacts(meeting_id, APPROVAL_KIND) or []
    state: Dict[str, bool] = {}
    for row in rows:
        tool = (row.get("target") or "").strip()
        if not tool:
            continue
        state[tool] = (row.get("detail") or "") != "revoked"
    return sorted(t for t, allowed in state.items() if allowed)
