"""Participant and Presenter, driven end to end (batch MS26, wave W9).

The batch asks for "e2e fixtures per mode", and the fixture is the same recorded meeting every
time: **one window of transcript, replayed through each mode, asserted on what came out.** That
shape is the point. A mode is a policy object and a framing paragraph, and the only way to know
those two are wired to anything is to send the same words into each and watch the modes
disagree — because if they do not disagree, the mode is a label.

The window below is chosen so every mode has something to do with it and no two do the same
thing: it contains a question that names the assistant, a question aimed at the user, a
decision, and a commitment.

| | note-taker | participant | presenter |
|---|---|---|---|
| named question | ignored | **answered aloud** | **queued** |
| question to the user | ignored | **chip + draft** | **queued** |
| decision / action | chip | chip | chip |
| audience queue | — | — | **grows** |

The two behaviours that look alike and are opposites get the most attention: answering to your
own name is speaking to the room, and drafting for the user's name is speaking to the user. A
mode that did the second as the first would be answering, out loud, on behalf of a person the
room believes they are talking to.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class Cfg:
    class flags:
        modes = True

    retention = "text"

    class vision:
        model = ""


# ── the fixture window, replayed into every mode ────────────────────────────

WINDOW = [
    {"t0_ms": 1000, "speaker": "them", "text": "Ana, what did we decide about pricing?"},
    {"t0_ms": 5000, "speaker": "them", "text": "and what do you think about the timeline?"},
    {"t0_ms": 9000, "speaker": "them", "text": "right, we're going with the second option"},
    {"t0_ms": 13_000, "speaker": "me", "text": "Ruslan will send the revised terms"},
]


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


class Asked:
    """A stub `ask` that records every call and answers plainly."""

    def __init__(self, text="we agreed forty a seat"):
        self.calls = []
        self.text = text

    async def __call__(self, meeting_id, question, *, mode=""):
        self.calls.append({"question": question, "mode": mode})
        return {"type": "answer", "text": self.text, "cited": []}


@pytest.fixture()
def meeting(store):
    """A live session with MS26 fully wired, and a mode setter."""
    import app.meetingsense.session as session_mod

    session_mod._SESSIONS.clear()
    asked = Asked()
    transport = session_mod.ListTransport()
    session = session_mod.MeetingSession(transport=transport, config=Cfg(), meeting_id="m1",
                                         ask=asked, now=lambda: 0.0)

    def start(mode="", **extra):
        if mode:
            store.add_artifact("m1", kind="mode", target=mode)
        run(session.start({"type": "start", "conversation_id": "c1",
                           "names": ["Ruslan"], "assistant_names": ["Ana"], **extra}))

    def drive(window=WINDOW):
        run(session._maybe_chips(list(window)))
        run(session._maybe_addressed(list(window)))
        run(session._maybe_queue(list(window)))

    return type("Live", (), {"session": session, "transport": transport, "asked": asked,
                             "start": staticmethod(start), "drive": staticmethod(drive),
                             "store": store})


def kinds(transport, frame_type="chip"):
    return [f["kind"] for f in transport.of_type(frame_type)]


# ── note-taker: the floor, unchanged ────────────────────────────────────────


class TestNoteTaker:
    def test_it_says_nothing_and_answers_nobody(self, meeting):
        # The mode MS23's acceptance is measured in. MS26 must not have given it a voice.
        meeting.start()
        meeting.drive()
        assert meeting.transport.of_type("answer") == []
        assert meeting.transport.of_type("queued") == []
        assert meeting.asked.calls == []

    def test_it_still_offers_the_note_taking_chips(self, meeting):
        meeting.start()
        meeting.drive()
        assert sorted(set(kinds(meeting.transport))) == ["action", "decision"]

    def test_and_not_the_shoulder_tap(self, meeting):
        meeting.start()
        meeting.drive()
        assert "question" not in kinds(meeting.transport)


# ── participant ─────────────────────────────────────────────────────────────


class TestParticipant:
    def test_it_answers_a_question_that_named_it(self, meeting):
        meeting.start("participant")
        meeting.drive()
        answers = meeting.transport.of_type("answer")
        assert len(answers) == 1
        assert answers[0]["addressed_as"] == "Ana"
        assert answers[0]["t0"] == 1000

    def test_the_answer_carries_the_modes_framing(self, meeting):
        # The prompt is wired, not decorative: the mode reaches `ask`, which layers the
        # framing over MS13's system prompt.
        meeting.start("participant")
        meeting.drive()
        spoken = [c for c in meeting.asked.calls if c["mode"] == "participant"]
        assert [c["question"] for c in spoken] == ["Ana, what did we decide about pricing?"]

    def test_a_question_aimed_at_the_user_is_drafted_never_answered(self, meeting):
        # The batch's sharpest line. Answering this out loud is the assistant speaking for the
        # person the room believes it is talking to.
        meeting.start("participant")
        meeting.drive()
        chips = [c for c in meeting.transport.of_type("chip") if c["kind"] == "question"]
        assert len(chips) == 1
        assert chips[0]["text"] == "and what do you think about the timeline?"
        assert chips[0]["draft"] == "we agreed forty a seat"
        # …and it was never spoken.
        assert [a["text"] for a in meeting.transport.of_type("answer")] == \
            ["we agreed forty a seat"]
        assert meeting.transport.of_type("answer")[0]["addressed_as"] == "Ana"

    def test_the_draft_is_asked_for_in_the_draft_framing(self, meeting):
        meeting.start("participant")
        meeting.drive()
        assert [c["mode"] for c in meeting.asked.calls if "timeline" in c["question"]] == \
            ["draft"]

    def test_a_named_question_is_not_also_drafted(self, meeting):
        # "Ana, can you tell us what you think?" is Ana's. Drafting it as well would put two
        # answers on screen for one question.
        meeting.start("participant")
        meeting.drive([{"t0_ms": 0, "speaker": "them",
                        "text": "Ana, can you tell us what you think?"}])
        assert [c["kind"] for c in meeting.transport.of_type("chip")] == []
        assert len(meeting.transport.of_type("answer")) == 1

    def test_a_question_the_user_asked_is_neither(self, meeting):
        meeting.start("participant")
        meeting.drive([{"t0_ms": 0, "speaker": "me", "text": "Ana, what do you think?"}])
        assert meeting.transport.of_type("answer") == []
        assert meeting.transport.of_type("chip") == []

    def test_with_no_assistant_names_it_answers_nobody(self, meeting):
        # The narrow default. Guessing gets you answering to somebody else's name in front of
        # them, which is not a bug you get to explain away.
        meeting.start("participant", assistant_names=[])
        meeting.drive()
        assert meeting.transport.of_type("answer") == []

    def test_one_answer_per_window(self, meeting):
        meeting.start("participant")
        meeting.drive([{"t0_ms": 0, "speaker": "them", "text": "Ana, what is the price?"},
                       {"t0_ms": 1, "speaker": "them", "text": "Ana, and the date?"}])
        assert len(meeting.transport.of_type("answer")) == 1

    def test_nothing_is_queued(self, meeting):
        meeting.start("participant")
        meeting.drive()
        assert meeting.transport.of_type("queued") == []

    def test_an_answer_with_nothing_in_it_is_not_spoken(self, meeting):
        # A model that returns "" has failed to answer, and an empty `answer` frame on the
        # card reads as the assistant being cut off mid-sentence.
        meeting.asked.text = "   "
        meeting.start("participant")
        meeting.drive()
        assert meeting.transport.of_type("answer") == []

    def test_with_no_names_the_policy_store_is_not_even_read(self, meeting, monkeypatch):
        # The fast path, and it is not decoration: `mode()` reads SQLite, and this runs on
        # every audio chunk of every meeting. A meeting that declared no names for the
        # assistant can never be addressed, so asking the store is work with one answer.
        import app.meetingsense.agent.subagents as subagents

        meeting.start("participant", assistant_names=[])
        reads = []
        monkeypatch.setattr(subagents, "resolve_mode",
                            lambda *a, **k: reads.append(1) or {"mode": "participant"})
        run(meeting.session._maybe_addressed(list(WINDOW)))
        assert reads == []

    def test_drafting_is_refused_by_a_policy_that_does_not_answer_to_its_name(self, meeting):
        # Defence in depth: no shipped mode both offers a `question` chip and refuses to be
        # addressed, so the router never builds this state. Driven directly, which is the only
        # way a second gate is testable — and the whole reason to have one.
        from app.meetingsense.agent import modes

        meeting.start("participant")
        silent = modes.Mode(name="x", label="X", description="", addressed=False)
        chip = {"kind": "question", "text": "and what do you think?"}
        out = run(meeting.session._participate([chip], silent))
        assert out == [chip] and "draft" not in out[0]


# ── presenter ───────────────────────────────────────────────────────────────


class TestPresenter:
    def test_every_question_is_queued_and_none_answered(self, meeting):
        # The mode's one hard rule. Interrupting a presentation to answer somebody in it is
        # worse than the question being missed.
        meeting.start("presenter")
        meeting.drive()
        assert meeting.transport.of_type("answer") == []
        assert meeting.asked.calls == []
        queued = [f["text"] for f in meeting.transport.of_type("queued")]
        assert queued == ["Ana, what did we decide about pricing?",
                          "and what do you think about the timeline?"]

    def test_a_question_that_named_the_assistant_is_queued_too(self, meeting):
        # No distinction, on purpose: "who was that for" is a judgement the user makes in two
        # seconds when they look at the list, and answering is not recoverable.
        meeting.start("presenter")
        meeting.drive()
        from app.meetingsense.agent import presenter

        assert "Ana, what did we decide about pricing?" in \
            [q["text"] for q in presenter.queued("m1")]

    def test_the_queue_survives_and_counts(self, meeting):
        meeting.start("presenter")
        meeting.drive()
        assert [f["waiting"] for f in meeting.transport.of_type("queued")] == [1, 2]

    def test_it_makes_no_question_chip(self, meeting):
        meeting.start("presenter")
        meeting.drive()
        assert "question" not in kinds(meeting.transport)

    def test_it_still_takes_notes(self, meeting):
        meeting.start("presenter")
        meeting.drive()
        assert sorted(set(kinds(meeting.transport))) == ["action", "decision"]

    def test_the_users_own_questions_are_not_queued(self, meeting):
        # The queue is the *audience*. A presenter's own rhetorical question — "so what does
        # that mean for us?" — is part of the talk, and queueing it hands them back their own
        # words to answer.
        meeting.start("presenter")
        meeting.drive([{"t0_ms": 0, "speaker": "me", "text": "so what does that mean for us?"}])
        assert meeting.transport.of_type("queued") == []

    def test_statements_from_the_floor_are_not_queued(self, meeting):
        meeting.start("presenter")
        meeting.drive([{"t0_ms": 0, "speaker": "them", "text": "that slide was helpful"}])
        assert meeting.transport.of_type("queued") == []


# ── the presenter's deck and clock ──────────────────────────────────────────


DECK = [{"title": "Where we are", "minutes": 5},
        {"title": "The numbers", "minutes": 10},
        {"title": "What we need", "minutes": 5}]


class TestDeck:
    @pytest.fixture()
    def presenter(self, store):
        import app.meetingsense.agent.presenter as module

        store.create_meeting(conversation_id="c1", meeting_id="m1", started_at=1.0)
        return module

    def test_a_deck_is_attached_and_read_back(self, presenter):
        assert presenter.set_deck("m1", DECK) == DECK
        assert presenter.deck("m1") == DECK

    def test_the_last_deck_attached_wins(self, presenter):
        presenter.set_deck("m1", DECK)
        presenter.set_deck("m1", [{"title": "One slide", "minutes": 20}])
        assert [s["title"] for s in presenter.deck("m1")] == ["One slide"]

    def test_a_section_with_no_title_is_dropped(self, presenter):
        # A pacing remark naming an empty string tells the user nothing and looks broken.
        assert presenter.set_deck("m1", [{"title": "  ", "minutes": 5},
                                         {"title": "Real", "minutes": 5}]) == \
            [{"title": "Real", "minutes": 5.0}]

    def test_a_deck_of_nothing_is_not_stored(self, presenter):
        assert presenter.set_deck("m1", [{"minutes": 5}, "junk", None]) == []
        assert presenter.deck("m1") == []

    def test_no_deck_is_no_deck(self, presenter):
        assert presenter.deck("m1") == []

    def test_planned_times_are_cumulative(self, presenter):
        assert presenter.planned_ms(DECK) == [300_000, 900_000, 1_200_000]


class TestPacing:
    @pytest.fixture()
    def presenter(self, store):
        import app.meetingsense.agent.presenter as module

        return module

    def test_on_time_says_nothing(self, presenter):
        assert presenter.pace(DECK, index=0, elapsed_ms=280_000) is None

    def test_a_small_drift_says_nothing(self, presenter):
        # Every presenter drifts. Being told so is a clock, and the user has one.
        assert presenter.pace(DECK, index=0, elapsed_ms=300_000 + 60_000) is None

    def test_behind_is_named_with_the_section(self, presenter):
        remark = presenter.pace(DECK, index=1, elapsed_ms=900_000 + 200_000)
        assert remark == "3 minutes behind on section 2 of 3, 'The numbers'."

    def test_ahead_is_named_too(self, presenter):
        # On the last section five minutes before it was due to start.
        assert presenter.pace(DECK, index=2, elapsed_ms=600_000) == \
            "5 minutes ahead on section 3 of 3, 'What we need'."

    def test_inside_a_section_is_on_time_however_long_it_is(self, presenter):
        # The whole of the fix: a section is a window. Anywhere between its planned start and
        # its planned end is exactly where the presenter meant to be.
        for elapsed in (900_000, 1_000_000, 1_200_000):
            assert presenter.pace(DECK, index=2, elapsed_ms=elapsed) is None

    def test_it_compares_against_the_section_end_not_its_start(self, presenter):
        # Being early inside a long section is not "ahead", it is the middle of that section.
        assert presenter.pace(DECK, index=1, elapsed_ms=400_000) is None

    def test_an_empty_deck_says_nothing(self, presenter):
        assert presenter.pace([], index=0, elapsed_ms=10_000_000) is None

    def test_an_index_off_the_end_says_nothing(self, presenter):
        assert presenter.pace(DECK, index=9, elapsed_ms=10_000_000) is None
        assert presenter.pace(DECK, index=-1, elapsed_ms=10_000_000) is None

    def test_a_deck_with_no_timings_says_nothing_about_time(self, presenter):
        # A list of titles is useful for saying where you are and no basis for saying whether
        # you are late.
        titles = [{"title": "One", "minutes": 0}, {"title": "Two", "minutes": 0}]
        assert presenter.pace(titles, index=0, elapsed_ms=10_000_000) is None


class TestQueue:
    @pytest.fixture()
    def presenter(self, store):
        import app.meetingsense.agent.presenter as module

        store.create_meeting(conversation_id="c1", meeting_id="m1", started_at=1.0)
        return module

    def test_a_question_is_held(self, presenter):
        assert presenter.enqueue("m1", "what about latency?", t0=1000) is True
        assert [q["text"] for q in presenter.queued("m1")] == ["what about latency?"]

    def test_the_same_question_twice_is_one(self, presenter):
        # A question asked twice from the floor is what happens when the first was not heard.
        presenter.enqueue("m1", "what about latency?")
        assert presenter.enqueue("m1", "What about latency?") is False
        assert len(presenter.queued("m1")) == 1

    def test_an_empty_question_is_not_held(self, presenter):
        assert presenter.enqueue("m1", "   ") is False

    def test_answering_takes_it_off(self, presenter):
        presenter.enqueue("m1", "what about latency?")
        assert presenter.mark_answered("m1", "What about latency?") is True
        assert presenter.queued("m1") == []

    def test_answering_records_rather_than_deletes(self, presenter):
        # What was asked and when it was dealt with is what an after-the-fact read is for.
        presenter.enqueue("m1", "what about latency?")
        presenter.mark_answered("m1", "what about latency?")
        rows = presenter.store.artifacts_for_meeting("m1", kind="audience_question")
        assert len(rows) == 2

    def test_answering_something_never_asked_does_nothing(self, presenter):
        assert presenter.mark_answered("m1", "never asked") is False

    def test_a_question_can_be_asked_again_after_it_was_answered(self, presenter):
        presenter.enqueue("m1", "what about latency?")
        presenter.mark_answered("m1", "what about latency?")
        assert presenter.enqueue("m1", "what about latency?") is True
        assert len(presenter.queued("m1")) == 1

    def test_the_queue_is_capped(self, presenter):
        for i in range(presenter.MAX_QUEUED + 5):
            presenter.enqueue("m1", f"question number {i}")
        assert len(presenter.queued("m1")) == presenter.MAX_QUEUED

    def test_it_is_per_meeting(self, presenter):
        presenter.store.create_meeting(conversation_id="c1", meeting_id="m2", started_at=2.0)
        presenter.enqueue("m1", "what about latency?")
        assert presenter.queued("m2") == []

    def test_deleting_the_meeting_takes_the_queue(self, presenter):
        presenter.enqueue("m1", "what about latency?")
        presenter.store.delete_meeting("m1")
        assert presenter.queued("m1") == []
