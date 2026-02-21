"""
Standalone Face Restoration Service.

This module provides face restoration WITHOUT requiring ComfyUI or any
ComfyUI custom nodes (Impact-Pack).  It uses the gfpgan/facexlib libraries
directly in the backend Python environment.

Architecture:
  1. Detects faces using facexlib's RetinaFace detector
  2. Restores each face using GFPGAN (or CodeFormer)
  3. Pastes restored faces back into the original image
  4. Saves result to the upload directory and returns the file URL

Fallback chain (used by enhance.py):
  1. Standalone GFPGAN (this module) - preferred, no ComfyUI needed
  2. ComfyUI workflow (fix_faces_gfpgan) - if Impact-Pack is installed
  3. Clear error with install instructions

Dependencies (pip install in backend env):
  - gfpgan>=1.3.8
  - facexlib>=0.3.0
  - basicsr>=1.4.2
  - torch>=2.0 (CPU or CUDA)

Model files (auto-downloaded or manually placed):
  - GFPGANv1.4.pth  -> <comfy_models>/gfpgan/GFPGANv1.4.pth
  - codeformer.pth   -> <comfy_models>/codeformer/codeformer.pth
"""

from __future__ import annotations

import io
import os
import uuid
from pathlib import Path
from typing import Optional, Tuple

from .config import UPLOAD_DIR

# ---------------------------------------------------------------------------
# Lazy imports for heavy dependencies (torch, gfpgan, etc.)
# We don't want to fail at import time if they're not installed.
# ---------------------------------------------------------------------------

_gfpganer_instance: Optional[object] = None
_gfpgan_available: Optional[bool] = None


def _get_model_dir() -> Path:
    """
    Find the directory containing face restoration model weights.

    Searches in order:
      1. <repo_root>/models/comfy/gfpgan/
      2. <repo_root>/ComfyUI/models/gfpgan/
      3. /ComfyUI/models/gfpgan/ (Docker)
      4. ~/.gfpgan/weights/ (gfpgan default download location)
    """
    current_file = Path(__file__).resolve()
    repo_root = current_file.parent.parent.parent  # HomePilot root

    candidates = [
        repo_root / "models" / "comfy" / "gfpgan",
        repo_root / "ComfyUI" / "models" / "gfpgan",
        Path("/ComfyUI/models/gfpgan"),
        Path.home() / ".gfpgan" / "weights",
    ]

    for candidate in candidates:
        if candidate.exists() and any(candidate.glob("*.pth")):
            return candidate

    # Return the first candidate as default (will be created if needed)
    return candidates[0]


def _find_model_path(model_filename: str = "GFPGANv1.4.pth") -> Optional[Path]:
    """
    Find the model file on disk.

    Searches multiple locations for the model weights file.
    Returns None if not found anywhere.
    """
    current_file = Path(__file__).resolve()
    repo_root = current_file.parent.parent.parent

    search_dirs = [
        repo_root / "models" / "comfy" / "gfpgan",
        repo_root / "models" / "comfy" / "codeformer",
        repo_root / "ComfyUI" / "models" / "gfpgan",
        repo_root / "ComfyUI" / "models" / "codeformer",
        repo_root / "ComfyUI" / "models" / "facerestore_models",
        Path("/ComfyUI/models/gfpgan"),
        Path("/ComfyUI/models/codeformer"),
        Path("/ComfyUI/models/facerestore_models"),
        Path.home() / ".gfpgan" / "weights",
    ]

    for d in search_dirs:
        candidate = d / model_filename
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate

    return None


