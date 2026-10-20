"""What a meeting transcriber should not write down.

Whisper was trained on subtitled video, and on audio with no speech in it — a fan, a keyboard,
music under a screen share, the tail of a call — it does not answer "nothing". It writes the
caption that most often sat over silence in its training data: "Thank you for watching",
"I'll see you in the next one. Bye.", "Subtitles by the Amara.org community". The reported
meeting had exactly these lines, attributed to people who never said them.

Three defences, in the order a clip meets them:

1. **A speech gate** (:func:`has_speech`). Silero VAD — the model faster-whisper bundles — asks
   whether the clip contains any speech at all, and a clip with none is never decoded. It
   *gates* rather than trims: MeetingSense has already cut each utterance at its own pauses,
   and trimming at those edges again is how a line loses its first word. A clip either goes to
   the model whole or not at all. As a side effect the transcriber does no work on noise, which
   keeps it ahead of real time on a CPU.
2. **Decoding options** (:data:`MEETING_OPTIONS`) that stop the model leaning on its own last
   line: ``condition_on_previous_text=False`` is the standard fix for repetition loops, and the
   language is passed in once the meeting has one (see ``meetingsense/language.py``).
3. **A segment filter** (:func:`keep`) applied to what comes back: the model's own
   no-speech/low-confidence rule per segment, the compression-ratio rule for loops, and the
   known silence captions — dropped outright when they are unmistakable, and when the model was
   unsure for the ones a real person might say ("Thank you.", "Bye.").
"""

from __future__ import annotations

import inspect
import logging
import os
import re
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

#: Decoding options for a meeting clip. Filtered against the installed faster-whisper's
#: signature (:func:`supported`), so an older version simply goes without the newer ones.
MEETING_OPTIONS: Dict[str, Any] = {
    "condition_on_previous_text": False,
    "no_speech_threshold": 0.6,
    "log_prob_threshold": -1.0,
    "compression_ratio_threshold": 2.4,
}

#: Silero's speech probability above which a frame is speech. Below the library's 0.5: call
#: audio is compressed and often quiet, and this gate only has to tell speech from no speech.
GATE_THRESHOLD = 0.35
#: Speech shorter than this is a click, a breath, a chair.
GATE_MIN_SPEECH_MS = 200

#: Per-segment rules, matching Whisper's own window-level ones.
NO_SPEECH_DROP = 0.6
LOW_LOGPROB = -1.0
COMPRESSION_DROP = 2.4

#: Captions that are never speech in a meeting. Narrow on purpose: "subscribe" alone is a
#: word people use about their products; "like and subscribe" is a video outro.
_ALWAYS = [
    r"\bthanks? (you )?(so much |very much )?for watching\b",
    r"\bsee you (in|on) the next (one|video|episode)\b",
    r"\b(please (like and )?subscribe|like,? (and|&) subscribe|subscribe to (my|our|the) channel)\b",
    r"\bdon'?t forget to (like|subscribe)\b",
    r"amara\.org",
    r"^\W*[\[(]?\s*(music|applause|laughter|laughs|silence|blank_audio|inaudible|no speech)\s*[\])]?\W*$",
    r"^[\W♪♫]*$",
]
#: Subtitle credits — dropped only as a short line of their own, since "translation from
#: Spanish" or "translated by our team" inside a sentence is a person talking.
_CREDITS = [
    r"^\W*(subtitles?|captions?)( \w+)? (by|from|created by|provided by)\b",
    r"^\W*(transcribed|translated|subtitled) by\b",
]
CREDIT_MAX_WORDS = 10
#: Captions a real person might say, dropped only when the model doubted them.
_IF_UNSURE = [
    r"^(you|thank you|thanks|thank you (so|very) much|bye|bye-bye|bye bye|goodbye|okay bye)[.!?]*$",
]
_ALWAYS_RE = [re.compile(p, re.IGNORECASE) for p in _ALWAYS]
_CREDITS_RE = [re.compile(p, re.IGNORECASE) for p in _CREDITS]
_IF_UNSURE_RE = [re.compile(p, re.IGNORECASE) for p in _IF_UNSURE]


def enabled() -> bool:
    """``MEETINGSENSE_SPEECH_FILTER=0`` turns all three defences off, for comparison."""
    return os.getenv("MEETINGSENSE_SPEECH_FILTER", "1").strip().lower() not in ("0", "false", "off")


def supported(transcribe: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """``options`` minus anything the installed ``transcribe`` does not accept."""
    try:
        params = inspect.signature(transcribe).parameters
    except (TypeError, ValueError):
        return {}
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(options)
    return {k: v for k, v in options.items() if k in params}


def has_speech(path: str) -> Optional[bool]:
    """Whether the clip at ``path`` contains speech; ``None`` when that cannot be told.

    ``None`` means "decode it anyway": a gate that cannot run must never be the reason a line
    goes missing.
    """
    try:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps
    except Exception:  # noqa: BLE001 — an older faster-whisper, or none
        return None
    try:
        audio = decode_audio(path, sampling_rate=16000)
        if audio is None or len(audio) == 0:
            return False
        regions = get_speech_timestamps(
            audio,
            VadOptions(
                threshold=GATE_THRESHOLD,
                min_speech_duration_ms=GATE_MIN_SPEECH_MS,
                min_silence_duration_ms=500,
                speech_pad_ms=0,
            ),
        )
        return bool(regions)
    except Exception as exc:  # noqa: BLE001
        log.debug("speech gate unavailable (%s: %s); decoding the clip", type(exc).__name__, exc)
        return None


def is_silence_caption(text: str, *, unsure: bool) -> bool:
    """Whether ``text`` is one of Whisper's captions for silence (see the module docstring)."""
    line = " ".join(str(text or "").split()).strip()
    if not line:
        return True
    if any(p.search(line) for p in _ALWAYS_RE):
        return True
    if len(line.split()) <= CREDIT_MAX_WORDS and any(p.search(line) for p in _CREDITS_RE):
        return True
    return unsure and any(p.search(line) for p in _IF_UNSURE_RE)


def keep(segment: Any) -> bool:
    """Whether one faster-whisper segment belongs in a meeting transcript."""
    text = (getattr(segment, "text", "") or "").strip()
    if not text:
        return False
    no_speech = _number(getattr(segment, "no_speech_prob", None))
    logprob = _number(getattr(segment, "avg_logprob", None))
    ratio = _number(getattr(segment, "compression_ratio", None))

    if no_speech is not None and no_speech >= NO_SPEECH_DROP and (logprob is None or logprob < -0.5):
        return False
    if logprob is not None and logprob < LOW_LOGPROB and (no_speech is None or no_speech > 0.3):
        return False
    if ratio is not None and ratio > COMPRESSION_DROP:
        return False
    unsure = (no_speech is not None and no_speech > 0.25) or (logprob is not None and logprob < -0.6)
    return not is_silence_caption(text, unsure=unsure)


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None
