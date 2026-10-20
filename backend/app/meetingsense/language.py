"""Which language a meeting is transcribed in.

Whisper detects the language of every clip afresh, from its first 30 seconds — and a meeting
clip is two to eight seconds of a call, often a single phrase, sometimes a laugh. On a clip
that short the guess is unreliable, and a wrong guess is not a small error: the model then
*translates* what it heard into the language it guessed. The reported transcript of an
English call contained lines like "e piacco" and "e pianico" — English audio decoded as
Italian.

So a meeting's language is decided once and then held:

* ``"auto"`` (the default): the first confident detections decide it. A detection counts
  when the model is at least :data:`MIN_PROBABILITY` sure, on a clip with at least
  :data:`MIN_WORDS` words; :data:`VOTES` agreeing detections lock the meeting to that language
  and every later clip is decoded in it.
* an ISO 639-1 code (``"en"``, ``"it"``, ``"es"`` …): that language from the first clip.
  Settings → Meetings sets this, and so does ``MEETINGSENSE_LANGUAGE`` for an operator.
* ``"multi"``: detect every clip, never lock — the old behaviour, for a meeting that really
  does switch languages.
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from typing import Any, Dict, Iterable, Optional, Tuple

log = logging.getLogger(__name__)

AUTO = "auto"
MULTI = "multi"

#: How sure the model must be before a detection counts as a vote.
MIN_PROBABILITY = 0.8
#: A detection on fewer words than this is a guess at a phrase, not at a language.
MIN_WORDS = 3
#: Agreeing votes that lock the meeting's language.
VOTES = 2

_CODE = re.compile(r"^[a-z]{2,3}$")


def normalise(value: Any) -> Tuple[str, Optional[str]]:
    """``(mode, code)`` for a requested language: ``("auto", None)``, ``("multi", None)`` or
    ``("fixed", "en")``. Anything unrecognisable is ``auto`` — the safe default, never an error.
    """
    text = str(value or "").strip().lower().replace("_", "-")
    if not text or text in (AUTO, "detect", "default"):
        return AUTO, None
    if text in (MULTI, "multilingual", "any", "mixed"):
        return MULTI, None
    # "en-US" → "en": Whisper takes the bare language code.
    code = text.split("-", 1)[0]
    if _CODE.match(code):
        return "fixed", code
    return AUTO, None


def configured_default() -> Any:
    """The operator's default, from ``MEETINGSENSE_LANGUAGE``; empty means auto."""
    return os.getenv("MEETINGSENSE_LANGUAGE", "")


class LanguageLock:
    """One meeting's language: fixed, or locked from the first confident detections."""

    def __init__(self, requested: Any = None) -> None:
        self.mode, self.language = normalise(requested)
        self._votes: Counter = Counter()

    def request(self, value: Any) -> None:
        """Apply a language asked for later (the start frame). An empty ask changes nothing."""
        if value is None or str(value).strip() == "":
            return
        self.mode, self.language = normalise(value)
        self._votes.clear()

    @property
    def decode_language(self) -> Optional[str]:
        """The language to decode the next clip in, or ``None`` to let the model detect it."""
        return None if self.mode == MULTI else self.language

    def observe(self, spans: Iterable[Dict[str, Any]]) -> Optional[str]:
        """Count one clip's detection. Returns the language when this clip locked it."""
        if self.mode != AUTO or self.language:
            return None
        spans = list(spans or [])
        detected = next((s.get("lang") for s in spans if s.get("lang")), None)
        probability = next((s.get("lang_p") for s in spans if s.get("lang_p") is not None), None)
        words = sum(len(str(s.get("text") or "").split()) for s in spans)
        if not detected or probability is None or words < MIN_WORDS:
            return None
        try:
            if float(probability) < MIN_PROBABILITY:
                return None
        except (TypeError, ValueError):
            return None
        self._votes[str(detected)] += 1
        if self._votes[str(detected)] >= VOTES:
            self.language = str(detected)
            log.info("meetingsense: transcription language locked to %r", self.language)
            return self.language
        return None
