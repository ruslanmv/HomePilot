"""Sub-agents, and what a meeting has approved (batch MS24, wave W8).

Two sub-agents and one policy, and the policy is the half that matters.

**`hp.ms.set_mode` is enforced server-side.** "Modes are server policy objects, not client
compositions" is the batch row's sentence, and it has two halves. The first — what a mode
*means* — landed in MS23 as `modes.py`. The second is here: which mode a meeting is *in* is
server state, read from the store on every turn. A per-turn mode on the wire would let a client
put a meeting into Practice for one request, and that is not a mode, it is an escalation.

**Tool approval is per meeting, and the default is refusal.** A mode says whether tools may be
used at all; an approval says which, for this meeting. Two questions, kept apart, because
collapsing them means somebody who picks Practice has silently agreed to whatever tools the
install happens to have.

**The sub-agents propose; they never write.** `reflect` merges what it accepts through MS12's
`merge`, which never deletes — so an extractor that is wrong is cheap, which is the whole
reason it is a separate agent rather than a bigger notes prompt.
"""

from __future__ import annotations

import asyncio
import json
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
        import app.meetingsense.agent.subagents as subagents
        import app.meetingsense.session as session
        import app.meetingsense.store as store

        self.agent = agent
        self.graph = graph
        self.sub = subagents
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
    mods.store.create_meeting(conversation_id="c1", meeting_id="m1", started_at=1.0)
    return mods


def answering(text="ok"):
    async def call(messages, **kwargs):
        return text

    return call


# ── the mode is server state ────────────────────────────────────────────────


class TestModeIsServerState:
    def test_a_stored_mode_governs_the_turn(self, modules):
        modules.store.add_artifact("m1", kind="mode", target="practice")
        state = run(modules.agent.run(meeting_id="m1", deps=modules.graph.Deps()))
        assert state["mode"] == "practice"

    def test_a_client_supplied_mode_cannot_override_it(self, modules):
        # The escalation this exists to prevent: a turn that arrives claiming Practice on a
        # meeting somebody set to Note-taker.
        modules.store.add_artifact("m1", kind="mode", target="note-taker")
        state = run(modules.agent.run(meeting_id="m1", mode="practice",
                                      deps=modules.graph.Deps()))
        assert state["mode"] == "note-taker"
        assert state["allows"]["tools"] is False

    def test_and_the_client_is_told_rather_than_quietly_ignored(self, modules):
        modules.store.add_artifact("m1", kind="mode", target="note-taker")
        state = run(modules.agent.run(meeting_id="m1", mode="practice",
                                      deps=modules.graph.Deps()))
        assert any("ignored" in e and "practice" in e for e in state["errors"])

    def test_agreeing_with_the_stored_mode_is_not_a_conflict(self, modules):
        modules.store.add_artifact("m1", kind="mode", target="coach")
        state = run(modules.agent.run(meeting_id="m1", mode="coach",
                                      deps=modules.graph.Deps()))
        assert state["errors"] == []

    def test_the_last_setting_wins(self, modules):
        for mode in ("practice", "participant", "coach"):
            modules.store.add_artifact("m1", kind="mode", target=mode)
        assert modules.sub.current_mode("m1") == "coach"

    def test_a_meeting_never_set_falls_back_to_what_was_asked(self, modules):
        # Only a default: a meeting with no stored mode is one nobody has decided about, and
        # the caller's suggestion is better than nothing. It is still resolved through the
        # policy table, so an unknown name lands on the floor.
        assert modules.sub.resolve_mode("m1", "coach")["mode"] == "coach"
        assert modules.sub.resolve_mode("m1", "")["mode"] == ""
        state = run(modules.agent.run(meeting_id="m1", mode="nonsense",
                                      deps=modules.graph.Deps()))
        assert state["mode"] == "note-taker"

    def test_an_unreadable_policy_store_lands_on_the_floor_not_the_ceiling(self, modules,
                                                                          monkeypatch):
        # Asserted on the resolver, not only on the turn: `perceive` has a belt of its own that
        # turns *any* failure into the floor, so a run-level assertion passes just as happily
        # when `resolve_mode` crashes as when it decides. The claim here is that it decides.
        def angry(*args, **kwargs):
            raise RuntimeError("the store is gone")

        monkeypatch.setattr(modules.store, "artifacts_for_meeting", angry)
        decision = modules.sub.resolve_mode("m1", "practice")
        assert decision["mode"] == "note-taker"
        assert decision["source"] == "unreadable"
        # And the client is told, for the same reason a stored mode tells it: a caller that
        # thinks it is in Practice and is not should find out.
        assert decision["overridden"] is True

        state = run(modules.agent.run(meeting_id="m1", mode="practice",
                                      deps=modules.graph.Deps()))
        assert state["mode"] == "note-taker"
        assert state["allows"]["tools"] is False

    def test_an_unreadable_store_asked_for_nothing_is_not_a_conflict(self, modules,
                                                                     monkeypatch):
        def angry(*args, **kwargs):
            raise RuntimeError("the store is gone")

        monkeypatch.setattr(modules.store, "artifacts_for_meeting", angry)
        assert modules.sub.resolve_mode("m1", "")["overridden"] is False

    def test_a_blank_row_does_not_erase_the_mode(self, modules):
        # Defence in depth against a writer that records a mode artifact with no target: the
        # last *setting* wins, and a row that sets nothing is not a setting. Without this the
        # newest blank row would read as "never set" and hand the turn back to the client.
        modules.store.add_artifact("m1", kind="mode", target="participant")
        modules.store.add_artifact("m1", kind="mode", target="")
        assert modules.sub.current_mode("m1") == "participant"
        assert modules.sub.resolve_mode("m1", "practice")["mode"] == "participant"

    def test_it_survives_being_read_twice(self, modules):
        # A mode has to hold across a reconnect and a second client attaching to the same
        # meeting, which is why it is in the store rather than on a session object.
        modules.store.add_artifact("m1", kind="mode", target="presenter")
        assert modules.sub.current_mode("m1") == modules.sub.current_mode("m1") == "presenter"


