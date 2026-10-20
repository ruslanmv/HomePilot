"""The call, heard twice: once from the call and once through the microphone.

A meeting records two channels — the call's own audio ("them") and the microphone ("me").
Played through laptop speakers, the call reaches the microphone too, and every remote line
was transcribed a second time as the user's: the same sentence under *Them* and under *You*,
a second apart. The browser's echo cancellation cannot help, because it only cancels audio
the browser itself plays, and a Slack, Zoom or Teams *app* is not the browser.

The fix works on what both channels have already produced — text with timings — rather than
on the audio. A microphone line is an echo when almost every word of it was just said on the
call, at the same moment. Real crosstalk survives: the user's own words are not in the call's
channel, so they do not match, whatever the volume.

Deliberately conservative. A short reply ("Okay.") is only an echo when the call said exactly
those words at that moment; a longer line needs :data:`COVERAGE` of its words to match. A
missed echo is a duplicated line, which is what the user had before; a false positive is a
line of theirs that disappears, which is worse.
"""

from __future__ import annotations

import os
import re
from collections import Counter, deque
from typing import Any, Deque, Dict, Optional, Sequence, Tuple

#: The speaker labels of the two channels, as :mod:`.audio` assigns them.
FAR = "them"
NEAR = "me"

#: How far apart in time the two copies may be. The acoustic path is tens of milliseconds;
#: the rest is the two channels being cut and transcribed separately.
WINDOW_MS = 2500
#: Share of a longer microphone line that must appear in the call's words at that moment.
COVERAGE = 0.6
#: At or below this many words, a line is an echo only when *every* word matches.
SHORT_LINE_WORDS = 3
#: How many recent call lines are kept to compare against.
HISTORY = 48

_WORD = re.compile(r"[\w']+", re.UNICODE)


def enabled() -> bool:
    """``MEETINGSENSE_ECHO_GUARD=0`` keeps every microphone line, echoes included."""
    return os.getenv("MEETINGSENSE_ECHO_GUARD", "1").strip().lower() not in ("0", "false", "off")


def tokens(text: str) -> Tuple[str, ...]:
    return tuple(w.lower().strip("'") for w in _WORD.findall(text or "") if w.strip("'"))


class EchoGuard:
    """Remembers what the call said, and recognises it when the microphone says it again."""

    def __init__(self) -> None:
        self._far: Deque[Tuple[int, int, Tuple[str, ...]]] = deque(maxlen=HISTORY)
        self._far_partial: Optional[Tuple[int, int, Tuple[str, ...]]] = None
        self.suppressed = 0

    def heard(self, segment: Dict[str, Any]) -> None:
        """Record a line the call channel produced (``t0_ms``/``t1_ms`` or ``t0``/``t1``)."""
        entry = _entry(segment)
        if entry is not None:
            self._far.append(entry)

    def heard_partial(self, frame: Dict[str, Any]) -> None:
        """Record the call channel's provisional line, replaced by the next one."""
        self._far_partial = _entry(frame)

    def is_echo(self, segment: Dict[str, Any], *, partial: bool = False) -> bool:
        """Whether a microphone line is the call coming back through the speakers."""
        near = _entry(segment)
        if near is None:
            return False
        t0, t1, words = near
        candidates = list(self._far)
        if self._far_partial is not None:
            candidates.append(self._far_partial)
        pool: Counter = Counter()
        for f0, f1, far_words in candidates:
            if f1 + WINDOW_MS >= t0 and f0 - WINDOW_MS <= t1:
                pool.update(far_words)
        if not pool:
            return False
        matched = sum(min(count, pool[word]) for word, count in Counter(words).items())
        if len(words) <= SHORT_LINE_WORDS:
            echo = matched == len(words)
        else:
            echo = matched / len(words) >= COVERAGE
        if echo and not partial:
            self.suppressed += 1
        return echo


def _entry(segment: Dict[str, Any]) -> Optional[Tuple[int, int, Tuple[str, ...]]]:
    words = tokens(str(segment.get("text") or ""))
    if not words:
        return None
    t0 = _ms(segment.get("t0_ms", segment.get("t0")))
    t1 = _ms(segment.get("t1_ms", segment.get("t1")))
    if t0 is None:
        return None
    return t0, max(t0, t1 if t1 is not None else t0), words


def _ms(value: Any) -> Optional[int]:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def split(segments: Sequence[Dict[str, Any]], guard: EchoGuard, speaker: Optional[str]):
    """``(kept, dropped)`` for one channel's fresh segments, teaching the guard as it goes."""
    if speaker == FAR:
        for seg in segments:
            guard.heard(seg)
        return list(segments), []
    if speaker != NEAR:
        return list(segments), []
    kept, dropped = [], []
    for seg in segments:
        (dropped if guard.is_echo(seg) else kept).append(seg)
    return kept, dropped
