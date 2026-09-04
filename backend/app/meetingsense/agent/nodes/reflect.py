"""reflect — MS12's rolling notes, wrapped (MS23).

Wrapped, not reimplemented, and the wrapping is thin on purpose: MS23's acceptance is that
Note-taker mode produces *identical* output to the fixed loop, and the only way to be sure of
that is for both to call the same engine with the same window. So this node's whole body is
`add`, `due`, `run` — the three calls `session._maybe_notes` makes, in the same order.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..state import MeetingAgentState

log = logging.getLogger(__name__)


async def reflect(state: MeetingAgentState, deps: Any = None) -> Dict[str, Any]:
    """Feed the notes engine and keep the frame it produced, if any."""
    trace = list(state.get("trace") or []) + ["reflect"]
    engine = getattr(deps, "notes", None)
    fresh = list(state.get("fresh") or [])
    allows = state.get("allows") or {}

    if engine is None or not allows.get("notes", True) or not fresh:
        return {"trace": trace}

    try:
        engine.add(fresh)
        # `force` on stop, exactly as the fixed loop does: without it the last minute of every
        # meeting is missing from its notes.
        force = state.get("event") == "stop"
        if not force and not engine.due():
            return {"trace": trace}
        frame = await engine.run(force=force)
    except Exception as error:  # noqa: BLE001 — notes are never worth a meeting
        log.exception("meetingsense: reflect failed")
        return {"trace": trace, "errors": list(state.get("errors") or []) + [f"reflect: {error}"]}

    if frame is None:
        return {"trace": trace}

    # MS24. The sub-agents run *after* the engine and only add to what it produced: MS12's
    # `merge` never deletes and dedupes on the item text, so a proposal that repeats something
    # the engine already found costs nothing and one it missed is kept. They are additive on
    # purpose — an extractor that could remove a note would be a second author of one record.
    frame = await _augment(frame, state, deps)
    return {"trace": trace, "notes": frame,
            "frames": list(state.get("frames") or []) + [frame]}


async def _augment(frame: Dict[str, Any], state: MeetingAgentState, deps: Any) -> Dict[str, Any]:
    """Fold the sub-agents' proposals into the notes frame. Never raises, never removes."""
    from .. import subagents

    extract = getattr(deps, "extract_actions", None)
    read_slide = getattr(deps, "read_slide", None)
    if extract is None and read_slide is None:
        return frame

    out = dict(frame)
    if extract is not None:
        try:
            proposed = await extract(list(state.get("fresh") or []))
        except Exception:  # noqa: BLE001 — a proposal is never worth the notes
            log.exception("meetingsense: action extraction failed")
            proposed = []
        if proposed:
            out["actions"] = _merge_actions(out.get("actions") or [], proposed)

    keyframe = state.get("keyframe") or {}
    if read_slide is not None and keyframe:
        try:
            reading = await read_slide(keyframe)
        except Exception:  # noqa: BLE001
            log.exception("meetingsense: slide reading failed")
            reading = None
        if reading and not reading.get("repeat"):
            out["slides"] = list(out.get("slides") or []) + [reading]
    return out


def _merge_actions(existing: Any, proposed: Any) -> list:
    """Add what is new, keep what is there.

    Deduped on the same key MS12 uses — case- and punctuation-insensitive — so an extractor
    that phrases a commitment differently from the notes engine does not produce two rows for
    one promise, which is the most obvious way for notes to look broken.
    """
    from ...notes_engine import _key

    out = [dict(item) for item in existing if isinstance(item, dict)]
    seen = {_key(item.get("text") or "") for item in out}
    for item in proposed:
        if not isinstance(item, dict):
            continue
        key = _key(item.get("text") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(dict(item))
    return out
