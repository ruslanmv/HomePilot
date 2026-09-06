"""Is this an answer, or is it the shape of one? (batch V6)

The failure this batch exists for does not look like a failure. A vision model handed a
downscaled 4K screenshot rarely errors — it returns *something*: "An image of a computer
screen.", or "I'm sorry, I can't help with that.", or the same clause four times. The request
succeeded, the JSON is well-formed, and the person asked what the error message said.

So the ladder needs a judgement, not a status code. It is deliberately generous: everything here
costs a retry when it is wrong, never a lost answer, because the ladder keeps the best reply it
saw and returns that rather than discarding it. Being too strict wastes a model call. Being too
lax hands somebody two words of noise and calls it done — which is where this started.
"""

from __future__ import annotations

import re
from typing import Tuple

#: Below this a reply cannot be an answer to a question about a screen. "An image." is 9.
MIN_LENGTH = 24

#: A reply that is mostly punctuation or repeated glyphs is what a model emits when the image
#: told it nothing — the tokens have to come from somewhere.
MIN_ALPHA_FRACTION = 0.45

_REFUSAL = re.compile(
    r"\b(i'?m sorry|i am sorry|i cannot assist|i can'?t assist|i cannot help|i can'?t help"
    r"|as an ai(?: language)? model|i'?m not able to (?:help|assist))\b",
    re.IGNORECASE,
)

_BLIND = re.compile(
    r"\b(no image (?:was )?(?:provided|attached|given)|i (?:cannot|can'?t|am unable to) "
    r"(?:see|view|access|open|read)(?: the| this| any)?(?: image| picture| screenshot| screen)?"
    r"|there is no (?:image|picture|screenshot)|unable to (?:view|process) (?:the |this )?image)\b",
    re.IGNORECASE,
)

#: "A screenshot of a computer screen." — grammatical, true, and no use to anyone. Only counted
#: against a reply that is *also* short, so a long description that happens to open this way is
#: left alone.
_VACUOUS = re.compile(
    r"^(?:this is |here is |the image (?:is|shows) |a |an )?"
    r"(?:image|picture|photo|screenshot|screen ?shot)\b[^.]{0,40}\.?$",
    re.IGNORECASE,
)


def assess(text: str) -> Tuple[bool, str]:
    """``(usable, reason)``. ``reason`` is empty when the reply is usable.

    Reasons are stable strings — ``empty``, ``too-short``, ``refusal``, ``blind``, ``vacuous``,
    ``repetition``, ``not-language`` — because they end up in ``meta.ladder`` and are how anyone
    reading a log later tells the six failure modes apart.
    """
    body = (text or "").strip()
    if not body:
        return False, "empty"
    if _REFUSAL.search(body):
        return False, "refusal"
    if _BLIND.search(body):
        return False, "blind"
    if len(body) < MIN_LENGTH:
        return False, "too-short"
    if len(body) < 80 and _VACUOUS.match(body):
        return False, "vacuous"

    letters = sum(1 for character in body if character.isalpha() or character.isspace())
    if letters / len(body) < MIN_ALPHA_FRACTION:
        return False, "not-language"
    if _looping(body):
        return False, "repetition"
    return True, ""


def _looping(body: str) -> bool:
    """A reply that has run out of things to say and is repeating itself.

    Two shapes, because they come from different places: one word filling the reply (a decoder
    that has lost the plot), and one clause emitted over and over (a model padding to the token
    limit because the image gave it nothing to describe).
    """
    words = re.findall(r"\w+", body.lower())
    if len(words) >= 12:
        most_common = max(set(words), key=words.count)
        if words.count(most_common) / len(words) > 0.4:
            return True

    sentences = [s.strip().lower() for s in re.split(r"[.!?\n]+", body) if len(s.strip()) > 12]
    if len(sentences) >= 3 and len(set(sentences)) <= len(sentences) // 2:
        return True
    return False
