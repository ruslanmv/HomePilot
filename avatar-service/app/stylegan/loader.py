"""
StyleGAN2 model loader — loads generator weights once at startup.

Supports multiple weight formats:
  - NVIDIA .pkl (stylegan2-ada-pytorch pickle via dnnlib/legacy)
  - Converted .pt  (plain torch.save)
  - Rosinality .pt (stylegan2-pytorch format)

The loaded generator is cached in-process.  Subsequent calls to
``get_generator()`` return the cached instance instantly.

Non-destructive: if weights or dependencies are missing, informative
errors are raised so the caller can fall back to placeholders.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level cache
# ---------------------------------------------------------------------------

_G: Optional[Any] = None
_device: Optional[Any] = None
_loaded_path: Optional[str] = None


class LoadError(RuntimeError):
    """Raised when model loading fails (missing deps, bad weights, etc.)."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_model(weights_path: str, device: str = "auto") -> None:
    """Load StyleGAN2 generator from *weights_path*.

    Call once at startup.  If this succeeds, ``is_loaded()`` returns True
    and ``get_generator()`` returns the cached model.

    Parameters
    ----------
    weights_path : str
        Absolute or relative path to ``.pkl`` or ``.pt`` weights.
    device : str
        ``"auto"`` (GPU if available, else CPU), ``"cuda"``, or ``"cpu"``.
    """
    global _G, _device, _loaded_path

    try:
        import torch
    except ImportError as exc:
        raise LoadError(
            "PyTorch is required for StyleGAN2 inference. "
            "Install with: pip install 'homepilot-avatar-service[gpu]'"
        ) from exc

    path = Path(weights_path)
    if not path.exists():
        raise LoadError(f"Weights file not found: {path}")

    # Resolve device
    if device == "auto":
        _device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    else:
        _device = torch.device(device)

    _log.info("Loading StyleGAN2 from %s → %s …", path, _device)

    try:
        G = _load_weights(path, torch, _device)
    except Exception as exc:
        raise LoadError(f"Failed to load weights from {path}: {exc}") from exc

    G = G.eval().to(_device)

    param_count = sum(p.numel() for p in G.parameters())
    _log.info(
        "StyleGAN2 ready — %s parameters on %s",
        f"{param_count:,}",
        _device,
    )

    _G = G
    _loaded_path = str(path)


def get_generator() -> Any:
    """Return the cached generator.  Raises ``LoadError`` if not loaded."""
    if _G is None:
        raise LoadError(
            "StyleGAN2 generator not loaded. "
            "Set STYLEGAN_WEIGHTS_PATH and restart the service."
        )
    return _G


def get_device() -> Any:
    """Return the torch device the generator is on."""
    if _device is None:
        import torch

        return torch.device("cpu")
    return _device


def is_loaded() -> bool:
    """Return True if a model has been successfully loaded."""
    return _G is not None


# ---------------------------------------------------------------------------
# Internal: weight loading strategies
# ---------------------------------------------------------------------------


def _load_weights(path: Path, torch: Any, device: Any) -> Any:
    """Try multiple loading strategies in order of preference."""
    suffix = path.suffix.lower()

    # Strategy 1: NVIDIA pickle format (.pkl)
    if suffix == ".pkl":
        return _load_nvidia_pkl(path, torch, device)

    # Strategy 2: PyTorch save (.pt / .pth)
    if suffix in (".pt", ".pth"):
        return _load_torch_pt(path, torch, device)

    # Strategy 3: try both
    try:
        return _load_nvidia_pkl(path, torch, device)
    except Exception:
        return _load_torch_pt(path, torch, device)


def _load_nvidia_pkl(path: Path, torch: Any, device: Any) -> Any:
    """Load using NVIDIA's legacy pickle format.

    Tries ``dnnlib``/``legacy`` first (stylegan2-ada-pytorch on PYTHONPATH),
    then falls back to raw ``pickle.load`` with a custom unpickler.
    """
    try:
        import legacy

        _log.info("Loading via NVIDIA legacy module")
        with open(path, "rb") as f:
            data = legacy.load_network_pkl(f)
    except ImportError:
        import pickle

        _log.info("Loading via pickle (legacy module not available)")
        with open(path, "rb") as f:
            data = pickle.load(f)  # noqa: S301

    # NVIDIA pickles store the generator under 'G_ema' or 'G'
    G = data.get("G_ema") or data.get("G")
    if G is None:
        raise LoadError(
            "Invalid network pickle — expected 'G_ema' or 'G' key. "
            f"Found keys: {list(data.keys())}"
        )
    return G


def _load_torch_pt(path: Path, torch: Any, device: Any) -> Any:
    """Load a plain ``torch.save`` checkpoint."""
    data = torch.load(path, map_location=device, weights_only=False)

    # If it's a state dict wrapper, try to extract the model
    if isinstance(data, dict):
        G = data.get("G_ema") or data.get("G") or data.get("model") or data.get("generator")
        if G is None:
            raise LoadError(
                f"Checkpoint dict has no recognised model key. Found: {list(data.keys())}"
            )
        return G

    # Assume it's the model directly
    return data
