"""
Avatar placeholder face generator — built-in fallback.

Generates deterministic stylized face portrait images so the Create Avatar flow
works end-to-end even when avatar-service (StyleGAN) and ComfyUI are unavailable.

Quality: These are geometric/artistic placeholders — clearly not AI-generated
photos. The UI warns users that real AI generation requires the avatar-service.

Images are saved to the backend uploads directory and served via /files/.
"""

from __future__ import annotations

import logging
import math
import random
import time
from pathlib import Path
from typing import List, Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .schemas import AvatarResult

_log = logging.getLogger(__name__)


def _uploads_dir() -> Path:
    """Resolve the backend uploads directory (same as files router)."""
    p = Path(__file__).resolve().parents[2] / "data" / "uploads"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _make_seeds(seed: Optional[int], count: int) -> List[int]:
    if seed is not None:
        return [seed + i for i in range(count)]
    return [random.randint(0, 2**31 - 1) for _ in range(count)]


def _lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    """Linearly interpolate between two RGB colors."""
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _draw_soft_ellipse(
    img: Image.Image,
    bbox: tuple,
    fill: tuple,
    feather: int = 6,
) -> None:
    """Draw an anti-aliased ellipse by rendering at 2x and downscaling."""
    x0, y0, x1, y1 = [int(v) for v in bbox]
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    scale = 2
    tmp = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(tmp)
    d.ellipse([0, 0, w * scale - 1, h * scale - 1], fill=(*fill, 255))
    tmp = tmp.resize((w, h), Image.LANCZOS)
    if feather > 0:
        tmp = tmp.filter(ImageFilter.GaussianBlur(radius=feather * 0.5))
    img.paste(fill, (x0, y0, x0 + w, y0 + h), tmp.split()[3])