def check_standalone_available() -> Tuple[bool, str]:
    """
    Check if standalone face restoration is available.

    Returns:
        (available, reason) - True if gfpgan can be used directly,
        False with a human-readable reason explaining what's missing.
    """
    global _gfpgan_available

    if _gfpgan_available is not None:
        if _gfpgan_available:
            return True, "Standalone GFPGAN ready"
        # Re-check in case user installed deps since last check
        pass

    # Check Python dependencies
    missing_deps = []

    try:
        import torch  # noqa: F401
    except ImportError:
        missing_deps.append("torch")

    try:
        import gfpgan  # noqa: F401
    except ImportError:
        missing_deps.append("gfpgan")

    try:
        import facexlib  # noqa: F401
    except ImportError:
        missing_deps.append("facexlib")

    try:
        import basicsr  # noqa: F401
    except ImportError:
        missing_deps.append("basicsr")

    if missing_deps:
        _gfpgan_available = False
        return False, (
            f"Missing Python packages: {', '.join(missing_deps)}. "
            f"Install with: pip install {' '.join(missing_deps)}"
        )

    # Check for model weights
    model_path = _find_model_path("GFPGANv1.4.pth")
    if not model_path:
        # Also check for alternative model names
        alt_path = _find_model_path("GFPGANv1.3.pth")
        if not alt_path:
            _gfpgan_available = False
            return False, (
                "GFPGAN model weights not found. "
                "Download GFPGANv1.4.pth to models/comfy/gfpgan/ or "
                "let the service auto-download on first use."
            )

    _gfpgan_available = True
    return True, "Standalone GFPGAN ready"


def _get_gfpganer(
    model_name: str = "GFPGANv1.4.pth",
    upscale: int = 1,
) -> object:
    """
    Get or create the GFPGANer instance (lazy singleton).

    The GFPGANer class from the gfpgan library handles:
      - Face detection (via facexlib RetinaFace)
      - Face alignment and cropping
      - Face restoration via the GFPGAN network
      - Pasting restored faces back into the original image

    Args:
        model_name: Model filename (e.g. "GFPGANv1.4.pth")
        upscale: Output upscale factor (1 = same size, 2 = 2x)

    Returns:
        GFPGANer instance ready for inference
    """
    global _gfpganer_instance

    if _gfpganer_instance is not None:
        return _gfpganer_instance

    import torch
    from gfpgan import GFPGANer

    model_path = _find_model_path(model_name)

    # Determine model architecture version from filename
    if "v1.4" in model_name.lower() or "v14" in model_name.lower():
        arch = "clean"
        channel_multiplier = 2
        model_version = "1.4"
    elif "v1.3" in model_name.lower() or "v13" in model_name.lower():
        arch = "clean"
        channel_multiplier = 2
        model_version = "1.3"
    elif "v1.2" in model_name.lower() or "v12" in model_name.lower():
        arch = "clean"
        channel_multiplier = 2
        model_version = "1.2"
    else:
        # Default to v1.4 architecture
        arch = "clean"
        channel_multiplier = 2
        model_version = "1.4"

    # Use CUDA if available, otherwise CPU
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[FACE_RESTORE] Initializing GFPGANer on {device}")
    print(f"[FACE_RESTORE] Model: {model_name} (v{model_version}, arch={arch})")

    if model_path:
        print(f"[FACE_RESTORE] Using local model: {model_path}")
        restorer = GFPGANer(
            model_path=str(model_path),
            upscale=upscale,
            arch=arch,
            channel_multiplier=channel_multiplier,
            bg_upsampler=None,  # No background upsampling for speed
            device=device,
        )
    else:
        # Let gfpgan auto-download the model
        print(f"[FACE_RESTORE] Model not found locally, will auto-download")
        model_dir = _get_model_dir()
        model_dir.mkdir(parents=True, exist_ok=True)
        restorer = GFPGANer(
            model_path=str(model_dir / model_name),
            upscale=upscale,
            arch=arch,
            channel_multiplier=channel_multiplier,
            bg_upsampler=None,
            device=device,
        )

    _gfpganer_instance = restorer
    print(f"[FACE_RESTORE] GFPGANer initialized successfully")
    return restorer


