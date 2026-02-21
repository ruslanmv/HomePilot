"""
Face Restoration Service — ComfyUI-only architecture.

All GPU/ML work runs inside ComfyUI.  The backend is a thin HTTP
orchestrator that:
  1. Checks if ComfyUI is healthy (GET /system_stats)
  2. Checks if required nodes are registered (GET /object_info)
  3. Submits a FaceDetailer workflow (Impact-Pack)
  4. Returns the result

The backend NEVER imports torch, gfpgan, facexlib, or basicsr.
One failure mode, one error message, one fix path.

Required ComfyUI setup (once):
  cd ComfyUI/custom_nodes
  git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git
  # restart ComfyUI

The FaceDetailer node (from Impact-Pack) detects faces, crops them,
re-generates/enhances each face region using a diffusion checkpoint,
and composites the result back.  It requires a checkpoint model,
a face bbox detector provider (Ultralytics), and conditioning.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional, Tuple

import httpx

from .config import COMFY_BASE_URL

# ---------------------------------------------------------------------------
# Required ComfyUI nodes for face restoration (FaceDetailer pipeline)
# ---------------------------------------------------------------------------
FACE_RESTORE_NODES = ["FaceDetailer", "UltralyticsDetectorProvider"]

_INSTALL_HINT = (
    "Face restoration requires ComfyUI-Impact-Pack + ultralytics.\n\n"
    "Fix (run once):\n"
    "  cd ComfyUI/custom_nodes\n"
    "  git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git\n"
    "  # Ultralytics detector provider typically requires:\n"
    "  pip install ultralytics   (in ComfyUI's Python env)\n"
    "  # then restart ComfyUI\n\n"
    "Verify: curl http://localhost:8188/object_info | python3 -c \"\n"
    "  import sys,json; d=json.load(sys.stdin)\n"
    "  print('FaceDetailer' in d, 'UltralyticsDetectorProvider' in d)\""
)

# ---------------------------------------------------------------------------
# Face detector model (ships with Impact-Pack)
# ---------------------------------------------------------------------------
_DETECTOR_MODELS = [
    "bbox/face_yolov8m.pt",
    "bbox/face_yolov8n.pt",
    "bbox/face_yolov8s.pt",
]

# Checkpoint fallback order for FaceDetailer (needs a full diffusion model)
_CHECKPOINT_FALLBACKS = [
    "sd_xl_base_1.0_inpainting_0.1.safetensors",
    "sd_xl_base_1.0.safetensors",
    "v1-5-pruned-emaonly.safetensors",
    "v1-5-pruned.safetensors",
]


class ComfyUIUnavailable(Exception):
    """Raised when ComfyUI cannot be reached."""
    pass


class FaceRestoreNodesNotInstalled(Exception):
    """Raised when the required Impact-Pack nodes are not registered."""
    pass


# ---------------------------------------------------------------------------
# Health & readiness checks
# ---------------------------------------------------------------------------

def comfyui_healthy() -> bool:
    """
    Quick liveness check — can we reach ComfyUI at all?

    Uses /system_stats (lightweight, no side effects).
    Returns True if ComfyUI responds with 200, False otherwise.
    """
    try:
        r = httpx.get(
            f"{COMFY_BASE_URL}/system_stats",
            timeout=5.0,
        )
        return r.status_code == 200
    except Exception:
        return False


def face_restore_ready() -> Tuple[bool, str]:
    """
    Readiness check — is face restoration available?

    Returns:
        (ready, message)
        - (True, "ready") if ComfyUI is up AND the required nodes exist
        - (False, human-readable reason) otherwise
    """
    if not comfyui_healthy():
        return False, (
            "ComfyUI is not reachable at "
            f"{COMFY_BASE_URL}. Start ComfyUI first."
        )

    # Check if the required nodes are registered
    from .comfy import check_nodes_available
    ok, missing = check_nodes_available(FACE_RESTORE_NODES)

    if not ok:
        return False, (
            f"ComfyUI is running but missing node(s): {', '.join(missing)}.\n"
            f"{_INSTALL_HINT}"
        )

    return True, "Face restoration ready (ComfyUI)"


# ---------------------------------------------------------------------------
# Public API — used by enhance.py
# ---------------------------------------------------------------------------

def _find_checkpoint() -> str:
    """
    Find an available checkpoint for FaceDetailer.

    FaceDetailer needs a full diffusion checkpoint (unlike GFPGAN which was
    a standalone model).  We try common checkpoints in order of preference.

    Returns the checkpoint filename, or the first fallback if none are found
    (the workflow will fail with a clear ComfyUI error in that case).
    """
    from .providers import get_comfy_models_path

    models_path = get_comfy_models_path()
    for ckpt in _CHECKPOINT_FALLBACKS:
        ckpt_path = models_path / "checkpoints" / ckpt
        if ckpt_path.exists() and ckpt_path.stat().st_size > 0:
            return ckpt
    # No checkpoint found — return default, ComfyUI will give a clear error
    return _CHECKPOINT_FALLBACKS[0]


def _find_detector_model() -> str:
    """
    Find an available face detector model for UltralyticsDetectorProvider.

    Impact-Pack ships with bbox/face_yolov8m.pt by default.
    Returns the detector model name.
    """
    # Impact-Pack stores detector models under its own directory,
    # not under ComfyUI/models.  Just return the most common default.
    return _DETECTOR_MODELS[0]


def restore_faces_via_comfyui(
    image_url: str,
    model_filename: str = "GFPGANv1.4.pth",
) -> dict:
    """
    Restore faces by submitting a FaceDetailer workflow to ComfyUI.

    Uses the Impact-Pack FaceDetailer node which:
      1. Detects faces with UltralyticsDetectorProvider (bbox)
      2. Crops each face region
      3. Re-generates/enhances the face using a diffusion checkpoint
      4. Composites the result back into the original image

    Args:
        image_url: Image URL or /files/... path
        model_filename: Face restore model hint (used for logging; the
            actual model used is the checkpoint found by _find_checkpoint)

    Returns:
        {"images": [...], "videos": [...]} from ComfyUI

    Raises:
        ComfyUIUnavailable: ComfyUI is offline
        FaceRestoreNodesNotInstalled: Impact-Pack not installed
        RuntimeError: Workflow execution failed
    """
    from .comfy import check_nodes_available, run_workflow

    # ── Pre-flight checks ─────────────────────────────────────────
    if not comfyui_healthy():
        raise ComfyUIUnavailable(
            f"ComfyUI is not reachable at {COMFY_BASE_URL}. "
            "Start ComfyUI and try again."
        )

    ok, missing = check_nodes_available(FACE_RESTORE_NODES)
    if not ok:
        raise FaceRestoreNodesNotInstalled(
            f"Missing ComfyUI nodes: {', '.join(missing)}.\n{_INSTALL_HINT}"
        )

    # ── Resolve checkpoint and detector model ─────────────────────
    ckpt_name = _find_checkpoint()
    detector_model = _find_detector_model()

    # ── Submit workflow ────────────────────────────────────────────
    print(f"[FACE_RESTORE] Submitting fix_faces_facedetailer to ComfyUI")
    print(f"[FACE_RESTORE]   image={image_url}")
    print(f"[FACE_RESTORE]   checkpoint={ckpt_name}, detector={detector_model}")

    result = run_workflow("fix_faces_facedetailer", {
        "image_path": image_url,
        "ckpt_name": ckpt_name,
        "detector_model": detector_model,
        "denoise": 0.4,
        "seed": random.randint(1, 2**31),
        "filename_prefix": "homepilot_face_restore",
    })

    images = result.get("images", [])
    print(f"[FACE_RESTORE] Completed — {len(images)} image(s) returned")
    return result
