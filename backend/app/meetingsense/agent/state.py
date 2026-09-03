"""What flows through the meeting graph (batch MS23, wave W8).

One dict, JSON-safe, read as a snapshot and written as a partial update — the same shape
`langgraph_personas/state.py` uses, because a second state convention in one repository is a
second thing to learn for no gain.

**Memory is not in here.** D8 is explicit: memory is three deterministic stores — working
(this state), episodic (the `ms_*` tables and the summary message), semantic (MS15's vectors).
The graph *consumes* them through `recall` and `reflect`; it never decides what is stored. That
is not tidiness. MS23's acceptance is that the graph's output in Note-taker mode is identical to
the fixed loop's, and that is only checkable if the graph cannot remember anything the fixed
loop does not.

So every node here is a function of `(state) -> partial state`, with no attribute on `self`, no
module global, and nothing written to disk that the fixed loop would not also write.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class MeetingAgentState(TypedDict, total=False):
    """The unified state every node reads and updates.

    Deliberately flat and JSON-safe: a checkpointed run has to be inspectable by a person
    asking "why did it do that", and a state carrying live objects answers that question with
    a repr.
    """

    # ── input ────────────────────────────────────────────────────────────
    meeting_id: str
    conversation_id: str
    #: What woke the graph. One of the `EVENTS` below.
    event: str
    #: Segments transcribed since the last turn — the fixed loop's `fresh`.
    fresh: List[Dict[str, Any]]
    #: A question, when the event is `ask`.
    question: str
    #: The keyframe that just arrived, when the event is `slide`.
    keyframe: Dict[str, Any]
    #: Milliseconds into the meeting. Injected, never read from a clock inside a node.
    elapsed_ms: int

    # ── policy ───────────────────────────────────────────────────────────
    #: The mode name. Server policy (MS24), not a client composition.
    mode: str
    #: What this mode permits, resolved once by `perceive` so every later node reads the same
    #: answer even if the mode changes mid-turn.
    allows: Dict[str, bool]

    # ── working memory ───────────────────────────────────────────────────
    #: Rows `recall` retrieved, each carrying its own citation.
    recalled: List[Dict[str, Any]]
    #: The notes frame `reflect` produced, or None.
    notes: Optional[Dict[str, Any]]
    #: What `decide` chose to do next. One of the `ACTIONS` below.
    plan: List[str]
    #: Tool results from `act`.
    tool_results: List[Dict[str, Any]]

    # ── output ───────────────────────────────────────────────────────────
    #: Frames to send, in order. **This is the whole output of a run**: the acceptance test
    #: compares this list against the fixed loop's, so anything a node wants a client to see
    #: goes here and nowhere else.
    frames: List[Dict[str, Any]]
    #: Node names in the order they ran. For the "why did it do that" question, and for a test
    #: that wants to assert a mode took the short path rather than the long one.
    trace: List[str]
    #: Anything that went wrong, named. A node never raises: a graph that can take a meeting
    #: down is worse than one that occasionally does nothing.
    errors: List[str]


#: What can wake the graph. Closed, like the panel kinds and the event bus: an unknown event is
#: a node that never runs, which is a silence nobody can debug.
EVENTS = ("segments", "ask", "slide", "stop")

#: What `decide` may put in the plan. Also closed, and each maps to exactly one node.
ACTIONS = ("recall", "answer", "coach", "act")


def new_state(**kwargs: Any) -> MeetingAgentState:
    """A state with every list present, so no node has to guess whether a key exists."""
    state: MeetingAgentState = {
        "meeting_id": "",
        "conversation_id": "",
        "event": "segments",
        "fresh": [],
        "question": "",
        "keyframe": {},
        "elapsed_ms": 0,
        "mode": "note-taker",
        "allows": {},
        "recalled": [],
        "notes": None,
        "plan": [],
        "tool_results": [],
        "frames": [],
        "trace": [],
        "errors": [],
    }
    state.update(kwargs)  # type: ignore[typeddict-item]
    return state
