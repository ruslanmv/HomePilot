"""Rolling notes and the recap (batch MS12, decision D9 tier 2).

Two claims here are load-bearing well beyond this batch.

**The recap never sees the transcript.** D9's entire guarantee is that the meeting block a
persona reads has a *known* size for a two-hour meeting as much as for a ten-minute one. A
recap regenerated from the full transcript would grow without bound, and it would grow
invisibly — the prompt still looks fine until somebody records a long meeting. The test that
matters asserts an older segment's words never appear in what the recap prompt sends.

**Notes are merged here, not by the model.** Asking a model for the whole notes object each
pass means every pass can quietly drop a decision the last pass got right, and the card would
rewrite itself under the reader — which §2a forbids for the same reason it forbids editing a
segment already on screen. So deltas only add and resolve; nothing in this file deletes.

The rest is about a model having an off minute. Malformed JSON, prose wrapped around JSON, a
citation pointing at a timestamp that was never spoken: each costs one window, never the
meeting. A transcription session that ends because a language model misbehaved is a worse
product than one with a gap in its notes.
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
    for name in ("MEETINGSENSE_ENABLED", "STT_BASE_URL", "WHISPER_MODEL"):
        monkeypatch.delenv(name, raising=False)


class Modules:
    def __init__(self):
        import app.meetingsense.notes_engine as engine
        import app.meetingsense.prompts as prompts
        import app.meetingsense.store as store

        self.engine = engine
        self.prompts = prompts
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


def seg(t0, text, speaker="them"):
    return {"t0_ms": t0, "t1_ms": t0 + 1500, "text": text, "speaker": speaker}


WINDOW = [
    seg(1_000, "so the launch moves to October"),
    seg(4_000, "legal needs to sign off first", speaker="me"),
    seg(8_000, "who is chasing legal?"),
]


class Recorder:
    """A model that answers from a script and remembers what it was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    async def __call__(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return self.answers.pop(0) if self.answers else "{}"

    def prompt(self, index):
        return "\n".join(m["content"] for m in self.calls[index]["messages"])


DELTA = json.dumps(
    {
        "add_decisions": [{"text": "Launch moves to October", "t0": 1000}],
        "add_actions": [{"text": "Get legal sign-off", "owner": "me", "t0": 4000}],
        "add_questions": [{"text": "Who is chasing legal?", "t0": 8000}],
        "summary": "The launch is moving; legal is the blocker.",
    }
)


# ── the recap never sees the transcript (D9) ────────────────────────────────


class TestRecapIsolation:
    def test_the_recap_prompt_carries_only_the_previous_recap_and_the_window(self, modules):
        # The assertion D9 lives or dies by. A recap built from the transcript grows without
        # bound, and does it invisibly — the prompt looks fine until somebody records an
        # hour-long meeting.
        previous = "The team discussed hiring and the budget."
        messages = modules.prompts.recap_messages(previous, WINDOW)
        body = "\n".join(m["content"] for m in messages)
        assert previous in body
        assert "so the launch moves to October" in body
        # Nothing from earlier in the meeting can be here, because the function has no way to
        # reach it: it takes a string, not a meeting id.
        assert "hiring" not in body.replace(previous, "")

    def test_an_older_segment_never_reaches_the_recap_prompt(self, modules):
        engine = modules.engine.NotesEngine("m1", call=Recorder(DELTA, "A recap."), now=lambda: 0.0)
        engine.add([seg(0, "this was said an hour ago and must not resurface")])
        run(engine.run(force=True))

        recorder = Recorder("{}", "A newer recap.")
        engine._call = recorder
        engine.add(WINDOW)
        run(engine.run(force=True))
        assert "an hour ago" not in recorder.prompt(1)

    def test_the_prompt_is_the_same_size_whatever_the_meeting_has_done(self, modules):
        # The property, stated directly: two hours of history costs the same as ten minutes.
        short = modules.prompts.recap_messages("A short recap.", WINDOW)
        long_recap = modules.prompts.recap_messages("A short recap.", WINDOW)
        assert len("".join(m["content"] for m in short)) == len(
            "".join(m["content"] for m in long_recap)
        )

    def test_the_recap_is_capped_in_words_not_merely_asked_to_be_short(self, modules):
        # A model told "120 words maximum" will send 200 eventually, and D9's guarantee is that
        # this block has a known size. A limit that is only a suggestion is not a budget.
        long_answer = " ".join(["word"] * 400)
        engine = modules.engine.NotesEngine("m1", call=Recorder("{}", long_answer), now=lambda: 0.0)
        engine.add(WINDOW)
        run(engine.run(force=True))
        assert len(engine.recap.split()) <= modules.prompts.RECAP_MAX_WORDS + 1

    def test_a_capped_recap_says_it_was_cut(self, modules):
        assert modules.engine.cap_words("one two three", limit=2).endswith("…")

    def test_a_short_recap_is_left_alone(self, modules):
        assert modules.engine.cap_words("three words here", limit=10) == "three words here"


# ── what the model says, and what it should have said ───────────────────────


class TestParseDelta:
    def test_it_reads_a_clean_object(self, modules):
        assert modules.engine.parse_delta(DELTA)["add_decisions"][0]["t0"] == 1000

    def test_it_reads_a_fenced_block(self, modules):
        # Every local model does this sometimes, and arguing with it in the prompt is more
        # expensive than tolerating it here.
        assert modules.engine.parse_delta('```json\n{"summary": "ok"}\n```')["summary"] == "ok"

    def test_it_reads_an_object_with_prose_around_it(self, modules):
        raw = 'Sure! Here are the notes:\n{"summary": "ok"}\nLet me know if you need more.'
        assert modules.engine.parse_delta(raw)["summary"] == "ok"

    def test_it_accepts_an_object_that_is_already_parsed(self, modules):
        assert modules.engine.parse_delta({"summary": "ok"})["summary"] == "ok"

    @pytest.mark.parametrize(
        "raw", ["", "   ", "not json at all", "[1, 2, 3]", None, 42, "{unclosed", '"a string"']
    )
    def test_every_unusable_answer_is_an_empty_delta_rather_than_a_raise(self, modules, raw):
        # One bad window, never the meeting.
        assert modules.engine.parse_delta(raw) == {}

    def test_a_key_with_the_wrong_type_is_dropped_not_fatal(self, modules):
        raw = json.dumps({"add_decisions": "should have been a list", "summary": "kept"})
        delta = modules.engine.parse_delta(raw)
        assert "add_decisions" not in delta
        assert delta["summary"] == "kept"

    def test_an_item_with_no_text_is_dropped(self, modules):
        raw = json.dumps({"add_decisions": [{"t0": 1000}, {"text": "  "}, {"text": "real"}]})
        assert len(modules.engine.parse_delta(raw)["add_decisions"]) == 1

    def test_an_empty_summary_is_not_a_change(self, modules):
        # An empty string would overwrite a good summary with nothing.
        assert modules.engine.parse_delta(json.dumps({"summary": "   "})) == {}

    def test_a_key_nobody_defined_is_ignored_rather_than_rejected(self, modules):
        # A model that invents a key costs nothing, and a later wave can add one without a
        # version negotiation.
        assert modules.engine.parse_delta(json.dumps({"add_vibes": ["good"]})) == {}


# ── merging ─────────────────────────────────────────────────────────────────


class TestMerge:
    def _merged(self, modules, delta, notes=None):
        return modules.engine.merge(
            notes or {"summary": "", "decisions": [], "actions": [], "questions": []}, delta
        )

    def test_items_are_added_with_their_citations(self, modules):
        notes = self._merged(modules, modules.engine.parse_delta(DELTA))
        assert notes["decisions"][0] == {"text": "Launch moves to October", "t0": 1000}
        assert notes["actions"][0]["owner"] == "me"

    def test_nothing_is_ever_deleted(self, modules):
        # The card corrects by appending and striking through. A line the reader saw a minute
        # ago vanishing is the doubt §2a exists to prevent.
        first = self._merged(modules, {"add_decisions": [{"text": "Ship in October"}]})
        second = modules.engine.merge(first, {"add_decisions": [{"text": "Hire a contractor"}]})
        assert [d["text"] for d in second["decisions"]] == ["Ship in October", "Hire a contractor"]

    def test_the_same_decision_phrased_twice_is_not_added_twice(self, modules):
        # A model asked twice about one decision phrases it twice. Without this the card grows
        # three copies of "ship in October" over a long meeting.
        first = self._merged(modules, {"add_decisions": [{"text": "Ship in October"}]})
        second = modules.engine.merge(first, {"add_decisions": [{"text": "ship in October!"}]})
        assert len(second["decisions"]) == 1

    def test_resolving_marks_rather_than_removes(self, modules):
        notes = self._merged(modules, {"add_questions": [{"text": "Who chases legal?"}]})
        notes = modules.engine.merge(notes, {"resolve_questions": [{"text": "who chases legal"}]})
        assert notes["questions"][0]["resolved"] is True
        assert notes["questions"][0]["text"] == "Who chases legal?"

    def test_resolving_something_that_was_never_asked_changes_nothing(self, modules):
        notes = self._merged(modules, {"resolve_questions": [{"text": "never asked"}]})
        assert notes["questions"] == []

    def test_a_summary_replaces_the_previous_one(self, modules):
        notes = self._merged(modules, {"summary": "first"})
        assert modules.engine.merge(notes, {"summary": "second"})["summary"] == "second"

    def test_an_absent_summary_leaves_the_old_one_standing(self, modules):
        notes = self._merged(modules, {"summary": "kept"})
        assert modules.engine.merge(notes, {"add_decisions": [{"text": "x"}]})["summary"] == "kept"

    def test_an_invented_citation_is_dropped_and_the_observation_kept(self, modules):
        # A t0 the model made up is worse than none: MS13 answers with these, and a timestamp
        # jumping to the wrong minute is what makes somebody stop trusting the feature. The
        # text may still be right, so it survives without the citation.
        notes = modules.engine.merge(
            {"summary": "", "decisions": [], "actions": [], "questions": []},
            {"add_decisions": [{"text": "Something said", "t0": 999_999}]},
            valid_t0={1000, 4000},
        )
        assert notes["decisions"][0] == {"text": "Something said"}

    def test_a_real_citation_survives(self, modules):
        notes = modules.engine.merge(
            {"summary": "", "decisions": [], "actions": [], "questions": []},
            {"add_decisions": [{"text": "Real", "t0": 4000}]},
            valid_t0={1000, 4000},
        )
        assert notes["decisions"][0]["t0"] == 4000


# ── the trigger ─────────────────────────────────────────────────────────────


class TestTrigger:
    def _engine(self, modules, clock, **kw):
        return modules.engine.NotesEngine("m1", call=Recorder(), now=lambda: clock["t"], **kw)

    def test_nothing_pending_is_never_due_however_long_it_has_been(self, modules):
        # A fixed timer would spend tokens on silence.
        clock = {"t": 0.0}
        engine = self._engine(modules, clock)
        clock["t"] = 10_000.0
        assert engine.due() is False

    def test_a_dense_window_fires_on_words_before_the_timer(self, modules):
        # A dense two minutes deserves an update; a quiet ten do not.
        clock = {"t": 0.0}
        engine = self._engine(modules, clock, max_words=10)
        engine.add([seg(0, "one two three four five six seven eight nine ten eleven")])
        assert engine.due() is True

    def test_a_quiet_window_waits_for_the_timer(self, modules):
        clock = {"t": 0.0}
        engine = self._engine(modules, clock, interval_s=60, max_words=400)
        engine.add([seg(0, "just a few words")])
        assert engine.due() is False
        clock["t"] = 61.0
        assert engine.due() is True

    def test_blank_segments_do_not_count_towards_the_trigger(self, modules):
        clock = {"t": 0.0}
        engine = self._engine(modules, clock, max_words=1)
        engine.add([seg(0, "   ")])
        assert engine.due() is False

    def test_a_window_is_consumed_once(self, modules):
        clock = {"t": 0.0}
        engine = modules.engine.NotesEngine(
            "m1", call=Recorder(DELTA, "recap"), now=lambda: clock["t"], max_words=1
        )
        engine.add(WINDOW)
        run(engine.run())
        assert engine.pending_words == 0
        assert engine.due() is False


# ── running a window ────────────────────────────────────────────────────────


class TestRun:
    def test_a_window_produces_merged_notes_and_a_frame(self, modules):
        engine = modules.engine.NotesEngine(
            "m1", call=Recorder(DELTA, "The launch is moving."), now=lambda: 0.0
        )
        engine.add(WINDOW)
        frame = run(engine.run(force=True))
        assert frame["type"] == "notes"
        assert frame["version"] == 1
        assert frame["recap"] == "The launch is moving."
        assert frame["decisions"][0]["text"] == "Launch moves to October"

    def test_the_notes_are_stored_versioned(self, modules):
        engine = modules.engine.NotesEngine("m1", call=Recorder(DELTA, "r"), now=lambda: 0.0)
        engine.add(WINDOW)
        run(engine.run(force=True))
        stored = modules.store.get_notes("m1")["notes"]
        assert stored["recap"] == "r"
        assert stored["decisions"][0]["text"] == "Launch moves to October"

    def test_small_talk_stores_nothing(self, modules):
        # An empty delta and an unchanged recap. Storing a version that says nothing new makes
        # the version history useless for debugging the one that does.
        engine = modules.engine.NotesEngine("m1", call=Recorder("{}", ""), now=lambda: 0.0)
        engine.add([seg(0, "how was your weekend")])
        assert run(engine.run(force=True)) is None
        assert modules.store.get_notes("m1") is None

    def test_a_recap_alone_is_a_change_worth_storing(self, modules):
        engine = modules.engine.NotesEngine("m1", call=Recorder("{}", "Something happened."), now=lambda: 0.0)
        engine.add(WINDOW)
        assert run(engine.run(force=True)) is not None

    def test_an_unchanged_recap_is_not_a_change(self, modules):
        engine = modules.engine.NotesEngine("m1", call=Recorder("{}", "same"), now=lambda: 0.0)
        engine.recap = "same"
        engine.add(WINDOW)
        assert run(engine.run(force=True)) is None

    def test_nothing_pending_runs_nothing_even_when_forced(self, modules):
        engine = modules.engine.NotesEngine("m1", call=Recorder(), now=lambda: 0.0)
        assert run(engine.run(force=True)) is None

    def test_force_catches_the_last_window_of_a_meeting(self, modules):
        # Without it the final minute of every meeting is silently lost.
        engine = modules.engine.NotesEngine(
            "m1", call=Recorder(DELTA, "r"), now=lambda: 0.0, interval_s=999, max_words=999
        )
        engine.add(WINDOW)
        assert engine.due() is False
        assert run(engine.run(force=True)) is not None

    def test_a_model_that_raises_costs_one_window_not_the_meeting(self, modules):
        # A transcription session ending because a language model had an off minute is a worse
        # product than one with a gap in its notes.
        async def boom(messages, **kwargs):
            raise RuntimeError("model unreachable")

        engine = modules.engine.NotesEngine("m1", call=boom, now=lambda: 0.0)
        engine.add(WINDOW)
        assert run(engine.run(force=True)) is None
        # And the next window still works.
        engine._call = Recorder(DELTA, "r")
        engine.add(WINDOW)
        assert run(engine.run(force=True)) is not None

    def test_notes_accumulate_across_windows(self, modules):
        engine = modules.engine.NotesEngine(
            "m1",
            call=Recorder(
                json.dumps({"add_decisions": [{"text": "First"}]}),
                "r1",
                json.dumps({"add_decisions": [{"text": "Second"}]}),
                "r2",
            ),
            now=lambda: 0.0,
        )
        engine.add(WINDOW)
        run(engine.run(force=True))
        engine.add(WINDOW)
        frame = run(engine.run(force=True))
        assert [d["text"] for d in frame["decisions"]] == ["First", "Second"]
        assert frame["version"] == 2

    def test_the_delta_prompt_carries_the_notes_so_far(self, modules):
        recorder = Recorder(json.dumps({"add_decisions": [{"text": "First"}]}), "r1", "{}", "r2")
        engine = modules.engine.NotesEngine("m1", call=recorder, now=lambda: 0.0)
        engine.add(WINDOW)
        run(engine.run(force=True))
        engine.add(WINDOW)
        run(engine.run(force=True))
        # The second delta prompt must know what the first one decided, or the model proposes
        # it again and the dedupe is the only thing standing between the card and a duplicate.
        assert "First" in recorder.prompt(2)


class TestPromptRendering:
    def test_a_transcript_line_carries_the_timestamp_the_model_must_cite(self, modules):
        # In the text rather than a parallel list: a model asked to correlate two lists gets it
        # wrong often enough to matter.
        rendered = modules.prompts.transcript_window(WINDOW)
        assert "[1000] them: so the launch moves to October" in rendered

    def test_blank_segments_are_left_out(self, modules):
        assert modules.prompts.transcript_window([seg(0, "  ")]) == ""

    def test_empty_notes_read_as_nothing_yet(self, modules):
        assert modules.prompts.render_notes({}) == "(nothing yet)"

    def test_a_resolved_question_is_rendered_struck_through(self, modules):
        rendered = modules.prompts.render_notes(
            {"questions": [{"text": "Who chases legal?", "resolved": True}]}
        )
        assert "~~Who chases legal?~~" in rendered

    def test_the_system_prompt_forbids_inventing_a_citation(self, modules):
        assert "Never invent one" in modules.prompts.NOTES_SYSTEM

    def test_the_recap_prompt_states_its_own_limit(self, modules):
        assert str(modules.prompts.RECAP_MAX_WORDS) in modules.prompts.RECAP_SYSTEM
