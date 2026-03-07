"""
Avatar workflow runner — executes preset workflows via ComfyUI.

Additive module.  Provides a higher-level API for running avatar workflows
using preset configurations from the registry.  This complements (does NOT
replace) the existing ``services.comfyui.workflows.run_avatar_workflow()``.

Features:
  - Deep variable replacement (``{{var}}``) in workflow JSON templates
  - Automatic image upload to ComfyUI input directory
  - Preset-aware defaults (steps, cfg, sampler, dimensions)
  - Identity strength injection for InstantID nodes

Non-destructive: existing code paths are untouched.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from .registry import WorkflowPreset
from ...services.comfyui.client import (
    ComfyUIUnavailable,
    comfyui_healthy,
    submit_prompt,
    wait_for_images,
)
from ...avatar.schemas import AvatarResult

_log = logging.getLogger(__name__)

# Workflow template directories
AVATAR_WORKFLOW_DIR = Path(__file__).resolve().parents[4] / "workflows" / "avatar"
COMFYUI_WORKFLOW_DIR = Path(__file__).resolve().parents[4] / "comfyui" / "workflows"


class WorkflowRunnerError(RuntimeError):
    """Raised when a workflow execution fails."""


# ---------------------------------------------------------------------------
# Variable injection
# ---------------------------------------------------------------------------


def deep_replace(obj: Any, variables: Dict[str, Any]) -> Any:
    """Recursively replace ``{{key}}`` placeholders in a workflow graph.

    Works on strings, lists, and dicts.  Numeric values stored as strings
    that match ``{{key}}`` exactly are replaced with the typed value
    (so ``"{{steps}}"`` becomes ``30`` not ``"30"``).
    """
    if isinstance(obj, str):
        # Exact match → return typed value (int, float, etc.)
        stripped = obj.strip()
        if stripped.startswith("{{") and stripped.endswith("}}"):
            key = stripped[2:-2]
            if key in variables:
                return variables[key]
        # Partial match → string replacement
        for key, val in variables.items():
            obj = obj.replace("{{" + key + "}}", str(val))
        return obj
    if isinstance(obj, list):
        return [deep_replace(item, variables) for item in obj]
    if isinstance(obj, dict):
        return {k: deep_replace(v, variables) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# Graph loader
# ---------------------------------------------------------------------------


def load_graph(preset: WorkflowPreset) -> Dict[str, Any]:
    """Load the ComfyUI JSON graph for a preset.

    Resolves ``__comfyui__/`` prefix to the global ComfyUI workflow directory.
    """
    graph_file = preset.graph_file

    if graph_file.startswith("__comfyui__/"):
        path = COMFYUI_WORKFLOW_DIR / graph_file[len("__comfyui__/"):]
    elif graph_file.startswith("__"):
        raise WorkflowRunnerError(
            f"Preset {preset.id} uses virtual graph '{graph_file}' — "
            "not a ComfyUI workflow (handle externally)."
        )
    else:
        path = AVATAR_WORKFLOW_DIR / graph_file

    if not path.exists():
        raise WorkflowRunnerError(f"Workflow template not found: {path}")

    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_preset_workflow(
    *,
    comfyui_url: str,
    preset: WorkflowPreset,
    prompt: str,
    negative_prompt: Optional[str] = None,
    reference_image: Optional[str] = None,
    subject_image: Optional[str] = None,
    mask_image: Optional[str] = None,
    pose_image: Optional[str] = None,
    count: int = 1,
    seed: Optional[int] = None,
    checkpoint: Optional[str] = None,
    identity_strength: Optional[float] = None,
    denoise: Optional[float] = None,
    extra_vars: Optional[Dict[str, Any]] = None,
) -> List[AvatarResult]:
    """Execute a preset workflow and return avatar results.

    Builds a variable dict from the preset defaults + overrides,
    loads the graph, injects variables, and submits to ComfyUI.

    Parameters
    ----------
    comfyui_url : str
        ComfyUI base URL (e.g., ``http://localhost:8188``).
    preset : WorkflowPreset
        Workflow preset from the registry.
    prompt : str
        Positive prompt text.
    negative_prompt : str, optional
        Negative prompt text.
    reference_image : str, optional
        Face/body reference image (local path or ComfyUI input name).
    subject_image : str, optional
        Image to edit (for inpainting/repair workflows).
    mask_image : str, optional
        Mask image (for inpainting workflows).
    pose_image : str, optional
        Pose reference (for OpenPose workflows).
    count : int
        Number of images to generate.
    seed : int, optional
        Generation seed (random if not provided).
    checkpoint : str, optional
        Override checkpoint name.
    identity_strength : float, optional
        InstantID/IP-Adapter weight (0.0–1.0).
    denoise : float, optional
        Override denoise value.
    extra_vars : dict, optional
        Additional template variables.
    """
    if not comfyui_healthy(comfyui_url):
        raise ComfyUIUnavailable("ComfyUI is offline")

    wf_template = load_graph(preset)
    base_seed = seed if seed is not None else random.randint(0, 2**31 - 1)

    # Build variable dict from preset defaults + overrides
    variables: Dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": negative_prompt or "",
        "width": preset.default_width,
        "height": preset.default_height,
        "steps": preset.default_steps,
        "cfg": preset.default_cfg,
        "sampler_name": preset.default_sampler,
        "scheduler": preset.default_scheduler,
        "denoise": denoise if denoise is not None else preset.default_denoise,
        "batch_size": 1,  # We loop per-image for reference-based workflows
        "batch": 1,
    }

    if checkpoint:
        variables["ckpt_name"] = checkpoint
    if identity_strength is not None:
        variables["identity_strength"] = identity_strength
    if reference_image:
        variables["ref_image"] = reference_image
    if subject_image:
        variables["subject_image"] = subject_image
        variables["image_path"] = subject_image
    if mask_image:
        variables["mask_image"] = mask_image
        variables["mask_path"] = mask_image
    if pose_image:
        variables["pose_image"] = pose_image
    if extra_vars:
        variables.update(extra_vars)

    # Generate count images (submit workflow once per image with different seeds)
    results: List[AvatarResult] = []
    for i in range(count):
        variables["seed"] = base_seed + i
        wf = deep_replace(json.loads(json.dumps(wf_template)), variables)

        _log.info(
            "[WorkflowRunner] Submitting preset=%s seed=%d (%d/%d)",
            preset.id, base_seed + i, i + 1, count,
        )

        prompt_id = await submit_prompt(comfyui_url, wf)
        images = await wait_for_images(comfyui_url, prompt_id)

        if images:
            filename = images[0].get("filename", "")
            results.append(
                AvatarResult(
                    url=f"/comfy/view/{filename}",
                    seed=base_seed + i,
                    metadata={
                        "source": "comfyui",
                        "workflow": preset.graph_file,
                        "preset": preset.id,
                    },
                )
            )

    return results
