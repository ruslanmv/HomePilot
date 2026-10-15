# backend/app/personas/avatar_crop.py
"""
Manual crop of a persona's profile picture ("Edit profile picture").

The original picture is never changed. A square is cut from it at full
resolution, using the area the user framed in the editor, and saved next to it
as ``thumb_avatar_<name>_crop_<id>.webp`` (512 x 512). That file becomes the
persona's thumbnail, so every small round avatar shows it; the circle is drawn
by CSS. The area, the zoom and the source are kept in
``persona_appearance["avatar_crop"]`` so the editor can reopen at the same
framing and the crop can be refined later.

The area arrives as percentages of the picture as the browser shows it, which
already honours EXIF orientation, so the server applies EXIF orientation
before cutting — the two always agree, whatever the source resolution.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image, ImageOps, UnidentifiedImageError

CROP_SIZE = 512
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
# Refuse decompression bombs well before Pillow's own warning threshold.
MAX_PIXELS = 50_000_000


class CropError(ValueError):
    """The request cannot be applied (bad area, unreadable or unsupported image)."""


@dataclass(frozen=True)
class CropResult:
    thumb_rel: str          # relative to the upload root, served under /files/
    box: tuple              # (left, top, right, bottom) in source pixels
    source_size: tuple      # (width, height) after EXIF orientation


def parse_area(raw: Any) -> Dict[str, float]:
    """``{"x", "y", "width", "height"}`` in percent of the picture, validated."""
    if not isinstance(raw, dict):
        raise CropError("area must be an object with x, y, width and height (percent)")
    out: Dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        try:
            v = float(raw[key])
        except (KeyError, TypeError, ValueError):
            raise CropError(f"area.{key} must be a number") from None
        if v != v or v in (float("inf"), float("-inf")):
            raise CropError(f"area.{key} must be a finite number")
        out[key] = v
    if out["width"] <= 0 or out["height"] <= 0:
        raise CropError("area width and height must be positive")
    if out["width"] > 100.5 or out["height"] > 100.5:
        raise CropError("area cannot be larger than the picture")
    return out


def open_oriented(path: Path) -> Image.Image:
    """Open an image, check it is a supported, reasonably sized picture, and
    apply its EXIF orientation. The caller closes the returned image."""
    try:
        im = Image.open(path)
        im.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise CropError("The file is not a readable image") from e
    if im.format not in ALLOWED_FORMATS:
        im.close()
        raise CropError("Use a PNG, JPEG or WebP picture")
    if im.width * im.height > MAX_PIXELS:
        im.close()
        raise CropError("The picture is too large")
    oriented = ImageOps.exif_transpose(im)
    if oriented is not im:
        im.close()
    return oriented


def square_box(area: Dict[str, float], width: int, height: int) -> tuple:
    """The square, in source pixels, that the area describes — clamped inside
    the picture. Never stretches: the side is one value for both axes."""
    left = area["x"] / 100.0 * width
    top = area["y"] / 100.0 * height
    w_px = area["width"] / 100.0 * width
    h_px = area["height"] / 100.0 * height
    side = max(1, int(round(min(w_px, h_px, width, height))))
    # Centre the square on the requested area, then keep it inside the picture.
    cx, cy = left + w_px / 2.0, top + h_px / 2.0
    x0 = int(round(cx - side / 2.0))
    y0 = int(round(cy - side / 2.0))
    x0 = max(0, min(x0, width - side))
    y0 = max(0, min(y0, height - side))
    return (x0, y0, x0 + side, y0 + side)


def crop_to_thumb(
    upload_root: Path,
    source_rel: str,
    area: Dict[str, float],
    size: int = CROP_SIZE,
) -> CropResult:
    """Cut the framed square from the original and save it as a WebP thumbnail
    next to it. Returns paths relative to ``upload_root``."""
    root = upload_root.resolve()
    src = (root / source_rel.lstrip("/")).resolve()
    if root not in src.parents or not src.is_file():
        raise FileNotFoundError("The picture to crop was not found")

    with open_oriented(src) as im:
        width, height = im.size
        box = square_box(area, width, height)
        region = im.crop(box)
        if region.mode not in ("RGB", "RGBA"):
            region = region.convert("RGBA" if "A" in region.getbands() else "RGB")
        side = box[2] - box[0]
        # Down-scale with a high-quality filter; a small region is enlarged to
        # the same size so every thumbnail has one resolution.
        out = region if side == size else region.resize((size, size), Image.LANCZOS)
        # avatar_<name>.png → thumb_avatar_<name>_crop_<id>.webp: the "thumb_avatar_" prefix
        # persona export/import already looks for.
        stem = src.stem if src.stem.startswith("avatar_") else f"avatar_{src.stem}"
        name = f"thumb_{stem}_crop_{uuid.uuid4().hex[:8]}.webp"
        dst = src.parent / name
        out.save(dst, format="WEBP", quality=92, method=6)

    return CropResult(
        thumb_rel=str(dst.relative_to(root)),
        box=box,
        source_size=(width, height),
    )


def crop_record(
    *,
    source_rel: str,
    area: Dict[str, float],
    zoom: Optional[float],
    result: CropResult,
    auto_thumb: Optional[str],
) -> Dict[str, Any]:
    """What ``persona_appearance["avatar_crop"]`` keeps for re-editing."""
    return {
        "source": source_rel,
        "area": {k: round(v, 4) for k, v in area.items()},
        "zoom": round(float(zoom), 4) if isinstance(zoom, (int, float)) else None,
        "output": result.thumb_rel,
        "size": CROP_SIZE,
        "box": list(result.box),
        "source_size": list(result.source_size),
        # The automatic thumbnail the crop replaced, so it can be restored.
        "auto_thumb": auto_thumb,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def active_crop(appearance: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The saved crop, if it is still what the persona shows. Choosing a new
    picture anywhere else replaces the thumbnail, and with it the crop."""
    crop = appearance.get("avatar_crop")
    if not isinstance(crop, dict) or not crop.get("output"):
        return None
    if crop.get("output") != appearance.get("selected_thumb_filename"):
        return None
    return crop



