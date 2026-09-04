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

    # MS24. The mode is **server state**, not something a turn asserts. A stored mode wins over
    # whatever arrived in the state; what arrived is a default for a meeting that has never had
    # one set. A per-turn mode on the wire would let a client put a meeting into Practice for a
    # single request, which is not a mode — it is an escalation.
    decision = _resolve_mode(state)
    mode = modes_mod.resolve(decision["mode"])
    out: Dict[str, Any] = {
        "event": event,
        "mode": mode.name,
        "allows": mode.allows(),
        "trace": list(state.get("trace") or []) + ["perceive"],
    }
    if decision.get("overridden"):
        # Reported rather than silently ignored: a client that thinks it is driving should
        # find out that it is not.
        out["errors"] = list(state.get("errors") or []) + [
            f"mode {decision['requested']!r} ignored; this meeting is set to {mode.name!r}"
        ]
    return out


def _resolve_mode(state: MeetingAgentState) -> Dict[str, Any]:
    """Ask the policy store, falling back to what the state carried. Never raises."""
    from .. import subagents

    try:
        return subagents.resolve_mode(str(state.get("meeting_id") or ""),
                                      str(state.get("mode") or ""))
    except Exception:  # noqa: BLE001 — an unreadable policy store means the floor, not a crash
        return {"mode": "", "source": "none", "overridden": False, "requested": None}
