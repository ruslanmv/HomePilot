"""coach — feedback on how it is going, not on what was said (MS23).

The distinction matters and is the whole node: `answer` is about the meeting's content, and
this is about the meeting's conduct — "you have been on this slide eleven minutes", "Ana has
not spoken". W9 writes the coaching itself; MS23 builds the path, the policy gate and the frame
shape, so W9 changes one function rather than adding a node and a mode and a flag.

**It never speaks in a mode that does not allow it**, which is checked here as well as in
`decide`: a plan is a decision and this is the thing that acts on it, and two gates on one
permission is the cheapest insurance there is against a later edit to either.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..state import MeetingAgentState

log = logging.getLogger(__name__)

#: Frame type. Its own, not a `notes` or an `answer`: a client renders coaching differently —
#: quieter, dismissible — and folding it into either would make that impossible to do.
FRAME = "coaching"


async def coach(state: MeetingAgentState, deps: Any = None) -> Dict[str, Any]:
    """Offer one observation, or nothing."""
    trace = list(state.get("trace") or []) + ["coach"]
    plan = list(state.get("plan") or [])[1:]
    if not (state.get("allows") or {}).get("coach"):
        return {"trace": trace, "plan": plan}
    observe = getattr(deps, "coach", None)
    if observe is None:
        return {"trace": trace, "plan": plan}
    try:
        text = await observe(dict(state))
    except Exception as error:  # noqa: BLE001
        log.exception("meetingsense: coach failed")
        return {"trace": trace, "plan": plan,
                "errors": list(state.get("errors") or []) + [f"coach: {error}"]}
    text = (text or "").strip() if isinstance(text, str) else ""
    if not text:
        # Nothing worth saying is the common case and the right default. A coach that always
        # has an observation is a coach nobody leaves on.
        return {"trace": trace, "plan": plan}
    frame = {"type": FRAME, "meeting_id": state.get("meeting_id"), "text": text,
             "t": int(state.get("elapsed_ms") or 0)}
    return {"trace": trace, "plan": plan,
            "frames": list(state.get("frames") or []) + [frame]}
