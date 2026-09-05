"""The pieces Participant and Presenter are built from (batch MS26, wave W9).

`test_modes_e2e.py` proves the modes *disagree* — the same window into three modes, three
different outcomes. That is the batch's acceptance and it is not sufficient on its own: an
integration test passes as long as the whole disagrees somewhere, and every part of MS26 has a
rule of its own that no amount of end-to-end agreement would notice breaking.

So these are the rules, one at a time. The two that carry the most weight:

- **A mode's framing never displaces MS13's system prompt.** `ASK_SYSTEM` says cite the
  timestamp and never invent one, and a Participant does not get to relax that.
- **A name is a word, not a substring.** `_mentions` deciding that "Ana" appears in "analysis"
  is the assistant answering to a word somebody said about a spreadsheet.
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture()
def mp():
    import app.meetingsense.agent.mode_prompts as module

    return module


@pytest.fixture()
def pa():
    import app.meetingsense.agent.participant as module

    return module


@pytest.fixture()
def ask_mod():
    import app.meetingsense.ask as module

    return module


def said(text, *, speaker="them", t0=1000):
    return {"t0_ms": t0, "speaker": speaker, "text": text}


# ── mode prompts ────────────────────────────────────────────────────────────


class TestModePrompts:
    def test_the_base_rules_are_always_there(self, mp, ask_mod):
        # "Cite the timestamp" and "never invent one" are the difference between an assistant
        # and a liability, and no mode gets to drop them.
        for mode in ("participant", "presenter", "coach", "practice", "draft"):
            assert ask_mod.ASK_SYSTEM in mp.system_for(mode, ask_mod.ASK_SYSTEM)

    def test_the_base_rules_come_last(self, mp, ask_mod):
        # The final word in a system prompt is the one a model weights hardest, and the base
        # rules are the conditions the role is exercised under rather than suggestions it may
        # override.
        for mode in ("participant", "presenter", "coach", "practice", "draft"):
            assert mp.system_for(mode, ask_mod.ASK_SYSTEM).endswith(ask_mod.ASK_SYSTEM)
            assert not mp.system_for(mode, ask_mod.ASK_SYSTEM).startswith(ask_mod.ASK_SYSTEM)

    def test_no_mode_is_the_base_unchanged(self, mp, ask_mod):
        # Byte-identical to what MS13 shipped: an install that never sets a mode must get
        # exactly the prompt it got before this batch.
        assert mp.system_for("", ask_mod.ASK_SYSTEM) == ask_mod.ASK_SYSTEM

    def test_an_unknown_mode_gets_no_framing_rather_than_somebody_elses(self, mp, ask_mod):
        # The same direction `modes.resolve` falls in: a typo or a stale client quiets the
        # assistant down, it does not hand it a role nobody chose.
        assert mp.system_for("presentr", ask_mod.ASK_SYSTEM) == ask_mod.ASK_SYSTEM
        assert mp.framing("nonsense") == ""

    def test_note_taker_has_no_framing_at_all(self, mp):
        # It never answers. A prompt for it would be dead text a later reader assumes is live,
        # and MS23's acceptance is that its output matches the fixed loop's.
        assert mp.framing("note-taker") == ""

    def test_the_mode_name_is_matched_loosely(self, mp):
        assert mp.framing("  Participant ") == mp.framing("participant")

    def test_every_speaking_mode_has_framing(self, mp):
        from app.meetingsense.agent import modes

        for mode in modes.MODES:
            if mode.answer:
                assert mp.framing(mode.name), f"{mode.name} answers and says nothing about how"


class TestUsableDraft:
    def test_a_short_reply_is_a_draft(self, mp):
        assert mp.usable_draft("We agreed forty a seat.") == "We agreed forty a seat."

    @pytest.mark.parametrize("text", [
        None, "", "   ", 42,
        # The model declining, in the exact form it was asked for — and the near misses, since
        # a model told to reply "PASS" will eventually reply "PASS." or "pass".
        "PASS", "pass", "PASS.", " Pass ",
    ])
    def test_declining_is_no_draft(self, mp, text):
        assert mp.usable_draft(text) == ""

    def test_an_essay_is_no_draft(self, mp):
        # A draft the user has to edit down is slower than answering themselves.
        assert mp.usable_draft(" ".join(["word"] * 61)) == ""
        assert mp.usable_draft(" ".join(["word"] * 60)) != ""

    def test_a_model_that_writes_around_the_word_has_drafted(self, mp):
        # "I'll pass on this one" is a draft, not a refusal. The literal is checked exactly for
        # this reason.
        assert mp.usable_draft("I'll pass on this one") == "I'll pass on this one"


# ── participant ─────────────────────────────────────────────────────────────


class TestAddressed:
    def test_a_question_naming_the_assistant(self, pa):
        hit = pa.addressed(said("Ana, what did we decide?"), assistant_names=["Ana"])
        assert hit["name"] == "Ana" and hit["t0"] == 1000

    def test_a_statement_naming_it_is_not_a_question(self, pa):
        # "Ana already sent that" is somebody talking *about* the assistant. Answering it is
        # the assistant joining a conversation it was mentioned in.
        assert pa.addressed(said("Ana already sent that over"), assistant_names=["Ana"]) is None

    def test_a_question_that_does_not_name_it(self, pa):
        assert pa.addressed(said("what did we decide?"), assistant_names=["Ana"]) is None

    def test_the_users_own_question(self, pa):
        # It arrived down the microphone this machine owns. The socket is where that belongs.
        assert pa.addressed(said("Ana, what did we decide?", speaker="me"),
                            assistant_names=["Ana"]) is None

    def test_with_no_names_it_is_never_addressed(self, pa):
        assert pa.addressed(said("hey, what did we decide?"), assistant_names=[]) is None

    def test_a_name_is_a_word_not_a_substring(self, pa):
        # "Ana" is not in "analysis". Answering to a word somebody said about a spreadsheet is
        # the exact failure that makes people turn the mode off.
        assert pa.addressed(said("what does the analysis say?"), assistant_names=["Ana"]) is None
        assert pa.addressed(said("is Anahita joining?"), assistant_names=["Ana"]) is None

    def test_a_one_letter_name_is_refused(self, pa):
        # It would match most sentences. Refusing it is the difference between a name and a
        # coincidence.
        assert pa.addressed(said("what a mess?"), assistant_names=["a"]) is None

    def test_the_first_matching_name_is_reported(self, pa):
        hit = pa.addressed(said("Ana, or Bot, what did we decide?"),
                           assistant_names=["Bot", "Ana"])
        assert hit["name"] == "Bot"

    def test_matching_is_case_insensitive(self, pa):
        assert pa.addressed(said("ANA, what did we decide?"), assistant_names=["Ana"])


class TestAimedAtUser:
    def test_a_second_person_question(self, pa):
        assert pa.aimed_at_user(said("what do you think?"))["question"] == "what do you think?"

    def test_it_uses_the_same_rule_the_chip_uses(self, pa):
        # Two definitions of "was that aimed at me" would drift, and the one that drifted would
        # be the one nobody was reading. So the filler list applies here too.
        assert pa.aimed_at_user(said("does that make sense?")) is None
        assert pa.aimed_at_user(said("what time is the release?")) is None

    def test_a_question_naming_the_assistant_is_not_the_users(self, pa):
        # Even with second person in it: "Ana, can you tell us what you think?" is Ana's, and
        # drafting it as well puts two answers on screen for one question.
        assert pa.aimed_at_user(said("Ana, can you tell us what you think?"),
                                assistant_names=["Ana"]) is None

    def test_the_users_name_counts_as_being_aimed_at(self, pa):
        assert pa.aimed_at_user(said("Ruslan, what is the date?"), user_names=["Ruslan"])


class TestDraft:
    def _answering(self, text):
        async def call(meeting_id, question, *, mode=""):
            call.mode = mode
            return {"type": "answer", "text": text}

        call.mode = None
        return call

    def test_it_asks_in_the_draft_framing(self, pa):
        answer = self._answering("we agreed forty a seat")
        assert run(pa.draft("what do you think?", answer=answer, meeting_id="m1")) == \
            "we agreed forty a seat"
        assert answer.mode == "draft"

    def test_an_unusable_answer_is_no_draft(self, pa):
        # `usable_draft`'s rules apply here, not a second set of them.
        assert run(pa.draft("q?", answer=self._answering("PASS"), meeting_id="m1")) == ""
        assert run(pa.draft("q?", answer=self._answering(" ".join(["x"] * 80)),
                            meeting_id="m1")) == ""

    def test_an_empty_question_asks_nothing(self, pa):
        answer = self._answering("something")
        assert run(pa.draft("   ", answer=answer, meeting_id="m1")) == ""
        assert answer.mode is None

    def test_a_raising_answer_is_no_draft_and_no_crash(self, pa):
        async def angry(*a, **k):
            raise RuntimeError("the model is down")

        assert run(pa.draft("q?", answer=angry, meeting_id="m1")) == ""

    def test_a_frame_that_is_not_a_frame(self, pa):
        async def odd(*a, **k):
            return "just a string"

        assert run(pa.draft("q?", answer=odd, meeting_id="m1")) == ""


class TestAttachDraft:
    def test_it_lands_on_a_question_chip(self, pa):
        chip = {"kind": "question", "text": "what do you think?"}
        assert pa.attach_draft(chip, "I think yes.")["draft"] == "I think yes."

    def test_it_never_lands_on_another_kind(self, pa):
        # A draft on a `decision` chip is a reply to something nobody asked.
        chip = {"kind": "decision", "text": "we're going with Postgres"}
        assert "draft" not in pa.attach_draft(chip, "I think yes.")

    def test_an_empty_draft_is_not_attached(self, pa):
        chip = {"kind": "question", "text": "what do you think?"}
        assert "draft" not in pa.attach_draft(chip, "   ")

    def test_the_original_chip_is_untouched(self, pa):
        # The caller holds the list it is iterating. A mutation here would edit a chip the
        # dedupe has already keyed and the transport may already have sent.
        chip = {"kind": "question", "text": "what do you think?"}
        pa.attach_draft(chip, "I think yes.")
        assert "draft" not in chip


# ── ask, with a mode ────────────────────────────────────────────────────────


class TestAskTakesAMode:
    def test_the_mode_reaches_the_system_prompt(self, ask_mod, mp):
        messages = ask_mod.build_prompt("what did we decide?", mode="participant")
        assert messages[0]["content"] == mp.system_for("participant", ask_mod.ASK_SYSTEM)

    def test_no_mode_is_byte_identical_to_what_ms13_shipped(self, ask_mod):
        assert ask_mod.build_prompt("q?")[0]["content"] == ask_mod.ASK_SYSTEM

    def test_the_mode_does_not_touch_the_user_message(self, ask_mod):
        # A mode is a framing, not a tier. The budget, the trim order and what is retrieved are
        # D9's and are not a role's to change.
        plain = ask_mod.build_prompt("q?", recap="r")[1]["content"]
        assert ask_mod.build_prompt("q?", recap="r", mode="coach")[1]["content"] == plain

    def test_answer_passes_its_mode_through(self, ask_mod, tmp_path, monkeypatch):
        import app.meetingsense.store as store_mod

        db = tmp_path / "m.sqlite3"

        def _connect():
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            return conn

        monkeypatch.setattr(store_mod, "_connect", _connect)
        store_mod.migrate()
        store_mod.create_meeting(conversation_id="c1", meeting_id="m1", started_at=1.0)

        seen = {}

        async def call(messages, **kwargs):
            seen["system"] = messages[0]["content"]
            return "an answer"

        run(ask_mod.answer("m1", "what did we decide?", call=call, mode="practice"))
        assert seen["system"].startswith("This is a rehearsal.")
