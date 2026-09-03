"""act — tool calls, through the router that already exists (MS23/MS24).

`agentic/runtime_tool_router.py` resolves a capability to an allowed tool id and invokes it.
This node does neither of those things itself: a second resolver would be a second allow-list,
and an allow-list that disagrees with the one Forge enforces is a security control that is
wrong half the time.

**Two gates, and they are different questions.** The mode says whether this meeting may use
tools at all (policy); MS24's pre-approval says *which* tools, for *this* meeting (consent).
A mode that permits tools does not approve any particular one, and an approved tool is not
usable in a mode that forbids tools.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from ..state import MeetingAgentState

log = logging.getLogger(__name__)

#: Tool calls one turn may make. A graph that can loop on tools is a graph that can spend a
#: meeting's worth of tokens answering one question.
MAX_CALLS = 3


async def act(state: MeetingAgentState, deps: Any = None) -> Dict[str, Any]:
    """Run whatever tools this mode and this meeting both allow."""
    trace = list(state.get("trace") or []) + ["act"]
    plan = list(state.get("plan") or [])[1:]
    if not (state.get("allows") or {}).get("tools"):
        return {"trace": trace, "plan": plan}

    invoke = getattr(deps, "invoke", None)
    wanted = getattr(deps, "tool_calls", None)
    if invoke is None or not wanted:
        return {"trace": trace, "plan": plan}

    approved = getattr(deps, "approved_tools", None)
    results: List[Dict[str, Any]] = list(state.get("tool_results") or [])
    errors = list(state.get("errors") or [])

    for call in list(wanted)[:MAX_CALLS]:
        name = str((call or {}).get("tool") or "")
        args = (call or {}).get("args") or {}
        if approved is not None and name not in approved:
            # Refused, and recorded: a tool call that vanishes silently is one nobody can
            # approve, because nobody knows it was wanted.
            errors.append(f"act: {name} is not approved for this meeting")
            continue
        try:
            output = await invoke(name, args)
        except Exception as error:  # noqa: BLE001
            log.exception("meetingsense: tool %s failed", name)
            errors.append(f"act: {name} failed: {error}")
            continue
        results.append({"tool": name, "args": args, "output": output})

    return {"trace": trace, "plan": plan, "tool_results": results, "errors": errors}
