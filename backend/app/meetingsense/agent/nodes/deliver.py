"""deliver — put the frames on the transport (MS23).

The last node, and the only one that touches the outside. Everything before it appends to
`state["frames"]`; this sends them in order and returns the state unchanged otherwise, so a
run's output is inspectable *before* anything has been sent — which is what lets MS23's
acceptance compare two runs rather than two sockets.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..state import MeetingAgentState

log = logging.getLogger(__name__)


async def deliver(state: MeetingAgentState, deps: Any = None) -> Dict[str, Any]:
    """Send every frame. Never raises: a dead socket is not a reason to lose the notes."""
    trace = list(state.get("trace") or []) + ["deliver"]
    send = getattr(deps, "send", None)
    if send is None:
        return {"trace": trace}
    errors = list(state.get("errors") or [])
    for frame in list(state.get("frames") or []):
        try:
            await send(frame)
        except Exception as error:  # noqa: BLE001
            log.debug("meetingsense: could not deliver a frame", exc_info=True)
            errors.append(f"deliver: {error}")
            break
    return {"trace": trace, "errors": errors}
