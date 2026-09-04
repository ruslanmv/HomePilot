"""Coach's refusal, enforced (batch MS27, wave W9).

The batch row asks for "an explicit test that Coach never receives screen OCR text", with the
reason attached: *§E.2's refusal is only real if enforced*. This file is that enforcement,
tested three ways, because one way is not enough for this particular rule.

MeetingSense captures keyframes and a vision model captions them — that is how it knows a slide
said "Q3 revenue is flat". The capability is for the user's own slides in Presenter. Pointed at
a Coach it becomes something else entirely: a coach that reads the screen reads the other
participants' documents, their open tabs, their messages, in a meeting where nobody agreed to
that and where the user cannot see what was captured either.

What makes that worth three tests rather than one is the shape of the failure. It is silent —
nothing looks wrong, the coaching just gets better. The people affected are not in the room and
will never know. And a single behavioural test only covers the path it happens to drive.

  1. **Behavioural.** Drive a meeting stuffed with captions and assert not one word reaches the
     model.
  2. **Structural.** Read the module's source and fail if it so much as mentions a keyframe.
  3. **Defensive.** Hand `scrub` the mixed list a future caller might build, and watch it drop
     the screen rows on its own.

Delete any one of the three and a plausible edit gets through.
"""

from __future__ import annotations

import asyncio
import inspect
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


#: A string that exists nowhere else in the suite. If it turns up in a prompt, it came off a
#: slide — there is no other route into the process.
SECRET = "ZZQX-CONFIDENTIAL-BOARD-DECK-4417"


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    import app.meetingsense.agent.coaching as coaching
    import app.meetingsense.store as store_mod

    db = tmp_path / "meetings.sqlite3"

    def _connect():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(store_mod, "_connect", _connect)
    store_mod.migrate()
    store_mod.create_meeting(conversation_id="c1", meeting_id="m1", started_at=1.0)
    return type("M", (), {"coaching": coaching, "store": store_mod})


class Recorder:
    """A model that records every prompt it is ever handed."""

    def __init__(self, reply='{"say": "you have not covered pricing"}'):
        self.prompts = []
        self.reply = reply

    async def __call__(self, messages, **kwargs):
        self.prompts.append(messages)
        return self.reply

    def everything(self) -> str:
        return "\n".join(m["content"] for prompt in self.prompts for m in prompt)


def slide_heavy(store):
    """A meeting whose screen was full of something Coach must not read."""
    for i in range(4):
        store.add_keyframe("m1", t_ms=i * 10_000, url=f"blob:{i}", hash=f"h{i}")
    frames = store.get_keyframes("m1")
    for frame in frames:
        store.set_keyframe_caption(frame["id"], f"{SECRET} — slide {frame['t_ms']}")


# ── 1. behavioural ──────────────────────────────────────────────────────────


class TestNothingFromTheScreenReachesTheModel:
    def test_a_meeting_full_of_captions_puts_none_of_them_in_the_prompt(self, mods):
        slide_heavy(mods.store)
        mods.coaching.add_prep("m1", "Brief", "Land the pricing point and the October date.")
        mods.store.add_segments("m1", [{"t0_ms": 0, "t1_ms": 1000, "speaker": "me",
                                        "text": "let us start with the timeline"}])
        model = Recorder()
        run(mods.coaching.observe("m1", call=model))
        assert model.prompts, "the coach did not run, so this test proved nothing"
        assert SECRET not in model.everything()

    def test_the_transcript_does_reach_it(self, mods):
        # The control. Without this the test above would pass over a coach that receives
        # nothing at all, which is a different bug wearing the same green tick.
        mods.coaching.add_prep("m1", "Brief", "Land the pricing point.")
        mods.store.add_segments("m1", [{"t0_ms": 0, "t1_ms": 1000, "speaker": "me",
                                        "text": "a distinctive spoken sentence"}])
        model = Recorder()
        run(mods.coaching.observe("m1", call=model))
        assert "a distinctive spoken sentence" in model.everything()

    def test_and_the_prep_material_does(self, mods):
        mods.coaching.add_prep("m1", "Brief", "Land the pricing point and the October date.")
        model = Recorder()
        run(mods.coaching.observe("m1", call=model))
        assert "Land the pricing point" in model.everything()

    def test_a_caption_smuggled_in_as_a_segment_is_still_refused(self, mods):
        # The realistic edit: somebody builds a "everything that happened" list and passes it
        # in. Every row here looks like a segment and one of them came off the screen.
        mods.coaching.add_prep("m1", "Brief", "Land the pricing point.")
        model = Recorder()
        run(mods.coaching.observe("m1", call=model, segments=[
            {"t0_ms": 0, "speaker": "me", "text": "a spoken sentence"},
            {"t0_ms": 1, "speaker": "screen", "text": SECRET, "caption": SECRET},
        ]))
        assert SECRET not in model.everything()
        assert "a spoken sentence" in model.everything()

    def test_a_row_that_calls_itself_a_slide_is_refused_however_it_is_shaped(self, mods):
        mods.coaching.add_prep("m1", "Brief", "Land the pricing point.")
        model = Recorder()
        run(mods.coaching.observe("m1", call=model, segments=[
            {"kind": "slide", "text": SECRET},
            {"kind": "ocr", "text": SECRET},
            {"kind": "keyframe", "text": SECRET},
            {"kind": "screen", "text": SECRET},
            {"t0_ms": 0, "speaker": "me", "text": "a spoken sentence"},
        ]))
        assert SECRET not in model.everything()

    def test_with_no_prep_it_does_not_run_at_all(self, mods):
        # Coach without prep has nothing to draw a talking point *from*, and improvising from
        # the transcript is the thing this mode is defined as not doing.
        slide_heavy(mods.store)
        model = Recorder()
        assert run(mods.coaching.observe("m1", call=model)) == ""
        assert model.prompts == []


