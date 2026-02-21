"""
Face Restoration Service — ComfyUI-only architecture.

All GPU/ML work runs inside ComfyUI.  The backend is a thin HTTP
orchestrator that:
  1. Checks if ComfyUI is healthy (GET /system_stats)
  2. Checks if required nodes are registered (GET /object_info)
  3. Submits the fix_faces_gfpgan workflow
  4. Returns the result

The backend NEVER imports torch, gfpgan, facexlib, or basicsr.
One failure mode, one error message, one fix path.

Required ComfyUI setup (once):
  cd ComfyUI/custom_nodes
  git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git
  pip install facexlib gfpgan   # in ComfyUI's Python env
  # restart ComfyUI
"""

from __future__ import annotations

from typing import Optional, Tuple

import httpx

from .config import COMFY_BASE_URL

# ---------------------------------------------------------------------------
# Required ComfyUI nodes for face restoration
# ---------------------------------------------------------------------------
FACE_RESTORE_NODES = ["FaceRestoreModelLoader", "FaceRestoreWithModel"]

_INSTALL_HINT = (
    "Face restoration requires ComfyUI-Impact-Pack.\n\n"
    "Fix (run once, in ComfyUI's Python env):\n"
    "  cd ComfyUI/custom_nodes\n"
    "  git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack.git\n"
    "  pip install facexlib gfpgan\n"
    "  # then restart ComfyUI\n\n"
    "Verify: curl http://localhost:8188/object_info | grep FaceRestoreModelLoader"
)


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

def restore_faces_via_comfyui(
    image_url: str,
    model_filename: str = "GFPGANv1.4.pth",
) -> dict:
    """
    Restore faces by submitting the fix_faces_gfpgan workflow to ComfyUI.

    Args:
        image_url: Image URL or /files/... path
        model_filename: Face restore model (e.g. GFPGANv1.4.pth)

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

    # ── Submit workflow ────────────────────────────────────────────
    print(f"[FACE_RESTORE] Submitting fix_faces_gfpgan to ComfyUI")
    print(f"[FACE_RESTORE]   image={image_url}, model={model_filename}")

    result = run_workflow("fix_faces_gfpgan", {
        "image_path": image_url,
        "model_name": model_filename,
        "filename_prefix": "homepilot_face_restore",
    })

    images = result.get("images", [])
    print(f"[FACE_RESTORE] Completed — {len(images)} image(s) returned")
    return result
