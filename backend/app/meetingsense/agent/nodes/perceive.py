"""perceive — turn an event into state, and resolve the policy once (MS23)."""

from __future__ import annotations

from typing import Any, Dict

from .. import modes as modes_mod
from ..state import EVENTS, MeetingAgentState


async def perceive(state: MeetingAgentState, deps: Any = None) -> Dict[str, Any]:
    """Normalise the event and pin the mode's policy for this turn.

    **Resolved once, here.** Every later node reads `state["allows"]` rather than calling
    `modes.allows()` again, so a mode changed mid-turn cannot make `decide` and `act` disagree
    about what is permitted — which would be a run that planned to coach and then refused to.
    """
    event = str(state.get("event") or "segments")
    if event not in EVENTS:
        # Unknown events are ignored rather than guessed at, the same §6.9 rule the wire
        # follows: a newer caller should lose the feature it asked for, not the meeting.
        return {"errors": list(state.get("errors") or []) + [f"unknown event {event!r}"],
                "event": "segments", "allows": modes_mod.DEFAULT.allows(),
                "trace": list(state.get("trace") or []) + ["perceive"]}

    mode = modes_mod.resolve(str(state.get("mode") or ""))
    return {
        "event": event,
        "mode": mode.name,
        "allows": mode.allows(),
        "trace": list(state.get("trace") or []) + ["perceive"],
    }