# ── 2. structural ───────────────────────────────────────────────────────────


class TestTheModuleCannotReachTheScreen:
    def test_it_never_mentions_a_keyframe(self, mods):
        # The behavioural tests cover the paths they drive. This covers the paths nobody has
        # written yet: an edit that adds a keyframe read to this module fails here before it
        # can be wired to anything.
        source = inspect.getsource(mods.coaching)
        body = source.split('"""', 2)[-1]  # past the module docstring, which discusses them
        for forbidden in ("get_keyframes", "keyframe_by_hash", "get_keyframe(",
                          "keyframes.", "vision", "analyze_image"):
            assert forbidden not in body, f"coaching.py reaches the screen: {forbidden}"

    def test_context_names_its_sources_and_there_are_two(self, mods):
        source = inspect.getsource(mods.coaching.context)
        assert "prep(" in source
        assert "_transcript(" in source
        assert "keyframe" not in source

    def test_the_transcript_reader_reads_only_segments(self, mods):
        source = inspect.getsource(mods.coaching._transcript)
        assert "get_segments" in source
        assert source.count("store.") == 1


# ── 3. defensive ────────────────────────────────────────────────────────────


class TestScrub:
    @pytest.mark.parametrize("row", [
        {"caption": "a slide"},
        {"keyframe_id": "k1"},
        {"hash": "abc"},
        {"url": "blob:x"},
        {"slide": 3},
        {"ocr": "text"},
        {"image": "b64"},
        {"kind": "slide", "text": "hello"},
        {"kind": "OCR", "text": "hello"},
        {"kind": "Keyframe", "text": "hello"},
        {"kind": "screen", "text": "hello"},
    ])
    def test_a_screen_row_is_dropped(self, mods, row):
        assert mods.coaching.scrub([row]) == []
        assert mods.coaching.from_screen(row) is True

    @pytest.mark.parametrize("row", [
        {"t0_ms": 0, "speaker": "me", "text": "hello"},
        {"text": "hello"},
        {"kind": "transcript", "text": "hello"},
    ])
    def test_a_spoken_row_is_kept(self, mods, row):
        assert mods.coaching.scrub([row]) == [row]
        assert mods.coaching.from_screen(row) is False

    def test_it_is_generous_about_what_counts(self, mods):
        # Being wrong in this direction costs a line of transcript. Being wrong the other way
        # is a failure nobody in the meeting would ever know had happened.
        assert mods.coaching.from_screen({"text": "x", "url": None}) is True

    def test_junk_is_dropped_rather_than_carried(self, mods):
        assert mods.coaching.scrub([None, "a string", 42, {"text": "hello"}]) == [{"text": "hello"}]

    def test_nothing_in_nothing_out(self, mods):
        assert mods.coaching.scrub([]) == []
        assert mods.coaching.scrub(None) == []
        assert mods.coaching.from_screen("not a row") is False


# ── the prep material itself ────────────────────────────────────────────────