def restore_faces(
    image_path: str,
    model_name: str = "GFPGANv1.4.pth",
    aligned: bool = False,
    only_center_face: bool = False,
    paste_back: bool = True,
    weight: float = 0.5,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Restore faces in an image using GFPGAN directly (no ComfyUI).

    This function:
      1. Loads the input image
      2. Detects and restores faces using GFPGANer
      3. Saves the result to UPLOAD_DIR
      4. Returns the output filename for the /files/ endpoint

    Args:
        image_path: Path to the input image (local path or URL-downloaded file)
        model_name: GFPGAN model filename
        aligned: Whether input faces are already aligned
        only_center_face: Only restore the center/largest face
        paste_back: Paste restored faces back into the original image
        weight: Blending weight for CodeFormer fidelity (0=quality, 1=fidelity)

    Returns:
        (output_filename, error) - filename relative to UPLOAD_DIR if successful,
        error message string if failed.
    """
    try:
        import cv2
        import numpy as np
        from PIL import Image
    except ImportError as e:
        return None, f"Missing dependency: {e}. pip install opencv-python-headless numpy Pillow"

    print(f"[FACE_RESTORE] Standalone restore_faces called")
    print(f"[FACE_RESTORE]   image_path={image_path}")
    print(f"[FACE_RESTORE]   model={model_name}, aligned={aligned}")

    # Load image
    try:
        if image_path.startswith(('http://', 'https://')):
            # Download from URL
            import httpx
            with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                r = client.get(image_path)
                r.raise_for_status()
                img_array = np.frombuffer(r.content, np.uint8)
                input_img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        elif image_path.startswith('/files/'):
            # Local backend file
            filename = image_path.replace('/files/', '', 1)
            local_path = Path(UPLOAD_DIR) / filename
            if not local_path.exists():
                return None, f"File not found: {local_path}"
            input_img = cv2.imread(str(local_path), cv2.IMREAD_COLOR)
        else:
            # Direct local path
            input_img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)

        if input_img is None:
            return None, f"Failed to load image from {image_path}"

        print(f"[FACE_RESTORE] Input image loaded: {input_img.shape}")
    except Exception as e:
        return None, f"Failed to load image: {e}"

    # Run face restoration
    try:
        restorer = _get_gfpganer(model_name=model_name, upscale=1)

        # GFPGANer.enhance() returns (cropped_faces, restored_faces, output_img)
        # - cropped_faces: list of detected face crops (BGR numpy arrays)
        # - restored_faces: list of restored face crops
        # - output_img: full image with faces pasted back (if paste_back=True)
        cropped_faces, restored_faces, output_img = restorer.enhance(
            input_img,
            has_aligned=aligned,
            only_center_face=only_center_face,
            paste_back=paste_back,
            weight=weight,
        )

        num_faces = len(restored_faces)
        print(f"[FACE_RESTORE] Detected and restored {num_faces} face(s)")

        if output_img is None:
            if num_faces == 0:
                return None, "No faces detected in the image"
            return None, "Face restoration produced no output"

    except Exception as e:
        return None, f"Face restoration failed: {e}"

    # Save output image
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        output_filename = f"face_restored_{uuid.uuid4().hex[:12]}.png"
        output_path = Path(UPLOAD_DIR) / output_filename

        # Convert BGR -> RGB for saving, then write via OpenCV
        success = cv2.imwrite(str(output_path), output_img)
        if not success:
            return None, f"Failed to save output image to {output_path}"

        file_size = output_path.stat().st_size
        print(f"[FACE_RESTORE] Output saved: {output_filename} ({file_size} bytes)")

        return output_filename, None
    except Exception as e:
        return None, f"Failed to save output: {e}"


def invalidate_model_cache() -> None:
    """
    Clear the cached GFPGANer instance.

    Call this if the model weights changed on disk or if you need
    to free GPU memory.
    """
    global _gfpganer_instance, _gfpgan_available
    _gfpganer_instance = None
    _gfpgan_available = None
    print("[FACE_RESTORE] Model cache invalidated")
