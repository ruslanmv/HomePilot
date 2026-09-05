"""The adapter itself (batches V4, V5).

V4 made this the one place every image passes through and had it do nothing. V5 gives it two
things to do, and they are the two that decide whether a vision answer is any good:

* **fit the image to a budget** — aspect preserved, never enlarged, re-encoded as PNG for a
  screen. An 8-megapixel screenshot is not "too big for the model" in the sense the old error
  message implied; it is an image whose text has already been destroyed by the time the model's
  own encoder is finished with it.
* **tile it, when the model can take it** — overlapping crops at close to native resolution, so
  the text survives. Gated on :func:`profiles.supports_multiple_images`, which is False for
  every model until one is measured, because four tiles to a model that cannot reason across
  images is one bad answer turned into four.

Pillow is used when it is installed and is never required. Without it the adapter degrades to
exactly V4 — measure nothing, pass the bytes through, say so in ``warnings`` — because a vision
request that started failing over an optional dependency would be a worse product than one that
answers from the original image.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import profiles as _profiles
from .profiles import Profile, profile_for, supports_multiple_images  # noqa: F401 — re-exported

#: What a caller is doing with the image. Kept as the caller-facing vocabulary; the mapping from
#: one of these to a :class:`~.profiles.Profile` lives in :func:`profiles.profile_for`.
PURPOSES = ("screen", "photo", "document")

#: Strategies, named so ``meta.adapter.strategy`` says which path ran.
PASSTHROUGH = "passthrough"
RESIZED = "resized"
TILED = "tiled"


@dataclass
class Part:
    """One image on the way to the model, and the name the prompt refers to it by."""

    data: bytes
    mime_type: str
    label: str = "overview"
    width: Optional[int] = None
    height: Optional[int] = None

    def meta(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "width": self.width,
            "height": self.height,
            "bytes": len(self.data),
            "mime_type": self.mime_type,
        }


@dataclass
class AdaptedImage:
    """Everything sent to the model, plus everything true about what came in."""

    parts: List[Part] = field(default_factory=list)
    strategy: str = PASSTHROUGH
    profile: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    original_width: Optional[int] = None
    original_height: Optional[int] = None
    original_bytes: int = 0
    warnings: List[str] = field(default_factory=list)

    # `data` and `mime_type` are the first part. They are properties rather than a second copy
    # of the same bytes so that the single-image callers written against V4 keep working and
    # cannot drift out of step with `parts`.
    @property
    def data(self) -> bytes:
        return self.parts[0].data if self.parts else b""

    @property
    def mime_type(self) -> str:
        return self.parts[0].mime_type if self.parts else "image/png"

    @property
    def tiles(self) -> int:
        """How many images the model is being sent. 1 whenever tiling did not run."""
        return len(self.parts) or 1

    @property
    def scale(self) -> float:
        """How much the overview was reduced. 1.0 when nothing was resized."""
        if not self.original_width or not self.width:
            return 1.0
        return round(self.width / float(self.original_width), 4)

    def meta(self) -> Dict[str, Any]:
        """The block that goes into an analysis response under ``adapter``."""
        return {
            "strategy": self.strategy,
            "profile": self.profile,
            "width": self.width,
            "height": self.height,
            "original_width": self.original_width,
            "original_height": self.original_height,
            "original_bytes": self.original_bytes,
            "bytes": sum(len(p.data) for p in self.parts),
            "scale": self.scale,
            "tiles": self.tiles,
            "parts": [p.meta() for p in self.parts],
            "warnings": list(self.warnings),
        }


def _pillow():
    """Pillow's ``Image`` module, or ``None``. Never raises."""
    try:
        from PIL import Image

        return Image
    except Exception:
        return None


def _measure(data: bytes) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    """``(width, height, mime)`` — any of them ``None`` when they cannot be read.

    Never raises. A measurement is a nice-to-have; a vision request that failed because an
    optional library could not decode a frame would be a worse product than one that says
    ``width: null``.
    """
    Image = _pillow()
    if Image is None:
        return None, None, None
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = (image.format or "").lower()
            mime = f"image/{'jpeg' if fmt == 'jpg' else fmt}" if fmt else None
            return image.width, image.height, mime
    except Exception:
        return None, None, None


def _encode(image, mime_hint: str) -> Tuple[bytes, str]:
    """PNG for anything screen-shaped, and that is not a stylistic preference.

    JPEG's ringing artefacts land on high-contrast edges, and at the sizes a screenshot gets
    downscaled to, a glyph stroke *is* a high-contrast edge one or two pixels wide. Re-encoding
    a screen as JPEG damages precisely the thing the user is asking the model to read.

    The exception is a photograph large enough that PNG becomes absurd, where the fallback keeps
    quality high enough that the artefacts stay well below anything a caption depends on.
    """
    buffer = io.BytesIO()
    if image.mode not in ("RGB", "RGBA", "L"):
        image = image.convert("RGBA" if "A" in image.mode else "RGB")
    try:
        image.save(buffer, format="PNG", optimize=True)
    except Exception:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=92)
        return buffer.getvalue(), "image/jpeg"

    data = buffer.getvalue()
    if len(data) > _PNG_CEILING and mime_hint == "image/jpeg":
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=92)
        return buffer.getvalue(), "image/jpeg"
    return data, "image/png"


#: Above this, a PNG of a *photograph* is re-encoded as JPEG. Screens are never re-encoded as
#: JPEG regardless of size — a screenshot that large is exactly the case where the text matters.
_PNG_CEILING = 4 * 1024 * 1024


