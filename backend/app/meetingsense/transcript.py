"""Utterance assembly (batch MS2).

Audio arrives as VAD-delimited chunks with a **200 ms overlap** — each chunk repeats the tail
of the one before it. The overlap exists because cutting on silence still cuts words: a
speaker who pauses mid-phrase produces a boundary in the middle of "recog-" / "-nition", and
whichever side the cut lands on, one of the two chunks transcribes a fragment. Overlapping
means the word is whole in at least one of them.

The cost of that is duplication: the overlap is transcribed twice, so the tail of one segment
and the head of the next say the same thing. This module removes it.

Pure functions over dictionaries. No I/O, no clock, no FastAPI — every decision here is a
comparison between two strings, and it should be testable as one.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

Span = Dict[str, Any]

#: How much of a tail to consider when hunting for a repeat. Ten words is comfortably more
#: than 200 ms of speech (roughly 2.5 words at a normal pace) without being so long that an
#: ordinary repetition — "no, no, that's not what I meant" — looks like an overlap.
MAX_OVERLAP_WORDS = 10

#: Below this, a match is a coincidence rather than a repeat. One shared word between two
#: utterances is ordinary English; three in a row in the same order is the overlap.
MIN_OVERLAP_WORDS = 2

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def normalise(word: str) -> str:
    """Compare words the way a listener would: case- and punctuation-insensitive.

    Whisper punctuates by guess, so the same word can arrive as "October" at the end of one
    chunk and "October," at the start of the next. Comparing raw strings would call those
    different and leave the duplicate in.
    """
    return word.lower().strip("".join(c for c in word if not c.isalnum() and not c.isspace()))


def words(text: str) -> List[str]:
    return _WORD.findall(text or "")


def overlap_length(previous: str, current: str, *, max_words: int = MAX_OVERLAP_WORDS) -> int:
    """How many words at the start of ``current`` repeat the end of ``previous``.

    Returns the **longest** match, not the first: with "the launch moves to October" followed
    by "moves to October and legal", both "moves to October" (3) and "to October" (2) match,
    and trimming the shorter one would leave "to October" duplicated.
    """
    tail = [normalise(w) for w in words(previous)][-max_words:]
    head = [normalise(w) for w in words(current)][:max_words]
    if not tail or not head:
        return 0
    for length in range(min(len(tail), len(head)), MIN_OVERLAP_WORDS - 1, -1):
        if tail[-length:] == head[:length]:
            return length
    return 0


def strip_leading_words(text: str, count: int) -> str:
    """Drop the first ``count`` words, keeping the original spacing of what remains."""
    if count <= 0:
        return text
    seen = 0
    for match in _WORD.finditer(text or ""):
        seen += 1
        if seen == count:
            return (text[match.end():]).lstrip(" ,.;:!?-—")
    return ""


class _Tail:
    """The last few words that were actually emitted.

    Comparing against the *previous span's surviving text* is not enough, and the bug is easy
    to miss: given "a b c", "b c d", "c d e", the second is trimmed to "d", and the third is
    then compared against "d" alone — so "c d" sails through duplicated. What a chunk overlaps
    is what was **said**, not what happened to survive the last trim, so the window is over
    emitted words and is refilled from every span that goes out.
    """

    def __init__(self, size: int = MAX_OVERLAP_WORDS) -> None:
        self._size = size
        self._words: List[str] = []

    def text(self) -> str:
        return " ".join(self._words)

    def extend(self, text: str) -> None:
        self._words = (self._words + words(text))[-self._size:]


def dedupe(spans: Sequence[Span], *, tail: Optional["_Tail"] = None) -> List[Span]:
    """Remove the overlap-induced repetition between consecutive spans.

    Trims the **head of the later** span rather than the tail of the earlier one, deliberately:
    a segment that has already been sent to the client and written to the store must not
    change afterwards. Editing history is how a live transcript starts flickering, and the
    reader stops trusting what they read a moment ago.

    A span whose text is entirely a repeat is dropped, not kept empty.

    ``tail`` lets a caller carry the window across calls, which is what makes the streaming
    case the same code as the batch one: :class:`UtteranceAssembler` passes its own window so
    the first span of a chunk is compared against the last words of the chunk before it. Pass
    nothing and each call starts fresh.
    """
    out: List[Span] = []
    tail = tail if tail is not None else _Tail()
    for span in spans:
        text = (span.get("text") or "").strip()
        if not text:
            continue
        overlap = overlap_length(tail.text(), text)
        if overlap:
            trimmed = strip_leading_words(text, overlap)
            if not trimmed:
                # Wholly a repeat — the speaker said nothing new in this chunk.
                continue
            span = {**span, "text": trimmed}
            text = trimmed
        out.append(span)
        tail.extend(text)
    return out


class UtteranceAssembler:
    """Turns a stream of transcribed chunks into a clean, monotonic transcript.

    Stateful only in the two things it cannot recompute: what the previous chunk said (to
    spot the overlap) and where the meeting started (to make timestamps meeting-relative
    rather than chunk-relative).

    MS1's providers report spans relative to the *clip*. A caller that framed the audio knows
    where the clip sat in the meeting, and passes that as ``chunk_t0_ms`` — so the offsetting
    happens once, here, rather than in each transport.
    """

    def __init__(self) -> None:
        self._tail = _Tail()
        self._last_end_ms = 0

    @property
    def last_end_ms(self) -> int:
        return self._last_end_ms

    def push(
        self,
        spans: Sequence[Span],
        *,
        chunk_t0_ms: int = 0,
        speaker: Optional[str] = None,
    ) -> List[Span]:
        """Absorb one chunk's spans; return the ones that are new.

        Returns ``[]`` for a chunk that was entirely overlap — which is a real outcome when
        somebody stops talking mid-chunk, and must not be mistaken for a failure.
        """
        prepared: List[Span] = []
        for span in spans:
            text = (span.get("text") or "").strip()
            if not text:
                continue
            t0 = int(round(float(span.get("t0") or 0.0) * 1000)) + chunk_t0_ms
            raw_t1 = span.get("t1")
            t1 = None if raw_t1 is None else int(round(float(raw_t1) * 1000)) + chunk_t0_ms
            prepared.append(
                {
                    "t0_ms": t0,
                    "t1_ms": t1,
                    "text": text,
                    "conf": span.get("conf"),
                    "speaker": span.get("speaker") or speaker,
                }
            )

        # One rule, one implementation: the assembler's own window is handed to ``dedupe``, so
        # a span is compared against everything emitted for this meeting — the chunk before it
        # included — rather than only against its neighbours inside this chunk.
        fresh = dedupe(prepared, tail=self._tail)

        if fresh:
            end = fresh[-1]["t1_ms"] if fresh[-1]["t1_ms"] is not None else fresh[-1]["t0_ms"]
            # Monotonic: a late chunk must never wind the clock back, or the card reorders.
            self._last_end_ms = max(self._last_end_ms, int(end))
        return fresh
