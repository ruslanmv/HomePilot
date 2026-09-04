"""Asking about a meeting (batch MS13, decision D9 tier 3).

One claim carries this batch, and it is the reason D9 exists: **the full transcript never goes
into the prompt.** A two-hour meeting is roughly 20,000 words. A prompt built from it is slow,
expensive, and on a local model with an 8k window simply truncated somewhere arbitrary — which
produces an answer that is confidently wrong about exactly the part that got cut, with nothing
in the output to say so.

So the test that matters builds a two-hour meeting and asserts the prompt stays inside the
budget while still containing the sentence that answers the question. Both halves are needed: a
prompt that is small because it dropped the answer is not a success.

The second theme is citations. A model that invents "at 00:42:15" about a meeting that ran
twelve minutes is worse than one that says it does not know, because the invention is only
checkable by somebody who already has the answer. Every timestamp offered to the model comes
from a real row, and the frame reports which of them the answer actually used.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("MEETINGSENSE_ENABLED", "STT_BASE_URL", "WHISPER_MODEL"):
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.ask as ask
        import app.meetingsense.routes as routes
        import app.meetingsense.store as store

        self.ask = ask
        self.routes = routes
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
    return mods


class Recorder:
    """A model that answers from a script and remembers the prompt it was given."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    async def __call__(self, messages, **kwargs):
        self.calls.append(messages)
        return self.answers.pop(0) if self.answers else "I don't know."

    @property
    def prompt(self):
        return "\n".join(m["content"] for m in self.calls[-1])


def seg(t0, text, speaker="them"):
    return {"t0_ms": t0, "t1_ms": t0 + 2000, "text": text, "speaker": speaker}


MEETING_ROWS = [
    seg(0, "morning everyone thanks for joining"),
    seg(10_000, "first item is the October launch date"),
    seg(30_000, "legal needs to sign off before we announce"),
    seg(60_000, "Marina is chasing legal this week"),
    seg(600_000, "anything else before we wrap up"),
    seg(610_000, "no I think that is everything"),
]


def seed(modules, rows=MEETING_ROWS, *, recap="", captions=()):
    meeting_id = modules.store.create_meeting(conversation_id="c", title="Q3", retention="text")
    modules.store.add_segments(meeting_id, [{**r, "seq": i + 1} for i, r in enumerate(rows)])
    for i, (t_ms, caption) in enumerate(captions):
        kid = modules.store.add_keyframe(meeting_id, t_ms=t_ms, url=f"/files/s{i}.png")
        modules.store.set_keyframe_caption(kid, caption)
    if recap:
        modules.store.save_notes(meeting_id, {"recap": recap, "decisions": [], "actions": [], "questions": []})
    return meeting_id


# ── the budget, and what it must not drop ───────────────────────────────────


class TestTheTranscriptNeverGoesIn:
    def _long_meeting(self):
        """Two hours, and **every segment matches the question**.

        That last part is the point, and the first version of this fixture did not have it: the
        segments were about scheduling, the question was about the budget, and almost nothing
        matched. The prompt was then small because retrieval found nothing — so the test passed
        with the budget enforcement removed *and* with the k limit removed. It was measuring the
        fixture, not the code.

        With every segment a candidate, k decides how many survive and the budget decides how
        much of that fits, which is what the batch actually promises.

        The filler shares *one* term with the question and the answering sentence shares both,
        which is what makes this a fair test of ranking rather than a rigged one. An earlier
        version had every segment share both terms, and then the shortest filler outscored the
        answer — a true statement about keyword search, and not a useful fixture. Ranking a
        question whose every term appears everywhere is what MS15's vector search is for.
        """
        rows = [seg(i * 4_000, f"a routine budget discussion point number {i} continues") for i in range(1800)]
        rows[600] = seg(2_400_000, "we agreed the budget ceiling is four hundred thousand")
        return rows

    def test_a_two_hour_meeting_stays_inside_the_budget(self, modules):
        # The reason D9 exists. Without this the prompt is 20,000 words, and a local model
        # truncates it somewhere arbitrary — producing an answer confidently wrong about the
        # part that got cut, with nothing in the output to say so.
        # Two bounds hold this, and they are tested in different places: `k` is the primary one
        # and is what this fixture exercises, while the budget trim is the backstop for a
        # meeting whose twelve best segments are unusually long — that is what TestTrimOrder
        # covers. Removing `k` fails this test; removing the trim fails those.
        meeting_id = seed(modules, self._long_meeting(), recap="A long planning meeting.")
        recorder = Recorder("The ceiling is four hundred thousand [00:40:00].")
        run(modules.ask.answer(meeting_id, "what is the budget ceiling?", call=recorder))
        assert modules.ask.estimate_tokens(recorder.prompt) <= modules.ask.TOKEN_BUDGET

    def test_and_still_contains_the_sentence_that_answers_it(self, modules):
        # The other half. A prompt that is small because it dropped the answer is not a success,
        # and a budget test on its own would pass for one.
        meeting_id = seed(modules, self._long_meeting(), recap="A long planning meeting.")
        recorder = Recorder("Four hundred thousand.")
        run(modules.ask.answer(meeting_id, "what is the budget ceiling?", call=recorder))
        assert "four hundred thousand" in recorder.prompt

    def test_the_bulk_of_the_meeting_is_absent(self, modules):
        meeting_id = seed(modules, self._long_meeting())
        recorder = Recorder("...")
        run(modules.ask.answer(meeting_id, "what is the budget ceiling?", call=recorder))
        # 1800 segments went in; a handful come out.
        assert recorder.prompt.count("routine discussion item") < 30

    def test_no_more_than_k_segments_are_retrieved(self, modules):
        rows = [seg(i * 5_000, f"we should discuss legal item {i}") for i in range(200)]
        assert len(modules.ask.retrieve(rows, [], "legal")) == modules.ask.MAX_RETRIEVED

    def test_the_limit_is_respected_when_lowered(self, modules):
        rows = [seg(i * 5_000, f"legal item {i}") for i in range(50)]
        assert len(modules.ask.retrieve(rows, [], "legal", limit=3)) == 3


