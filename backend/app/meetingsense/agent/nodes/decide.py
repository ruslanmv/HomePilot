"""decide — what to do next, from the event and the mode (MS23).

The only node that branches, and it branches on **policy plus event**, never on content. A
decision that read the transcript and chose to interrupt would be a decision nobody could
predict or explain, and D8's whole argument for keeping memory outside the graph is that
"why did it do that" has to have an answer.

Note-taker plans nothing. That is what makes the acceptance test possible: the graph's path in
that mode is `perceive → reflect → deliver`, which is the fixed loop with two no-ops around it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..state import MeetingAgentState

#: What a proactive mode asks itself when a slide goes up. One sentence, because the point is
#: a remark and not a briefing — and because whatever comes back is spoken over somebody
#: else's meeting.
SLIDE_QUESTION = (
    "A new slide is on screen: {caption}. In one sentence, say the most useful thing about it "
    "given what has been said so far. If there is nothing worth adding, say nothing."
)


async def decide(state: MeetingAgentState, deps: Any = None) -> Dict[str, Any]:
    """Build the plan: a list of action names, in the order they should run."""
    allows = state.get("allows") or {}
    event = state.get("event")
    plan: List[str] = []
    question: Optional[str] = None

    if event == "ask" and str(state.get("question") or "").strip():
        if allows.get("answer"):
            # Recall first, so the answer has something to cite. Skipped in modes that cannot
            # retrieve — Note-taker never gets here, but Participant on an install without a
            # vector store does, and MS13's keyword tier still answers.
            if allows.get("recall"):
                plan.append("recall")
            plan.append("answer")
        if allows.get("tools"):
            plan.append("act")
    elif event == "slide" and allows.get("proactive"):
        # Presenter's one unprompted move: a new slide is a moment where saying something is
        # expected rather than an interruption.
        #
        # The remark is routed through `answer`, so it goes through MS13's tiers and budget
        # like every other thing this assistant says — and that means it needs a question.
        # The caption is it. **Without a caption there is no plan at all**: an unprompted
        # remark about a slide nobody has described yet is noise, and the vision model
        # answering thirty seconds later is not a reason to have guessed.
        caption = str((state.get("keyframe") or {}).get("caption") or "").strip()
        if caption and allows.get("answer"):
            plan.append("answer")
            question = SLIDE_QUESTION.format(caption=caption)
    elif event == "stop" and allows.get("coach"):
        plan.append("coach")

    out: Dict[str, Any] = {"plan": plan, "trace": list(state.get("trace") or []) + ["decide"]}
    if question is not None:
        # Written into the state rather than passed sideways, so `answer` reads its input the
        # same way whoever asked it — a person or this node — and the trace explains both.
        out["question"] = question
    return out


def route_after_decide(state: MeetingAgentState) -> str:
    """The next node's name, or ``deliver`` when the plan is empty.

    A plain function of the state, so the same routing drives LangGraph's conditional edge and
    the fallback walker — one answer to "what runs next", whichever engine is asking.
    """
    plan = list(state.get("plan") or [])
    return plan[0] if plan else "deliver"