# ── tool approval ───────────────────────────────────────────────────────────


class TestApproval:
    def test_the_default_is_refusal(self, modules):
        # The only default a consent can safely have.
        assert modules.sub.approved("m1") == []

    def test_approving_is_additive(self, modules):
        # "Also allow this" and "stop allowing that" are different intentions, and a
        # set-replacing API turns the first into the second whenever a client forgets to send
        # the old list.
        modules.sub.approve("m1", ["hp.web.search"])
        assert modules.sub.approve("m1", ["hp.notes.read"]) == ["hp.notes.read", "hp.web.search"]

    def test_approving_twice_is_idempotent(self, modules):
        modules.sub.approve("m1", ["hp.web.search"])
        modules.sub.approve("m1", ["hp.web.search"])
        assert modules.sub.approved("m1") == ["hp.web.search"]
        # And leaves one row, not two. The log is what an audit reads, and a re-send of the
        # same approval — which every reconnecting client does — is not a second consent.
        rows = modules.store.artifacts_for_meeting("m1", kind="tool_approval")
        assert len(rows) == 1

    def test_revoking_leaves_a_record_rather_than_deleting_one(self, modules):
        # A meeting's record of what it was allowed to do, and when that changed, is the thing
        # an audit reads.
        modules.sub.approve("m1", ["hp.web.search", "hp.shell.run"])
        assert modules.sub.revoke("m1", ["hp.shell.run"]) == ["hp.web.search"]
        rows = modules.store.artifacts_for_meeting("m1", kind="tool_approval")
        assert [r["target"] for r in rows].count("hp.shell.run") == 2

    def test_re_approving_after_a_revoke_works(self, modules):
        modules.sub.approve("m1", ["hp.web.search"])
        modules.sub.revoke("m1", ["hp.web.search"])
        assert modules.sub.approved("m1") == []
        assert modules.sub.approve("m1", ["hp.web.search"]) == ["hp.web.search"]
        # Read back, not taken from `approve`'s return value: the return is computed, so a
        # replay that made a revoke permanent would still answer this call correctly and only
        # be wrong on the next turn — which is the turn that matters.
        assert modules.sub.approved("m1") == ["hp.web.search"]

    def test_approvals_are_per_meeting(self, modules):
        modules.store.create_meeting(conversation_id="c1", meeting_id="m2", started_at=2.0)
        modules.sub.approve("m1", ["hp.web.search"])
        assert modules.sub.approved("m2") == []

    def test_deleting_a_meeting_takes_its_approvals(self, modules):
        # They live in `ms_artifacts`, so the delete that removes everything else about a
        # meeting removes these too — a consent that outlived its meeting would be a consent
        # nobody could withdraw.
        modules.sub.approve("m1", ["hp.web.search"])
        modules.store.delete_meeting("m1")
        assert modules.sub.approved("m1") == []

    def test_an_unreadable_store_approves_nothing(self, modules, monkeypatch):
        # The same direction as the mode: what we cannot read, we do not grant.
        modules.sub.approve("m1", ["hp.web.search"])

        def angry(*args, **kwargs):
            raise RuntimeError("the store is gone")

        monkeypatch.setattr(modules.store, "artifacts_for_meeting", angry)
        assert modules.sub.approved("m1") == []
        assert modules.graph.deps_for("m1").approved_tools == []

    def test_deps_for_reads_the_approvals_rather_than_taking_them(self, modules):
        # The one place a caller should build Deps for a live meeting. There is no reason for
        # a caller to hold the approved list, and every reason for it not to.
        modules.sub.approve("m1", ["hp.web.search"])
        deps = modules.graph.deps_for("m1")
        assert deps.approved_tools == ["hp.web.search"]

    def test_a_hand_built_deps_approves_nothing(self, modules):
        # Forgetting `deps_for` is safe in the direction that matters.
        assert modules.graph.Deps().approved_tools is None
        state = run(modules.agent.run(
            meeting_id="m1", event="ask", question="q?", mode="practice",
            deps=modules.graph.Deps(ask=_answer, invoke=_invoke,
                                    tool_calls=[{"tool": "hp.web.search", "args": {}}]),
        ))
        assert state["tool_results"] == []

    def test_the_two_gates_are_separate_questions(self, modules):
        # An approved tool is unusable in a mode that forbids tools, and a mode that permits
        # tools approves nothing by itself.
        modules.sub.approve("m1", ["hp.web.search"])
        modules.store.add_artifact("m1", kind="mode", target="participant")
        state = run(modules.agent.run(
            meeting_id="m1", event="ask", question="q?",
            deps=modules.graph.deps_for("m1", ask=_answer, invoke=_invoke,
                                        tool_calls=[{"tool": "hp.web.search", "args": {}}]),
        ))
        assert state["tool_results"] == []

    def test_both_gates_open(self, modules):
        modules.sub.approve("m1", ["hp.web.search"])
        modules.store.add_artifact("m1", kind="mode", target="practice")
        state = run(modules.agent.run(
            meeting_id="m1", event="ask", question="q?",
            deps=modules.graph.deps_for("m1", ask=_answer, invoke=_invoke,
                                        tool_calls=[{"tool": "hp.web.search", "args": {}}]),
        ))
        assert [r["tool"] for r in state["tool_results"]] == ["hp.web.search"]


