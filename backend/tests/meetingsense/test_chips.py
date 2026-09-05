"""Deterministic triggers, and the chips they produce (batch MS25, wave W9).

**The negatives are the batch.** A chip interrupts: it appears while somebody is talking and
because of what they just said, so a chip that is wrong is not a bad summary the user scrolls
past — it is the assistant visibly misunderstanding the room, in front of the room. Every
trigger below is therefore tested twice, once for the sentence it exists to catch and once for
the sentence that looks like it and must stay quiet. `TestMustNotFire` collects the second kind
in one place so the list can be read as a list.

**Ask-before-acting is an order, not a label.** `accept` is what runs a proposal, and it runs
only after somebody said yes, only through the runtime tool router, and only for a tool this
meeting has approved. Each of those three is tested by making it say no.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture()
def chips():
    import app.meetingsense.chips as module

    return module


@pytest.fixture()
def store(tmp_path, monkeypatch):
    import app.meetingsense.store as store_mod

    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(store_mod, "_connect", _connect)
    store_mod.migrate()
    return store_mod


@pytest.fixture()
def meeting(store):
    """A meeting row, for the tests that do not open a session to make one."""
    store.create_meeting(conversation_id="c1", meeting_id="m1", started_at=1.0)
    return store


def said(text, *, speaker="them", t0=1000):
    return {"t0_ms": t0, "speaker": speaker, "text": text}


def kinds(found):
    return [c["kind"] for c in found]


# ── the triggers that must fire ─────────────────────────────────────────────


class TestQuestionAimedAtMe:
    def test_a_direct_question_from_the_call(self, chips):
        found = chips.detect([said("What do you think about the vendor terms?")])
        assert kinds(found) == ["question"]

    def test_addressed_by_name_without_a_pronoun(self, chips):
        found = chips.detect([said("Ana, what is the release date?")], names=["Ana"])
        assert kinds(found) == ["question"]

    def test_an_unpunctuated_question_still_counts(self, chips):
        # A speech model punctuates a transcript, and it does not always hear the rise.
        found = chips.detect([said("so are you happy with that")])
        assert kinds(found) == ["question"]


class TestDecision:
    def test_an_announced_decision(self, chips):
        found = chips.detect([said("Right, we're going with the second option.")])
        assert kinds(found) == ["decision"]

    def test_lets_go_with(self, chips):
        assert kinds(chips.detect([said("let's go with Postgres")])) == ["decision"]


class TestAction:
    def test_a_named_owner_and_a_commitment(self, chips):
        found = chips.detect([said("Ana will send the revised terms")])
        assert kinds(found) == ["action"]
        assert found[0]["owner"] == "Ana"

    def test_first_person_is_an_owner(self, chips):
        found = chips.detect([said("I'll write up the summary", speaker="me")])
        assert found[0]["owner"] == "me"


class TestDate:
    def test_a_deadline(self, chips):
        found = chips.detect([said("we need the draft by Friday")])
        assert kinds(found) == ["date"]
        assert found[0]["when"].lower() == "by friday"

    def test_an_iso_date(self, chips):
        assert kinds(chips.detect([said("the cutover is 2026-04-20")])) == ["date"]

    def test_a_month_and_a_day(self, chips):
        assert kinds(chips.detect([said("it ships March 3")])) == ["date"]


class TestLinkOnASlide:
    def test_a_url_in_a_caption(self, chips):
        found = chips.detect(keyframe={"t_ms": 5000, "caption": "Docs at https://example.com/x"})
        assert kinds(found) == ["link"]
        assert found[0]["url"] == "https://example.com/x"

    def test_trailing_punctuation_is_not_part_of_the_link(self, chips):
        found = chips.detect(keyframe={"caption": "See www.example.com/plan."})
        assert found[0]["url"] == "www.example.com/plan"


# ── the triggers that must not fire ─────────────────────────────────────────


class TestMustNotFire:
    """One list, deliberately. This is the acceptance criterion, so it reads as a list."""

    @pytest.mark.parametrize("text,speaker", [
        # A question the user asked is a question they already know about.
        ("What do you think about the terms?", "me"),
        # A question to the room, not to this user. A chip here is the assistant volunteering.
        ("What time is the release?", "them"),
        # Verbal commas. Every one of these has a second person and a question mark, which is
        # exactly why they are here: they pass the shape and must not fire.
        ("Does that make sense?", "them"),
        ("Do you know what I mean?", "them"),
        ("Can you hear me?", "them"),
        # "you" is not inside "young" — and the sentence has to be a question for the
        # pronoun check to be reached at all, or the word-boundary is never consulted.
        ("Was the young team happy with it?", "them"),
        ("The young team shipped it", "them"),
    ])
    def test_not_a_question_aimed_at_me(self, chips, text, speaker):
        assert "question" not in kinds(chips.detect([said(text, speaker=speaker)]))

    @pytest.mark.parametrize("text", [
        # Asking about deciding is what a meeting does *before* deciding.
        "So are we going with the second option?",
        "Should we go with Postgres",
        # A confirming question. The marker matches in full — "we're going with" — and the
        # sentence is still asking, which is why the question guard is checked before it.
        "So we're going with the second option?",
        # The sentence people say instead of deciding.
        "We have not decided yet",
        "We haven't agreed on anything",
        # Negated ahead of a marker that does match on its own.
        "I'm not sure we're going with the second option",
    ])
    def test_not_a_decision(self, chips, text):
        assert "decision" not in kinds(chips.detect([said(text)]))

    @pytest.mark.parametrize("text", [
        # A question about who will act is not somebody acting.
        "Who will send the revised terms?",
        # And nor is checking. The owner is named and the commitment is in the plain form; the
        # only thing that makes this not an action is the question mark.
        "So Ana will send the terms?",
        # The sentence that means nobody will.
        "Someone will send the terms",
        "We will see how it goes",
        "It will be fine",
        # A prediction, not a promise.
        "I will try to get to it",
        # Negated.
        "Ana will not send the terms",
    ])
    def test_not_an_action(self, chips, text):
        assert "action" not in kinds(chips.detect([said(text)]))

    @pytest.mark.parametrize("text", [
        # A company, not a weekday. This one line is most of the date trigger's correctness:
        # "on monday" is a date pattern, and "on monday.com" is a SaaS tool.
        "we track it on monday.com",
        "the runbook is on friday.example.com",
        # A permalink, not a deadline.
        "it is at https://example.com/2026-04-20/notes",
        "see blog.example.com/march-3-recap",
        # A bare weekday is as often a description of the week as a deadline.
        "it has been a long Friday",
        # Numbers that are not dates.
        "we are on version 3.2 now",
        "give me 3 minutes",
    ])
    def test_not_a_date(self, chips, text):
        assert "date" not in kinds(chips.detect([said(text)]))

    def test_a_spoken_url_is_not_a_slide_link(self, chips):
        # The batch row says "URL on a slide", and the distinction is not pedantry: a link
        # somebody read out is a link the listener already has.
        assert "link" not in kinds(chips.detect([said("go to https://example.com/x")]))

    @pytest.mark.parametrize("caption", [
        # A slide deck is full of both of these, and neither is a link.
        "Built with node.js and express",
        "Attached: report.pdf",
        "Contact: ana@example.com",
    ])
    def test_not_a_link(self, chips, caption):
        assert chips.detect(keyframe={"caption": caption}) == []

    def test_a_plain_host_on_a_slide_is_missed_on_purpose(self, chips):
        # A real miss, and the right one: requiring a scheme or `www.` is what keeps
        # `report.pdf` from becoming a link, and a link chip that opens a filename in a
        # browser is worse than no link chip.
        assert chips.detect(keyframe={"caption": "Find us at monday.com"}) == []


# ── shape ───────────────────────────────────────────────────────────────────


class TestShape:
    def test_one_sentence_can_be_two_offers(self, chips):
        # "Ana will send the terms by Friday" is genuinely an action and a date, and they are
        # two different things to do about it.
        found = chips.detect([said("Ana will send the terms by Friday")])
        assert sorted(kinds(found)) == ["action", "date"]

    def test_a_turn_is_capped(self, chips):
        many = [said(f"Ana will send draft {i}", t0=i * 1000) for i in range(10)]
        assert len(chips.detect(many)) == chips.MAX_PER_TURN

    def test_the_same_offer_twice_in_one_turn_is_one_chip(self, chips):
        found = chips.detect([said("let's go with Postgres", t0=0),
                              said("Let's go with Postgres!", t0=9000)])
        assert len(found) == 1

    def test_the_id_is_derived_not_counted(self, chips):
        # A resume replaying segments, or two clients on one meeting, must produce the same
        # chip on both cards rather than two chips on one.
        chip = chips.detect([said("let's go with Postgres")])[0]
        assert chips.chip_id("m1", chip) == chips.chip_id("m1", chip)
        assert chips.chip_id("m1", chip) != chips.chip_id("m2", chip)

    def test_a_frame_carries_the_proposal_and_nothing_has_run(self, chips):
        chip = chips.detect([said("the draft is due by Friday")])[0]
        body = chips.frame("m1", chip)
        assert body["type"] == "chip"
        assert body["proposal"]["capability"] == "calendar.create_event"
        assert "output" not in body and "accepted" not in body

    def test_a_question_offers_nothing_to_run(self, chips):
        # There is nothing to *do* about a question except answer it, and the card already has
        # a way to ask.
        chip = chips.detect([said("What do you think about the terms?")])[0]
        assert "proposal" not in chips.frame("m1", chip)

    def test_a_junk_segment_does_not_take_the_turn(self, chips):
        # Skipped, not caught: `detect` has no `try` around its loop, so a segment that is not
        # a segment must be recognised rather than raise into a handler. A swallowed error
        # here would be a trigger that silently stopped firing with a green suite.
        assert kinds(chips.detect(["not a dict", None, said("let's go with Postgres")])) \
            == ["decision"]

    def test_detection_does_not_swallow_its_own_errors(self, chips, monkeypatch):
        def angry(*a, **k):
            raise RuntimeError("a trigger is broken")

        monkeypatch.setattr(chips, "_decision", angry)
        with pytest.raises(RuntimeError):
            chips.detect([said("let's go with Postgres")])

    @pytest.mark.parametrize("chip", [
        None, "not a chip", {"kind": "decision", "text": "   "},
        {"kind": "decision"}, {"text": "something"},
        # The guard that matters for a future trigger: a kind the card cannot render.
        {"kind": "vibe", "text": "the room felt tense"},
    ])
    def test_an_unrenderable_chip_is_not_offered(self, chips, chip):
        assert chips.usable(chip) is False

    def test_detection_reads_no_clock_and_no_store(self, chips):
        import inspect

        source = inspect.getsource(chips.detect)
        for forbidden in ("time.", "datetime", "store.", "await "):
            assert forbidden not in source


# ── ask-before-acting ───────────────────────────────────────────────────────


class Decision:
    def __init__(self, tool_id, reason="ok", mode="server"):
        self.resolved_tool_id = tool_id
        self.reason = reason
        self.mode = mode


class Router:
    def __init__(self, tool_id="hp.calendar.create_event", reason="ok"):
        self.tool_id = tool_id
        self.reason = reason
        self.resolved = []
        self.invoked = []

    async def resolve(self, capability, tool_source):
        self.resolved.append((capability, tool_source))
        return Decision(self.tool_id, self.reason)

    async def invoke(self, tool_id, args):
        self.invoked.append((tool_id, args))
        return "done"


class TestAskBeforeActing:
    def _chip(self, chips):
        return chips.detect([said("the draft is due by Friday")])[0]

    def test_showing_a_chip_runs_nothing(self, chips, meeting):
        router = Router()
        chip = self._chip(chips)
        chips.frame("m1", chip)
        assert router.resolved == [] and router.invoked == []

    def test_accepting_resolves_through_the_router_and_runs(self, chips, meeting):
        import app.meetingsense.agent.subagents as subagents

        subagents.approve("m1", ["hp.calendar.create_event"])
        router = Router()
        out = run(chips.accept("m1", self._chip(chips), router=router, tool_source="proj"))
        assert out["ok"] is True
        assert router.resolved == [("calendar.create_event", "proj")]
        assert router.invoked[0][0] == "hp.calendar.create_event"

    def test_an_unapproved_tool_is_refused_even_after_the_user_said_yes(self, chips, meeting):
        # MS24's gate, on the *resolved tool id* rather than the capability: checking the
        # capability would approve a name and run whatever the catalog maps it to today.
        router = Router()
        out = run(chips.accept("m1", self._chip(chips), router=router))
        assert out["ok"] is False
        assert out["needs_approval"] == "hp.calendar.create_event"
        assert router.invoked == []

    def test_approving_the_capability_is_not_approving_the_tool(self, chips, meeting):
        import app.meetingsense.agent.subagents as subagents

        subagents.approve("m1", ["calendar.create_event"])
        router = Router()
        out = run(chips.accept("m1", self._chip(chips), router=router))
        assert out["ok"] is False and router.invoked == []

    def test_a_refusal_is_recorded_rather_than_vanishing(self, chips, meeting):
        run(chips.accept("m1", self._chip(chips), router=Router()))
        rows = meeting.artifacts_for_meeting("m1", kind="chip_action")
        assert [r["detail"].split(":")[0] for r in rows] == ["refused"]

    def test_a_run_is_recorded_too(self, chips, meeting):
        import app.meetingsense.agent.subagents as subagents

        subagents.approve("m1", ["hp.calendar.create_event"])
        run(chips.accept("m1", self._chip(chips), router=Router()))
        rows = meeting.artifacts_for_meeting("m1", kind="chip_action")
        assert [r["detail"].split(":")[0] for r in rows] == ["ran"]

    def test_an_approval_does_not_carry_to_the_next_meeting(self, chips, meeting):
        import app.meetingsense.agent.subagents as subagents

        meeting.create_meeting(conversation_id="c1", meeting_id="m2", started_at=2.0)
        subagents.approve("m1", ["hp.calendar.create_event"])
        router = Router()
        out = run(chips.accept("m2", self._chip(chips), router=router))
        assert out["ok"] is False and router.invoked == []

    def test_a_chip_with_nothing_to_run_says_so(self, chips, meeting):
        chip = chips.detect([said("What do you think about the terms?")])[0]
        router = Router()
        out = run(chips.accept("m1", chip, router=router))
        assert out["ok"] is False and router.resolved == []

    def test_the_routers_own_words_are_forwarded(self, chips, meeting):
        # It knows whether the project has no tools, no matching tool, or no tool source at
        # all, and the user is owed the difference.
        router = Router(tool_id=None, reason="Agent configured with no tools.")
        out = run(chips.accept("m1", self._chip(chips), router=router))
        assert out["reason"] == "Agent configured with no tools."

    def test_a_router_that_raises_is_not_a_crash(self, chips, meeting):
        class Angry:
            async def resolve(self, capability, tool_source):
                raise RuntimeError("forge is down")

        out = run(chips.accept("m1", self._chip(chips), router=Angry()))
        assert out["ok"] is False and "forge is down" in out["reason"]

    def test_a_tool_that_raises_is_recorded_as_failed(self, chips, meeting):
        import app.meetingsense.agent.subagents as subagents

        subagents.approve("m1", ["hp.calendar.create_event"])

        class Angry(Router):
            async def invoke(self, tool_id, args):
                raise RuntimeError("nope")

        out = run(chips.accept("m1", self._chip(chips), router=Angry()))
        assert out["ok"] is False
        rows = meeting.artifacts_for_meeting("m1", kind="chip_action")
        assert [r["detail"].split(":")[0] for r in rows] == ["failed"]

    def test_there_is_no_second_allow_list(self, chips):
        # MS23 settled this: a second resolver is a second allow-list, and one that disagrees
        # with the one Forge enforces is a security control that is wrong half the time.
        import inspect

        source = inspect.getsource(chips.accept)
        for forbidden in ("allowed_tool_ids", "pick_tool_for_capability", "tool_policy"):
            assert forbidden not in source


# ── inside a live meeting ───────────────────────────────────────────────────


class Cfg:
    class flags:
        modes = True

    retention = "text"

    class vision:
        model = ""


class TestInASession:
    @pytest.fixture()
    def live(self, store, monkeypatch):
        import app.meetingsense.session as session_mod

        transport = session_mod.ListTransport()
        session = session_mod.MeetingSession(transport=transport, config=Cfg(),
                                             meeting_id="m1", now=lambda: 100.0)
        session_mod._SESSIONS.clear()
        return session, transport

    def _start(self, session, **extra):
        run(session.start({"type": "start", "conversation_id": "c1", **extra}))

    def test_a_decision_becomes_a_chip_frame(self, live):
        session, transport = live
        self._start(session)
        sent = run(session._maybe_chips([said("let's go with Postgres")]))
        assert [f["type"] for f in sent] == ["chip"]
        assert transport.of_type("chip")[0]["kind"] == "decision"

    def test_the_flag_off_produces_nothing(self, live, monkeypatch):
        session, transport = live

        class Off:
            class flags:
                modes = False
            retention = "text"

        session.config = Off()
        self._start(session)
        assert run(session._maybe_chips([said("let's go with Postgres")])) == []
        assert transport.of_type("chip") == []

    def test_the_same_offer_is_made_once_per_meeting(self, live):
        # Not per turn: the second turn is a different call, and a card that grows a second
        # "we're going with Postgres" chip ten minutes later is a card nobody reads.
        session, _ = live
        self._start(session)
        run(session._maybe_chips([said("let's go with Postgres", t0=0)]))
        assert run(session._maybe_chips([said("Let's go with Postgres.", t0=600_000)])) == []

    def test_a_meeting_is_capped(self, live, chips):
        session, _ = live
        self._start(session)
        for i in range(60):
            run(session._maybe_chips([said(f"let's go with option {i}", t0=i * 1000)]))
        assert len(session.chips) == chips.MAX_PER_MEETING

    def test_names_come_from_the_start_frame(self, live, store):
        # In Participant: MS26 made the trigger set a property of the mode, and `question` is
        # not in Note-taker's — "somebody just asked you something" is the assistant tapping
        # the user on the shoulder, which Note-taker exists not to do.
        session, _ = live
        store.add_artifact("m1", kind="mode", target="participant")
        self._start(session, names=["Ana"])
        sent = run(session._maybe_chips([said("Ana, what is the release date?")]))
        assert [f["kind"] for f in sent] == ["question"]

    def test_with_no_names_second_person_is_the_only_signal(self, live, store):
        session, _ = live
        store.add_artifact("m1", kind="mode", target="participant")
        self._start(session)
        assert run(session._maybe_chips([said("Ana, what is the release date?")])) == []

    def test_the_default_mode_makes_no_question_chip(self, live):
        # The shipped state: no mode set resolves to Note-taker, which offers the note-taking
        # chips and not the shoulder-tap. A behaviour MS25 had and MS26 deliberately narrowed.
        session, _ = live
        self._start(session, names=["Ana"])
        assert run(session._maybe_chips([said("Ana, what do you think?")])) == []
        assert [f["kind"] for f in run(session._maybe_chips([said("let's go with Postgres")]))] \
            == ["decision"]

    def test_a_chip_that_raises_does_not_take_the_meeting(self, live, monkeypatch, chips):
        session, transport = live
        self._start(session)

        def angry(*a, **k):
            raise RuntimeError("down")

        monkeypatch.setattr(chips, "detect", angry)
        assert run(session._maybe_chips([said("let's go with Postgres")])) == []

    def test_the_server_keeps_what_it_offered(self, live):
        # An id crosses the wire, never a chip: a chip carries the arguments a tool will be
        # invoked with, and accepting a body would let the page rewrite what the user thought
        # they were agreeing to.
        session, transport = live
        self._start(session)
        run(session._maybe_chips([said("the draft is due by Friday")]))
        offered = transport.of_type("chip")[0]
        assert session.chips[offered["id"]]["kind"] == "date"

    def test_a_caption_arriving_makes_the_link_chip(self, live, monkeypatch):
        # Through `_caption`, not by calling `_maybe_chips`: a URL is only "on a slide" once
        # something has read the slide, and the caption is the thing that read it. An install
        # with no vision model gets slides and no link chips, which is the honest outcome.
        import app.meetingsense.keyframes as keyframes_mod

        session, transport = live
        self._start(session)

        async def captioned(*a, **k):
            return {"type": "slide", "id": "k1", "t": 5000,
                    "caption": "Docs at https://example.com/x", "reused": False}

        monkeypatch.setattr(keyframes_mod, "caption", captioned)
        run(session._caption("k1", url="blob:x", hash_="h", t_ms=5000))
        assert [f["kind"] for f in transport.of_type("chip")] == ["link"]

    def test_no_caption_means_no_link_chip(self, live, monkeypatch):
        import app.meetingsense.keyframes as keyframes_mod

        session, transport = live
        self._start(session)

        async def uncaptioned(*a, **k):
            return None

        monkeypatch.setattr(keyframes_mod, "caption", uncaptioned)
        run(session._caption("k1", url="blob:x", hash_="h", t_ms=5000))
        assert transport.of_type("chip") == []

    def test_a_spoken_url_makes_no_chip_but_a_captioned_slide_does(self, live):
        session, transport = live
        self._start(session)
        run(session._maybe_chips([said("go to https://example.com/x")]))
        assert transport.of_type("chip") == []
        run(session._maybe_chips([], keyframe={"type": "slide", "t": 5000,
                                               "caption": "Docs: https://example.com/x"}))
        assert [f["kind"] for f in transport.of_type("chip")] == ["link"]


class TestTheWire:
    """`chip_action` carries an id, and an unknown one is answered rather than ignored."""

    @pytest.fixture()
    def routes(self):
        import app.meetingsense.routes as routes_mod

        return routes_mod

    def test_an_unknown_id_is_answered(self, routes, store):
        import app.meetingsense.session as session_mod

        transport = session_mod.ListTransport()
        session = session_mod.MeetingSession(transport=transport, config=Cfg(), meeting_id="m1")
        session.state = session_mod.MeetingState.LIVE
        run(routes._handle_chip_action(session, {"type": "chip_action", "id": "chip_nope"}))
        assert transport.of_type("error")[0]["code"] == "chip_unknown"

    def test_an_accepted_chip_answers_with_a_result(self, routes, store, chips, monkeypatch):
        import app.meetingsense.agent.subagents as subagents
        import app.meetingsense.session as session_mod

        subagents.approve("m1", ["hp.calendar.create_event"])
        monkeypatch.setattr(chips, "router_bridge", lambda: Router())

        transport = session_mod.ListTransport()
        session = session_mod.MeetingSession(transport=transport, config=Cfg(), meeting_id="m1")
        run(session.start({"type": "start", "conversation_id": "c1"}))
        run(session._maybe_chips([said("the draft is due by Friday")]))
        offered = transport.of_type("chip")[0]

        run(routes._handle_chip_action(session, {"type": "chip_action", "id": offered["id"]}))
        result = transport.of_type("chip_result")[0]
        assert result["ok"] is True and result["id"] == offered["id"]

    def test_a_forged_chip_body_is_ignored(self, routes, store, chips, monkeypatch):
        # The trust boundary. The server offered the chip and still has it, so what runs is
        # what was shown. If a body on the wire could stand in for it, whatever is on the page
        # could rewrite the arguments between the offer and the acceptance, and
        # ask-before-acting would be asking about one thing and acting on another.
        import app.meetingsense.agent.subagents as subagents
        import app.meetingsense.session as session_mod

        subagents.approve("m1", ["hp.calendar.create_event"])
        router = Router()
        monkeypatch.setattr(chips, "router_bridge", lambda: router)

        transport = session_mod.ListTransport()
        session = session_mod.MeetingSession(transport=transport, config=Cfg(), meeting_id="m1")
        run(session.start({"type": "start", "conversation_id": "c1"}))
        run(session._maybe_chips([said("the draft is due by Friday")]))
        offered = transport.of_type("chip")[0]

        run(routes._handle_chip_action(session, {
            "type": "chip_action", "id": offered["id"],
            "chip": {"kind": "date", "text": "x", "proposal": {
                "capability": "shell.run", "args": {"cmd": "curl evil.example.com"}}},
        }))
        assert router.resolved == [("calendar.create_event", None)]
        assert router.invoked[0][1] == {"text": "the draft is due by Friday", "when": "by Friday"}

    def test_no_router_on_this_install_is_a_reason_not_a_crash(self, routes, store, chips,
                                                               monkeypatch):
        import app.meetingsense.session as session_mod

        monkeypatch.setattr(chips, "router_bridge", lambda: None)
        transport = session_mod.ListTransport()
        session = session_mod.MeetingSession(transport=transport, config=Cfg(), meeting_id="m1")
        run(session.start({"type": "start", "conversation_id": "c1"}))
        run(session._maybe_chips([said("the draft is due by Friday")]))
        offered = transport.of_type("chip")[0]
        run(routes._handle_chip_action(session, {"type": "chip_action", "id": offered["id"]}))
        assert transport.of_type("chip_result")[0]["ok"] is False
