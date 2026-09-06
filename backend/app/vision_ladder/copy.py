"""What a person reads when the screen could not be read (batch V6).

One rule shapes every sentence here: **the model's name is not the first thing anybody reads.**

Before this batch the answer to a failed screenshot was some version of "moondream returned no
description of the image" — which tells the user the name of a piece of software they did not
choose, in a sentence that gives them nothing to do about it. The name belongs in exactly one
place: the last message, next to the command that fixes it, once every retry has been spent.

The second rule follows from the first: say which half worked. The screenshot is fine and still
on screen. "I couldn't read it" and "your computer failed" are very different sentences and only
one of them is true.
"""

from __future__ import annotations

from typing import Iterable, List, Optional

#: What the assistant says while the ladder is running. One sentence, present tense, no
#: percentage and no stages — V6 does not know how long its rungs will take and inventing a
#: progress bar for them would be a lie with a UI.
LOOKING = "Let me take a proper look at that screenshot…"

#: Named here rather than inline so RS1's copy and the backend's copy cannot drift.
SETTINGS_PATH = "Settings › Multimodal"


def could_not_read(*, suggestion: Optional[str] = None, tried: Optional[Iterable[str]] = None) -> str:
    """The last rung. The only sentence in the system allowed to name a model.

    ``suggestion`` is a model to **install**, not the one that failed: a name the user can act
    on. Naming the model that just failed reads as blame and leaves them exactly where they
    were.
    """
    lines: List[str] = [
        "I took the screenshot and it's still on screen, but I couldn't make out enough of it "
        "to answer that."
    ]
    if suggestion:
        lines.append(
            f"A stronger vision model would fix it — run `ollama pull {suggestion}`, then pick "
            f"it under {SETTINGS_PATH}."
        )
    else:
        lines.append(
            "Installing a vision model built for reading screens would fix it — "
            f"`ollama pull qwen2.5vl:7b` is a good place to start, then pick it under "
            f"{SETTINGS_PATH}."
        )
    names = [name for name in (tried or []) if name]
    if names:
        # Last, smallest, and phrased as what was done rather than what failed.
        lines.append(f"(Already tried: {', '.join(dict.fromkeys(names))}.)")
    return " ".join(lines)


def no_vision_model() -> str:
    """Nothing installed can look at an image at all. Still not a failure sentence."""
    return (
        "I took the screenshot, but there's no vision model installed to look at it yet. "
        f"Run `ollama pull qwen2.5vl:7b` and pick it under {SETTINGS_PATH}, and I'll be able to "
        "read your screen."
    )