def _look(appearance: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sel = appearance.get("selected")
    return sel if isinstance(sel, dict) and sel else None


def files_rel(url: Optional[str]) -> Optional[str]:
    """The upload-relative path a /files/ URL points at (absolute or not)."""
    if not isinstance(url, str):
        return None
    if "/files/" in url:
        ref = url.split("/files/", 1)[1]
    elif url.startswith("files/"):
        ref = url[len("files/"):]
    else:
        return None
    from urllib.parse import unquote

    ref = unquote(ref.split("?", 1)[0].split("#", 1)[0]).lstrip("/")
    return ref or None


def _same_picture(appearance: Dict[str, Any]) -> set:
    """Every file that is the persona's current picture: the original, the
    thumbnail shown, and the framing's source, output and automatic thumbnail."""
    crop = appearance.get("avatar_crop") if isinstance(appearance.get("avatar_crop"), dict) else {}
    names = (appearance.get("selected_filename"), appearance.get("selected_thumb_filename"),
             crop.get("source"), crop.get("output"), crop.get("auto_thumb"))
    return {n for n in names if isinstance(n, str) and n}


def keeps_manual_picture(before: Dict[str, Any], after: Dict[str, Any], chosen_url: Optional[str] = None) -> bool:
    """
    True while a picture chosen in Edit Profile Picture stays: it is in use, and
    the user has not picked another look since. A look that is only another
    reference to the same picture (a settings panel wrapping the current
    picture, or its thumbnail, in a look of its own) is not another look.
    """
    if active_crop(before) is None:
        return False
    if _look(after) == _look(before):
        return True
    rel = files_rel(chosen_url)
    return rel is not None and rel in _same_picture(before)


def keep_manual_picture(before: Dict[str, Any], after: Dict[str, Any], chosen_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Saving other persona settings must not undo Edit Profile Picture.

    Settings panels send back the whole persona_appearance they loaded — maybe
    from before the crop, with the old automatic thumbnail — so, while the user
    has not picked another look, the picture, its thumbnail and the framing
    stay as they were. Picking another look replaces them, as it always did.
    """
    if not keeps_manual_picture(before, after, chosen_url):
        return after
    kept = dict(after)
    for key in ("selected_filename", "selected_thumb_filename", "avatar_crop"):
        if key in before:
            kept[key] = before[key]
    return kept