class TestTrimOrder:
    """D9's priority, made executable: retrieval first, verbatim second, the recap never."""

    def _rows(self, n, prefix):
        return [{"t0_ms": i * 1000, "text": f"{prefix} sentence number {i} with several words in it"}
                for i in range(n)]

    def test_the_recap_survives_a_budget_that_drops_everything_else(self, modules):
        # The recap is the only tier representing the parts of the meeting nothing else can
        # reach. Dropping it for a transcript fragment trades two hours for thirty seconds.
        messages = modules.ask.build_prompt(
            "what happened?",
            recap="THE RECAP SURVIVES.",
            verbatim_rows=self._rows(40, "verbatim"),
            retrieved_rows=self._rows(40, "retrieved"),
            budget=60,
        )
        body = messages[1]["content"]
        assert "THE RECAP SURVIVES." in body
        assert "Question: what happened?" in body

    def test_retrieval_is_trimmed_before_the_verbatim_window(self, modules):
        messages = modules.ask.build_prompt(
            "what happened?",
            recap="short",
            verbatim_rows=self._rows(3, "verbatim"),
            retrieved_rows=self._rows(30, "retrieved"),
            budget=90,
        )
        body = messages[1]["content"]
        assert "verbatim" in body
        assert body.count("retrieved") < 30

    def test_the_oldest_retrieved_row_goes_first(self, modules):
        # The newest is likeliest to be what the question is about; trimming from the end would
        # strip the context nearest the asking.
        rows = [
            {"t0_ms": 0, "text": "OLDEST " + "padding " * 20},
            {"t0_ms": 90_000, "text": "NEWEST " + "padding " * 20},
        ]
        # The budget is measured rather than guessed: big enough for one row, too small for
        # two. A hand-picked number here silently becomes "too small for either", and the test
        # then passes for the wrong reason — neither row survives, and "OLDEST not in body" is
        # true because nothing is.
        both = modules.ask.build_prompt("q", recap="r", retrieved_rows=rows)[1]["content"]
        one = modules.ask.build_prompt("q", recap="r", retrieved_rows=rows[1:])[1]["content"]
        budget = (modules.ask.estimate_tokens(one) + modules.ask.estimate_tokens(both)) // 2

        body = modules.ask.build_prompt("q", recap="r", retrieved_rows=rows, budget=budget)[1]["content"]
        assert "NEWEST" in body
        assert "OLDEST" not in body

    def test_a_prompt_that_fits_is_left_alone(self, modules):
        rows = [{"t0_ms": 0, "text": "brief"}]
        body = modules.ask.build_prompt("q", recap="r", retrieved_rows=rows, verbatim_rows=rows)[1]["content"]
        assert body.count("brief") == 2

    def test_the_question_is_always_present(self, modules):
        # However hard the trim, the model has to know what it was asked.
        body = modules.ask.build_prompt(
            "the question", recap="r", retrieved_rows=self._rows(100, "x"), budget=1
        )[1]["content"]
        assert "the question" in body


# ── retrieval ───────────────────────────────────────────────────────────────