def adapt(
    data: bytes,
    *,
    mime_type: str = "image/png",
    model: Optional[str] = None,
    purpose: str = "screen",
    mode: Optional[str] = None,
    environ=None,
) -> AdaptedImage:
    """Take an image to a vision model: fit it to a budget, and tile it when that is allowed.

    ``model`` chooses nothing about the budget and everything about tiling: it is the name the
    multi-image gate is checked against. ``mode`` is ``analyze_image``'s existing
    ``caption | ocr | both``, which already says whether the caller wants to *read* the screen.
    """
    payload = data or b""
    warnings: List[str] = []

    if purpose not in PURPOSES:
        # Recorded rather than rejected: an unknown purpose is a caller that has not been
        # updated, and refusing its image would break it for a label.
        warnings.append(f"unknown-purpose:{purpose}")
    if not payload:
        warnings.append("empty")

    profile = profile_for(purpose, mode)
    width, height, sniffed = _measure(payload)
    # A sniffed type beats a declared one: `/upload` maps by file extension, and an extension is
    # what somebody typed.
    resolved_mime = sniffed or mime_type or "image/png"

    if width is None:
        if payload:
            warnings.append("unmeasured")
        return _unchanged(payload, resolved_mime, profile, warnings)

    target = _profiles.fit(width, height, profile)
    Image = _pillow()
    if Image is None:  # pragma: no cover — `width` is None without Pillow
        return _unchanged(payload, resolved_mime, profile, warnings, width, height)

    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            # Orientation first, and every measurement after it. A photo carrying a 90° EXIF
            # tag is 2400×1200 on disk and 1200×2400 to a human, and fitting the on-disk shape
            # then rotating stretches it: the model gets a photograph nobody took.
            source, rotated = _upright(source)
            if rotated:
                width, height = source.width, source.height
                target = _profiles.fit(width, height, profile)
            # `rotated` forces a re-encode even at the original size: handing back `payload`
            # there would send the bytes as they sit on disk, which is the photograph on its
            # side that the transpose just corrected.
            untouched = target == (width, height) and not rotated
            overview, over_mime = (
                (payload, resolved_mime)
                if untouched
                else _encode(source if target == (width, height) else source.resize(target, Image.LANCZOS), resolved_mime)
            )
            parts = [Part(overview, over_mime, "overview", target[0], target[1])]
            strategy = PASSTHROUGH if untouched else RESIZED

            if profile.tile and target != (width, height):
                if supports_multiple_images(model, environ):
                    parts.extend(_tiles(Image, source, profile, width, height))
                    if len(parts) > 1:
                        strategy = TILED
                else:
                    # Said out loud, because "the answer was vague" and "the detail crops were
                    # never sent" look identical from outside.
                    warnings.append("tiling-unavailable:single-image-model")
    except Exception:
        # Anything Pillow can open it can usually also resize; if it cannot, the original is
        # still a perfectly good thing to send.
        warnings.append("adapt-failed")
        return _unchanged(payload, resolved_mime, profile, warnings, width, height)

    return AdaptedImage(
        parts=parts,
        strategy=strategy,
        profile=profile.name,
        width=target[0],
        height=target[1],
        original_width=width,
        original_height=height,
        original_bytes=len(payload),
        warnings=warnings,
    )


def _upright(image):
    """``(image, rotated)`` — the picture the way a person sees it, and whether that moved it.

    A photograph carrying an EXIF orientation tag is one shape on disk and another on screen.
    Describing the on-disk one produces an answer about a scene nobody photographed, and the
    caller has no way to tell that is what happened.
    """
    try:
        from PIL import ImageOps

        orientation = 1
        try:
            orientation = int((image.getexif() or {}).get(274, 1) or 1)
        except Exception:
            orientation = 1
        if orientation in (0, 1):
            return image, False
        return (ImageOps.exif_transpose(image) or image), True
    except Exception:
        return image, False


def _tiles(Image, source, profile: Profile, width: int, height: int) -> List[Part]:
    """Overlapping detail crops, each capped at ``profile.tile_long_edge``.

    Crops come from the *original*, not the overview: cropping the downscale would hand the
    model four pieces of the same blur it could not read whole.
    """
    budget = max(0, profile.max_parts - 1)
    cols, rows = _profiles.grid_for(width, height, budget)
    if cols * rows < 2:
        return []

    out: List[Part] = []
    for label, box in _profiles.tile_boxes(width, height, cols, rows, profile.overlap):
        crop = source.crop(box)
        size = _profiles.fit(
            crop.width,
            crop.height,
            Profile(
                name=profile.name,
                max_long_edge=profile.tile_long_edge,
                max_megapixels=profile.max_megapixels,
                tile=False,
            ),
        )
        if size != (crop.width, crop.height):
            crop = crop.resize(size, Image.LANCZOS)
        data, mime = _encode(crop, "image/png")
        out.append(Part(data, mime, label, crop.width, crop.height))
    return out


def _unchanged(
    payload: bytes,
    mime: str,
    profile: Profile,
    warnings: List[str],
    width: Optional[int] = None,
    height: Optional[int] = None,
) -> AdaptedImage:
    """V4's behaviour, which is still the right answer whenever the image cannot be worked on."""
    return AdaptedImage(
        parts=[Part(payload, mime, "overview", width, height)],
        strategy=PASSTHROUGH,
        profile=profile.name,
        width=width,
        height=height,
        original_width=width,
        original_height=height,
        original_bytes=len(payload),
        warnings=warnings,
    )


def describe(adapted: Optional[AdaptedImage]) -> Dict[str, Any]:
    """``adapter`` metadata for a response, or ``{}`` when nothing passed through."""
    return adapted.meta() if adapted else {}
