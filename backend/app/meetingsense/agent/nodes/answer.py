"""answer — MS13's three tiers, wrapped (MS23)."""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..state import MeetingAgentState

log = logging.getLogger(__name__)


async def answer(state: MeetingAgentState, deps: Any = None) -> Dict[str, Any]:
    """Answer the question and put the frame on the wire.

    Calls MS13's `answer`, not a second prompt builder. The budget, the trim order and the
    citation rule are all decisions that were argued once; a graph that re-made them would be
    a second product with the same name.
    """
    trace = list(state.get("trace") or []) + ["answer"]
    plan = list(state.get("plan") or [])[1:]
    ask = getattr(deps, "ask", None)
    question = str(state.get("question") or "").strip()
    if ask is None or not question or not (state.get("allows") or {}).get("answer"):
        return {"trace": trace, "plan": plan}
    try:
        frame = await ask(state.get("meeting_id") or "", question)
    except Exception as error:  # noqa: BLE001
        log.exception("meetingsense: answer failed")
        return {"trace": trace, "plan": plan,
                "errors": list(state.get("errors") or []) + [f"answer: {error}"]}
    if not frame:
        return {"trace": trace, "plan": plan}
    return {"trace": trace, "plan": plan,
            "frames": list(state.get("frames") or []) + [frame]}
