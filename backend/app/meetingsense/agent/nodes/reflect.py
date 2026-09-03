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
    return {"trace": trace, "notes": frame,
            "frames": list(state.get("frames") or []) + [frame]}
