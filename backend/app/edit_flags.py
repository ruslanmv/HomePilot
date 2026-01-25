"""
Edit flags parser for advanced edit controls.

This module allows the frontend to pass edit parameters via hidden flags
appended to the edit instruction, without modifying the /chat API schema.

Example:
    User input: "Make the sky dramatic --steps 30 --cfg 6.5 --denoise 0.55"

    Parsed result:
        - clean_text: "Make the sky dramatic"
        - flags: EditFlags(steps=30, cfg=6.5, denoise=0.55, ...)
"""

import re
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any

# Pattern to match flags like --key value
FLAG_RE = re.compile(r"(--[a-zA-Z0-9_-]+)\s+([^\s-][^\n\r]*?)(?=\s+--|$)")

# Pattern to match URLs (http/https)
URL_RE = re.compile(r"https?://\S+", re.I)

# Pattern to match edit command keywords at the start
EDIT_CMD_RE = re.compile(r"^\s*(edit|inpaint|modify)\s+", re.I)


@dataclass
class EditFlags:
    """
    Container for parsed edit flags.

    All values have sensible defaults for quality image editing.
    """
    # Edit mode: auto, global, inpaint
    mode: str = "auto"

    # Generation parameters
    steps: int = 30
    cfg: float = 5.5
    denoise: float = 0.55
    seed: int = 0
    sampler_name: str = "euler"
    scheduler: str = "normal"

    # Model controls
    ckpt_name: Optional[str] = None
    controlnet_name: Optional[str] = None
    controlnet_strength: float = 1.0
    cn_enabled: bool = False

    # Optional mask (URL or filename; backend will preprocess)
    mask_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for workflow variables."""
        return {
            "mode": self.mode,
            "steps": self.steps,
            "cfg": self.cfg,
            "denoise": self.denoise,
            "seed": self.seed,
            "sampler_name": self.sampler_name,
            "scheduler": self.scheduler,
            "ckpt_name": self.ckpt_name,
            "controlnet_name": self.controlnet_name,
            "controlnet_strength": self.controlnet_strength,
            "cn_enabled": self.cn_enabled,
            "mask_url": self.mask_url,
        }


def parse_edit_flags(text: str) -> Tuple[str, EditFlags]:
    """
    Extract flags from user text and return (clean_text, flags).

    Cleans the prompt by removing:
    - Edit command prefix (edit, inpaint, modify)
    - URLs (image URLs that are handled separately)
    - Flags like --steps 30, --cfg 6.5

    Args:
        text: User's edit instruction potentially containing flags and URLs

    Returns:
        Tuple of (cleaned text without flags/URLs, parsed EditFlags object)
    """
    flags = EditFlags()
    clean = text

    # First, parse all flags
    matches = list(FLAG_RE.finditer(text))

    for m in matches:
        key = (m.group(1) or "").strip().lower()
        value = (m.group(2) or "").strip()

        try:
            if key == "--mode":
                flags.mode = value.lower()
            elif key == "--steps":
                flags.steps = int(float(value))
            elif key == "--cfg":
                flags.cfg = float(value)
            elif key == "--denoise":
                flags.denoise = float(value)
            elif key == "--seed":
                flags.seed = int(float(value))
            elif key == "--sampler":
                flags.sampler_name = value
            elif key == "--scheduler":
                flags.scheduler = value
            elif key == "--ckpt":
                flags.ckpt_name = value
            elif key == "--cn":
                flags.cn_enabled = value.lower() in ("1", "true", "yes", "on")
            elif key == "--cn-strength":
                flags.controlnet_strength = float(value)
            elif key == "--controlnet":
                flags.controlnet_name = value
            elif key == "--mask":
                flags.mask_url = value
        except (ValueError, TypeError):
            # Skip invalid flag values
            pass

    # Remove all flags from the text
    for m in reversed(matches):
        clean = clean[:m.start()] + clean[m.end():]

    # Remove URLs from the prompt (image URL is passed separately)
    clean = URL_RE.sub("", clean)

    # Remove edit command prefix (e.g., "edit ", "inpaint ")
    clean = EDIT_CMD_RE.sub("", clean)

    # Clean up extra whitespace
    clean = " ".join(clean.split()).strip()

    return clean, flags


def infer_edit_mode(user_text: str) -> str:
    """
    Heuristic routing: inpaint for localized edits, global for style changes.

    Args:
        user_text: Cleaned user edit instruction

    Returns:
        Inferred edit mode: "inpaint" or "global"
    """
    t = user_text.lower()

    # Localized edit keywords suggest inpainting
    inpaint_keywords = (
        "remove", "erase", "delete", "replace", "change", "add", "swap",
        "object", "logo", "text", "person", "background", "hat", "shirt",
        "hair", "face", "eye", "nose", "mouth", "hand", "arm", "leg",
        "building", "car", "tree", "sky", "water", "cloud"
    )

    # Global style keywords suggest full image regeneration
    global_keywords = (
        "cinematic", "anime", "oil painting", "watercolor", "cartoon",
        "night", "sunset", "dramatic lighting", "color grade", "style",
        "filter", "tone", "mood", "atmosphere", "aesthetic", "artistic",
        "vintage", "retro", "modern", "futuristic", "cyberpunk", "noir"
    )

    # Check for localized edit keywords
    for kw in inpaint_keywords:
        if kw in t:
            return "inpaint"

    # Check for global style keywords
    for kw in global_keywords:
        if kw in t:
            return "global"

    # Default to auto (let the workflow decide)
    return "auto"


def build_edit_workflow_vars(
    image_url: str,
    prompt: str,
    flags: EditFlags,
    negative_prompt: str = "",
) -> Dict[str, Any]:
    """
    Build workflow variables dictionary from parsed flags.

    Args:
        image_url: URL of the source image
        prompt: Cleaned edit instruction
        flags: Parsed edit flags
        negative_prompt: Negative prompt (optional)

    Returns:
        Dictionary of variables for ComfyUI workflow
    """
    import random

    # Default checkpoints based on workflow type
    ckpt_default_global = "sd_xl_base_1.0.safetensors"
    ckpt_default_inpaint = "sd_xl_base_1.0_inpainting_0.1.safetensors"
    ckpt_default_sd15_inpaint = "sd-v1-5-inpainting.ckpt"
    cn_default = "control_v11p_sd15_inpaint.safetensors"

    # Generate random seed if not explicitly set (prevents ComfyUI caching)
    seed = flags.seed
    if seed == 0 or seed == -1:
        seed = random.randint(1, 2147483647)

    vars_dict: Dict[str, Any] = {
        "image_path": image_url,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "steps": flags.steps,
        "cfg": flags.cfg,
        "seed": seed,
        "denoise": flags.denoise,
        "sampler_name": flags.sampler_name,
        "scheduler": flags.scheduler,
        "filename_prefix": "homepilot_edit",
    }

    # Set checkpoint and mask based on whether mask is provided
    # IMPORTANT: Only set mask_path when there's actually a mask
    if flags.mask_url:
        # Inpaint mode - mask is provided
        vars_dict["mask_path"] = flags.mask_url
        vars_dict["ckpt_name"] = flags.ckpt_name or ckpt_default_inpaint

        # Optional ControlNet (recommended with SD1.5 inpaint)
        if flags.cn_enabled:
            vars_dict["ckpt_name"] = flags.ckpt_name or ckpt_default_sd15_inpaint
            vars_dict["controlnet_name"] = flags.controlnet_name or cn_default
            vars_dict["controlnet_strength"] = flags.controlnet_strength
    else:
        # Global edit (img2img) - no mask needed
        vars_dict["ckpt_name"] = flags.ckpt_name or ckpt_default_global

    return vars_dict


def determine_workflow(flags: EditFlags, prompt: str) -> str:
    """
    Determine which workflow to use based on flags and prompt.

    IMPORTANT: Inpaint workflows REQUIRE a mask. If no mask is provided,
    we MUST use the standard edit (img2img) workflow, even if keywords
    suggest inpainting. The keyword-based mode detection is informational
    only - actual workflow selection depends on mask availability.

    Args:
        flags: Parsed edit flags
        prompt: Cleaned edit instruction

    Returns:
        Workflow name to use
    """
    # Critical: Only use inpaint workflows when a mask is actually provided
    # The InpaintModelConditioning node requires a noise_mask input
    if flags.mask_url:
        if flags.cn_enabled:
            return "edit_inpaint_cn"
        return "edit_inpaint"

    # Without a mask, use standard img2img edit workflow
    # This applies regardless of detected keywords (remove, replace, etc.)
    return "edit"
