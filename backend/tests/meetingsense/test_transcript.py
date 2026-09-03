"""Utterance assembly — the 200 ms overlap, and getting rid of what it duplicates (MS2).

Chunks overlap by 200 ms because cutting on silence still cuts words: a speaker pausing
mid-phrase puts the boundary inside "recog-"/"-nition", and one of the two chunks then
transcribes a fragment. Overlapping means the word is whole somewhere. The cost is that the
overlap is transcribed twice, and this is what removes the second copy.

The rule that shapes every test here: **trim the head of the later span, never the tail of
the earlier one.** A segment already sent and already stored must not change afterwards.
Editing history is how a live transcript starts flickering and the reader stops trusting what
they read a moment ago.
"""

from __future__ import annotations

import pytest

from app.meetingsense.transcript import (
    MIN_OVERLAP_WORDS,
    UtteranceAssembler,
    dedupe,
    normalise,
    overlap_length,
    strip_leading_words,
    words,
)


# ── the primitives ──────────────────────────────────────────────────────────


class TestNormalise:
    def test_case_and_trailing_punctuation_are_ignored(self):
        # Whisper punctuates by guess: the same word arrives as "October" ending one chunk
        # and "October," starting the next. Raw comparison would call those different and
        # leave the duplicate in.
        assert normalise("October,") == normalise("october")
        assert normalise("Marina.") == normalise("marina")

    def test_words_splits_on_punctuation_not_apostrophes(self):
        assert words("we can't — really") == ["we", "can", "t", "really"]


class TestOverlapLength:
    def test_no_overlap_is_zero(self):
        assert overlap_length("the launch moves", "legal needs to sign") == 0

    def test_a_repeated_tail_is_found(self):
        assert overlap_length("so the launch moves to October", "moves to October and legal") == 3

    def test_the_longest_match_wins_not_the_first(self):
        # With both "moves to October" (3) and "to October" (2) matching, trimming the
        # shorter would leave "to October" duplicated in the transcript.
        assert overlap_length("the launch moves to October", "moves to October and legal") == 3

    def test_one_shared_word_is_a_coincidence(self):
        # "the" ending one utterance and starting the next is ordinary English, not an
        # overlap. Trimming on it would eat a real word.
        assert overlap_length("we need the", "the budget is unclear") < MIN_OVERLAP_WORDS

    def test_punctuation_between_the_two_does_not_break_the_match(self):
        # Two words, so it clears the floor; the point is the full stop and comma around
        # "October", which a raw string comparison would treat as different words.
        assert overlap_length("moves to October.", "to October, and legal") == 2

    def test_a_single_word_overlap_is_below_the_floor(self):
        # Deliberate: one shared word is ordinary English. This is what MIN_OVERLAP_WORDS
        # buys, and it is why the test above needed two.
        assert overlap_length("moves to October.", "October, and legal") == 0

    def test_empty_input_is_zero_not_a_crash(self):
        assert overlap_length("", "anything") == 0
        assert overlap_length("anything", "") == 0

    def test_the_search_window_is_bounded(self):
        # A long identical passage should not make this quadratic over the whole transcript.
        long_text = " ".join(["word"] * 500)
        assert overlap_length(long_text, long_text) <= 10


class TestStripLeadingWords:
    def test_removes_exactly_that_many_words(self):
        assert strip_leading_words("moves to October and legal", 3) == "and legal"

    def test_leading_punctuation_goes_with_them(self):
        assert strip_leading_words("moves to October, and legal", 3) == "and legal"

    def test_stripping_everything_leaves_nothing(self):
        assert strip_leading_words("moves to October", 3) == ""

    def test_zero_is_a_no_op(self):
        assert strip_leading_words("unchanged text", 0) == "unchanged text"


# ── dedupe ──────────────────────────────────────────────────────────────────


def span(text, t0=0.0, t1=None, **extra):
    return {"text": text, "t0": t0, "t1": t1, **extra}