def _generate_face(seed: int, size: int = 512) -> Image.Image:
    """Generate a deterministic stylized face portrait from a seed.

    Produces a studio-quality stylized placeholder with:
    - Smooth gradient background
    - Properly proportioned face geometry
    - Realistic skin tone diversity
    - Varied hair styles and colors
    - Anti-aliased rendering
    """
    rng = random.Random(seed)
    img = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(img)

    # ── Background: smooth studio-style gradient ──
    bg_hue = rng.random()
    bg_sat = 0.15 + rng.random() * 0.1
    bg_top = (
        int(30 + 25 * bg_sat * math.sin(bg_hue * 6.28)),
        int(30 + 25 * bg_sat * math.sin(bg_hue * 6.28 + 2.09)),
        int(35 + 25 * bg_sat * math.sin(bg_hue * 6.28 + 4.19)),
    )
    bg_bottom = tuple(max(5, c - 20) for c in bg_top)
    for y in range(size):
        t = y / size
        c = _lerp_color(bg_top, bg_bottom, t)
        draw.line([(0, y), (size, y)], fill=c)

    cx, cy = size // 2, int(size * 0.46)

    # ── Face proportions (varied) ──
    face_w = int(size * (0.30 + rng.random() * 0.05))
    face_h = int(size * (0.36 + rng.random() * 0.05))

    # ── Skin tone (broad realistic diversity) ──
    skin_tones = [
        (58, 40, 30),    # deep espresso
        (80, 55, 38),    # dark brown
        (110, 78, 52),   # rich brown
        (141, 100, 64),  # warm brown
        (175, 130, 88),  # medium tan
        (198, 156, 109), # golden tan
        (215, 178, 140), # light tan
        (230, 198, 164), # warm beige
        (240, 210, 180), # light beige
        (248, 224, 200), # fair
        (252, 232, 210), # very fair
        (255, 237, 218), # porcelain
    ]
    skin = skin_tones[rng.randint(0, len(skin_tones) - 1)]
    skin_shadow = tuple(max(0, c - 25) for c in skin)
    skin_highlight = tuple(min(255, c + 18) for c in skin)

    # ── Neck and shoulders ──
    neck_w = int(face_w * 0.42)
    neck_top = cy + face_h - int(face_h * 0.15)
    shoulder_w = int(size * 0.38)

    # Shoulders (clothing)
    cloth_hue = rng.random()
    cloth_base = (
        int(40 + 60 * math.sin(cloth_hue * 6.28)),
        int(40 + 60 * math.sin(cloth_hue * 6.28 + 2.09)),
        int(45 + 60 * math.sin(cloth_hue * 6.28 + 4.19)),
    )
    _draw_soft_ellipse(
        img,
        (cx - shoulder_w, neck_top + int(face_h * 0.35),
         cx + shoulder_w, neck_top + int(face_h * 1.3)),
        cloth_base,
        feather=8,
    )

    # Neck
    for y in range(neck_top, neck_top + int(face_h * 0.5)):
        t = (y - neck_top) / max(1, face_h * 0.5)
        nw = int(neck_w * (1.0 + t * 0.3))
        c = _lerp_color(skin, skin_shadow, t * 0.4)
        draw.line([(cx - nw, y), (cx + nw, y)], fill=c)

    # ── Face (multi-layer for depth) ──
    _draw_soft_ellipse(
        img,
        (cx - face_w - 2, cy - face_h - 2, cx + face_w + 2, cy + face_h + 2),
        skin_shadow,
        feather=10,
    )
    _draw_soft_ellipse(
        img,
        (cx - face_w, cy - face_h, cx + face_w, cy + face_h),
        skin,
        feather=4,
    )
    # Highlight on forehead
    _draw_soft_ellipse(
        img,
        (cx - face_w * 0.5, cy - face_h * 0.85,
         cx + face_w * 0.5, cy - face_h * 0.45),
        skin_highlight,
        feather=15,
    )

    # ── Jaw contour (subtle shadow) ──
    jaw_shadow = tuple(max(0, c - 15) for c in skin)
    _draw_soft_ellipse(
        img,
        (cx - face_w + 5, cy + face_h * 0.3,
         cx + face_w - 5, cy + face_h + 5),
        jaw_shadow,
        feather=12,
    )
    # Re-cover center of jaw
    _draw_soft_ellipse(
        img,
        (cx - face_w + 15, cy + face_h * 0.1,
         cx + face_w - 15, cy + face_h - 5),
        skin,
        feather=8,
    )

    # ── Eyes ──
    eye_y = cy - int(face_h * 0.12)
    eye_sep = int(face_w * 0.42)
    eye_w = int(face_w * 0.24)
    eye_h = int(face_w * 0.14)

    iris_palette = [
        (68, 50, 28),    # dark brown
        (92, 64, 32),    # hazel
        (45, 75, 45),    # green
        (55, 78, 140),   # blue
        (42, 42, 42),    # near-black
        (85, 75, 55),    # amber
        (65, 90, 80),    # grey-green
        (75, 95, 130),   # steel blue
    ]
    iris_color = iris_palette[rng.randint(0, len(iris_palette) - 1)]

    for side in (-1, 1):
        ex = cx + side * eye_sep

        # Eye socket shadow
        _draw_soft_ellipse(
            img,
            (ex - eye_w - 4, eye_y - eye_h - 3,
             ex + eye_w + 4, eye_y + eye_h + 3),
            skin_shadow,
            feather=8,
        )

        # Eye white (sclera)
        _draw_soft_ellipse(
            img,
            (ex - eye_w, eye_y - eye_h, ex + eye_w, eye_y + eye_h),
            (235, 235, 232),
            feather=2,
        )

        # Iris
        iris_r = int(eye_w * 0.58)
        _draw_soft_ellipse(
            img,
            (ex - iris_r, eye_y - iris_r, ex + iris_r, eye_y + iris_r),
            iris_color,
            feather=2,
        )

        # Pupil
        pr = int(iris_r * 0.42)
        _draw_soft_ellipse(
            img,
            (ex - pr, eye_y - pr, ex + pr, eye_y + pr),
            (8, 8, 8),
            feather=1,
        )

        # Specular highlight
        hr = int(pr * 0.5)
        hx = ex - int(iris_r * 0.25)
        hy = eye_y - int(iris_r * 0.3)
        _draw_soft_ellipse(
            img,
            (hx - hr, hy - hr, hx + hr, hy + hr),
            (255, 255, 255),
            feather=2,
        )

        # Upper eyelid crease
        lid_color = tuple(max(0, c - 35) for c in skin)
        draw.arc(
            [ex - eye_w - 2, eye_y - eye_h - 5,
             ex + eye_w + 2, eye_y + eye_h * 0.3],
            start=190, end=350, fill=lid_color, width=max(2, size // 180),
        )

    # ── Eyebrows ──
    brow_dark = rng.random() > 0.3
    brow_color = tuple(max(0, c - (80 if brow_dark else 50)) for c in skin)
    brow_y = eye_y - eye_h - int(face_h * 0.07)
    brow_thickness = max(3, size // 100)
    for side in (-1, 1):
        bx = cx + side * eye_sep
        draw.arc(
            [bx - int(eye_w * 1.3), brow_y - int(eye_h * 0.9),
             bx + int(eye_w * 1.3), brow_y + int(eye_h * 0.9)],
            start=200, end=340, fill=brow_color, width=brow_thickness,
        )

    # ── Nose ──
    nose_y = cy + int(face_h * 0.12)
    nose_w = int(face_w * 0.12)
    nose_shadow = tuple(max(0, c - 18) for c in skin)
    # Nose bridge shadow (subtle)
    for i in range(3):
        draw.line(
            [(cx - 1 + i, eye_y + eye_h + 4), (cx - 1 + i, nose_y - 5)],
            fill=(*nose_shadow, 60) if img.mode == "RGBA" else nose_shadow,
            width=1,
        )
    # Nose tip
    _draw_soft_ellipse(
        img,
        (cx - nose_w, nose_y - nose_w * 0.6, cx + nose_w, nose_y + nose_w * 0.6),
        skin_highlight,
        feather=6,
    )
    # Nostrils
    for side in (-1, 1):
        nx = cx + side * int(nose_w * 0.7)
        nr = max(2, size // 180)
        draw.ellipse(
            [nx - nr, nose_y - nr * 0.5, nx + nr, nose_y + nr * 0.5],
            fill=nose_shadow,
        )

    # ── Mouth ──
    mouth_y = cy + int(face_h * 0.35)
    mouth_w = int(face_w * 0.28)
    lip_base = (
        min(255, skin[0] + 35),
        max(0, skin[1] - 15),
        max(0, skin[2] - 8),
    )
    lip_dark = tuple(max(0, c - 20) for c in lip_base)

    smile = rng.random() > 0.25
    if smile:
        # Upper lip
        draw.arc(
            [cx - mouth_w, mouth_y - int(face_h * 0.04),
             cx + mouth_w, mouth_y + int(face_h * 0.08)],
            start=0, end=180, fill=lip_dark, width=max(2, size // 140),
        )
        # Lower lip (fuller)
        draw.arc(
            [cx - int(mouth_w * 0.85), mouth_y - int(face_h * 0.01),
             cx + int(mouth_w * 0.85), mouth_y + int(face_h * 0.1)],
            start=0, end=180, fill=lip_base, width=max(3, size // 120),
        )
    else:
        # Closed relaxed mouth
        draw.line(
            [(cx - int(mouth_w * 0.75), mouth_y),
             (cx + int(mouth_w * 0.75), mouth_y)],
            fill=lip_dark, width=max(2, size // 160),
        )
        # Lower lip suggestion
        draw.arc(
            [cx - int(mouth_w * 0.6), mouth_y,
             cx + int(mouth_w * 0.6), mouth_y + int(face_h * 0.07)],
            start=10, end=170, fill=lip_base, width=max(2, size // 170),
        )

    # ── Hair ──
    hair_colors = [
        (20, 15, 12),    # jet black
        (38, 28, 18),    # dark brown
        (65, 45, 25),    # medium brown
        (95, 65, 35),    # chestnut
        (130, 90, 50),   # auburn
        (170, 130, 70),  # light brown
        (195, 165, 100), # dark blonde
        (215, 190, 130), # golden blonde
        (230, 210, 160), # platinum blonde
        (140, 50, 35),   # red
        (45, 25, 20),    # very dark brown
    ]
    hair_color = hair_colors[rng.randint(0, len(hair_colors) - 1)]
    hair_highlight = tuple(min(255, c + 30) for c in hair_color)
    hair_style = rng.randint(0, 4)

    hair_top = cy - face_h - int(face_h * 0.2)

    if hair_style == 0:
        # Short cropped
        _draw_soft_ellipse(
            img,
            (cx - face_w - 6, hair_top + 5, cx + face_w + 6, cy - int(face_h * 0.25)),
            hair_color,
            feather=4,
        )
        _draw_soft_ellipse(
            img,
            (cx - face_w + 10, hair_top + 12, cx + face_w - 10, cy - int(face_h * 0.35)),
            hair_highlight,
            feather=8,
        )
    elif hair_style == 1:
        # Medium length
        _draw_soft_ellipse(
            img,
            (cx - face_w - 12, hair_top - 5, cx + face_w + 12, cy + int(face_h * 0.1)),
            hair_color,
            feather=6,
        )
        # Re-expose face
        _draw_soft_ellipse(
            img,
            (cx - face_w + 8, cy - face_h + 20, cx + face_w - 8, cy + face_h),
            skin,
            feather=4,
        )
    elif hair_style == 2:
        # Long flowing
        _draw_soft_ellipse(
            img,
            (cx - face_w - 16, hair_top - 10, cx + face_w + 16, cy + int(face_h * 0.15)),
            hair_color,
            feather=6,
        )
        # Side curtains
        for side in (-1, 1):
            sx = cx + side * (face_w + 4)
            for y_off in range(0, int(face_h * 1.2), 2):
                sw = int(14 + 4 * math.sin(y_off * 0.08))
                yy = cy - int(face_h * 0.2) + y_off
                draw.line(
                    [(sx - sw, yy), (sx + sw, yy)],
                    fill=_lerp_color(hair_color, hair_highlight, 0.1 * math.sin(y_off * 0.12)),
                )
        # Re-expose face
        _draw_soft_ellipse(
            img,
            (cx - face_w + 5, cy - face_h + 15, cx + face_w - 5, cy + face_h),
            skin,
            feather=4,
        )
    elif hair_style == 3:
        # Buzz / very short
        _draw_soft_ellipse(
            img,
            (cx - face_w - 3, hair_top + 12, cx + face_w + 3, cy - int(face_h * 0.4)),
            hair_color,
            feather=3,
        )
    else:
        # Swept back / slicked
        _draw_soft_ellipse(
            img,
            (cx - face_w - 8, hair_top, cx + face_w + 8, cy - int(face_h * 0.2)),
            hair_color,
            feather=5,
        )
        # Volume on top
        _draw_soft_ellipse(
            img,
            (cx - face_w + 5, hair_top - 5, cx + face_w - 5, cy - int(face_h * 0.45)),
            hair_highlight,
            feather=10,
        )

    # Re-draw eyes/brows over any hair overlap (safety pass)
    # (eyes are already rendered; hair styles that overlap re-expose face first)

    # ── Ears (subtle) ──
    ear_y = eye_y + int(eye_h * 0.5)
    ear_h = int(face_h * 0.22)
    ear_w = int(face_w * 0.12)
    for side in (-1, 1):
        ear_x = cx + side * (face_w - 2)
        _draw_soft_ellipse(
            img,
            (ear_x - ear_w, ear_y - ear_h, ear_x + ear_w, ear_y + ear_h),
            skin_shadow,
            feather=6,
        )

    # ── Final processing ──
    # Light Gaussian blur for smoothness
    img = img.filter(ImageFilter.GaussianBlur(radius=0.8))

    # Slight vignette for studio portrait feel
    vignette = Image.new("L", (size, size), 255)
    vd = ImageDraw.Draw(vignette)
    for i in range(40):
        alpha = int(i * 3.5)
        margin = i * 3
        vd.rectangle([margin, margin, size - margin, size - margin], fill=255 - alpha)
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=30))
    r, g, b = img.split()
    r = Image.composite(r, Image.new("L", (size, size), 0), vignette)
    g = Image.composite(g, Image.new("L", (size, size), 0), vignette)
    b = Image.composite(b, Image.new("L", (size, size), 0), vignette)
    img = Image.merge("RGB", (r, g, b))

    return img


def generate_placeholder_faces(
    count: int,
    seed: int | None = None,
    truncation: float = 0.7,
) -> List[AvatarResult]:
    """Generate placeholder face images and save them to the uploads dir.

    Returns a list of AvatarResult with /files/ URLs that the frontend can display.
    """
    out_dir = _uploads_dir()
    seeds = _make_seeds(seed, count)
    results: list[AvatarResult] = []

    for s in seeds:
        img = _generate_face(s)
        name = f"avatar_{int(time.time() * 1000)}_{s}.png"
        path = out_dir / name
        img.save(path, format="PNG", optimize=True)

        results.append(AvatarResult(
            url=f"/files/{name}",
            seed=s,
            metadata={"generator": "placeholder", "truncation": truncation},
        ))

    _log.info("Generated %d placeholder faces (seeds: %s)", count, seeds)
    return results
