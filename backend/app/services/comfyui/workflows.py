"""
ComfyUI workflow loader — load JSON templates and inject runtime inputs.

Workflow templates live in ``workflows/avatar/`` at the project root.
The backend injects prompt text, seed, batch size, and reference images
into well-known ComfyUI node class_types.

Workflow selection:
  - When a reference image is provided, use the mode-specific workflow
    (img2img via VAEEncode of the reference).
  - When no reference image is provided, fall back to txt2img workflow.
  - ``studio_reference`` always requires a reference image.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...avatar.schemas import AvatarResult
from ...comfy import _download_image_for_comfyui
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
    denoise_override: Optional[float] = None,
    identity_strength: Optional[float] = None,
    negative_prompt: Optional[str] = None,
    pose_image_url: Optional[str] = None,
    width_override: Optional[int] = None,
    height_override: Optional[int] = None,
) -> List[AvatarResult]:
    """Load a workflow template, inject inputs, submit, and collect results."""
    if not comfyui_healthy(comfyui_base_url):
        raise ComfyUIUnavailable("Face/avatar service (ComfyUI) is offline")

    has_ref = bool(reference_image_url)

    # studio_reference MUST have a reference image
    if mode == "studio_reference" and not has_ref:
        raise ComfyUIUnavailable(
            "From Reference mode requires a reference image. "
            "Upload a photo or switch to Face + Style mode."
        )

    wf_path = _workflow_path(mode, has_reference=has_ref)
    wf_template: Dict[str, Any] = json.loads(wf_path.read_text())

    if has_ref:
        # ----- Reference-based (img2img): submit once per image -----
        # The reference latent is a single image, so KSampler produces 1 output.
        # We submit the workflow count times with different seeds.
        results: list[AvatarResult] = []
        base_seed = seed if seed is not None else random.randint(0, 2**31 - 1)

        for i in range(count):
            wf = json.loads(json.dumps(wf_template))  # deep copy
            _inject_prompt(wf, prompt)
            if negative_prompt:
                _inject_negative_prompt(wf, negative_prompt)
            _inject_seed(wf, base_seed + i)
            _inject_reference(wf, reference_image_url)
            _inject_pose_reference(wf, pose_image_url)
            _inject_checkpoint(wf, checkpoint_override)
            _inject_denoise(wf, denoise_override)
            _inject_dimensions(wf, width_override, height_override)
            if identity_strength is not None:
                _inject_identity_strength(wf, identity_strength)

            prompt_id = await submit_prompt(comfyui_base_url, wf)
            images = await wait_for_images(comfyui_base_url, prompt_id)
            if images:
                filename = images[0].get("filename", "")
                subfolder = images[0].get("subfolder", "")
                url = f"/comfy/view/{filename}"
                if subfolder:
                    url += f"?subfolder={subfolder}"
                results.append(
                    AvatarResult(
                        url=url,
                        seed=base_seed + i,
                        metadata={"source": "comfyui", "workflow": wf_path.name},
                    )
                )
        return results
    else:
        # ----- Text-to-image: single batch submission -----
        wf = wf_template
        _inject_prompt(wf, prompt)
        # Always inject a seed — ComfyUI caches identical prompts+seeds and
        # skips re-execution, returning 0 images on the second call.
        effective_seed = seed if seed is not None else random.randint(0, 2**31 - 1)
        _inject_seed(wf, effective_seed)
        _inject_batch_size(wf, count)
        _inject_checkpoint(wf, checkpoint_override)
        _inject_dimensions(wf, width_override, height_override)

        prompt_id = await submit_prompt(comfyui_base_url, wf)
        images = await wait_for_images(comfyui_base_url, prompt_id)

        results = []
        for i, img in enumerate(images[:count]):
            filename = img.get("filename", "")
            subfolder = img.get("subfolder", "")
            url = f"/comfy/view/{filename}"
            if subfolder:
                url += f"?subfolder={subfolder}"
            results.append(
                AvatarResult(
                    url=url,
                    seed=effective_seed + i,
                    metadata={"source": "comfyui", "workflow": wf_path.name},
                )
            )
        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Workflow mapping: reference-based → mode-specific, no-reference → txt2img
_REF_WORKFLOWS = {
    "studio_reference": "avatar_instantid.json",
    "studio_faceswap": "avatar_faceswap.json",
    "creative": "avatar_photomaker.json",
    "hybrid_body": "avatar_body_from_face.json",
    "hybrid_body_pose": "avatar_body_pose.json",
    "hybrid_outfit": "avatar_outfit_instantid.json",
    "hybrid_portrait": "avatar_portrait_instantid.json",
    "hybrid_sdxl_body": "avatar_sdxl_body.json",
    "identity_reproject": "avatar_identity_reproject.json",
}

_NOREF_WORKFLOWS = {
    "studio_faceswap": "avatar_txt2img.json",
    "creative": "avatar_txt2img.json",
}


def _workflow_path(mode: str, has_reference: bool = False) -> Path:
    if has_reference:
        name = _REF_WORKFLOWS.get(mode)
    else:
        name = _NOREF_WORKFLOWS.get(mode)
    if not name:
        raise ValueError(f"Unsupported ComfyUI avatar mode: {mode}")
    return WORKFLOW_DIR / name


def _inject_prompt(wf: Dict[str, Any], prompt: str) -> None:
    """Inject user prompt into the positive CLIP text-encode node only.

    Nodes tagged with ``_meta.title`` containing "Negative" are skipped
    so the negative prompt template is preserved.

    Supports both SD1.5 (CLIPTextEncode → text) and
    SDXL (CLIPTextEncodeSDXL → text_g + text_l).

    For CLIPTextEncodeSDXL, also ensures required dimension fields are present
    (width, height, crop_w, crop_h, target_width, target_height).
    """
    for node in wf.values():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type", "")
        meta = node.get("_meta", {})
        title = (meta.get("title", "") or "").lower()
        if "negative" in title:
            continue
        if cls in ("CLIPTextEncode", "TextEncode", "Text Encode"):
            node.setdefault("inputs", {})["text"] = prompt
        elif cls == "CLIPTextEncodeSDXL":
            inputs = node.setdefault("inputs", {})
            inputs["text_g"] = prompt
            inputs["text_l"] = prompt
            _ensure_sdxl_clip_dimensions(inputs)


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


def _inject_dimensions(
    wf: Dict[str, Any],
    width: Optional[int],
    height: Optional[int],
) -> None:
    """Override output dimensions in EmptyLatentImage nodes.

    Used for framing control: half-body portraits use taller aspect ratios
    (e.g. 512×768) while headshots use square (e.g. 512×512).
    """
    if width is None and height is None:
        return
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImage":
            inputs = node.setdefault("inputs", {})
            if width is not None:
                inputs["width"] = width
            if height is not None:
                inputs["height"] = height


def _inject_reference(wf: Dict[str, Any], ref: Optional[str]) -> None:
    """Inject reference image into LoadImage nodes.

    ComfyUI's LoadImage expects a **local filename** inside its input/
    directory, not an HTTP URL.  If *ref* looks like a URL we download it
    first via the shared helper in ``comfy.py``.

    Also handles backend-relative URLs such as ``/comfy/view/filename.png``
    (returned by avatar generation) by fetching the image from ComfyUI
    directly.
    """
    if not ref:
        return

    # Handle backend-relative URLs that are not local filenames.
    if ref.startswith("/comfy/view/"):
        # This is a proxy URL produced by run_avatar_workflow().
        # Fetch the image directly from ComfyUI's /view endpoint.
        from ...config import COMFY_BASE_URL

        filename = ref[len("/comfy/view/"):]
        ref = f"{COMFY_BASE_URL.rstrip('/')}/view?filename={filename}&type=output"
    elif ref.startswith("/"):
        # Other backend-relative paths (e.g. /files/...).
        from ...config import PUBLIC_BASE_URL

        base = (PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
        ref = f"{base}{ref}"

    # Convert URL → local filename in ComfyUI's input directory
    local_name = ref
    if ref.startswith("http://") or ref.startswith("https://"):
        local_name = _download_image_for_comfyui(ref)

    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") in (
            "LoadImage",
            "LoadImageFromURL",
            "ImageLoad",
        ):
            # Skip pose reference nodes — they get their own injection
            meta = node.get("_meta", {})
            title = (meta.get("title", "") or "").lower()
            if "pose" in title:
                continue
            node.setdefault("inputs", {})["image"] = local_name


def _resolve_image_url(ref: str) -> str:
    """Resolve a reference URL to a local ComfyUI input filename.

    Handles backend-relative URLs (``/comfy/view/...``) and HTTP URLs
    by downloading the image into ComfyUI's input directory.
    """
    if ref.startswith("/comfy/view/"):
        from ...config import COMFY_BASE_URL
        filename = ref[len("/comfy/view/"):]
        ref = f"{COMFY_BASE_URL.rstrip('/')}/view?filename={filename}&type=output"
    elif ref.startswith("/"):
        from ...config import PUBLIC_BASE_URL
        base = (PUBLIC_BASE_URL or "http://localhost:8000").rstrip("/")
        ref = f"{base}{ref}"

    if ref.startswith("http://") or ref.startswith("https://"):
        return _download_image_for_comfyui(ref)
    return ref


def _inject_pose_reference(wf: Dict[str, Any], pose_ref: Optional[str]) -> None:
    """Inject pose reference image into LoadImage nodes titled 'Pose Reference'.

    Only targets nodes whose ``_meta.title`` contains 'pose' (case-insensitive).
    """
    if not pose_ref:
        return

    local_name = _resolve_image_url(pose_ref)

    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") in (
            "LoadImage",
            "LoadImageFromURL",
            "ImageLoad",
        ):
            meta = node.get("_meta", {})
            title = (meta.get("title", "") or "").lower()
            if "pose" in title:
                node.setdefault("inputs", {})["image"] = local_name


def _inject_denoise(wf: Dict[str, Any], denoise: Optional[float]) -> None:
    """Override the denoise strength on KSampler nodes.

    Higher values (0.85+) allow more prompt-guided changes — useful for
    outfit variations where we want to change clothing/scene while the
    reference image only anchors the face structure.
    """
    if denoise is None:
        return
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") in (
            "KSampler",
            "SamplerCustom",
            "KSamplerAdvanced",
        ):
            node.setdefault("inputs", {})["denoise"] = denoise


def _inject_identity_strength(wf: Dict[str, Any], strength: float) -> None:
    """Inject identity strength as weight on ApplyInstantID nodes.

    Controls how strictly the face reference is preserved:
      1.0 = very strict (face dominates)
      0.5 = balanced
      0.1 = loose (more creative freedom)
    """
    for node in wf.values():
        if isinstance(node, dict) and node.get("class_type") in (
            "ApplyInstantID",
            "ApplyIPAdapter",
        ):
            node.setdefault("inputs", {})["weight"] = strength


def _inject_negative_prompt(wf: Dict[str, Any], negative: str) -> None:
    """Inject negative prompt into CLIP nodes tagged as 'Negative'.

    Supports both SD1.5 (CLIPTextEncode → text) and
    SDXL (CLIPTextEncodeSDXL → text_g + text_l).
    """
    for node in wf.values():
        if not isinstance(node, dict):
            continue
        cls = node.get("class_type", "")
        meta = node.get("_meta", {})
        title = (meta.get("title", "") or "").lower()
        if "negative" not in title:
            continue
        if cls in ("CLIPTextEncode", "TextEncode", "Text Encode"):
            node.setdefault("inputs", {})["text"] = negative
        elif cls == "CLIPTextEncodeSDXL":
            inputs = node.setdefault("inputs", {})
            inputs["text_g"] = negative
            inputs["text_l"] = negative
            _ensure_sdxl_clip_dimensions(inputs)


def _ensure_sdxl_clip_dimensions(inputs: Dict[str, Any]) -> None:
    """Ensure CLIPTextEncodeSDXL has required dimension fields.

    ComfyUI requires width, height, crop_w, crop_h, target_width, target_height
    on CLIPTextEncodeSDXL nodes.  If missing, we fill in sensible SDXL defaults.
    """
    inputs.setdefault("width", 1024)
    inputs.setdefault("height", 1024)
    inputs.setdefault("crop_w", 0)
    inputs.setdefault("crop_h", 0)
    inputs.setdefault("target_width", inputs.get("width", 1024))
    inputs.setdefault("target_height", inputs.get("height", 1024))


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