async def _answer(meeting_id, question):
    return {"type": "answer", "text": "ok"}


async def _invoke(tool, args):
    return f"{tool} ran"


# ── SlideReader ─────────────────────────────────────────────────────────────


class TestSlideReader:
    def test_it_reads_a_caption_into_a_record(self, modules):
        body = json.dumps({"title": "Q3 revenue", "claim": "revenue is flat since June",
                           "topics": ["revenue", "q3"]})
        out = run(modules.sub.read_slide({"t_ms": 1000, "hash": "a", "caption": "A chart."},
                                         call=answering(body)))
        assert out["title"] == "Q3 revenue"
        assert out["claim"] == "revenue is flat since June"
        assert out["topics"] == ["revenue", "q3"]

    def test_an_uncaptioned_slide_is_not_worth_asking_about(self, modules):
        called = []

        async def call(messages, **kwargs):
            called.append(1)
            return "{}"

        assert run(modules.sub.read_slide({"t_ms": 0, "caption": None}, call=call)) is None
        assert called == []

    def test_a_re_shown_slide_is_a_return_not_a_second_reading(self, modules):
        # MS9 already decided a re-shown slide is the same slide; this is the same dHash
        # saying so. A timeline can show it went up twice without the notes claiming two.
        called = []

        async def call(messages, **kwargs):
            called.append(1)
            return "{}"

        out = run(modules.sub.read_slide({"t_ms": 60_000, "hash": "a", "caption": "A chart."},
                                         call=call, seen_hashes=["a"]))
        assert out["repeat"] is True
        assert called == []

    def test_with_no_model_the_caption_stands(self, modules):
        # A caption is already a sentence somebody or something wrote; passing it through is
        # more use than nothing.
        out = run(modules.sub.read_slide({"t_ms": 0, "hash": "a", "caption": "The chart."}))
        assert out["claim"] == "The chart."

    def test_topics_are_capped(self, modules):
        body = json.dumps({"title": "x", "claim": "y", "topics": list("abcdef")})
        assert len(run(modules.sub.read_slide({"caption": "c"}, call=answering(body)))["topics"]) == 3

    def test_a_model_that_answers_with_prose_is_ignored(self, modules):
        assert run(modules.sub.read_slide({"caption": "c"},
                                          call=answering("I think this slide is nice."))) is None

    def test_a_model_that_raises_is_not_a_crash(self, modules):
        async def angry(messages, **kwargs):
            raise RuntimeError("down")

        assert run(modules.sub.read_slide({"caption": "c"}, call=angry)) is None

    def test_it_reads_a_fenced_answer(self, modules):
        # With chatter after the fence, which is what a model that was told "JSON only" does
        # anyway. The fence has to be preferred over the outermost braces in the whole string:
        # a greedy scan would swallow the sign-off and parse nothing.
        body = ("```json\n{\"title\": \"T\", \"claim\": \"C\", \"topics\": []}\n```\n"
                "Hope that helps! {let me know}")
        assert run(modules.sub.read_slide({"caption": "c"}, call=answering(body)))["title"] == "T"


