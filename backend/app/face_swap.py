"""
Face Swap — implementation using ComfyUI ReActor / InSwapper workflow.

Additive module — called by enhance.py's identity_edit endpoint when
tool_type == "face_swap".  Does NOT modify any existing module.

Pipeline:
  1. Load source image (body/scene to keep)
  2. Load reference image (face donor)
  3. InsightFace face detection (AntelopeV2)
  4. InSwapper / ReActor face swap
  5. GFPGAN face enhancement (post-swap quality pass)
  6. Save output

Architecture:
  Backend is a thin HTTP orchestrator.  ALL GPU/ML work runs inside ComfyUI.
  The backend never imports torch, insightface, or any ML library.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .comfy import run_workflow


# ---------------------------------------------------------------------------
# Workflow name — maps to workflows/face_swap.json
# ---------------------------------------------------------------------------

WORKFLOW_NAME = "face_swap"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute_face_swap(
    source_image_url: str,
    reference_image_url: str,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Perform face swap using ComfyUI InSwapper/ReActor workflow.

    Args:
        source_image_url: URL or path of the target image (body to keep)
        reference_image_url: URL or path of the face donor image
        seed: Optional seed for reproducibility

    Returns:
        {"images": ["/outputs/face_swap_<id>.png", ...], "seed": int}

    Raises:
        Exception on workflow failure (caught by caller in enhance.py)
    """
    effective_seed = seed if seed is not None else random.randint(1, 2**32)

    print(f"[FACE SWAP] source={source_image_url[:80]}")
    print(f"[FACE SWAP] reference={reference_image_url[:80]}")
    print(f"[FACE SWAP] seed={effective_seed}")

    variables = {
        "image_path": source_image_url,
        "reference_image_path": reference_image_url,
        "seed": effective_seed,
        "filename_prefix": "homepilot_face_swap",
    }

    result = run_workflow(WORKFLOW_NAME, variables)

    images = result.get("images", [])
    print(f"[FACE SWAP] Completed — {len(images)} output(s)")

    return {
        "images": images,
        "seed": effective_seed,
    }
