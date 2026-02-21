"""
StyleGAN2 weight loader — placeholder.

Replace with real pickle-based weight loading when GPU weights are available.
"""

from __future__ import annotations


def load_model(weights_path: str, device: str = "cuda"):
    """Load StyleGAN2 model weights. Placeholder — not yet implemented."""
    raise NotImplementedError(
        "Real StyleGAN2 inference requires GPU weights. "
        f"Expected weights at: {weights_path}"
    )