# ── ActionExtractor ─────────────────────────────────────────────────────────


WINDOW = [
    {"t0_ms": 0, "speaker": "them", "text": "we should look at the vendor terms"},
    {"t0_ms": 4_000, "speaker": "me", "text": "Ana will send the revised terms by Friday"},
]


class TestActionExtractor:
    def test_it_proposes_owners_and_deadlines(self, modules):
        body = json.dumps({"actions": [
            {"text": "Send the revised terms", "owner": "Ana", "due": "Friday", "t0": 4000}]})
        out = run(modules.sub.extract_actions(WINDOW, call=answering(body)))
        assert out == [{"text": "Send the revised terms", "owner": "Ana", "due": "Friday",
                        "t0": 4000}]

    def test_an_invented_timestamp_is_dropped_not_kept(self, modules):
        # MS12's rule, obeyed here: a `t0` the model invented is worse than none, because
        # MS13 answers with these and a timestamp that jumps is what makes somebody stop
        # trusting the feature.
        body = json.dumps({"actions": [{"text": "Do the thing", "t0": 999_999}]})
        out = run(modules.sub.extract_actions(WINDOW, call=answering(body)))
        assert out == [{"text": "Do the thing"}]

    def test_it_never_guesses_an_owner(self, modules):
        body = json.dumps({"actions": [{"text": "Do the thing", "owner": ""}]})
        assert "owner" not in run(modules.sub.extract_actions(WINDOW, call=answering(body)))[0]

    def test_the_proposal_count_is_capped(self, modules):
        body = json.dumps({"actions": [{"text": f"thing {i}"} for i in range(20)]})
        out = run(modules.sub.extract_actions(WINDOW, call=answering(body)))
        assert len(out) == modules.sub.MAX_ACTIONS

    def test_an_empty_window_asks_nothing(self, modules):
        called = []

        async def call(messages, **kwargs):
            called.append(1)
            return "{}"

        assert run(modules.sub.extract_actions([], call=call)) == []
        assert called == []

    def test_with_no_model_it_finds_only_the_unmistakable(self, modules):
        # Deliberately narrow. An install with no model gets the commitments that were phrased
        # plainly and misses the rest, which beats a regular expression guessing at intent.
        out = run(modules.sub.extract_actions(WINDOW))
        assert len(out) == 1
        assert out[0]["owner"] == "Ana"

    def test_a_model_that_raises_proposes_nothing(self, modules):
        async def angry(messages, **kwargs):
            raise RuntimeError("down")

        assert run(modules.sub.extract_actions(WINDOW, call=angry)) == []


# ── the sub-agents inside a turn ────────────────────────────────────────────


class Engine:
    def __init__(self):
        self.frame = {"type": "notes", "version": 1, "recap": "r",
                      "actions": [{"text": "Book the room"}]}

    def add(self, segments):
        pass

    def due(self):
        return True

    async def run(self, *, force=False):
        self.last = dict(self.frame)
        return self.last


