"""
StyleGAN2 seeded face generation.

Generates deterministic face images from random or fixed seeds using the
loaded StyleGAN2 generator.  Each seed always produces the same face,
enabling reproducible results and seed-based exploration.

Non-destructive design:
  - If the model is not loaded, raises ``StyleGANUnavailable`` so the
    caller can fall back to placeholder generation.
  - Never modifies the loaded model or global state.
  - All outputs are new PIL Images (no mutation).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PIL import Image

from .loader import LoadError, get_device, get_generator, is_loaded

_log = logging.getLogger(__name__)


class StyleGANUnavailable(RuntimeError):
    """Raised when StyleGAN inference cannot run."""


def generate_faces(
    count: int = 4,
    seeds: Optional[List[int]] = None,
    truncation: float = 0.7,
    output_size: int = 512,
) -> List[Dict[str, Any]]:
    """Generate face images from StyleGAN2.

    Parameters
    ----------
    count : int
        Number of faces to generate (1-8).
    seeds : list[int] | None
        Deterministic seeds.  If None or too short, random seeds are used.
    truncation : float
        Truncation psi (0.1-1.0).  Lower = more "average" face,
        higher = more diverse/unusual.
    output_size : int
        Output image dimension (square).

    Returns
    -------
    list[dict]
        Each dict has: ``image`` (PIL.Image), ``seed`` (int), ``metadata`` (dict).

    Raises
    ------
    StyleGANUnavailable
        If the generator is not loaded.
    """
    if not is_loaded():
        raise StyleGANUnavailable(
            "StyleGAN2 model not loaded. "
            "Set STYLEGAN_WEIGHTS_PATH and restart the service."
        )

    try:
        import numpy as np
        import torch
    except ImportError as exc:
        raise StyleGANUnavailable(f"Missing dependency: {exc}") from exc

    G = get_generator()
    device = get_device()
    truncation = float(max(0.1, min(1.0, truncation)))

    # Fill in missing seeds
    if seeds is None:
        seeds = []
    if len(seeds) < count:
        import random as _rng

        seeds = list(seeds) + [_rng.randint(0, 2**31 - 1) for _ in range(count - len(seeds))]

    results: List[Dict[str, Any]] = []

    with torch.no_grad():
        for seed in seeds[:count]:
            pil_img = _generate_single(G, seed, truncation, device, np, torch)

            # Resize if model output differs from requested size
            if pil_img.size[0] != output_size or pil_img.size[1] != output_size:
                pil_img = pil_img.resize((output_size, output_size), Image.LANCZOS)

            results.append({
                "image": pil_img,
                "seed": seed,
                "metadata": {
                    "generator": "stylegan2",
                    "truncation": truncation,
                    "native_resolution": G.img_resolution if hasattr(G, "img_resolution") else "unknown",
                },
            })

    _log.info("Generated %d face(s) with truncation=%.2f", len(results), truncation)
    return results


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _generate_single(
    G: Any,
    seed: int,
    truncation: float,
    device: Any,
    np: Any,
    torch: Any,
) -> Image.Image:
    """Generate a single face from a seed.  Returns a PIL RGB Image."""
    # Deterministic latent vector from seed
    z = torch.from_numpy(
        np.random.RandomState(seed).randn(1, G.z_dim)
    ).to(device=device, dtype=torch.float32)

    # Class conditioning (usually None for FFHQ)
    c = None
    if hasattr(G, "c_dim") and G.c_dim > 0:
        c = torch.zeros([1, G.c_dim], device=device)

    # Generate — handles both NVIDIA and Rosinality API styles
    if hasattr(G, "mapping") and hasattr(G, "synthesis"):
        # NVIDIA stylegan2-ada-pytorch style
        w = G.mapping(z, c)
        if hasattr(G.mapping, "w_avg"):
            w_avg = G.mapping.w_avg.unsqueeze(0).unsqueeze(1)
            w = w_avg + truncation * (w - w_avg)
        img = G.synthesis(w, noise_mode="const")
    else:
        # Direct forward pass (Rosinality or simple models)
        img = G(z, c, truncation_psi=truncation, noise_mode="const")

    return _tensor_to_pil(img[0], torch)


def _tensor_to_pil(tensor: Any, torch: Any) -> Image.Image:
    """Convert a CHW float tensor in [-1, 1] → PIL RGB Image."""
    x = tensor.detach().to(dtype=torch.float32, device="cpu")
    x = (x * 127.5 + 128).clamp(0, 255).to(torch.uint8)
    x = x.permute(1, 2, 0).contiguous().numpy()
    return Image.fromarray(x, mode="RGB")