class TestRetrieval:
    def test_it_finds_the_matching_segment(self, modules):
        rows = modules.ask.retrieve(MEETING_ROWS, [], "who is chasing legal?")
        assert any("Marina is chasing legal" in r["text"] for r in rows)

    def test_it_ignores_segments_with_nothing_in_common(self, modules):
        rows = modules.ask.retrieve(MEETING_ROWS, [], "legal")
        assert not any("morning everyone" in r["text"] for r in rows)

    def test_a_question_of_only_stop_words_retrieves_nothing(self, modules):
        # Better than returning the whole meeting ranked by noise.
        assert modules.ask.retrieve(MEETING_ROWS, [], "what is it") == []

    def test_question_words_are_not_stopped(self, modules):
        # "who", "when" and "why" are exactly what makes a meeting question specific, so an
        # aggressive stop list would throw away the signal.
        assert "who" in modules.ask.keywords("who is chasing legal")

    def test_results_come_back_in_time_order_not_score_order(self, modules):
        # A model reading an answer out of fragments does better when they are in the order
        # they were said, and so does a reader checking a citation.
        rows = [seg(50_000, "legal legal legal"), seg(10_000, "legal sign-off needed")]
        out = modules.ask.retrieve(rows, [], "legal")
        assert [r["t0_ms"] for r in out] == [10_000, 50_000]

    def test_a_segment_repeating_a_word_does_not_beat_one_covering_the_question(self, modules):
        # Distinct terms, not occurrences: rewarding repetition surfaces the rambling parts of
        # a meeting over the decisive ones.
        rambling = "legal legal legal legal legal"
        decisive = "legal sign-off is needed before the October launch"
        assert modules.ask.score(decisive, ["legal", "october"]) > modules.ask.score(rambling, ["legal", "october"])

    def test_slide_captions_are_searched_too(self, modules):
        rows = modules.ask.retrieve([], [{"t_ms": 5_000, "caption": "Budget ceiling: 400k"}], "budget")
        assert rows and rows[0]["kind"] == "slide"

    def test_an_uncaptioned_slide_is_not_a_result(self, modules):
        assert modules.ask.retrieve([], [{"t_ms": 1, "caption": None}], "budget") == []

    def test_the_verbatim_window_is_not_retrieved_twice(self, modules):
        # On a short meeting the same sentence appearing in both tiers is most of the budget.
        rows = [seg(0, "legal early"), seg(100_000, "legal late")]
        out = modules.ask.retrieve(rows, [], "legal", exclude_after_ms=50_000)
        assert [r["t0_ms"] for r in out] == [0]


class TestVerbatimWindow:
    def test_it_takes_the_last_ninety_seconds(self, modules):
        rows = modules.ask.verbatim(MEETING_ROWS, now_ms=610_000)
        assert [r["t0_ms"] for r in rows] == [600_000, 610_000]

    def test_a_short_meeting_is_entirely_verbatim(self, modules):
        rows = [seg(0, "a"), seg(1000, "b")]
        assert len(modules.ask.verbatim(rows, now_ms=2000)) == 2


# ── the answer ──────────────────────────────────────────────────────────────


class TestAnswer:
    def test_it_returns_an_answer_frame(self, modules):
        meeting_id = seed(modules)
        frame = run(modules.ask.answer(meeting_id, "who chases legal?", call=Recorder("Marina does.")))
        assert frame["type"] == "answer"
        assert frame["text"] == "Marina does."

    def test_it_reports_the_citations_the_answer_actually_used(self, modules):
        # So a client can render them as links, and a test can check nothing else was cited.
        meeting_id = seed(modules)
        recorder = Recorder("Marina is chasing legal [00:01:00].")
        frame = run(modules.ask.answer(meeting_id, "who chases legal?", call=recorder))
        assert frame["cited"] == ["00:01:00"]

    def test_a_timestamp_the_model_invented_is_not_reported_as_a_citation(self, modules):
        # The frame says what was *offered and used*, never what the model made up. A citation
        # to 00:42:15 in a twelve-minute meeting is only checkable by somebody who already has
        # the answer.
        meeting_id = seed(modules)
        recorder = Recorder("It was decided at [00:42:15].")
        frame = run(modules.ask.answer(meeting_id, "who chases legal?", call=recorder))
        assert frame["cited"] == []

    def test_the_system_prompt_forbids_inventing_one(self, modules):
        assert "Never invent a timestamp" in modules.ask.ASK_SYSTEM

    def test_the_recap_reaches_the_prompt(self, modules):
        meeting_id = seed(modules, recap="The launch slipped to October.")
        recorder = Recorder("October.")
        run(modules.ask.answer(meeting_id, "when is the launch?", call=recorder))
        assert "The launch slipped to October." in recorder.prompt

    def test_an_empty_question_is_refused_without_calling_the_model(self, modules):
        recorder = Recorder("should not be called")
        frame = run(modules.ask.answer(seed(modules), "   ", call=recorder))
        assert frame["error"] == "empty_question"
        assert recorder.calls == []

    def test_a_model_that_raises_answers_rather_than_propagating(self, modules):
        # On the WebSocket path the alternative is a dropped meeting.
        async def boom(messages, **kwargs):
            raise RuntimeError("model gone")

        frame = run(modules.ask.answer(seed(modules), "anything?", call=boom))
        assert frame["error"] == "answer_failed"
        assert frame["text"] == ""

    def test_a_meeting_with_nothing_in_it_still_answers(self, modules):
        meeting_id = modules.store.create_meeting(conversation_id="c", retention="text")
        frame = run(modules.ask.answer(meeting_id, "what happened?", call=Recorder("Nothing was recorded.")))
        assert frame["type"] == "answer"
        assert frame["sources"] == 0