class TestInsideATurn:
    def _deps(self, modules, **kw):
        return modules.graph.Deps(notes=Engine(), **kw)

    def test_an_extracted_action_is_added_to_the_notes(self, modules):
        async def extract(window):
            return [{"text": "Send the revised terms", "owner": "Ana"}]

        state = run(modules.agent.run(meeting_id="m1", event="segments", fresh=WINDOW,
                                      deps=self._deps(modules, extract_actions=extract)))
        texts = [a["text"] for a in state["frames"][0]["actions"]]
        assert texts == ["Book the room", "Send the revised terms"]

    def test_it_never_removes_what_the_engine_found(self, modules):
        # Additive, always. An extractor that could remove a note would be a second author of
        # one record, and MS12's `merge` never deletes for the same reason.
        async def extract(window):
            return []

        state = run(modules.agent.run(meeting_id="m1", event="segments", fresh=WINDOW,
                                      deps=self._deps(modules, extract_actions=extract)))
        assert [a["text"] for a in state["frames"][0]["actions"]] == ["Book the room"]

    def test_a_duplicate_proposal_does_not_produce_a_second_row(self, modules):
        # Deduped on MS12's own key — case- and punctuation-insensitive — so an extractor that
        # phrases a commitment differently does not make the notes look broken.
        async def extract(window):
            return [{"text": "book the room!"}]

        state = run(modules.agent.run(meeting_id="m1", event="segments", fresh=WINDOW,
                                      deps=self._deps(modules, extract_actions=extract)))
        assert len(state["frames"][0]["actions"]) == 1

    def test_a_slide_reading_lands_beside_the_notes(self, modules):
        async def read(keyframe):
            return {"t_ms": 1000, "hash": "a", "repeat": False, "title": "Q3", "claim": "flat",
                    "topics": []}

        state = run(modules.agent.run(meeting_id="m1", event="segments", fresh=WINDOW,
                                      keyframe={"caption": "c", "hash": "a"},
                                      deps=self._deps(modules, read_slide=read)))
        assert [s["title"] for s in state["frames"][0]["slides"]] == ["Q3"]

    def test_a_reading_joins_the_slides_already_in_the_frame(self, modules):
        # MS10's frames carry slides. A reading is added to them, never in place of them —
        # the same "never removes" rule the actions follow.
        engine = Engine()
        engine.frame["slides"] = [{"title": "Agenda"}]

        async def read(keyframe):
            return {"repeat": False, "title": "Q3"}

        state = run(modules.agent.run(meeting_id="m1", event="segments", fresh=WINDOW,
                                      keyframe={"caption": "c", "hash": "a"},
                                      deps=modules.graph.Deps(notes=engine, read_slide=read)))
        assert [s["title"] for s in state["frames"][0]["slides"]] == ["Agenda", "Q3"]

    def test_a_repeated_slide_is_not_recorded_again(self, modules):
        async def read(keyframe):
            return {"repeat": True, "hash": "a"}

        state = run(modules.agent.run(meeting_id="m1", event="segments", fresh=WINDOW,
                                      keyframe={"caption": "c", "hash": "a"},
                                      deps=self._deps(modules, read_slide=read)))
        assert "slides" not in state["frames"][0]

    def test_a_sub_agent_that_raises_leaves_the_notes_intact(self, modules):
        async def angry(*args, **kwargs):
            raise RuntimeError("down")

        state = run(modules.agent.run(meeting_id="m1", event="segments", fresh=WINDOW,
                                      keyframe={"caption": "c"},
                                      deps=self._deps(modules, extract_actions=angry,
                                                      read_slide=angry)))
        assert state["frames"][0]["actions"] == [{"text": "Book the room"}]

    def test_no_sub_agents_is_the_note_takers_frame_unchanged(self, modules):
        # MS23's acceptance still has to hold: with no sub-agents wired, the frame is the
        # engine's, untouched.
        engine = Engine()
        state = run(modules.agent.run(meeting_id="m1", event="segments", fresh=WINDOW,
                                      deps=modules.graph.Deps(notes=engine)))
        assert state["frames"][0] == Engine().frame
        # The same object the engine returned, not a copy of it. Identity is the honest form
        # of "untouched", and it is the only form that is checkable: a shallow copy is equal
        # today and diverges the moment the augment path grows a step that runs before it
        # knows whether it has anything to do. MS23's acceptance says *identical*, and the
        # fixed loop hands the engine's own frame to the transport.
        assert state["notes"] is engine.last