class TestDedupe:
    def test_the_later_span_is_trimmed_not_the_earlier_one(self):
        out = dedupe([span("the launch moves to October"), span("moves to October and legal")])
        assert out[0]["text"] == "the launch moves to October", "already-sent text must not change"
        assert out[1]["text"] == "and legal"

    def test_a_span_that_is_wholly_a_repeat_is_dropped(self):
        out = dedupe([span("we still need legal sign-off"), span("need legal sign-off")])
        assert len(out) == 1

    def test_unrelated_spans_pass_through_untouched(self):
        pair = [span("first thing"), span("completely different")]
        assert [s["text"] for s in dedupe(pair)] == ["first thing", "completely different"]

    def test_blank_spans_are_dropped(self):
        assert dedupe([span("   "), span("real")]) == [span("real")]

    def test_metadata_survives_a_trim(self):
        out = dedupe([span("to October"), span("October and legal", conf=0.9, speaker="them")])
        assert out[1]["conf"] == 0.9
        assert out[1]["speaker"] == "them"

    def test_it_chains_across_three_spans(self):
        out = dedupe([span("a b c"), span("b c d"), span("c d e")])
        assert [s["text"] for s in out] == ["a b c", "d", "e"]


# ── the assembler ───────────────────────────────────────────────────────────


class TestAssembler:
    def test_chunk_relative_times_become_meeting_relative(self):
        # MS1's providers report spans relative to the clip. The caller framed the audio and
        # knows where the clip sat, so the offsetting happens once, here.
        a = UtteranceAssembler()
        out = a.push([span("hello", t0=0.2, t1=1.0)], chunk_t0_ms=14_000)
        assert out[0]["t0_ms"] == 14_200
        assert out[0]["t1_ms"] == 15_000

    def test_an_unmeasured_end_stays_none(self):
        # MS1's contract: t1 None means the provider did not measure the end. A zero here
        # would be a number a card renders as fact.
        a = UtteranceAssembler()
        assert a.push([span("hello", t0=0.0, t1=None)])[0]["t1_ms"] is None

    def test_overlap_between_consecutive_chunks_is_removed(self):
        a = UtteranceAssembler()
        a.push([span("the launch moves to October", t0=0.0, t1=2.0)], chunk_t0_ms=0)
        second = a.push([span("moves to October and legal", t0=0.0, t1=2.0)], chunk_t0_ms=1_800)
        assert [s["text"] for s in second] == ["and legal"]

    def test_a_chunk_that_is_entirely_overlap_returns_nothing(self):
        # A real outcome — somebody stopped talking mid-chunk — and not a failure. A caller
        # that treated [] as an error would log one every time a speaker paused.
        a = UtteranceAssembler()
        a.push([span("we still need legal sign-off", t0=0.0, t1=2.0)])
        assert a.push([span("need legal sign-off", t0=0.0, t1=1.0)], chunk_t0_ms=1_800) == []

    def test_the_clock_never_winds_back(self):
        # A late chunk must not reorder the card.
        a = UtteranceAssembler()
        a.push([span("first", t0=0.0, t1=5.0)], chunk_t0_ms=10_000)
        assert a.last_end_ms == 15_000
        a.push([span("late arrival", t0=0.0, t1=1.0)], chunk_t0_ms=2_000)
        assert a.last_end_ms == 15_000

    def test_speaker_defaults_to_the_chunk_and_a_span_can_override(self):
        a = UtteranceAssembler()
        out = a.push([span("mine"), span("theirs", speaker="them")], speaker="me")
        assert [s["speaker"] for s in out] == ["me", "them"]

    def test_an_empty_chunk_is_survivable(self):
        assert UtteranceAssembler().push([]) == []

    def test_state_is_only_what_cannot_be_recomputed(self):
        # Two things: the previous text, to spot the overlap; and the furthest end, to keep
        # time monotonic. Anything else here would be a cache waiting to go stale.
        a = UtteranceAssembler()
        a.push([span("something", t0=0.0, t1=1.0)])
        assert a.last_end_ms == 1_000


@pytest.mark.parametrize(
    "first,second,expected",
    [
        # The case the overlap exists for: a word cut in half by a silence boundary.
        ("so the launch", "the launch moves", "moves"),
        # Nothing repeated — nothing removed.
        ("good morning", "shall we start", "shall we start"),
        # Repetition a speaker actually said. Two words is the floor, so "no no" survives.
        ("that is a no", "no from me", "no from me"),
    ],
)
def test_real_boundaries(first, second, expected):
    a = UtteranceAssembler()
    a.push([span(first)])
    out = a.push([span(second)], chunk_t0_ms=1_800)
    assert (out[0]["text"] if out else "") == expected
