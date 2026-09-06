"""Measuring what a resize did to the text (batch V8).

The plan lists six failure modes that must stay distinguishable, and five of them are already
visible in a response: the model returned nothing, the image would not decode, it was over a
limit, the provider rejected the format, the selected model was ignored. The sixth —
**"the resize damaged OCR resolution"** — is the one that has never had a number attached to it,
and it is the one this whole vision series exists because of. It is why the product used to
answer "try a larger model": nothing could tell a small model from a destroyed image.

So measure the stroke, not the letter. Text is strokes with a font wrapped around them, and what
a downscale does to a screenshot is thin its strokes until they fall below one output pixel and
average into the background. That is arithmetic:

    a bar `w` source pixels wide, scaled by `s`, lands on `w × s` output pixels;
    below about one, its contrast against the ground collapses.

`stroke_survival` finds the bars a corpus case drew, measures each one's remaining contrast in
the adapted image, and reports the narrowest width still legible. The answer is in **source**
pixels, which is the useful unit: "at 3840 wide, strokes under 3px are gone" is a sentence about
the user's screen, and it is what says whether a crop is needed and where the caps belong.

Reading OCR accuracy directly would be better and is not available: it needs a licensed corpus
of real screenshots and an OCR engine whose errors would then be mixed into the measurement.
This measures the thing the adapter actually controls.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

#: Michelson contrast below which a stroke is not a stroke any more. 0.15 is deliberately
#: generous: the question is "did the mark survive at all", not "is it comfortable to read".
LEGIBLE = 0.15


@dataclass
class StrokeReading:
    """One bar width, and what became of it."""

    source_width: int
    output_width: float
    contrast: float

    @property
    def legible(self) -> bool:
        return self.contrast >= LEGIBLE and self.output_width >= 0.9


@dataclass
class Survival:
    """What the adapter's output kept of the strokes that went in."""

    scale: float
    readings: List[StrokeReading]
    #: Narrowest source stroke still legible, or ``None`` when none of them made it.
    finest: Optional[int] = None
    note: str = ""

    def summary(self) -> str:
        if self.note:
            return self.note
        if self.finest is None:
            return "nothing survived"
        return f"{self.finest}px and up"


def _transpose_op():
    from PIL import Image

    return Image.ROTATE_90


def _grey(data: bytes):
    from PIL import Image

    with Image.open(io.BytesIO(data)) as picture:
        return picture.convert("L").copy()


class _Rows:
    """Row access over one flat buffer.

    `getpixel` is a Python call per pixel, and this scans every second row of images up to
    1400×1400 in two orientations. Pulling the whole greyscale plane once and slicing it took a
    bench run from 45 seconds to under three — the same numbers, three orders of magnitude fewer
    interpreter round trips.
    """

    __slots__ = ("data", "width", "height")

    def __init__(self, image):
        self.data = image.tobytes()
        self.width = image.width
        self.height = image.height

    def row(self, y: int) -> Sequence[int]:
        start = y * self.width
        return self.data[start:start + self.width]


def _michelson(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    high, low = max(values), min(values)
    if high + low <= 0:
        return 0.0
    return (high - low) / float(high + low)


def _runs(row: Sequence[int], ground: float, ink_above: bool) -> List[Tuple[int, int, float]]:
    """Contiguous runs of ink in one row, as ``(start, width, peak)``."""
    threshold = ground + (35 if ink_above else -35)
    out: List[Tuple[int, int, float]] = []
    start = None
    peak = 0.0
    for index, value in enumerate(row):
        lit = value > threshold if ink_above else value < threshold
        if lit:
            if start is None:
                start, peak = index, value
            peak = max(peak, value) if ink_above else min(peak, value)
        elif start is not None:
            out.append((start, index - start, peak))
            start = None
    if start is not None:
        out.append((start, len(row) - start, peak))
    return out


def stroke_survival(
    adapted_bytes: bytes,
    *,
    source_widths: Sequence[int],
    scale: float,
    band: Tuple[float, float] = (0.0, 1.0),
) -> Survival:
    """How much of a stroke ruler is left in ``adapted_bytes``.

    The ruler's position moves with every crop, so nothing here depends on knowing where it is.
    The busiest row is found by total absolute difference, its runs of ink are extracted, and the
    run **nearest each expected output width** is the candidate for that bar. A bar that averaged
    into the background leaves no run near its width, and is reported as gone — which is the
    measurement, not an inference from `width × scale`.

    A ruler cropped out of this particular tile simply reports nothing survived, and that is the
    honest answer for that tile.
    """
    if not adapted_bytes:
        return Survival(scale=scale, readings=[], note="no image")
    try:
        grey = _grey(adapted_bytes)
    except Exception:
        return Survival(scale=scale, readings=[], note="not decodable")

    # Both orientations. A ruler of vertical bars becomes a ruler of horizontal ones the moment
    # an EXIF tag turns the picture upright, and a scan that only reads rows then measures the
    # gaps between bars instead of the bars — which reported 6px for a case that keeps 2px.
    best_row, best_energy = None, -1.0
    for source in (grey, grey.transpose(_transpose_op())):
        rows = _Rows(source)
        top = max(0, int(rows.height * band[0]))
        bottom = min(rows.height, max(top + 1, int(rows.height * band[1])))
        for y in range(top, bottom, 2):
            row = rows.row(y)
            energy = sum(abs(row[i + 1] - row[i]) for i in range(len(row) - 1))
            if energy > best_energy:
                best_row, best_energy = row, energy

    if best_row is None:
        return Survival(scale=scale, readings=[], note="no rows to read")

    ground = sorted(best_row)[len(best_row) // 2]  # the median is the page, not the marks
    light_marks = (sum(best_row) / len(best_row)) >= ground
    runs = _runs(best_row, ground, ink_above=light_marks)
    if not runs:
        return Survival(scale=scale, readings=[
            StrokeReading(source_width=w, output_width=w * scale, contrast=0.0) for w in source_widths
        ])

    readings: List[StrokeReading] = []
    for width in source_widths:
        want = width * scale
        # Nearest run by width. Ties go to the narrower one, which is the conservative reading.
        start, run_width, peak = min(runs, key=lambda r: (abs(r[1] - want), r[1]))
        if abs(run_width - want) > max(1.0, want * 0.75):
            # Nothing anywhere near this width is left in the row: the bar is gone.
            readings.append(StrokeReading(source_width=width, output_width=want, contrast=0.0))
            continue
        contrast = _michelson([peak, ground])
        readings.append(StrokeReading(source_width=width, output_width=want, contrast=contrast))

    legible = [r.source_width for r in readings if r.legible]
    return Survival(scale=scale, readings=readings, finest=min(legible) if legible else None)


def finest_legible_stroke(survival: Survival) -> Optional[int]:
    """Shorthand for the number that matters: the thinnest source stroke still readable."""
    return survival.finest
