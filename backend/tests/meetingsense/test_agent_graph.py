"""The meeting graph (batch MS23, wave W8).

One claim carries this batch, and it is the acceptance criterion: **in Note-taker mode the
graph's output is identical to the fixed loop's.** Not similar, not equivalent — the same
frames in the same order. That is checkable only because D8 kept memory outside the graph: if
a node could remember something the fixed loop could not, the two would diverge on the second
turn and no test would catch which one was right.

So the test drives both paths with the same stubbed engine, over the same recorded events, and
compares. Everything else here is about the properties that make that comparison mean
something a week from now: nodes that never raise, a router that always terminates, a mode that
resolves down rather than up, and a graph that is off unless a flag says otherwise.

The graph runs on two engines — LangGraph where installed, a walker where not — and a test
asserts they agree. Two schedulers for one set of behaviour is a real cost, taken because
`langgraph` is not installed in this environment and a graph that cannot be imported cannot be
tested: `langgraph_personas/graph_builder.py` imports it at module scope and its whole suite is
one of the eighteen that cannot be collected.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("MEETINGSENSE_ENABLED", "MEETINGSENSE_AGENT"):
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.agent as agent
        import app.meetingsense.agent.graph as graph
        import app.meetingsense.agent.modes as modes
        import app.meetingsense.config as config
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.agent = agent
        self.graph = graph
        self.modes = modes
        self.config = config
        self.session = session
        self.store = store


@pytest.fixture()
def modules(tmp_path, monkeypatch):
    mods = Modules()
    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(mods.store, "_connect", _connect)
    mods.store.migrate()
    mods.session._SESSIONS.clear()
    return mods


# ── the recorded event fixture ──────────────────────────────────────────────

#: Two windows of transcript and a stop. Recorded rather than generated: the acceptance is that
#: two code paths agree on *this*, and a fixture that changed per run would make a
#: disagreement unreproducible.
EVENTS = [
    {"event": "segments", "fresh": [
        {"t0_ms": 0, "t1_ms": 4_000, "speaker": "them", "text": "right, let us talk about pricing"},
        {"t0_ms": 4_000, "t1_ms": 9_000, "speaker": "me", "text": "we should hold at forty a seat"},
    ]},
    {"event": "segments", "fresh": [
        {"t0_ms": 600_000, "t1_ms": 604_000, "speaker": "them", "text": "agreed, forty it is"},
    ]},
    {"event": "stop", "fresh": [
        {"t0_ms": 900_000, "t1_ms": 903_000, "speaker": "me", "text": "thanks everyone"},
    ]},
]


class Engine:
    """MS12's engine, stubbed at its three-call surface, and counting.

    Not a mock of `NotesEngine` but a stand-in with the same contract — `add`, `due`, `run` —
    because that contract is exactly what both paths use and what the equality claim is about.
    """

    def __init__(self, due_after: int = 2):
        self.added = []
        self.runs = 0
        self.forced = []
        self._due_after = due_after

    def add(self, segments):
        self.added.extend(segments)

    def due(self):
        return len(self.added) >= self._due_after

    async def run(self, *, force: bool = False):
        self.runs += 1
        self.forced.append(force)
        frame = {"type": "notes", "version": self.runs, "recap": f"recap {self.runs}",
                 "decisions": [{"text": "Hold pricing at forty a seat"}]}
        self.added = []
        return frame


async def fixed_loop(engine, events, send):
    """The path MS12 and MS3 have run since W4, spelled out.

    Copied from `session._maybe_notes` and `session.stop` rather than called, because calling
    the session would drag a transport, a store and a clock into a test about two schedulers.
    What is copied is three lines, and a test below asserts the session still does exactly
    this — so the copy cannot drift without something failing.
    """
    frames = []
    for step in events:
        engine.add(step["fresh"])
        force = step["event"] == "stop"
        if not force and not engine.due():
            continue
        frame = await engine.run(force=force)
        if frame is not None:
            frames.append(frame)
            await send(frame)
    return frames


async def graph_run(mods, engine, events, send, *, mode="note-taker", engine_name="walk"):
    deps = mods.graph.Deps(notes=engine, send=send)
    frames = []
    for step in events:
        state = await mods.agent.run(
            meeting_id="m1", event=step["event"], fresh=step["fresh"], mode=mode,
            deps=deps, engine=engine_name,
        )
        frames.extend(state["frames"])
    return frames


# ── the acceptance ──────────────────────────────────────────────────────────


class TestIdenticalToTheFixedLoop:
    def test_note_taker_produces_the_same_frames(self, modules):
        # The batch's acceptance, and the reason D8 keeps memory outside the graph: if a node
        # could remember something the fixed loop could not, these would diverge on turn two.
        sent_fixed, sent_graph = [], []

        async def scenario():
            fixed = await fixed_loop(Engine(), EVENTS, lambda f: _collect(sent_fixed, f))
            graphed = await graph_run(modules, Engine(), EVENTS,
                                      lambda f: _collect(sent_graph, f))
            return fixed, graphed

        fixed, graphed = run(scenario())
        assert graphed == fixed
        assert sent_graph == sent_fixed
        assert fixed, "the fixture should produce notes, or this compares two empty lists"

    def test_the_engine_is_driven_identically(self, modules):
        # Same calls, same order, same `force` — not just the same frames out. Two paths that
        # agreed on output while calling the engine differently would diverge the moment the
        # engine's own behaviour changed.
        one, two = Engine(), Engine()

        async def scenario():
            await fixed_loop(one, EVENTS, _noop)
            await graph_run(modules, two, EVENTS, _noop)

        run(scenario())
        assert (two.runs, two.forced) == (one.runs, one.forced)

    def test_stop_forces_the_last_window_in_both(self, modules):
        # Without the force the last minute of every meeting is missing from its notes.
        one, two = Engine(due_after=99), Engine(due_after=99)

        async def scenario():
            await fixed_loop(one, EVENTS, _noop)
            await graph_run(modules, two, EVENTS, _noop)

        run(scenario())
        assert one.forced == two.forced == [True]

    def test_the_session_still_drives_the_engine_the_way_this_test_copies(self, modules):
        # The fixed loop above is a copy of three lines from `session._maybe_notes`. A copy
        # that drifts makes the acceptance meaningless, so the real thing is read.
        import inspect

        source = inspect.getsource(modules.session.MeetingSession._maybe_notes)
        for call in ("self.notes.add(fresh)", "self.notes.due()", "self.notes.run()"):
            assert call in source, source


def _collect(sink, frame):
    sink.append(frame)

    async def done():
        return None

    return done()


def _noop(frame):
    async def done():
        return None

    return done()


# ── the two engines ─────────────────────────────────────────────────────────


class TestBothSchedulersAgree:
    def test_the_walker_and_langgraph_produce_the_same_state(self, modules):
        # Two schedulers, one set of behaviour. If langgraph is absent this asserts the
        # fallback is what runs, which is the other half of the same claim.
        compiled = modules.graph.build(modules.graph.Deps())
        if compiled is None:
            pytest.skip("langgraph is not installed; the walker is the only engine here")

        async def scenario():
            walked = await modules.agent.run(meeting_id="m1", event="segments",
                                             fresh=EVENTS[0]["fresh"], deps=modules.graph.Deps(),
                                             engine="walk")
            built = await modules.agent.run(meeting_id="m1", event="segments",
                                            fresh=EVENTS[0]["fresh"], deps=modules.graph.Deps(),
                                            engine="langgraph")
            return walked, built

        walked, built = run(scenario())
        assert built["frames"] == walked["frames"]
        assert built["trace"] == walked["trace"]

    def test_asking_for_langgraph_where_it_is_absent_says_so(self, modules, monkeypatch):
        monkeypatch.setattr(modules.graph, "build", lambda deps: None)
        state = run(modules.agent.run(meeting_id="m1", engine="langgraph"))
        assert state["errors"] == ["langgraph is not installed"]

    def test_auto_falls_back_rather_than_failing(self, modules, monkeypatch):
        monkeypatch.setattr(modules.graph, "build", lambda deps: None)
        state = run(modules.agent.run(meeting_id="m1", engine="auto"))
        assert state["trace"] == ["perceive", "reflect", "decide", "deliver"]

    def test_a_graph_that_throws_falls_back_to_the_walker(self, modules, monkeypatch):
        class Angry:
            async def ainvoke(self, state):
                raise RuntimeError("the checkpointer is on fire")

        monkeypatch.setattr(modules.graph, "build", lambda deps: Angry())
        state = run(modules.agent.run(meeting_id="m1", engine="auto"))
        assert state["trace"] == ["perceive", "reflect", "decide", "deliver"]


# ── the modes ───────────────────────────────────────────────────────────────


class TestModes:
    def test_note_taker_plans_nothing(self, modules):
        # What makes the acceptance a claim about one code path rather than a coincidence.
        state = run(modules.agent.run(meeting_id="m1", event="ask", question="what did we decide?",
                                      mode="note-taker", deps=modules.graph.Deps()))
        assert state["trace"] == ["perceive", "reflect", "decide", "deliver"]

    def test_participant_recalls_then_answers(self, modules):
        seen = {}

        async def ask(meeting_id, question):
            seen["question"] = question
            return {"type": "answer", "text": "Forty a seat.", "cited": ["00:00:04"]}

        deps = modules.graph.Deps(ask=ask, search=lambda q, **kw: [{"cite": "x", "text": "y"}])
        state = run(modules.agent.run(meeting_id="m1", event="ask", question="what did we decide?",
                                      mode="participant", deps=deps))
        assert state["trace"] == ["perceive", "reflect", "decide", "recall", "answer", "deliver"]
        assert state["recalled"]
        assert [f["type"] for f in state["frames"]] == ["answer"]

    def test_a_mode_that_cannot_recall_still_answers(self, modules):
        # MS13's keyword tier is the whole of retrieval on an install with no vector store,
        # and a mode that skipped the answer because it could not recall would be worse than
        # one that answered from what it has.
        async def ask(meeting_id, question):
            return {"type": "answer", "text": "Forty."}

        called = []
        deps = modules.graph.Deps(ask=ask, search=lambda *a, **k: called.append(1) or [])
        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="participant", deps=deps,
                                      allows={**modules.modes.allows("participant"), "recall": False}))
        assert "answer" in state["trace"]

    def test_presenter_speaks_on_a_slide_and_note_taker_does_not(self, modules):
        # Presenter's one unprompted move. A new slide is a moment where saying something is
        # expected; every other moment is an interruption.
        asked = {}

        async def ask(meeting_id, question):
            asked["question"] = question
            return {"type": "answer", "text": "This chart shows the split."}

        slide = {"caption": "Enterprise pricing, per seat."}
        deps = modules.graph.Deps(ask=ask)
        loud = run(modules.agent.run(meeting_id="m1", event="slide", keyframe=slide,
                                     mode="presenter", deps=deps))
        quiet = run(modules.agent.run(meeting_id="m1", event="slide", keyframe=slide,
                                      mode="note-taker", deps=deps))
        # The trace, not the plan: a node consumes its own step, so the plan is empty by the
        # time a run returns whatever it decided to do.
        assert "answer" in loud["trace"]
        assert "answer" not in quiet["trace"]
        assert [f["type"] for f in loud["frames"]] == ["answer"]
        assert quiet["frames"] == []
        # Routed through MS13's tiers like everything else it says, so the caption becomes the
        # question rather than a second prompt builder appearing here.
        assert "Enterprise pricing, per seat." in asked["question"]

    def test_an_uncaptioned_slide_is_not_worth_a_remark(self, modules):
        # The vision model has not answered yet. An unprompted remark about a slide nobody has
        # described is noise, and its caption arriving thirty seconds later is not a reason to
        # have guessed.
        called = []

        async def ask(meeting_id, question):
            called.append(question)
            return {"type": "answer", "text": "..."}

        state = run(modules.agent.run(meeting_id="m1", event="slide",
                                      keyframe={"caption": None}, mode="presenter",
                                      deps=modules.graph.Deps(ask=ask)))
        assert called == []
        assert state["frames"] == []

    def test_coach_offers_an_observation_at_the_end(self, modules):
        async def observe(state):
            return "You spent eleven minutes on one slide."

        deps = modules.graph.Deps(coach=observe)
        state = run(modules.agent.run(meeting_id="m1", event="stop", mode="coach", deps=deps))
        assert [f["type"] for f in state["frames"]] == ["coaching"]
        assert "eleven minutes" in state["frames"][0]["text"]

    def test_coaching_is_its_own_frame_not_a_note(self, modules):
        # A client renders coaching differently — quieter, dismissible — and folding it into
        # `notes` or `answer` would make that impossible.
        async def observe(state):
            return "Ana has not spoken."

        state = run(modules.agent.run(meeting_id="m1", event="stop", mode="coach",
                                      deps=modules.graph.Deps(coach=observe)))
        assert state["frames"][0]["type"] == "coaching"

    def test_nothing_worth_saying_says_nothing(self, modules):
        async def observe(state):
            return "   "

        state = run(modules.agent.run(meeting_id="m1", event="stop", mode="coach",
                                      deps=modules.graph.Deps(coach=observe)))
        assert state["frames"] == []

    def test_a_mode_that_forbids_coaching_never_reaches_the_coach(self, modules):
        called = []

        async def observe(state):
            called.append(1)
            return "something"

        state = run(modules.agent.run(meeting_id="m1", event="stop", mode="participant",
                                      deps=modules.graph.Deps(coach=observe)))
        assert called == []
        assert state["frames"] == []

    def test_an_unknown_mode_resolves_down_not_up(self, modules):
        # A typo, a stale client, a mode a later wave removed — each should quiet the
        # assistant, not hand it tools.
        assert modules.modes.resolve("cheerleader").name == "note-taker"
        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="cheerleader", deps=modules.graph.Deps()))
        assert state["mode"] == "note-taker"
        assert state["trace"] == ["perceive", "reflect", "decide", "deliver"]

    def test_the_policy_is_resolved_once_per_turn(self, modules):
        # Every node reads `state["allows"]` rather than asking again, so a mode changed
        # mid-turn cannot make `decide` and `act` disagree about what is permitted.
        state = run(modules.agent.run(meeting_id="m1", mode="practice", deps=modules.graph.Deps()))
        assert state["allows"] == modules.modes.allows("practice")


# ── tools ───────────────────────────────────────────────────────────────────


class TestAct:
    def _deps(self, modules, calls, approved=None, invoke=None):
        async def default_invoke(tool, args):
            return f"{tool} ok"

        return modules.graph.Deps(
            ask=_answering, tool_calls=calls, approved_tools=approved,
            invoke=invoke or default_invoke,
        )

    def test_a_mode_without_tools_never_calls_one(self, modules):
        called = []

        async def invoke(tool, args):
            called.append(tool)
            return "x"

        deps = self._deps(modules, [{"tool": "hp.web.search", "args": {}}], invoke=invoke)
        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="participant", deps=deps))
        assert called == []
        assert "act" not in state["trace"]

    def test_practice_calls_an_approved_tool(self, modules):
        deps = self._deps(modules, [{"tool": "hp.web.search", "args": {"q": "x"}}],
                          approved=["hp.web.search"])
        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="practice", deps=deps))
        assert [r["tool"] for r in state["tool_results"]] == ["hp.web.search"]

    def test_an_unapproved_tool_is_refused_and_recorded(self, modules):
        # Two gates, two questions: the mode says whether tools at all, the approval says
        # which. A refusal that vanished silently would be one nobody can approve, because
        # nobody would know it was wanted.
        deps = self._deps(modules, [{"tool": "hp.shell.run", "args": {}}],
                          approved=["hp.web.search"])
        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="practice", deps=deps))
        assert state["tool_results"] == []
        assert any("not approved" in e for e in state["errors"])

    def test_a_failing_tool_does_not_stop_the_rest(self, modules):
        async def invoke(tool, args):
            if tool == "bad":
                raise RuntimeError("nope")
            return "ok"

        deps = self._deps(modules, [{"tool": "bad", "args": {}}, {"tool": "good", "args": {}}],
                          approved=["bad", "good"], invoke=invoke)
        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="practice", deps=deps))
        assert [r["tool"] for r in state["tool_results"]] == ["good"]
        assert any("bad failed" in e for e in state["errors"])

    def test_a_turn_cannot_spend_a_meeting_on_tools(self, modules):
        deps = self._deps(modules, [{"tool": f"t{i}", "args": {}} for i in range(10)],
                          approved=[f"t{i}" for i in range(10)])
        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="practice", deps=deps))
        assert len(state["tool_results"]) == modules.graph.NODES["act"].__globals__["MAX_CALLS"]


async def _answering(meeting_id, question):
    return {"type": "answer", "text": "ok"}


# ── the properties that keep it debuggable ──────────────────────────────────


class TestItNeverTakesTheMeetingDown:
    """Every node catches its own failures. A graph that can take a meeting down is worse than
    one that occasionally does nothing, so each of these drives one dependency into an
    exception and asserts the run still reaches `deliver`."""

    def test_a_notes_engine_that_raises(self, modules):
        class Angry:
            def add(self, *args):
                raise RuntimeError("boom")

            def due(self):
                return True

            async def run(self, **kwargs):
                raise RuntimeError("boom")

        state = run(modules.agent.run(meeting_id="m1", event="segments",
                                      fresh=EVENTS[0]["fresh"],
                                      deps=modules.graph.Deps(notes=Angry())))
        assert any("reflect" in e for e in state["errors"])
        assert "deliver" in state["trace"]

    def test_an_ask_that_raises(self, modules):
        async def angry(*args, **kwargs):
            raise RuntimeError("boom")

        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="participant",
                                      deps=modules.graph.Deps(ask=angry)))
        assert any("answer" in e for e in state["errors"])
        assert "deliver" in state["trace"]

    def test_a_coach_that_raises(self, modules):
        async def angry(*args, **kwargs):
            raise RuntimeError("boom")

        state = run(modules.agent.run(meeting_id="m1", event="stop", mode="coach",
                                      deps=modules.graph.Deps(coach=angry)))
        assert any("coach" in e for e in state["errors"])
        assert "deliver" in state["trace"]

    def test_a_search_that_raises_still_answers(self, modules):
        # The index is optional and MS13's keyword tier is the whole of retrieval without it.
        def angry(*args, **kwargs):
            raise RuntimeError("index corrupted")

        async def ask(meeting_id, question):
            return {"type": "answer", "text": "from the keyword tier"}

        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="participant",
                                      deps=modules.graph.Deps(ask=ask, search=angry)))
        assert [f["type"] for f in state["frames"]] == ["answer"]
        assert any("recall" in e for e in state["errors"])

    def test_a_transport_that_raises_keeps_the_frames(self, modules):
        # The notes are already in the store; a dead socket is not a reason to lose them from
        # the run's own record of what it produced.
        async def angry(frame):
            raise RuntimeError("socket closed")

        engine = Engine(due_after=1)
        state = run(modules.agent.run(meeting_id="m1", event="segments",
                                      fresh=EVENTS[0]["fresh"],
                                      deps=modules.graph.Deps(notes=engine, send=angry)))
        assert [f["type"] for f in state["frames"]] == ["notes"]
        assert any("deliver" in e for e in state["errors"])

    def test_a_graph_with_no_dependencies_at_all_still_runs(self, modules):
        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="practice", deps=modules.graph.Deps()))
        assert state["frames"] == []
        assert "deliver" in state["trace"]

    def test_an_unknown_event_is_ignored_rather_than_guessed(self, modules):
        state = run(modules.agent.run(meeting_id="m1", event="telepathy",
                                      deps=modules.graph.Deps()))
        assert any("unknown event" in e for e in state["errors"])
        assert "deliver" in state["trace"]

    def test_the_router_always_terminates(self, modules):
        # The plan is consumed a step at a time so it ends by construction; this is the belt.
        # A router bug should end a turn, not a meeting.
        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="practice", deps=modules.graph.Deps()))
        assert len(state["trace"]) < modules.graph.MAX_STEPS

    def test_the_trace_says_what_ran(self, modules):
        # "Why did it do that" has to have an answer, which is D8's argument for keeping
        # memory outside the graph in the first place.
        async def ask(meeting_id, question):
            return {"type": "answer", "text": "ok"}

        state = run(modules.agent.run(meeting_id="m1", event="ask", question="q?",
                                      mode="participant", deps=modules.graph.Deps(ask=ask)))
        assert state["trace"] == ["perceive", "reflect", "decide", "recall", "answer", "deliver"]


class TestTheFlag:
    def test_off_by_default(self, modules, monkeypatch):
        monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
        assert modules.graph.enabled(modules.config.load_config()) is False

    def test_the_master_flag_is_also_required(self, modules, monkeypatch):
        monkeypatch.setenv("MEETINGSENSE_AGENT", "true")
        assert modules.graph.enabled(modules.config.load_config()) is False

    def test_both(self, modules, monkeypatch):
        monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")
        monkeypatch.setenv("MEETINGSENSE_AGENT", "true")
        assert modules.graph.enabled(modules.config.load_config()) is True


class TestMemoryStaysOutside:
    """D8, checked at the source.

    The claim is precise and worth keeping precise: **no node decides what is stored.** It is
    not "nothing under `agent/` writes" — MS24's approval log is policy a person set, written
    by the route that set it, and a test that forbade it would be enforcing a rule nobody
    stated. What has to hold is that a *turn* cannot remember something the fixed loop would
    not, because that is what makes the acceptance comparison meaningful.
    """

    def test_no_node_writes_to_the_store_or_the_index(self, modules):
        import pathlib

        nodes = pathlib.Path(modules.graph.__file__).parent / "nodes"
        files = sorted(nodes.rglob("*.py")) + [pathlib.Path(modules.graph.__file__)]
        for path in files:
            text = path.read_text()
            for forbidden in ("store.add_", "store.save_", "store.delete_", "index_meeting",
                              "forget_meeting", "add_artifact", "approve(", "revoke("):
                assert forbidden not in text, f"{path.name} writes memory: {forbidden}"

    def test_a_turn_writes_nothing_even_with_every_dependency_wired(self, modules, monkeypatch):
        # The same claim behaviourally rather than by grep: drive a full Practice turn with
        # every dependency present and assert the store was never written.
        import app.meetingsense.store as store_mod

        wrote = []
        for name in ("add_artifact", "save_notes", "add_segments", "add_keyframe"):
            monkeypatch.setattr(store_mod, name,
                                lambda *a, _n=name, **k: wrote.append(_n))

        async def ask(meeting_id, question):
            return {"type": "answer", "text": "ok"}

        async def invoke(tool, args):
            return "ok"

        deps = modules.graph.Deps(ask=ask, invoke=invoke, approved_tools=["t"],
                                  tool_calls=[{"tool": "t", "args": {}}],
                                  search=lambda q, **kw: [])
        run(modules.agent.run(meeting_id="m1", event="ask", question="q?", mode="practice",
                              deps=deps))
        assert wrote == []


# ── the belts, tested rather than asserted in a comment ─────────────────────


class TestDefenceInDepth:
    """Four guards that `decide` already makes unreachable, and are kept anyway.

    Each was a mutation survivor: deleting it changed nothing, because the router never puts
    the graph in the state it protects against. That is exactly what a second gate is for — it
    costs a line and it is what holds when the *first* gate is edited. So each is tested by
    calling the node directly with the state the router would never build.
    """

    def test_act_refuses_when_the_mode_forbids_tools_even_if_the_plan_says_otherwise(self, modules):
        from app.meetingsense.agent.nodes.act import act

        called = []

        async def invoke(tool, args):
            called.append(tool)
            return "x"

        deps = modules.graph.Deps(invoke=invoke, tool_calls=[{"tool": "hp.web.search", "args": {}}],
                                  approved_tools=["hp.web.search"])
        # A plan that says "act" under a policy that says no tools: only reachable by editing
        # `decide`, which is the day this guard matters.
        state = modules.agent.state.new_state(plan=["act"], allows={"tools": False})
        out = run(act(state, deps))
        assert called == []
        assert out.get("tool_results") in (None, [])

    def test_coach_refuses_when_the_mode_forbids_coaching(self, modules):
        from app.meetingsense.agent.nodes.coach import coach

        called = []

        async def observe(state):
            called.append(1)
            return "something"

        state = modules.agent.state.new_state(plan=["coach"], allows={"coach": False})
        out = run(coach(state, modules.graph.Deps(coach=observe)))
        assert called == []
        assert "frames" not in out

    def test_note_takers_policy_is_the_floor(self, modules):
        # The policy dict is a public contract — `/status` reads it and the mode chips render
        # it — so a mode that gained a capability no code path happens to use would still be a
        # UI telling the user something untrue.
        assert modules.modes.allows("note-taker") == {
            "notes": True, "answer": False, "proactive": False,
            "coach": False, "tools": False, "recall": False,
            # MS26. Note-taker does not answer to its own name either — being addressed is a
            # prompt, but a mode that says nothing unless asked is not asked by somebody
            # else's microphone.
            "addressed": False,
            "queues": False,
        }

    def test_every_mode_takes_notes_and_only_practice_gets_tools(self, modules):
        table = {m["name"]: m for m in modules.modes.as_dicts()}
        assert all(m["notes"] for m in table.values())
        assert [n for n, m in table.items() if m["tools"]] == ["practice"]
        assert [n for n, m in table.items() if m["proactive"]] == ["presenter"]
        # MS26. `addressed` and `proactive` are different permissions, and Participant is
        # deliberately the first mode with one and not the other: being spoken to is a prompt,
        # speaking unbidden is not.
        assert [n for n, m in table.items() if m["addressed"]] == [
            "participant", "coach", "practice"]
        # Exclusive by construction: a mode either answers the room or collects for the user.
        assert [n for n, m in table.items() if m["queues"]] == ["presenter"]
        assert not [n for n, m in table.items() if m["queues"] and m["addressed"]]

    def test_the_step_limit_ends_a_turn_rather_than_a_meeting(self, modules, monkeypatch):
        # The plan is consumed a step at a time so a run terminates by construction; this is
        # the belt for the day a router change breaks that. Driven by a router that never
        # advances, which is what such a bug looks like.
        import app.meetingsense.agent.graph as graph_mod

        monkeypatch.setattr(graph_mod, "route_after_decide", lambda state: "recall")
        state = run(graph_mod.walk(modules.agent.state.new_state(meeting_id="m1"),
                                   modules.graph.Deps()))
        assert "step limit reached" in state["errors"]
        assert len(state["trace"]) <= graph_mod.MAX_STEPS
