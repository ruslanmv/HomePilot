# backend/app/personas/avatar_face.py
"""
Face-centred avatar thumbnails.

A persona's picture is usually a full-body shot (512x768, head to toe), and the
stored thumbnail is a square cut from its top: head to waist. In a 24-32 px
circle that leaves a face a few pixels wide. This module finds the face and
writes a square crop around it — ``thumb_face_<stem>.webp`` next to the
picture — for every place the picture is shown small and round.

Finding the face, best first:
  1. InsightFace, when it is installed (the optional ``avatar`` extra).
  2. A skin-region search with Pillow + numpy: the highest face-shaped skin
     region, cut at the neck. Good on the portraits HomePilot generates.
  3. No face found: the upper centre of a tall picture, where a standing
     person's head is; a square picture is used as it is.

The crop is written once and reused until the picture changes.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

#: Side of the written crop: sharp in a 168 px circle on a 2x screen.
FACE_THUMB_SIZE = 320

#: The crop is this many face-widths wide: face, hair and a little shoulder.
FACE_MARGIN = 1.9

Box = Tuple[float, float, float, float]  # x0, y0, x1, y1 in source pixels

_lock = threading.Lock()


def face_thumb_path(src_path: Path) -> Path:
    """Where the face crop of ``src_path`` lives."""
    stem = src_path.stem
    if stem.startswith("thumb_"):
        stem = stem[len("thumb_"):]
    return src_path.parent / f"thumb_face_{stem}.webp"


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _insightface_box(rgb: np.ndarray) -> Optional[Box]:
    # Only when another feature has already loaded it: a first load downloads
    # and initialises a large model, which a thumbnail must never wait for.
    try:
        from ..avatar import orientation_fix
    except Exception:
        return None
    analyzer = getattr(orientation_fix, "_FACE_ANALYZER", None)
    if analyzer is None:
        return None
    try:
        faces = analyzer.get(rgb[:, :, ::-1].copy())  # InsightFace expects BGR
    except Exception:
        logger.debug("InsightFace detection failed", exc_info=True)
        return None
    best = None
    for f in faces or []:
        bbox = getattr(f, "bbox", None)
        if bbox is None and hasattr(f, "get"):
            bbox = f.get("bbox")
        score = float(getattr(f, "det_score", 0.0) or 0.0)
        if bbox is None or score < 0.5:
            continue
        x0, y0, x1, y1 = (float(v) for v in bbox)
        area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
        if best is None or area > best[0]:
            best = (area, (x0, y0, x1, y1))
    return best[1] if best else None


def _skin_mask(small: Image.Image) -> np.ndarray:
    ycc = np.asarray(small.convert("YCbCr"), dtype=np.int16)
    y, cb, cr = ycc[:, :, 0], ycc[:, :, 1], ycc[:, :, 2]
    mask = (cr >= 135) & (cr <= 175) & (cb >= 78) & (cb <= 128) & (y >= 45)
    # Opening (erode, then dilate) drops speckle in hair and backgrounds.
    m = mask
    er = m.copy()
    er[1:, :] &= m[:-1, :]
    er[:-1, :] &= m[1:, :]
    er[:, 1:] &= m[:, :-1]
    er[:, :-1] &= m[:, 1:]
    di = er.copy()
    di[1:, :] |= er[:-1, :]
    di[:-1, :] |= er[1:, :]
    di[:, 1:] |= er[:, :-1]
    di[:, :-1] |= er[:, 1:]
    return di


def _components(mask: np.ndarray, min_area: int):
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    ys, xs = np.nonzero(mask)
    for sy, sx in zip(ys.tolist(), xs.tolist()):
        if seen[sy, sx]:
            continue
        seen[sy, sx] = True
        q = deque([(sy, sx)])
        pts = []
        while q:
            cy, cx = q.popleft()
            pts.append((cy, cx))
            for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    q.append((ny, nx))
        if len(pts) >= min_area:
            yield np.array(pts)


def _head_of(pts: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """The top of a skin region down to the neck: (x0, y0, x1, y1), inclusive."""
    top = int(pts[:, 0].min())
    bottom = int(pts[:, 0].max())
    widths = []
    for row in range(top, bottom + 1):
        xs = pts[pts[:, 0] == row, 1]
        widths.append((int(xs.min()), int(xs.max())) if xs.size else None)
    best_w = 0
    cut = bottom
    for i, span in enumerate(widths):
        if span is None:
            continue
        wdt = span[1] - span[0] + 1
        best_w = max(best_w, wdt)
        rows = i + 1
        # Past the cheeks the region narrows at the neck (or widens into
        # shoulders/chest): stop at whichever comes first.
        if rows >= 0.8 * best_w and best_w >= 3:
            if wdt < 0.72 * best_w or rows >= 1.45 * best_w:
                cut = top + i
                break
    spans = [s for s in widths[: cut - top + 1] if s is not None]
    if not spans:
        return None
    x0 = int(np.percentile([s[0] for s in spans], 15))
    x1 = int(np.percentile([s[1] for s in spans], 85))
    return x0, top, x1, cut


def _skin_box(im: Image.Image) -> Optional[Box]:
    W, H = im.size
    scale = 256.0 / max(W, H)
    sw, sh = max(1, round(W * scale)), max(1, round(H * scale))
    small = im.resize((sw, sh), Image.BILINEAR)
    mask = _skin_mask(small)
    luma = np.asarray(small.convert("L"), dtype=np.int16)
    n = sw * sh
    best = None
    for pts in _components(mask, max(16, int(n * 0.001))):
        # A wall, sand or a skin-toned backdrop: most of the frame, or running
        # into the top and a side, or from side to side. A face in a close
        # portrait runs into the bottom edge only (neck, chest).
        if len(pts) > n * 0.5:
            continue
        ys, xs = pts[:, 0], pts[:, 1]
        top, left, right = ys.min() == 0, xs.min() == 0, xs.max() == sw - 1
        if ((top and (left or right)) or (left and right)) and len(pts) > n * 0.02:
            continue
        head = _head_of(pts)
        if head is None:
            continue
        x0, y0, x1, y1 = head
        fw, fh = x1 - x0 + 1, y1 - y0 + 1
        if fw < max(5, sw * 0.04) or fh < 5 or fw > sw * 0.95:
            continue
        aspect = fh / fw
        if not 0.7 <= aspect <= 2.0:
            continue
        inside = mask[y0:y1 + 1, x0:x1 + 1]
        fill = float(inside.mean())
        if fill < 0.4:
            continue
        # Eyes, brows and mouth: darker non-skin pixels inside the box. A
        # region without them (an arm, a leg, a shoulder) is not a face.
        box_luma = luma[y0:y1 + 1, x0:x1 + 1]
        skin_luma = float(box_luma[inside].mean()) if inside.any() else 0.0
        features = float(((~inside) & (box_luma < skin_luma - 20)).mean())
        if not 0.015 <= features <= 0.45:
            continue
        top_rel = y0 / sh
        if top_rel > 0.75:
            continue
        # Faces sit above every other bare skin in a portrait.
        score = np.sqrt(fw * fh) * fill * (1.0 - top_rel) ** 2
        if best is None or score > best[0]:
            best = (score, (x0, y0, x1, y1))
    if best is None:
        return None
    x0, y0, x1, y1 = best[1]
    return (x0 / scale, y0 / scale, (x1 + 1) / scale, (y1 + 1) / scale)


def find_face_box(im: Image.Image) -> Optional[Box]:
    """The face in ``im`` as (x0, y0, x1, y1) source pixels, or None."""
    rgb = im.convert("RGB")
    box = _insightface_box(np.asarray(rgb))
    if box is None:
        box = _skin_box(rgb)
    return box


# ---------------------------------------------------------------------------
# Crop
# ---------------------------------------------------------------------------

def face_crop_box(size: Tuple[int, int], face: Optional[Box]) -> Tuple[int, int, int, int]:
    """The square to cut from a picture of ``size`` around ``face``."""
    W, H = size
    limit = min(W, H)
    if face is None:
        # The square the regular thumbnail uses: centred, from the top.
        left = (W - limit) // 2
        return (left, 0, left + limit, limit)
    x0, y0, x1, y1 = face
    fw, fh = max(1.0, x1 - x0), max(1.0, y1 - y0)
    side = min(float(limit), max(fw, fh * 0.85) * FACE_MARGIN)
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0 - side * 0.06  # a little more room above: hair
    left = int(round(min(max(cx - side / 2.0, 0.0), W - side)))
    top = int(round(min(max(cy - side / 2.0, 0.0), H - side)))
    s = int(round(side))
    return (left, top, left + s, top + s)


def write_face_thumb(src_path: Path, dst_path: Optional[Path] = None, size: int = FACE_THUMB_SIZE) -> Path:
    """Write the face crop of ``src_path`` and return its path."""
    dst = dst_path or face_thumb_path(src_path)
    with Image.open(src_path) as im:
        im = im.convert("RGB")
        box = face_crop_box(im.size, find_face_box(im))
        crop = im.crop(box).resize((size, size), Image.LANCZOS)
    tmp = dst.with_suffix(".tmp.webp")
    crop.save(tmp, format="WEBP", quality=86, method=6)
    tmp.replace(dst)
    return dst


def ensure_face_thumb(src_path: Path) -> Path:
    """The face crop of ``src_path``, written now if missing or older than it."""
    dst = face_thumb_path(src_path)
    try:
        if dst.is_file() and dst.stat().st_mtime >= src_path.stat().st_mtime:
            return dst
    except OSError:
        pass
    with _lock:
        if dst.is_file() and dst.stat().st_mtime >= src_path.stat().st_mtime:
            return dst
        return write_face_thumb(src_path, dst)