# ── the routes ──────────────────────────────────────────────────────────────


class TestAskRoute:
    @pytest.fixture()
    def client(self, modules):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(modules.routes.router)
        return TestClient(app)

    @pytest.fixture()
    def enabled(self, monkeypatch):
        monkeypatch.setenv("MEETINGSENSE_ENABLED", "true")

    def test_it_answers_a_finished_meeting(self, client, enabled, modules, monkeypatch):
        import app.meetingsense.notes_engine as notes_engine

        monkeypatch.setattr(notes_engine, "call_model", Recorder("Marina is chasing legal [00:01:00]."))
        meeting_id = seed(modules)
        body = client.post(f"/v1/meetingsense/{meeting_id}/ask", json={"text": "who chases legal?"}).json()
        assert body["text"].startswith("Marina")
        assert body["cited"] == ["00:01:00"]

    def test_an_empty_question_is_a_400(self, client, enabled, modules):
        response = client.post(f"/v1/meetingsense/{seed(modules)}/ask", json={"text": "  "})
        assert response.status_code == 400

    def test_a_missing_meeting_is_a_404(self, client, enabled):
        assert client.post("/v1/meetingsense/nope/ask", json={"text": "q"}).status_code == 404

    def test_it_is_a_404_while_the_flag_is_off(self, client, modules, monkeypatch):
        # Stated rather than inherited — see the note in `test_agent_graph.py`. MS30 made the
        # feature reachable by default, so "while the flag is off" is now a premise this test
        # has to set up rather than one it happens to be handed.
        monkeypatch.setenv("MEETINGSENSE_ENABLED", "false")
        response = client.post(f"/v1/meetingsense/{seed(modules)}/ask", json={"text": "q"})
        assert response.status_code == 404


class TestAskOnTheSocket:
    def test_a_live_question_is_answered_on_the_same_socket(self, modules, monkeypatch):
        # No second round trip through HTTP for a question asked mid-meeting.
        import app.meetingsense.notes_engine as notes_engine
        import app.meetingsense.session as session_mod

        monkeypatch.setattr(notes_engine, "call_model", Recorder("Marina."))
        session = session_mod.MeetingSession(
            transport=session_mod.ListTransport(),
            config=modules.routes.load_config(),
            now=lambda: 1000.0,
        )
        run(session.start({"conversation_id": "c"}))
        run(modules.routes._handle_ask(session, {"type": "ask", "text": "who chases legal?"}))
        assert session.transport.of_type("answer")

    def test_the_window_follows_the_session_clock_not_the_last_segment(self, modules, monkeypatch):
        # A question asked during a silence is still about *now*. Taking the last segment's
        # time would slide the verbatim window backwards every time somebody stopped talking.
        import app.meetingsense.notes_engine as notes_engine
        import app.meetingsense.session as session_mod

        seen = {}

        async def capture(meeting_id, question, **kwargs):
            seen.update(kwargs)
            return {"type": "answer", "text": "", "cited": []}

        monkeypatch.setattr(notes_engine, "call_model", Recorder("x"))
        monkeypatch.setattr(modules.routes.ask_mod, "answer", capture)

        clock = {"t": 1000.0}
        session = session_mod.MeetingSession(
            transport=session_mod.ListTransport(),
            config=modules.routes.load_config(),
            now=lambda: clock["t"],
        )
        run(session.start({"conversation_id": "c"}))
        clock["t"] = 1300.0  # five minutes of meeting, some of it silent
        run(modules.routes._handle_ask(session, {"text": "anything?"}))
        assert seen["now_ms"] == 300_000
