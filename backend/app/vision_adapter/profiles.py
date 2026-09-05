"""What to do with an image before a vision model sees it (batch V5).

Two profiles, and the difference between them is the only thing that matters:

``screen_overview``
    One image, scaled down to fit a budget. What is on the screen, roughly where. Enough for
    "what am I looking at" and cheap enough to be the first thing tried.

``screen_text``
    The same overview *plus* overlapping tiles at close to native resolution. What the screen
    actually says. This is the profile that answers "what does the error say", because a
    3840×2160 screenshot handed to a model whose vision encoder is a few hundred pixels square
    arrives as a blur of grey where the text was — the model is not too small, the text was
    destroyed before it got there.

**Tiling is gated, and ships off.** Sending four tiles to a model that has never been shown to
reason across several images turns one bad answer into four. The gate is
:func:`supports_multiple_images`, and its verified set is empty: nothing in this repository has
measured a model doing it, and a list of families that "should" work is not a measurement. V8's
bench set is the batch that fills it. Until then an operator who has checked their own model can
name it in ``VISION_MULTI_IMAGE_MODELS`` and get tiles today.

**The numbers are budgets, not model limits.** A vision encoder's internal resolution is not
something this code can discover, so the caps here are chosen to be safe on small models and are
expected to be tuned by V8 against real screenshots. Two rules are not tuning-dependent and hold
for every profile: an image is **never enlarged**, and a screen is re-encoded as **PNG**, because
JPEG's ringing lands exactly on the thin high-contrast strokes that text is made of.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

#: Environment override for the multi-image gate: substrings of model names, comma-separated.
#: An operator who has watched their own model read a tiled screenshot correctly can switch
#: tiling on for it without waiting for us to verify it for them.
MULTI_IMAGE_ENV = "VISION_MULTI_IMAGE_MODELS"

#: Models measured *here* to reason across several images. Deliberately empty — see the module
#: docstring. Adding a name to this set is the whole of "turning tiling on" for that family.
MULTI_IMAGE_VERIFIED: frozenset = frozenset()


@dataclass(frozen=True)
class Profile:
    """A budget and a tiling policy. Instances are the two constants below."""

    name: str
    #: Longest side, in pixels, of the single overview image. Never enlarges.
    max_long_edge: int
    #: Total pixels of the overview, as a second cap for shapes the long edge alone lets past
    #: — an ultrawide 5120×1440 is under a 2000px cap on neither count without this.
    max_megapixels: float
    #: Whether this profile may add detail tiles at all, before the model gate is consulted.
    tile: bool
    #: Longest side of a tile once cropped. Tiles are cropped from the *original*, so this is a
    #: cap and not a target: a tile smaller than this is sent at native resolution.
    tile_long_edge: int = 1100
    #: Fraction of a tile shared with its neighbour. See :func:`tile_boxes` for what it buys.
    overlap: float = 0.14
    #: Total images sent, overview included. Five is an overview plus a 2×2 grid, which is the
    #: smallest split that helps a 16:9 screen: halving it top and bottom leaves each line of
    #: text as wide as it was. A budget rather than a target, because every extra image is
    #: another encoder pass and another few hundred megabytes on a laptop.
    max_parts: int = 5


SCREEN_OVERVIEW = Profile(
    name="screen_overview",
    max_long_edge=1400,
    max_megapixels=1.6,
    tile=False,
)

SCREEN_TEXT = Profile(
    name="screen_text",
    max_long_edge=1400,
    max_megapixels=1.6,
    tile=True,
    tile_long_edge=1100,
    overlap=0.14,
    max_parts=5,
)

#: Anything that is not a screen. Same caps, no tiling: a photograph does not have small text
#: that a downscale destroys, and a document route worth having is a different batch.
PHOTO = Profile(
    name="photo",
    max_long_edge=1400,
    max_megapixels=1.6,
    tile=False,
)

_BY_NAME = {p.name: p for p in (SCREEN_OVERVIEW, SCREEN_TEXT, PHOTO)}


def profile_for(purpose: str, mode: Optional[str] = None) -> Profile:
    """Pick a profile from the caller's ``purpose`` and, for screens, its ``mode``.

    ``mode`` is ``analyze_image``'s existing ``caption | ocr | both``. It already carries the
    distinction the profiles need — somebody asking for OCR is asking to read the text — so the
    call sites do not grow a second, parallel way of saying the same thing.
    """
    if purpose in ("photo", "document"):
        return PHOTO
    if purpose == "screen" and (mode or "").strip().lower() in ("ocr", "both"):
        return SCREEN_TEXT
    return SCREEN_OVERVIEW


def by_name(name: str) -> Optional[Profile]:
    """Look a profile up by the name that appears in ``meta.adapter.profile``."""
    return _BY_NAME.get(name)


def _env_models(environ=None) -> List[str]:
    raw = (environ or os.environ).get(MULTI_IMAGE_ENV, "") or ""
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def supports_multiple_images(model: Optional[str], environ=None) -> bool:
    """Whether *model* may be sent more than one image.

    False for an unknown model, which is every model until somebody measures one. The failure
    this protects against is not a crash — Ollama accepts the array happily — it is a model that
    answers about the last tile it saw as though it were the whole screen, which reads as
    confident and is wrong.
    """
    name = (model or "").strip().lower()
    if not name:
        return False
    if any(marker in name for marker in MULTI_IMAGE_VERIFIED):
        return True
    return any(marker in name for marker in _env_models(environ))


def fit(width: int, height: int, profile: Profile) -> Tuple[int, int]:
    """The size *(w, h)* an image of ``width × height`` is scaled to under ``profile``.

    Aspect ratio is preserved, and the result is never larger than the input in either
    dimension: a 320×200 icon is sent as a 320×200 icon, not blown up to 1400 wide, where the
    only thing the extra pixels add is invented detail.
    """
    if width <= 0 or height <= 0:
        return width, height

    scale = 1.0
    long_edge = max(width, height)
    if long_edge > profile.max_long_edge:
        scale = profile.max_long_edge / float(long_edge)

    budget = profile.max_megapixels * 1_000_000
    pixels = width * height * scale * scale
    if budget > 0 and pixels > budget:
        scale *= (budget / pixels) ** 0.5

    if scale >= 1.0:
        return width, height

    out_w, out_h = max(1, int(round(width * scale))), max(1, int(round(height * scale)))
    if budget > 0 and out_w * out_h > budget:
        # Rounding half up can land a couple of hundred pixels over the cap, and a budget that
        # rounds its way past itself is not a budget. Truncate instead, on the pixel that broke
        # it rather than on every result.
        out_w, out_h = max(1, int(width * scale)), max(1, int(height * scale))
    return out_w, out_h


def grid_for(width: int, height: int, max_tiles: int) -> Tuple[int, int]:
    """``(cols, rows)`` for an image of this shape, within a budget of ``max_tiles`` tiles.

    Shape decides the split, because the thing being split is a screen: an ultrawide is three
    panes side by side and cutting it horizontally as well only halves lines of text that were
    never in danger. A long scrolling page is the same argument turned ninety degrees.
    """
    if max_tiles < 2 or width <= 0 or height <= 0:
        return 1, 1
    aspect = width / float(height)
    if aspect >= 2.1:
        cols, rows = 3, 1
    elif aspect <= 0.5:
        cols, rows = 1, 3
    else:
        cols, rows = 2, 2
    # Over budget, give up the split across the *short* axis first. A wide screen cut into a
    # top half and a bottom half has thrown away the split that was doing the work.
    while cols * rows > max_tiles:
        if aspect >= 1.0 and rows > 1:
            rows -= 1
        elif aspect < 1.0 and cols > 1:
            cols -= 1
        elif cols > 1:
            cols -= 1
        else:
            rows -= 1
    return max(1, cols), max(1, rows)


def tile_boxes(width: int, height: int, cols: int, rows: int, overlap: float) -> List[Tuple[str, Tuple[int, int, int, int]]]:
    """Labelled ``(left, top, right, bottom)`` crops covering the whole image, with overlap.

    The overlap is what makes tiling safe to read text from. With tiles of width *w* stepping by
    ``w × (1 − overlap)``, **anything narrower than ``w × overlap`` falls wholly inside at least
    one tile** — so a line of text, a button, an error string is never split across two crops
    with half of it missing from each. It is a geometric guarantee rather than a hope, and
    ``test_nothing_narrower_than_the_overlap_is_ever_split`` holds this file to it.
    """
    boxes: List[Tuple[str, Tuple[int, int, int, int]]] = []
    if cols < 1 or rows < 1:
        return boxes

    def spans(total: int, count: int) -> List[Tuple[int, int]]:
        if count <= 1:
            return [(0, total)]
        size = total / (count - overlap * (count - 1))
        step = size * (1.0 - overlap)
        out: List[Tuple[int, int]] = []
        for index in range(count):
            start = index * step
            end = min(total, start + size)
            # The last span is pinned to the edge so rounding never leaves a sliver of the
            # screen in no tile at all.
            if index == count - 1:
                start, end = max(0.0, total - size), float(total)
            out.append((int(round(start)), int(round(end))))
        return out

    xs = spans(width, cols)
    ys = spans(height, rows)
    for row, (top, bottom) in enumerate(ys):
        for col, (left, right) in enumerate(xs):
            boxes.append((_label(col, row, cols, rows), (left, top, right, bottom)))
    return boxes


_H = ("left", "center", "right")
_V = ("top", "middle", "bottom")


def _label(col: int, row: int, cols: int, rows: int) -> str:
    """A name a person and a model both read the same way: ``top-left``, ``center``, ``right``."""
    horizontal = _pick(_H, col, cols)
    vertical = _pick(_V, row, rows)
    if cols == 1:
        return vertical or "full"
    if rows == 1:
        return horizontal or "full"
    parts: Sequence[str] = [p for p in (vertical, horizontal) if p]
    return "-".join(parts) or "full"


def _pick(names: Tuple[str, str, str], index: int, count: int) -> str:
    if count <= 1:
        return ""
    if count == 2:
        return names[0] if index == 0 else names[2]
    if index == 0:
        return names[0]
    if index == count - 1:
        return names[2]
    return names[1]
