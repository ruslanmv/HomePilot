"""The meeting graph (batch MS23, wave W8).

Eight nodes and one conditional edge. The topology is **data** — `NODES`, `EDGES` and
`route_after_decide` — and two things execute it: LangGraph where it is installed, and a
twenty-line walker where it is not.

That is two schedulers and one set of behaviour, which is a trade worth naming. `langgraph` is
in `requirements.txt` but not on every install, and `langgraph_personas/graph_builder.py`
imports it at module scope — which is why `test_langgraph_personas.py` is one of the eighteen
suites that cannot even be collected here. A graph that cannot be imported cannot be tested,
and MS23's acceptance is a test. So the node functions are the implementation, the walker
exists so they can run and be compared anywhere, and a test asserts both engines produce the
same frames from the same state.

**The flag is `agent`, and off means the fixed loop.** Not a degraded graph, not a graph with
nodes disabled — the code path MS12 and MS13 have been running since W4, untouched. `run()` is
only called when the flag is on.

**Note-taker is the equality case.** In that mode `decide` plans nothing, so the path is
`perceive → reflect → deliver`: `reflect` is `session._maybe_notes`'s three calls in the same
order on the same engine, and `deliver` is the same `transport.send`. The acceptance test drives
both and compares frame for frame.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from . import modes as modes_mod
from .nodes import act, answer, coach, decide, deliver, perceive, recall, reflect
from .nodes.decide import route_after_decide
from .state import MeetingAgentState, new_state

log = logging.getLogger(__name__)

#: Every node, by the name the topology and the trace both use.
NODES: Dict[str, Callable[..., Awaitable[Dict[str, Any]]]] = {
    "perceive": perceive,
    "reflect": reflect,
    "decide": decide,
    "recall": recall,
    "answer": answer,
    "coach": coach,
    "act": act,
    "deliver": deliver,
}

#: Unconditional edges. `decide` is absent because its successor is the router's answer, and
#: the four action nodes are absent because each returns to the router with its step consumed.
EDGES: Sequence = (
    ("perceive", "reflect"),
    ("reflect", "decide"),
)

#: Nodes that hand back to the router rather than to a fixed successor.
LOOPING = ("recall", "answer", "coach", "act")

ENTRY = "perceive"
FINAL = "deliver"

#: A run may not visit more nodes than this. The plan is consumed a step at a time so it
#: terminates by construction, and this is the belt: a router bug should end a turn, not a
#: meeting.
MAX_STEPS = 24


@dataclass
class Deps:
    """Everything a node may reach outside its state. Injected, so a whole run stubs out.

    Every field defaults to ``None``, and every node treats ``None`` as "cannot" rather than
    "fail". A graph with no dependencies at all runs, traces, and produces no frames — which
    is the right answer for a mode that was asked to do something this install cannot.
    """

    #: MS12's `NotesEngine`.
    notes: Any = None
    #: ``async (meeting_id, question) -> frame`` — MS13's `answer`, bound.
    ask: Optional[Callable[..., Awaitable[Dict[str, Any]]]] = None
    #: ``(query, *, meeting_id, k) -> rows`` — MS15's `ms_search`, bound.
    search: Optional[Callable[..., Sequence[Dict[str, Any]]]] = None
    #: ``async (state) -> str`` — W9 writes this; MS23 builds the path to it.
    coach: Optional[Callable[..., Awaitable[str]]] = None
    #: MS24's sub-agents. ``async (window) -> [action]`` and ``async (keyframe) -> reading``.
    #: Both return proposals; `reflect` merges what it accepts and neither writes anything.
    extract_actions: Optional[Callable[..., Awaitable[Sequence[Dict[str, Any]]]]] = None
    read_slide: Optional[Callable[..., Awaitable[Optional[Dict[str, Any]]]]] = None
    #: ``async (tool, args) -> output`` — `runtime_tool_router.invoke`, bound.
    invoke: Optional[Callable[..., Awaitable[Any]]] = None
    #: What this turn wants to call. MS24 fills it from a sub-agent.
    tool_calls: Sequence[Dict[str, Any]] = field(default_factory=tuple)
    #: MS24's per-meeting pre-approval — the tools *this* meeting has consented to. ``None``
    #: is a `Deps` nobody told, and `act` reads it exactly as it reads ``[]``: approve nothing.
    approved_tools: Optional[Sequence[str]] = None
    #: ``async (frame) -> None`` — the session's transport.
    send: Optional[Callable[..., Awaitable[None]]] = None


def merge(state: MeetingAgentState, update: Dict[str, Any]) -> MeetingAgentState:
    """Apply a node's partial update. A plain overwrite, deliberately.

    Nodes return the *whole* new value of any key they touch — a list they have already
    concatenated, never a fragment to append. Reducer semantics would put the accumulation
    logic in the engine, and then LangGraph's reducers and the walker's would have to agree
    about it; this way there is nothing to agree about.
    """
    merged: MeetingAgentState = dict(state)  # type: ignore[assignment]
    merged.update(update or {})  # type: ignore[typeddict-item]
    return merged


async def walk(state: MeetingAgentState, deps: Deps) -> MeetingAgentState:
    """Execute the topology without LangGraph. The same nodes, the same router.

    Exists so the graph runs — and is testable — on an install that does not have langgraph,
    which includes this repository's own test environment.
    """
    current = ENTRY
    steps = 0
    while steps < MAX_STEPS:
        steps += 1
        node = NODES.get(current)
        if node is None:
            state = merge(state, {"errors": list(state.get("errors") or []) + [f"no node {current!r}"]})
            break
        state = merge(state, await node(state, deps))
        if current == FINAL:
            break
        following = dict(EDGES).get(current)
        if following is not None:
            current = following
        else:
            # `decide` and the four action nodes all ask the router, which reads the plan the
            # last node consumed a step from.
            current = route_after_decide(state)
    else:
        state = merge(state, {"errors": list(state.get("errors") or []) + ["step limit reached"]})
    return state


def build(deps: Deps):
    """A compiled LangGraph, or ``None`` when langgraph is not installed.

    Imported inside the function, which is the difference between this module and
    `langgraph_personas/graph_builder.py`: that one imports at module scope and takes its own
    test suite down on an install without the package.
    """
    try:
        from langgraph.graph import END, StateGraph
    except Exception:  # noqa: BLE001
        log.debug("meetingsense: langgraph is not installed; using the walker")
        return None

    graph = StateGraph(dict)
    for name, node in NODES.items():
        graph.add_node(name, _bind(node, deps))
    graph.set_entry_point(ENTRY)
    for source, target in EDGES:
        graph.add_edge(source, target)
    routes = {name: name for name in LOOPING}
    routes[FINAL] = FINAL
    graph.add_conditional_edges("decide", route_after_decide, routes)
    for name in LOOPING:
        graph.add_conditional_edges(name, route_after_decide, routes)
    graph.add_edge(FINAL, END)
    return graph.compile()


def _bind(node, deps: Deps):
    async def run_node(state):
        return merge(state, await node(state, deps))

    return run_node


async def run(
    *,
    meeting_id: str,
    event: str = "segments",
    deps: Optional[Deps] = None,
    engine: str = "auto",
    **kwargs: Any,
) -> MeetingAgentState:
    """One turn. Returns the final state — `frames` is the output, `trace` is the explanation.

    ``engine`` is ``"auto"`` (LangGraph if installed, else the walker), ``"walk"``, or
    ``"langgraph"``. Named rather than inferred so the equality test can drive both.
    """
    deps = deps or Deps()
    state = new_state(meeting_id=meeting_id, event=event, **kwargs)

    if engine in ("auto", "langgraph"):
        compiled = build(deps)
        if compiled is not None:
            try:
                final = await compiled.ainvoke(state)
                return final  # type: ignore[return-value]
            except Exception:  # noqa: BLE001 — a graph failure is never worth the meeting
                log.exception("meetingsense: the graph failed; falling back to the walker")
        elif engine == "langgraph":
            state = merge(state, {"errors": ["langgraph is not installed"]})
            return state
    return await walk(state, deps)


def deps_for(
    meeting_id: str,
    *,
    notes: Any = None,
    ask: Any = None,
    send: Any = None,
    invoke: Any = None,
    tool_calls: Sequence[Dict[str, Any]] = (),
    call: Any = None,
    search: Any = None,
    coach: Any = None,
) -> Deps:
    """Assemble the dependencies for one meeting, reading its policy from the store.

    The one place a caller should build `Deps` for a live meeting: it resolves the per-meeting
    tool approvals rather than leaving that to whoever wired the session. A `Deps` built by
    hand with `approved_tools=None` approves nothing, so forgetting this is safe — but
    forgetting it in the *other* direction, by passing a list a client sent, is exactly the
    escalation MS24 exists to prevent, and there is no reason for a caller to have that list.
    """
    from . import subagents

    return Deps(
        notes=notes,
        ask=ask,
        send=send,
        invoke=invoke,
        tool_calls=tuple(tool_calls or ()),
        search=search,
        coach=coach,
        approved_tools=subagents.approved(meeting_id),
        extract_actions=(lambda window: subagents.extract_actions(window, call=call))
        if call is not None else None,
        read_slide=(lambda keyframe: subagents.read_slide(keyframe, call=call))
        if call is not None else None,
    )


def enabled(config: Any) -> bool:
    """Whether the graph runs at all. Off by default, like every sub-flag.

    Off does not mean a graph with its nodes disabled: it means `run()` is never called and
    the session takes the path it has taken since W4.
    """
    return bool(getattr(config, "enabled", False)
                and getattr(getattr(config, "flags", None), "agent", False))


def modes() -> list:
    """Re-exported so a caller needs one import to ask what a mode does."""
    return modes_mod.as_dicts()
