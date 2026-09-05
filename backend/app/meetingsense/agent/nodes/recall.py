"""recall — MS15's retrieval, wrapped (MS23).

D8: the graph *consumes* memory and never decides what is stored. This node reads; nothing in
`agent/` writes to the vector store, and a test asserts that by watching the index.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from ..state import MeetingAgentState

log = logging.getLogger(__name__)

#: Rows one turn may retrieve. The same ceiling MS13 answers under, so a graph turn and an
#: `ask` over HTTP put the same amount in front of a model.
MAX_ROWS = 8


async def recall(state: MeetingAgentState, deps: Any = None) -> Dict[str, Any]:
    """Retrieve rows that match the question, each carrying its citation."""
    trace = list(state.get("trace") or []) + ["recall"]
    search = getattr(deps, "search", None)
    question = str(state.get("question") or "").strip()
    if search is None or not question or not (state.get("allows") or {}).get("recall"):
        return {"trace": trace, "plan": _advance(state)}
    try:
        rows = search(question, meeting_id=state.get("meeting_id") or None, k=MAX_ROWS) or []
    except Exception as error:  # noqa: BLE001 — a missing index must not lose the answer
        log.debug("meetingsense: recall unavailable", exc_info=True)
        return {"trace": trace, "plan": _advance(state),
                "errors": list(state.get("errors") or []) + [f"recall: {error}"]}
    return {"trace": trace, "recalled": list(rows), "plan": _advance(state)}


def _advance(state: MeetingAgentState) -> list:
    """Drop this step from the plan so the router moves on.

    The plan is consumed rather than indexed: a node that had to know its own position would
    break the moment a mode inserted a step before it.
    """
    return list(state.get("plan") or [])[1:]
