"""The bench corpus (batch V8), generated rather than committed.

Every case here is drawn with Pillow from a fixed description, so the corpus is reviewable as
code, weighs nothing in the repository, and cannot rot into a set of PNGs nobody remembers the
provenance of. A screenshot of somebody's actual desktop would be a better sample and a worse
fixture: it cannot be checked into a public repository, it cannot be regenerated at a different
size, and nobody can tell from looking at it what it is supposed to be testing.

The trade is stated plainly: these are **synthetic** screens. They have the geometry of the real
thing — a terminal's line pitch, a code editor's gutter, a settings dialog's rows — and hairline
strokes at known widths, which is what the measurements in ``metrics.py`` need. They do not have
subpixel antialiasing, JPEG history, or a real font stack. A number measured here is a number
about this corpus; the plan's caps are tuned against it because it is reproducible, not because
it is reality.

The list is the plan's, one case per entry:

    desktop · code error · browser page · settings window · terminal · dense terminal text ·
    SVG · 1920×1080 · 2560×1440 · 3840×2160 · ultrawide 5120×1440 · very tall page ·
    multi-monitor as one surface · tiny image that must not be enlarged · transparent PNG ·
    EXIF-rotated JPEG · animated GIF · animated WebP · corrupt bytes · decompression bomb
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

#: A dark editor-ish palette. Screens are mostly dark these days and dark is the harder case for
#: a downscale: thin light glyphs on a dark ground lose contrast faster than the reverse.
INK = (232, 236, 242)
GROUND = (16, 20, 27)
CHROME = (30, 36, 46)
ACCENT = (34, 211, 238)
WARN = (248, 113, 113)


#: Rendered bytes by case name. See `Case.bytes`.
_RENDERED: Dict[str, bytes] = {}


@dataclass
class Case:
    """One bench image, plus what it is meant to prove."""

    name: str
    #: What the case exists to catch. Read this before changing a case; a case whose purpose is
    #: not written down becomes a case nobody dares delete.
    asks: str
    build: Callable[[], bytes]
    width: int = 0
    height: int = 0
    mime: str = "image/png"
    purpose: str = "screen"
    mode: str = "ocr"
    #: Stroke widths, in source pixels, that the case draws and that `metrics` looks for.
    strokes: Tuple[int, ...] = ()
    tags: Tuple[str, ...] = ()

    def bytes(self) -> bytes:
        """The case's image, built once per process and kept.

        The cache is keyed by name at module level rather than held on the instance, because
        `cases()` returns fresh objects every call and the bench asks for them repeatedly. The
        decompression-bomb case allocates roughly 300 MB to draw; without this, a test session
        spent two and a half minutes redrawing one row.

        Caching is safe because a case is a pure description — the same name always renders the
        same bytes, which is also what makes a measured number comparable between runs.
        """
        if self.name not in _RENDERED:
            _RENDERED[self.name] = self.build()
        return _RENDERED[self.name]


def _image(width: int, height: int, mode: str = "RGB", ground=GROUND):
    from PIL import Image

    return Image.new(mode, (width, height), ground if mode != "RGBA" else ground + (255,))


def _encode(image, fmt: str = "PNG", **kwargs) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


# ── the pieces real screens are made of ─────────────────────────────────────


def _stroke_ruler(draw, x: int, y: int, widths=(1, 2, 3, 4, 6), height: int = 60, gap: int = 14):
    """Vertical bars at known widths — the measurable stand-in for glyph strokes.

    Text is strokes with a font wrapped around it. A downscale destroys a screenshot's text by
    thinning its strokes below one output pixel, and that is a thing with a number: after the
    adapter has run, `metrics.stroke_survival` looks for these bars and reports the narrowest
    one still there. Measuring the real thing needs OCR and a corpus nobody can ship; measuring
    the stroke needs arithmetic.
    """
    cursor = x
    for width in widths:
        draw.rectangle([cursor, y, cursor + width - 1, y + height], fill=INK)
        cursor += width + gap
    return cursor


def _fake_text(draw, x: int, y: int, columns: int, *, pitch: int = 11, weight: int = 2,
               colour=INK, length: int = 0):
    """A line of text-shaped marks: `weight`-wide strokes on a `pitch`-pixel rhythm.

    Not a font. A font would make the corpus depend on what is installed on the machine running
    it, and the measurements would move when that changed.
    """
    span = length or columns * pitch
    cursor = x
    index = 0
    while cursor < x + span:
        if index % 7 != 6:  # a gap every seventh position reads as a word break
            draw.rectangle([cursor, y, cursor + weight - 1, y + 9], fill=colour)
        cursor += pitch
        index += 1
    return y + 16


def _window(draw, box, title_height: int = 34):
    left, top, right, bottom = box
    draw.rectangle([left, top, right, bottom], fill=CHROME, outline=(58, 68, 84))
    draw.rectangle([left, top, right, top + title_height], fill=(22, 27, 35))
    for index in range(3):
        cx = left + 16 + index * 18
        cy = top + title_height // 2
        draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=(70, 82, 100))
    return top + title_height


# ── the cases ───────────────────────────────────────────────────────────────


def _desktop(width: int, height: int):
    def build() -> bytes:
        from PIL import ImageDraw

        picture = _image(width, height)
        draw = ImageDraw.Draw(picture)
        # A taskbar, two windows, and a stroke ruler in each — a screen with things at
        # different scales, which is what makes one global downscale a compromise.
        draw.rectangle([0, height - 46, width, height], fill=CHROME)
        _fake_text(draw, 14, height - 32, 26, pitch=9, weight=2)

        body = _window(draw, [int(width * 0.05), int(height * 0.08), int(width * 0.52), int(height * 0.62)])
        _stroke_ruler(draw, int(width * 0.07), body + 18)
        line = body + 100
        for _ in range(8):
            line = _fake_text(draw, int(width * 0.07), line, 34)

        body = _window(draw, [int(width * 0.55), int(height * 0.20), int(width * 0.95), int(height * 0.86)])
        _stroke_ruler(draw, int(width * 0.57), body + 18)
        line = body + 100
        for _ in range(10):
            line = _fake_text(draw, int(width * 0.57), line, 28, colour=ACCENT)
        return _encode(picture)

    return build


def _code_error(width: int, height: int):
    def build() -> bytes:
        from PIL import ImageDraw

        picture = _image(width, height)
        draw = ImageDraw.Draw(picture)
        draw.rectangle([0, 0, 58, height], fill=(22, 27, 35))  # gutter
        _stroke_ruler(draw, 80, 20)
        line = 100
        for index in range(18):
            _fake_text(draw, 22, line, 2, pitch=9, weight=2, colour=(90, 100, 116))  # line number
            line = _fake_text(draw, 78, line, 30 + (index % 9) * 4)
        # The error, in red, at the bottom — the thing somebody actually asks about.
        draw.rectangle([0, height - 120, width, height], fill=(30, 18, 20))
        _fake_text(draw, 22, height - 100, 46, colour=WARN)
        _fake_text(draw, 22, height - 78, 52, colour=WARN)
        _stroke_ruler(draw, 22, height - 56, widths=(1, 2, 3), height=28, gap=10)
        return _encode(picture)

    return build


def _browser(width: int, height: int):
    def build() -> bytes:
        from PIL import ImageDraw

        picture = _image(width, height, ground=(248, 249, 251))
        draw = ImageDraw.Draw(picture)
        draw.rectangle([0, 0, width, 92], fill=(226, 230, 237))
        draw.rounded_rectangle([120, 26, width - 120, 66], 14, fill=(255, 255, 255))
        _fake_text(draw, 140, 38, 40, pitch=8, weight=2, colour=(40, 46, 58))
        # Dark ink on a light ground: the other polarity, which downscales differently.
        _stroke_ruler(draw, 60, 130)
        line = 220
        for index in range(14):
            line = _fake_text(draw, 60, line, 60 - (index % 5) * 6, colour=(28, 32, 40))
        return _encode(picture)

    return build


def _settings(width: int, height: int):
    def build() -> bytes:
        from PIL import ImageDraw

        picture = _image(width, height)
        draw = ImageDraw.Draw(picture)
        body = _window(draw, [0, 0, width - 1, height - 1])
        draw.rectangle([0, body, 260, height], fill=(22, 27, 35))
        line = body + 24
        for _ in range(9):
            line = _fake_text(draw, 24, line, 16) + 12
        # Rows of label/control pairs: small text next to a toggle, at settings-dialog pitch.
        line = body + 28
        for index in range(11):
            _fake_text(draw, 300, line, 22)
            draw.rounded_rectangle([width - 120, line - 2, width - 68, line + 20], 11,
                                   fill=ACCENT if index % 3 == 0 else (60, 70, 86))
            line += 40
        _stroke_ruler(draw, 300, height - 90, widths=(1, 2, 3, 4), height=44, gap=12)
        return _encode(picture)

    return build


def _terminal(width: int, height: int, *, dense: bool = False):
    def build() -> bytes:
        from PIL import ImageDraw

        picture = _image(width, height, ground=(8, 10, 14))
        draw = ImageDraw.Draw(picture)
        pitch = 7 if dense else 10
        weight = 1 if dense else 2
        step = 12 if dense else 18
        line = 16
        index = 0
        while line < height - 70:
            colour = ACCENT if index % 6 == 0 else INK
            _fake_text(draw, 14, line, 0, pitch=pitch, weight=weight, colour=colour,
                       length=width - 40 - (index % 11) * 30)
            line += step
            index += 1
        _stroke_ruler(draw, 14, height - 60, widths=(1, 2, 3), height=40, gap=9)
        return _encode(picture)

    return build


def _svg_like(width: int, height: int):
    def build() -> bytes:
        from PIL import ImageDraw

        # A rasterised vector diagram: flat fills, hairline rules, small labels. What arrives at
        # the adapter is always a raster — nothing hands a vision model an SVG — so the case is
        # about hairlines surviving, not about SVG parsing.
        picture = _image(width, height, ground=(252, 252, 253))
        draw = ImageDraw.Draw(picture)
        for index in range(6):
            x = 60 + index * (width - 140) // 6
            draw.rectangle([x, 120, x + 90, 120 + 40 + index * 30], fill=(90, 130, 200))
            _fake_text(draw, x, 90, 8, pitch=7, weight=1, colour=(30, 34, 42))
        for index in range(9):  # hairline grid, one pixel each
            y = 120 + index * 40
            draw.line([40, y, width - 40, y], fill=(200, 205, 214), width=1)
        _stroke_ruler(draw, 60, height - 120, widths=(1, 1, 2, 2, 3), height=60, gap=16)
        return _encode(picture)

    return build


def _multi_monitor(width: int, height: int):
    def build() -> bytes:
        from PIL import ImageDraw

        # Two screens captured as one surface: the seam matters because a tiling grid that puts
        # a boundary on it splits nothing, and one that puts a boundary elsewhere splits a window.
        picture = _image(width, height)
        draw = ImageDraw.Draw(picture)
        half = width // 2
        draw.rectangle([half - 2, 0, half + 2, height], fill=(0, 0, 0))
        for offset in (0, half):
            body = _window(draw, [offset + 40, 60, offset + half - 40, height - 60])
            _stroke_ruler(draw, offset + 70, body + 20)
            line = body + 100
            for _ in range(9):
                line = _fake_text(draw, offset + 70, line, 30)
        return _encode(picture)

    return build


def _tiny():
    def build() -> bytes:
        from PIL import ImageDraw

        picture = _image(96, 64)
        draw = ImageDraw.Draw(picture)
        _stroke_ruler(draw, 6, 8, widths=(1, 2, 3), height=30, gap=8)
        return _encode(picture)

    return build


def _transparent():
    def build() -> bytes:
        from PIL import ImageDraw

        # Deliberately over the long-edge cap: an alpha image *under* the caps is passed through
        # untouched and proves nothing about the re-encode, which is where alpha would be lost.
        picture = _image(2400, 1500, mode="RGBA", ground=(0, 0, 0))
        picture.putalpha(0)
        draw = ImageDraw.Draw(picture)
        draw.rectangle([160, 160, 2240, 1340], fill=(20, 24, 32, 255))
        _stroke_ruler(draw, 220, 220)
        line = 360
        for _ in range(12):
            line = _fake_text(draw, 220, line, 44)
        return _encode(picture)

    return build


def _rotated():
    def build() -> bytes:
        from PIL import Image, ImageDraw

        picture = Image.new("RGB", (2400, 1350), GROUND)
        draw = ImageDraw.Draw(picture)
        _stroke_ruler(draw, 60, 60)
        line = 200
        for _ in range(14):
            line = _fake_text(draw, 60, line, 60)
        exif = picture.getexif()
        exif[274] = 6  # rotate 90° clockwise on display
        buffer = io.BytesIO()
        picture.save(buffer, format="JPEG", quality=92, exif=exif)
        return buffer.getvalue()

    return build


def _animated(fmt: str):
    def build() -> bytes:
        from PIL import Image, ImageDraw

        frames = []
        for index in range(4):
            picture = Image.new("RGB", (1200, 800), GROUND)
            draw = ImageDraw.Draw(picture)
            draw.rectangle([80 + index * 40, 80, 380 + index * 40, 380], fill=ACCENT)
            _stroke_ruler(draw, 80, 460)
            frames.append(picture)
        buffer = io.BytesIO()
        frames[0].save(buffer, format=fmt, save_all=True, append_images=frames[1:], duration=120, loop=0)
        return buffer.getvalue()

    return build


def _corrupt():
    def build() -> bytes:
        # A real PNG header followed by nothing that decodes. Truncation is what a half-finished
        # upload and a dropped socket both look like, and both reach this code.
        return b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 24

    return build


def _empty():
    def build() -> bytes:
        return b""

    return build


def _bomb():
    def build() -> bytes:
        from PIL import Image, ImageDraw

        # 10000×10000 = 100 megapixels, over Pillow's default MAX_IMAGE_PIXELS. Flat colour, so
        # it compresses to a few kilobytes on disk and expands to ~300 MB in memory — which is the
        # whole point of the case: byte count says nothing about what decoding will cost.
        picture = Image.new("RGB", (10000, 10000), GROUND)
        draw = ImageDraw.Draw(picture)
        _stroke_ruler(draw, 100, 100, height=400, gap=40)
        return _encode(picture)

    return build


def cases() -> List[Case]:
    """Every bench case, in the plan's order."""
    strokes = (1, 2, 3, 4, 6)
    out: List[Case] = [
        Case("desktop-1920", "one screen, several windows, at the size most people run",
             _desktop(1920, 1080), 1920, 1080, strokes=strokes, tags=("screen", "hd")),
        Case("desktop-2560", "the same screen with more pixels and the same physical text size",
             _desktop(2560, 1440), 2560, 1440, strokes=strokes, tags=("screen", "qhd")),
        Case("desktop-3840", "4K, where a single downscale to a model's budget hurts most",
             _desktop(3840, 2160), 3840, 2160, strokes=strokes, tags=("screen", "4k")),
        Case("code-error", "the actual question: what does the red text at the bottom say",
             _code_error(2560, 1440), 2560, 1440, strokes=(1, 2, 3), tags=("text", "qhd")),
        Case("browser-page", "dark ink on a light ground — the other polarity",
             _browser(1920, 1200), 1920, 1200, strokes=strokes, tags=("text", "light")),
        Case("settings-window", "small labels beside controls, at dialog pitch",
             _settings(1280, 900), 1280, 900, strokes=(1, 2, 3, 4), tags=("ui",)),
        Case("terminal", "monospaced lines, the densest legible thing on a screen",
             _terminal(1920, 1080), 1920, 1080, strokes=(1, 2, 3), tags=("text",)),
        Case("terminal-dense", "the same at a smaller pitch and hairline weight",
             _terminal(2560, 1440, dense=True), 2560, 1440, strokes=(1, 2, 3), tags=("text", "hard")),
        Case("svg-diagram", "flat fills and one-pixel rules, which a resize eats first",
             _svg_like(1600, 1000), 1600, 1000, strokes=(1, 2, 3), tags=("vector",)),
        Case("ultrawide", "5120×1440: passes a long-edge cap on aspect and fails on pixels",
             _desktop(5120, 1440), 5120, 1440, strokes=strokes, tags=("screen", "ultrawide")),
        Case("very-tall-page", "a long scrolling capture, where a wide split helps nothing",
             _browser(1200, 4200), 1200, 4200, strokes=strokes, tags=("text", "tall")),
        Case("multi-monitor", "two screens as one surface, with a seam a tiling grid can miss",
             _multi_monitor(3840, 1080), 3840, 1080, strokes=strokes, tags=("screen", "seam")),
        Case("tiny-icon", "96×64: must come back untouched, never enlarged",
             _tiny(), 96, 64, strokes=(1, 2, 3), tags=("small",)),
        Case("transparent-png", "alpha over the caps, so the re-encode actually runs on it",
             _transparent(), 2400, 1500, strokes=strokes, tags=("alpha",)),
        Case("exif-rotated", "tagged rotate-90: 2400×1350 on disk, 1350×2400 to a person",
             _rotated(), 2400, 1350, mime="image/jpeg", purpose="photo", mode="caption",
             strokes=strokes, tags=("exif",)),
        Case("animated-gif", "several frames where the model gets one",
             _animated("GIF"), 1200, 800, mime="image/gif", strokes=strokes, tags=("animated",)),
        Case("animated-webp", "the same in the format a modern capture produces",
             _animated("WEBP"), 1200, 800, mime="image/webp", strokes=strokes, tags=("animated",)),
        Case("corrupt-bytes", "a truncated upload, which must not become a 500",
             _corrupt(), 0, 0, tags=("broken",)),
        Case("empty-bytes", "nothing at all, which is a different failure from unreadable",
             _empty(), 0, 0, tags=("broken",)),
        Case("decompression-bomb", "100 megapixels from a few kilobytes on disk",
             _bomb(), 10000, 10000, strokes=strokes, tags=("bomb", "hostile")),
    ]
    return out


def by_name() -> Dict[str, Case]:
    return {case.name: case for case in cases()}
