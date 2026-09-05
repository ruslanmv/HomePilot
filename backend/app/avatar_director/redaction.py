"""Memory redaction in the adult tier (spec v1.1 §16.5, batch B28).

What she is allowed to remember about an intimate evening is *that it went well and what
pace you liked*, and nothing else.

## The distinction this module draws

There are two kinds of thing a memory write could carry out of an adult-tier session:

  * a **warmth signal** — "enjoyed date night", "prefers slow pacing", "asked to slow down
    twice". These are what make the next evening feel like a relationship rather than a
    script, they are what §6.12's curiosity is for, and they are safe to keep;
  * an **explicit detail** — what was said, what was shown, what happened. This is the part
    that must never reach the store, because a companion's long-term memory is a file on a
    disk that can be read by anyone with the disk, and because the user did not agree to a
    transcript when they agreed to an evening.

The split is not "sanitise the text". It is **allow-list the shape**: a redacted record keeps
a small, fixed set of fields with values drawn from a closed vocabulary, and free text is
dropped entirely rather than filtered. A filter is a blocklist wearing a hat, and a blocklist
on natural language loses.

## Why an allow-list rather than a scrubber

A scrubber has to be right about every phrasing, forever, in every language. An allow-list
has to be right once. So :func:`redact` does not look for words to remove; it builds a new
record from the fields it recognises and discards the rest, and the test that matters asserts
the *original* strings are absent from the output rather than that particular ones are.

## When it applies

Every memory write made while ``mode == 'adult'``, without exception, including the ones a
future batch adds. :func:`should_redact` is the one predicate and it takes the mode, so a
caller cannot get it subtly wrong — and B16's curiosity engine routes through here.

Pure module: no FastAPI, no I/O, no clock.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("avatar_director.redaction")

#: The mode this applies in. One string, named once.
ADULT_MODE = "adult"

#: The only fields a redacted record may carry. Everything else is dropped — see the header.
ALLOWED_FIELDS = ("topic", "warmth", "pacing", "checkins", "softExits", "durationBucket", "at")

#: The closed vocabulary for `warmth`. A free-text warmth signal is a transcript in disguise.
WARMTH = ("positive", "neutral", "mixed", "declined")

#: And for `pacing`. These are the words §16.5 uses; a deployment that wants more adds them
#: here, where a reviewer can see the whole list at once.
PACING = ("slow", "steady", "unhurried", "varied")

#: Duration is bucketed rather than recorded. "47 minutes" is a fact about an evening;
#: "short" is a fact about a preference.
DURATION_BUCKETS = ("brief", "short", "medium", "long")

#: The topic key an adult-tier record is filed under. Fixed, so a topic name cannot itself
#: become the detail — "user.intimate.<something they said>" would leak through the key.
TOPIC = "relationship.evening"


def should_redact(mode: Optional[str]) -> bool:
    """The one predicate. Takes the mode so a caller cannot get it subtly wrong."""
    return (mode or "").strip().lower() == ADULT_MODE


def _clamp(value: Any, allowed: Tuple[str, ...], default: str) -> str:
    """A value from a closed vocabulary, or the default. Never the caller's string."""
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _count(value: Any) -> int:
    try:
        return max(0, min(99, int(value)))
    except (TypeError, ValueError):
        return 0


def redact(record: Dict[str, Any]) -> Dict[str, Any]:
    """Build a safe record from an unsafe one.

    Constructive, not subtractive: nothing is copied across unless it is one of
    :data:`ALLOWED_FIELDS` *and* its value survives being clamped to a closed vocabulary. A
    field this module has never heard of cannot appear in the output, which is the property
    that makes it hold for the fields a future batch invents.
    """
    source = record if isinstance(record, dict) else {}
    return {
        "topic": TOPIC,
        "warmth": _clamp(source.get("warmth"), WARMTH, "neutral"),
        "pacing": _clamp(source.get("pacing"), PACING, "unhurried"),
        "checkins": _count(source.get("checkins")),
        "softExits": _count(source.get("softExits")),
        "durationBucket": _clamp(source.get("durationBucket"), DURATION_BUCKETS, "short"),
    }


def redact_write(mode: Optional[str], category: str, key: str, value: Any) -> Optional[Dict[str, Any]]:
    """One memory write, redacted if the mode calls for it.

    Returns ``None`` when the write must not happen at all — an adult-tier write to any
    category other than the interest store has no redacted form, so it is refused rather
    than reshaped. Reshaping it would mean guessing what a category the tier does not own is
    for, and guessing is how detail escapes.
    """
    if not should_redact(mode):
        return {"category": category, "key": key, "value": value}

    if category not in ("interest",):
        log.info("adult-tier write to category %r refused — no redacted form exists", category)
        return None

    payload = value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            payload = {}

    safe = redact(payload if isinstance(payload, dict) else {})
    return {
        "category": category,
        # The key is fixed too: `user.intimate.<something they said>` would leak through it.
        "key": TOPIC,
        "value": json.dumps(safe, separators=(",", ":"), sort_keys=True),
    }


def leaks(original: Dict[str, Any], redacted: Dict[str, Any], *, min_length: int = 4) -> List[str]:
    """Any word from the original that survived into the redacted record.

    The test helper this module exists to satisfy, and deliberately blunt: it does not check
    that particular phrases were removed, it checks that *nothing from the input* is in the
    output beyond the closed vocabularies. A redactor that passed a phrasing this file had
    never seen would fail here.
    """
    haystack = json.dumps(redacted, sort_keys=True).lower()
    vocabulary = {w.lower() for w in (*WARMTH, *PACING, *DURATION_BUCKETS, *ALLOWED_FIELDS)}
    vocabulary.update(TOPIC.lower().split("."))

    found = []
    for word in re.findall(r"[A-Za-z']+", json.dumps(original, sort_keys=True)):
        lowered = word.lower()
        if len(lowered) < min_length or lowered in vocabulary:
            continue
        if lowered in haystack:
            found.append(word)
    return sorted(set(found))


__all__ = [
    "ADULT_MODE",
    "ALLOWED_FIELDS",
    "DURATION_BUCKETS",
    "PACING",
    "TOPIC",
    "WARMTH",
    "leaks",
    "redact",
    "redact_write",
    "should_redact",
]
