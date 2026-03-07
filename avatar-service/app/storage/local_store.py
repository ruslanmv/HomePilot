"""
Avatar image storage — saves generated images to disk and returns URL dicts.

Contains both the original placeholder generator (preserved for fallback)
and a new ``save_pil_images()`` function for real StyleGAN2 outputs.
"""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw

OUTPUT_DIR = Path(os.getenv("AVATAR_OUTPUT_DIR", "../backend/data/uploads"))


def save_placeholder_pngs(
    count: int,
    seeds: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Generate placeholder PNG images and return result dicts."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not seeds:
        seeds = [random.randint(0, 2**31 - 1) for _ in range(count)]

    results: list[dict[str, Any]] = []
    for s in seeds[:count]:
        # Deterministic colour from seed
        r_val = (s * 37) % 200 + 30
        g_val = (s * 73) % 200 + 30
        b_val = (s * 113) % 200 + 30

        img = Image.new("RGB", (512, 512), color=(r_val, g_val, b_val))
        d = ImageDraw.Draw(img)
        d.text((20, 20), f"Avatar Placeholder\nseed={s}", fill=(240, 240, 240))
        d.ellipse([156, 100, 356, 300], outline=(255, 255, 255), width=2)  # face outline
        d.ellipse([200, 170, 240, 210], fill=(255, 255, 255))  # left eye
        d.ellipse([272, 170, 312, 210], fill=(255, 255, 255))  # right eye
        d.arc([210, 230, 302, 290], start=0, end=180, fill=(255, 255, 255), width=2)  # smile

        name = f"avatar_{int(time.time())}_{s}.png"
        path = OUTPUT_DIR / name
        img.save(path)

        results.append({
            "url": f"/files/{name}",
            "seed": s,
            "metadata": {"generator": "placeholder"},
        })

    return results


def save_pil_images(
    images: List[Dict[str, Any]],
    output_size: int = 512,
    sharpen: bool = True,
) -> List[Dict[str, Any]]:
    """Save PIL Images produced by a real generator (StyleGAN2, etc.).

    Additive: does not modify the placeholder generator above.

    Parameters
    ----------
    images : list[dict]
        Each dict must contain:
          - ``image``: PIL.Image.Image
          - ``seed``: int
          - ``metadata``: dict (optional)
    output_size : int
        Target square dimension for saved images.
    sharpen : bool
        Apply a mild sharpen filter (helps with upscaled StyleGAN outputs).

    Returns
    -------
    list[dict]
        Each dict has ``url``, ``seed``, ``metadata`` — same shape as
        ``save_placeholder_pngs`` so the caller doesn't need to change.
    """
    from PIL import ImageFilter

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for item in images:
        img = item.get("image")
        if img is None:
            continue

        seed = item.get("seed", 0)
        meta = item.get("metadata", {})

        # Resize if needed
        if img.size != (output_size, output_size):
            img = img.resize((output_size, output_size), Image.LANCZOS)

        # Mild sharpen for upscaled outputs
        if sharpen:
            img = img.filter(ImageFilter.SHARPEN)

        name = f"avatar_{int(time.time() * 1000)}_{seed}.png"
        path = OUTPUT_DIR / name
        img.save(path, format="PNG", optimize=True)

        results.append({
            "url": f"/files/{name}",
            "seed": seed,
            "metadata": meta,
        })

    return results
