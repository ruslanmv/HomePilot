"""
StyleGAN2 post-processing — resize, sharpen, encode.

Handles final image polishing before saving to disk.
Keeps processing lightweight and deterministic.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFilter


def resize_and_encode(
    img: Image.Image,
    output_path: Path,
    size: int = 512,
    sharpen: bool = True,
    quality: int = 95,
    format: str = "PNG",
) -> None:
    """Resize, optionally sharpen, and save an image.

    Parameters
    ----------
    img : PIL.Image
        Source image (any size).
    output_path : Path
        Where to write the result.
    size : int
        Target square dimension.
    sharpen : bool
        Apply a mild sharpen filter (recommended for StyleGAN outputs
        that are upscaled from 256->512).
    quality : int
        JPEG/WebP quality (ignored for PNG).
    format : str
        Output format: ``"PNG"``, ``"JPEG"``, or ``"WEBP"``.
    """
    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)

    if sharpen:
        img = img.filter(ImageFilter.SHARPEN)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    save_kwargs: dict = {"format": format}
    if format.upper() == "PNG":
        save_kwargs["optimize"] = True
    elif format.upper() in ("JPEG", "WEBP"):
        save_kwargs["quality"] = quality

    img.save(output_path, **save_kwargs)


def to_bytes(img: Image.Image, format: str = "PNG") -> bytes:
    """Encode a PIL Image to bytes for streaming responses."""
    buf = BytesIO()
    img.save(buf, format=format)
    return buf.getvalue()


def create_thumbnail(
    img: Image.Image,
    output_path: Path,
    size: int = 256,
) -> None:
    """Create a square face-anchored thumbnail (top-crop).

    Anchors to the top of the image so the face is always visible,
    matching the convention in ``personas/avatar_assets.py``.
    """
    img = img.convert("RGB")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    box = (left, 0, left + side, side)
    cropped = img.crop(box)
    thumb = cropped.resize((size, size), Image.LANCZOS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    thumb.save(output_path, format="WEBP", quality=85, method=6)
