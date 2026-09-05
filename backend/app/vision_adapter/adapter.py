"""The adapter itself (batch V4).

Deliberately boring. It measures, records and hands the bytes back.

The measurement is the deliverable: `meta.adapter` gives the six failure modes in the plan
somewhere to be distinguished. Without it, "the model returned nothing" and "the image was a
40-megapixel screenshot" and "the resize destroyed the text" all arrive as the same silence.

Pillow is used when it is installed and is not required. HomePilot runs on machines without it,
and a vision request must not start failing because an optional measurement could not be taken
— an unmeasured image is passed through with ``width: None``, which is honest and harmless.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: What a caller is doing with the image. V5 gives these different behaviour; today they are
#: recorded so that the day they diverge, the logs already say which was asked for.
PURPOSES = ("screen", "photo", "document")

#: The only strategy V4 has. Named rather than implied, so `meta.adapter.strategy` reads the
#: same before and after V5 and a reader can tell which one ran.
PASSTHROUGH = "passthrough"


@dataclass
class AdaptedImage:
    """Bytes for the model, plus everything that was true about them on the way in."""

    data: bytes
    mime_type: str
    strategy: str = PASSTHROUGH
    width: Optional[int] = None
    height: Optional[int] = None
    original_width: Optional[int] = None
    original_height: Optional[int] = None
    original_bytes: int = 0
    tiles: int = 1
    warnings: List[str] = field(default_factory=list)

    @property
    def scale(self) -> float:
        """How much the image was reduced. Always 1.0 while ``passthrough`` is the only path."""
        if not self.original_width or not self.width:
            return 1.0
        return round(self.width / float(self.original_width), 4)

    def meta(self) -> Dict[str, Any]:
        """The block that goes into an analysis response under ``adapter``."""
        return {
            "strategy": self.strategy,
            "width": self.width,
            "height": self.height,
            "original_width": self.original_width,
            "original_height": self.original_height,
            "original_bytes": self.original_bytes,
            "bytes": len(self.data),
            "scale": self.scale,
            "tiles": self.tiles,
            "warnings": list(self.warnings),
        }


def _measure(data: bytes) -> tuple[Optional[int], Optional[int], Optional[str]]:
    """``(width, height, mime)`` — any of them ``None`` when they cannot be read.

    Never raises. A measurement is a nice-to-have; a vision request that failed because an
    optional library could not decode a frame would be a worse product than one that says
    ``width: null``.
    """
    try:
        from PIL import Image
    except Exception:
        return None, None, None
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = (image.format or "").lower()
            mime = f"image/{'jpeg' if fmt == 'jpg' else fmt}" if fmt else None
            return image.width, image.height, mime
    except Exception:
        return None, None, None


def adapt(
    data: bytes,
    *,
    mime_type: str = "image/png",
    model: Optional[str] = None,
    purpose: str = "screen",
) -> AdaptedImage:
    """Take an image to a vision model. Today: measure it and hand it straight back.

    ``model`` is accepted and unused. V5 reads it to pick a profile, and taking it now means
    every call site is already passing it when that happens — a seam whose signature changes
    on the day it does something is four call sites of churn, not a seam.
    """
    payload = data or b""
    width, height, sniffed = _measure(payload)

    warnings: List[str] = []
    if not payload:
        warnings.append("empty")
    if purpose not in PURPOSES:
        # Recorded rather than rejected: an unknown purpose is a caller that has not been
        # updated, and refusing its image would break it for a label.
        warnings.append(f"unknown-purpose:{purpose}")
    if width is None and payload:
        warnings.append("unmeasured")

    return AdaptedImage(
        data=payload,
        # A sniffed type beats a declared one: `/upload` maps by file extension, and an
        # extension is what somebody typed.
        mime_type=sniffed or mime_type or "image/png",
        strategy=PASSTHROUGH,
        width=width,
        height=height,
        original_width=width,
        original_height=height,
        original_bytes=len(payload),
        tiles=1,
        warnings=warnings,
    )


def describe(adapted: Optional[AdaptedImage]) -> Dict[str, Any]:
    """``adapter`` metadata for a response, or ``{}`` when nothing passed through."""
    return adapted.meta() if adapted else {}