class TestPrep:
    def test_it_is_attached_and_read_back(self, mods):
        assert mods.coaching.add_prep("m1", "Brief", "Land the pricing point.")["words"] == 4
        assert [d["title"] for d in mods.coaching.prep("m1")] == ["Brief"]

    def test_documents_keep_their_order(self, mods):
        for name in ("Brief", "Questions", "Numbers"):
            mods.coaching.add_prep("m1", name, f"the {name} document")
        assert [d["title"] for d in mods.coaching.prep("m1")] == ["Brief", "Questions", "Numbers"]

    def test_an_untitled_document_gets_a_name(self, mods):
        assert mods.coaching.add_prep("m1", "", "some text")["title"] == "Prep"

    def test_nothing_to_attach_is_not_attached(self, mods):
        assert mods.coaching.add_prep("m1", "Brief", "   ") is None
        assert mods.coaching.add_prep("m1", "Brief", "") is None
        assert mods.coaching.prep("m1") == []

    def test_the_document_count_is_capped(self, mods):
        # Past this the "prep material" is a library, and a coach that has read a library has
        # read nothing.
        for i in range(mods.coaching.MAX_PREP + 4):
            mods.coaching.add_prep("m1", f"Doc {i}", f"document number {i}")
        assert len(mods.coaching.prep("m1")) == mods.coaching.MAX_PREP

    def test_prep_is_per_meeting(self, mods):
        mods.store.create_meeting(conversation_id="c1", meeting_id="m2", started_at=2.0)
        mods.coaching.add_prep("m1", "Brief", "Land the pricing point.")
        assert mods.coaching.prep("m2") == []

    def test_deleting_the_meeting_takes_the_prep(self, mods):
        mods.coaching.add_prep("m1", "Brief", "Land the pricing point.")
        mods.store.delete_meeting("m1")
        assert mods.coaching.prep("m1") == []

    def test_dropping_it_really_removes_it(self, mods):
        # A real delete, unlike MS24's approvals and MS26's queue, which record a withdrawal.
        # Those are a history of consent; this is the user's own document, and "take my brief
        # out" that leaves the brief in the database has not done what it said.
        mods.coaching.add_prep("m1", "Brief", "Land the pricing point.")
        assert mods.coaching.drop_prep("m1") == 1
        assert mods.coaching.prep("m1") == []
        assert mods.store.artifacts_for_meeting("m1", kind="prep") == []

    def test_dropping_it_leaves_everything_else_alone(self, mods):
        # The kind is part of the delete. Without it, removing a brief would take the meeting's
        # mode, its tool approvals and its audience queue with it.
        mods.store.add_artifact("m1", kind="mode", target="coach")
        mods.store.add_artifact("m1", kind="tool_approval", target="hp.web.search")
        mods.coaching.add_prep("m1", "Brief", "Land the pricing point.")
        mods.coaching.drop_prep("m1")
        assert [r["kind"] for r in mods.store.artifacts_for_meeting("m1")] == \
            ["mode", "tool_approval"]

    def test_dropping_nothing_removes_nothing(self, mods):
        assert mods.coaching.drop_prep("m1") == 0


class TestPrepBudget:
    def _long(self, words):
        return " ".join(f"w{i}" for i in range(words))

    def test_a_document_inside_the_budget_arrives_whole(self, mods):
        mods.coaching.add_prep("m1", "Brief", self._long(50))
        body = mods.coaching.context("m1", segments=[], budget_words=100)
        assert len(body["prep"][0]["text"].split()) == 50
        assert "truncated" not in body["prep"][0]

    def test_a_document_over_the_budget_is_truncated_not_dropped(self, mods):
        # The first document a user attaches is usually their brief, and half a brief is more
        # use than none of it.
        mods.coaching.add_prep("m1", "Brief", self._long(500))
        body = mods.coaching.context("m1", segments=[], budget_words=100)
        assert len(body["prep"]) == 1
        assert len(body["prep"][0]["text"].split()) == 100
        assert body["prep"][0]["truncated"] is True

    def test_the_budget_is_spent_whole_documents_first(self, mods):
        mods.coaching.add_prep("m1", "Brief", self._long(60))
        mods.coaching.add_prep("m1", "Questions", self._long(60))
        mods.coaching.add_prep("m1", "Numbers", self._long(60))
        body = mods.coaching.context("m1", segments=[], budget_words=100)
        assert [d["title"] for d in body["prep"]] == ["Brief", "Questions"]
        assert sum(len(d["text"].split()) for d in body["prep"]) == 100

    def test_a_zero_budget_carries_nothing(self, mods):
        mods.coaching.add_prep("m1", "Brief", self._long(50))
        assert mods.coaching.context("m1", segments=[], budget_words=0)["prep"] == []
