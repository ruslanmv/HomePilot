"""
Deterministic motion-graphic renderer (essay-to-video pipeline, Batch 1).

Renders diagram/proof/quote/cta scenes from structured data - StyleKit colors,
exact narration text, safe-margin-aware layout. There is no sampling step
between the text and the pixels, so a label cannot be misspelled.

Two output tiers:
  - PNG still via Pillow (already a backend dependency). This is what the
    backend endpoint produces today: it slots into StudioScene.imageUrl and
    the existing img2vid / Ken Burns / MP4-export paths downstream.
  - Full motion via the Remotion compositions in
    frontend/src/ui/studio/remotion/ (same props contract, see its README).
    That render runs from the JS toolchain, not from this module.

ADDITIVE ONLY - nothing here is imported by the diffusion path.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .library import get_style_kit
from .models import StyleKit

# Canvas per platform preset (matches library.default_canvas + safe margins)
_PRESET_CANVAS: Dict[str, Tuple[int, int, float]] = {
    "youtube_16_9": (1920, 1080, 0.05),
    "slides_16_9": (1920, 1080, 0.05),
    "shorts_9_16": (1080, 1920, 0.06),
}

_DEFAULT_KIT_ID = "ruslanmv-essays"


def output_dir() -> Path:
    """Where rendered stills live. Served by GET /studio/motion-graphics/{name}."""
    base = os.getenv("MOTION_GRAPHICS_DIR", "")
    p = Path(base) if base else Path(__file__).resolve().parents[2] / "data" / "motion_graphics"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _palette(kit: Optional[StyleKit]) -> Dict[str, str]:
    defaults = {
        "background": "#0a0a0a",
        "text_primary": "#ffffff",
        "text_secondary": "#94a3b8",
        "accent_start": "#00d4ff",
        "accent_mid": "#0f62fe",
        "accent_end": "#8a3ffc",
    }
    if kit and kit.palette:
        # Tolerate other kits' key names (primary/bg/...) by mapping loosely
        p = kit.palette
        defaults.update({
            "background": p.get("background", p.get("bg", defaults["background"])),
            "text_primary": p.get("text_primary", p.get("primary", defaults["text_primary"])),
            "text_secondary": p.get("text_secondary", p.get("muted", defaults["text_secondary"])),
            "accent_start": p.get("accent_start", p.get("secondary", defaults["accent_start"])),
            "accent_mid": p.get("accent_mid", defaults["accent_mid"]),
            "accent_end": p.get("accent_end", defaults["accent_end"]),
        })
    return defaults


def _hex_to_rgb(color: str) -> Tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _load_font(size: int, mono: bool = False):
    """Best-available font: IBM Plex if installed, then DejaVu, then default."""
    from PIL import ImageFont
    candidates = (
        ["IBMPlexMono-Regular.ttf", "DejaVuSansMono.ttf"] if mono
        else ["IBMPlexSans-Regular.ttf", "DejaVuSans.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # older Pillow: load_default() takes no size
        return ImageFont.load_default()


def _wrap(draw, text: str, font, max_width: int) -> List[str]:
    lines: List[str] = []
    for para in text.split("\n"):
        words = para.split()
        if not words:
            continue
        line = words[0]
        for word in words[1:]:
            probe = f"{line} {word}"
            if draw.textlength(probe, font=font) <= max_width:
                line = probe
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def _sentences(text: str, limit: int) -> List[str]:
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    return parts[:limit]


def _gradient_bar(draw, x0: int, y0: int, x1: int, y1: int, palette: Dict[str, str]) -> None:
    """Horizontal accent gradient (accent_start -> accent_end)."""
    r0, g0, b0 = _hex_to_rgb(palette["accent_start"])
    r1, g1, b1 = _hex_to_rgb(palette["accent_end"])
    width = max(1, x1 - x0)
    for i in range(width):
        t = i / width
        color = (round(r0 + (r1 - r0) * t), round(g0 + (g1 - g0) * t), round(b0 + (b1 - b0) * t))
        draw.line([(x0 + i, y0), (x0 + i, y1)], fill=color)


class MotionGraphicSpec:
    """Props for one scene render - the same contract the Remotion
    compositions consume (frontend/src/ui/studio/remotion/types.ts)."""

    def __init__(
        self,
        kind: str,                     # diagram | proof | quote | cta (hero/transition render as quote-style title cards)
        title: str,
        narration: str,
        width: int = 1920,
        height: int = 1080,
        safe_margin_pct: float = 0.05,
        style_kit_id: str = _DEFAULT_KIT_ID,
        links: Optional[List[str]] = None,
    ):
        self.kind = kind if kind in ("diagram", "proof", "quote", "cta") else "quote"
        self.title = title
        self.narration = narration
        self.width = width
        self.height = height
        self.safe_margin_pct = safe_margin_pct
        self.style_kit_id = style_kit_id
        self.links = links or []


def render_still(spec: MotionGraphicSpec, out_path: Path) -> Path:
    """Render one deterministic PNG still for the given spec."""
    from PIL import Image, ImageDraw

    palette = _palette(get_style_kit(spec.style_kit_id))
    img = Image.new("RGB", (spec.width, spec.height), _hex_to_rgb(palette["background"]))
    draw = ImageDraw.Draw(img)

    # Safe-content box - everything renders inside it (CanvasSpec contract)
    mx = round(spec.width * spec.safe_margin_pct)
    my = round(spec.height * spec.safe_margin_pct)
    box = (mx, my, spec.width - mx, spec.height - my)
    box_w = box[2] - box[0]

    scale = spec.height / 1080  # keep proportions across canvases
    f_title = _load_font(round(64 * scale))
    f_body = _load_font(round(44 * scale))
    f_small = _load_font(round(30 * scale), mono=True)

    # Accent bar + title, shared header for every archetype
    _gradient_bar(draw, box[0], box[1], box[0] + round(220 * scale), box[1] + round(10 * scale), palette)
    y = box[1] + round(40 * scale)
    for line in _wrap(draw, spec.title, f_title, box_w)[:2]:
        draw.text((box[0], y), line, font=f_title, fill=_hex_to_rgb(palette["text_primary"]))
        y += round(78 * scale)
    y += round(30 * scale)

    if spec.kind == "diagram":
        # Nodes = the beat's sentences, connected left-to-right with arrows.
        # Exact text, exact order - nothing invented.
        nodes = _sentences(spec.narration, 3) or [spec.narration]
        node_h = round(150 * scale)
        gap = round(60 * scale)
        node_w = (box_w - gap * (len(nodes) - 1)) // max(1, len(nodes))
        ny = y + max(0, (box[3] - y - node_h)) // 2
        accent = _hex_to_rgb(palette["accent_mid"])
        for i, node in enumerate(nodes):
            nx = box[0] + i * (node_w + gap)
            draw.rounded_rectangle(
                [nx, ny, nx + node_w, ny + node_h],
                radius=round(16 * scale), outline=accent, width=max(2, round(3 * scale)),
            )
            ty = ny + round(20 * scale)
            for line in _wrap(draw, node, f_small, node_w - round(40 * scale))[:4]:
                draw.text((nx + round(20 * scale), ty), line, font=f_small,
                          fill=_hex_to_rgb(palette["text_primary"]))
                ty += round(38 * scale)
            if i < len(nodes) - 1:
                ax0 = nx + node_w + round(8 * scale)
                ax1 = nx + node_w + gap - round(8 * scale)
                ay = ny + node_h // 2
                draw.line([(ax0, ay), (ax1, ay)], fill=accent, width=max(2, round(4 * scale)))
                ah = round(10 * scale)
                draw.polygon([(ax1, ay), (ax1 - ah, ay - ah), (ax1 - ah, ay + ah)], fill=accent)

    elif spec.kind == "proof":
        # Highlight exact figures from the narration; the numbers ARE the shot.
        figures = re.findall(r"\d+(?:\.\d+)?\s*%|\b\d+(?:\.\d+)?x\b|\b\d+(?:\.\d+)?\b", spec.narration)[:3]
        f_stat = _load_font(round(150 * scale))
        sx = box[0]
        for fig in figures:
            draw.text((sx, y), fig, font=f_stat, fill=_hex_to_rgb(palette["accent_start"]))
            sx += round(draw.textlength(fig, font=f_stat)) + round(90 * scale)
        y += round(190 * scale)
        for line in _wrap(draw, spec.narration, f_body, box_w)[:4]:
            draw.text((box[0], y), line, font=f_body, fill=_hex_to_rgb(palette["text_secondary"]))
            y += round(58 * scale)

    elif spec.kind == "cta":
        for line in _wrap(draw, spec.narration, f_body, box_w)[:4]:
            draw.text((box[0], y), line, font=f_body, fill=_hex_to_rgb(palette["text_primary"]))
            y += round(58 * scale)
        y += round(40 * scale)
        for link in spec.links[:4]:
            draw.text((box[0], y), link, font=f_small, fill=_hex_to_rgb(palette["accent_start"]))
            y += round(46 * scale)

    else:  # quote (and the hero/transition title-card fallback)
        quote_font = _load_font(round(58 * scale))
        draw.text((box[0], y), "“", font=_load_font(round(120 * scale)),
                  fill=_hex_to_rgb(palette["accent_end"]))
        y += round(110 * scale)
        for line in _wrap(draw, spec.narration, quote_font, box_w - round(60 * scale))[:6]:
            draw.text((box[0] + round(60 * scale), y), line, font=quote_font,
                      fill=_hex_to_rgb(palette["text_primary"]))
            y += round(74 * scale)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")
    return out_path


def render_scene_still(
    scene_id: str,
    kind: str,
    title: str,
    narration: str,
    platform_preset: str = "youtube_16_9",
    style_kit_id: str = _DEFAULT_KIT_ID,
    links: Optional[List[str]] = None,
) -> str:
    """Render a scene still and return the filename inside output_dir()."""
    width, height, margin = _PRESET_CANVAS.get(platform_preset, _PRESET_CANVAS["youtube_16_9"])
    spec = MotionGraphicSpec(
        kind=kind, title=title, narration=narration,
        width=width, height=height, safe_margin_pct=margin,
        style_kit_id=style_kit_id, links=links,
    )
    filename = f"{scene_id}.png"
    render_still(spec, output_dir() / filename)
    return filename
