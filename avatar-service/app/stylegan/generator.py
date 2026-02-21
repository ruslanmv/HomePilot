"""
StyleGAN2 seeded generation — placeholder.

Replace with real inference when model weights and torch are available.
"""

from __future__ import annotations

from typing import List, Optional


def generate_faces(
    count: int = 4,
    seeds: Optional[List[int]] = None,
    truncation: float = 0.7,
) -> list:
    """Generate face images from StyleGAN2. Placeholder — returns empty list."""
    raise NotImplementedError(
        "StyleGAN2 inference not yet implemented. "
        "Using placeholder PNG generator instead."
    )
