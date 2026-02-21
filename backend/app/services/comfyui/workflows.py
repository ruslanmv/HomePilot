"""
ComfyUI workflow loader — load JSON templates and inject runtime inputs.

Workflow templates live in ``workflows/avatar/`` at the project root.
The backend injects prompt text, seed, batch size, and reference images
into well-known ComfyUI node class_types.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...avatar.schemas import AvatarResult
from .client import ComfyUIUnavailable, comfyui_healthy, submit_prompt, wait_for_images

WORKFLOW_DIR = Path(__file__).resolve().parents[4] / "workflows" / "avatar"


async def run_avatar_workflow(
    comfyui_base_url: str,
    mode: str,
    prompt: str,
    reference_image_url: Optional[str],
    count: int,
    seed: Optional[int],
    checkpoint_override: Optional[str] = None,
) -> List[AvatarResult]:
    """Load a workflow template, inject inputs, submit, and collect results."""
    if not comfyui_healthy(comfyui_base_url):
        raise ComfyUIUnavailable("Face/avatar service (ComfyUI) is offline")

    wf_path = _workflow_path(mode)
    wf: Dict[str, Any] = json.loads(wf_path.read_text())

    _inject_prompt(wf, prompt)
    _inject_seed(wf, seed)
    _inject_batch_size(wf, count)
    _inject_reference(wf, reference_image_url)
    _inject_checkpoint(wf, checkpoint_override)

    prompt_id = await submit_prompt(comfyui_base_url, wf)
    images = await wait_for_images(comfyui_base_url, prompt_id)

    results: list[AvatarResult] = []
    for i, img in enumerate(images[:count]):
        filename = img.get("filename", "")
        results.append(
            AvatarResult(
                url=f"/comfy/view/{filename}",
                seed=(seed + i) if seed is not None else None,
                metadata={"source": "comfyui", "workflow": wf_path.name},
            )
        )
    return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _workflow_path(mode: str) -> Path:
    mapping = {
        "studio_reference": "avatar_instantid.json",
        "studio_faceswap": "avatar_faceswap.json",
        "creative": "avatar_photomaker.json",
    }
    name = mapping.get(mode)
    if not name:
        raise ValueError(f"Unsupported ComfyUI avatar mode: {mode}")
    return WORKFLOW_DIR / name


def _inject_prompt(wf: Dict[str, Any], prompt: str) -> None:
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") in (
            "CLIPTextEncode",
            "TextEncode",
            "Text Encode",
        ):
            node.setdefault("inputs", {})["text"] = prompt


def _inject_seed(wf: Dict[str, Any], seed: Optional[int]) -> None:
    if seed is None:
        return
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") in (
            "KSampler",
            "SamplerCustom",
            "KSamplerAdvanced",
        ):
            node.setdefault("inputs", {})["seed"] = seed


def _inject_batch_size(wf: Dict[str, Any], count: int) -> None:
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage":
            node.setdefault("inputs", {})["batch_size"] = count


def _inject_reference(wf: Dict[str, Any], ref: Optional[str]) -> None:
    if not ref:
        return
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") in (
            "LoadImage",
            "LoadImageFromURL",
            "ImageLoad",
        ):
            node.setdefault("inputs", {})["image"] = ref


def _inject_checkpoint(wf: Dict[str, Any], ckpt: Optional[str]) -> None:
    """Override the checkpoint in any CheckpointLoaderSimple / CheckpointLoader node.

    If the workflow already has a checkpoint loader, update its ``ckpt_name``.
    Otherwise, add a new CheckpointLoaderSimple node so the workflow uses the
    requested model.
    """
    if not ckpt:
        return

    # First: try to update an existing checkpoint loader node
    found = False
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") in (
            "CheckpointLoaderSimple",
            "CheckpointLoader",
        ):
            node.setdefault("inputs", {})["ckpt_name"] = ckpt
            found = True

    if found:
        return

    # No checkpoint loader in the workflow — add one with a unique node id
    existing_ids = {int(k) for k in wf if k.isdigit()}
    new_id = str(max(existing_ids, default=100) + 10)
    wf[new_id] = {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": ckpt},
    }
