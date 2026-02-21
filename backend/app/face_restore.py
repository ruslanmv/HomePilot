"""
Face Restoration Service — ComfyUI-only architecture.

All GPU/ML work runs inside ComfyUI.  The backend is a thin HTTP
orchestrator that:
  1. Checks if ComfyUI is healthy (GET /system_stats)
  2. Checks if required nodes are registered (GET /object_info)
  3. Submits FaceDetailer or GFPGAN workflow
  4. Returns the result

The backend NEVER imports torch, gfpgan, facexlib, or basicsr.

Two workflow tiers:
  - **FaceDetailer** (preferred): Uses UltralyticsDetectorProvider to detect
    faces, crops them, re-generates each face region with a diffusion
    checkpoint, then composites back.  Best quality but requires ultralytics.
  - **GFPGAN** (fallback): Uses FaceRestoreModelLoader + FaceRestoreWithModel
    to apply GFPGAN/CodeFormer directly.  Simpler, fewer dependencies, and
    works even when UltralyticsDetectorProvider fails to load.

Required ComfyUI setup (once):
  cd ComfyUI/custom_nodes
  git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git
  pip install facexlib gfpgan   (in ComfyUI's Python env)
  # restart ComfyUI
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Optional, Tuple

import httpx

from .config import COMFY_BASE_URL

# ---------------------------------------------------------------------------
# Required ComfyUI nodes — two tiers
# ---------------------------------------------------------------------------

# Tier 1 (preferred): Full FaceDetailer pipeline — best quality
FACEDETAILER_NODES = ["FaceDetailer", "UltralyticsDetectorProvider"]

# Tier 2 (fallback): Simple GFPGAN pipeline — fewer deps, always works
GFPGAN_NODES = ["FaceRestoreModelLoader", "FaceRestoreWithModel"]

# Legacy alias kept for any external code that imports it
FACE_RESTORE_NODES = FACEDETAILER_NODES

_INSTALL_HINT = (
    "Face restoration requires ComfyUI-Impact-Pack.\n\n"
    "Fix (run once):\n"
    "  cd ComfyUI/custom_nodes\n"
    "  git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git\n"
    "  pip install ultralytics facexlib gfpgan   (in ComfyUI's Python env)\n"
    "  # then restart ComfyUI"
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
        - (True, "ready") if ComfyUI is up AND at least one tier of nodes exists
        - (False, human-readable reason) otherwise
    """
    if not comfyui_healthy():
        return False, (
            "ComfyUI is not reachable at "
            f"{COMFY_BASE_URL}. Start ComfyUI first."
        )

    from .comfy import check_nodes_available

    # Check tier 1 (FaceDetailer)
    ok_t1, missing_t1 = check_nodes_available(FACEDETAILER_NODES)
    if ok_t1:
        return True, "Face restoration ready (FaceDetailer)"

    # Check tier 2 (GFPGAN fallback)
    ok_t2, missing_t2 = check_nodes_available(GFPGAN_NODES)
    if ok_t2:
        return True, "Face restoration ready (GFPGAN)"

    all_missing = sorted(set(missing_t1 + missing_t2))
    return False, (
        "ComfyUI is running but face restoration nodes are not available.\n"
        f"Missing: {', '.join(all_missing)}\n"
        f"{_INSTALL_HINT}"
    )


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
    Restore faces via ComfyUI with automatic fallback.

    Strategy:
      1. Try the full FaceDetailer pipeline (best quality, needs ultralytics).
      2. If UltralyticsDetectorProvider is unavailable, fall back to the
         simpler GFPGAN workflow (FaceRestoreModelLoader + FaceRestoreWithModel).
      3. Raise only when neither tier is available.

    Args:
        image_url: Image URL or /files/... path
        model_filename: Face restore model name (e.g. "GFPGANv1.4.pth")

    Returns:
        {"images": [...], "videos": [...]} from ComfyUI

    Raises:
        ComfyUIUnavailable: ComfyUI is offline
        FaceRestoreNodesNotInstalled: Neither tier of nodes is available
        RuntimeError: Workflow execution failed
    """
    from .comfy import check_nodes_available, run_workflow

    # ── Pre-flight checks ─────────────────────────────────────────
    if not comfyui_healthy():
        raise ComfyUIUnavailable(
            f"ComfyUI is not reachable at {COMFY_BASE_URL}. "
            "Start ComfyUI and try again."
        )

    # ── Tier 1: FaceDetailer (preferred) ──────────────────────────
    ok_t1, missing_t1 = check_nodes_available(FACEDETAILER_NODES)
    if ok_t1:
        ckpt_name = _find_checkpoint()
        detector_model = _find_detector_model()

        print(f"[FACE_RESTORE] Using FaceDetailer pipeline")
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
        print(f"[FACE_RESTORE] FaceDetailer completed — {len(images)} image(s)")
        return result

    # ── Tier 2: GFPGAN fallback ───────────────────────────────────
    ok_t2, missing_t2 = check_nodes_available(GFPGAN_NODES)
    if ok_t2:
        print(f"[FACE_RESTORE] FaceDetailer unavailable (missing: {', '.join(missing_t1)})")
        print(f"[FACE_RESTORE] Falling back to GFPGAN workflow")
        print(f"[FACE_RESTORE]   image={image_url}, model={model_filename}")

        result = run_workflow("fix_faces_gfpgan", {
            "image_path": image_url,
            "model_name": model_filename,
            "filename_prefix": "homepilot_face_restore",
        })

        images = result.get("images", [])
        print(f"[FACE_RESTORE] GFPGAN completed — {len(images)} image(s)")
        return result

    # ── Neither tier available ────────────────────────────────────
    raise FaceRestoreNodesNotInstalled(
        f"No face restoration nodes available in ComfyUI.\n"
        f"  FaceDetailer missing: {', '.join(missing_t1)}\n"
        f"  GFPGAN missing: {', '.join(missing_t2)}\n\n"
        f"{_INSTALL_HINT}"
    )
