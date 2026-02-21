"""
Placeholder PNG generator — produces labelled images for end-to-end testing.

Replace with real StyleGAN2 inference when GPU weights are available.
"""

from __future__ import annotations

import os
import random
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw

OUTPUT_DIR = Path(os.getenv("AVATAR_OUTPUT_DIR", "../backend/data/avatars"))


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
            "url": f"/static/avatars/{name}",
            "seed": s,
            "metadata": {"generator": "placeholder"},
        })

    return results
