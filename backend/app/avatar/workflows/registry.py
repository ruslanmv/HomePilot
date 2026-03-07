"""
Avatar workflow preset registry — maps wizard steps to ComfyUI workflow templates.

Additive module.  This registry provides a declarative mapping of all 19
production workflow presets.  Each preset specifies:
  - Which ComfyUI JSON graph to load
  - Which pipeline step it serves (FACE, BODY, OUTFIT, EDIT, REPAIR)
  - Required input images
  - Engine type (SD15, SDXL, FLUX, UTILITY)
  - Default generation parameters (steps, cfg, sampler, dimensions)
  - Whether it's an advanced/optional preset

The registry does NOT execute workflows — it only provides metadata.
Actual execution goes through ``services.comfyui.workflows.run_avatar_workflow()``
or the new ``runner.run_workflow()`` for presets that need custom variables.

Non-destructive: existing workflow code is not modified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Literal, Optional, Tuple

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Step = Literal[
    "FACE",
    "BODY",
    "OUTFIT",
    "PORTRAIT",
    "REPAIR_FACE",
    "EDIT_OUTFIT",
    "EDIT_BG",
    "EDIT_EXPRESSION",
    "EDIT_POSE",
]

Engine = Literal["SD15", "SDXL", "FLUX", "UTILITY"]


# ---------------------------------------------------------------------------
# Preset definition
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WorkflowPreset:
    """A single production workflow preset."""

    id: str
    step: Step
    label: str
    description: str
    graph_file: str  # JSON filename relative to workflows/avatar/
    engine: Engine = "SD15"
    requires: tuple = ()  # Required input image variable names
    advanced: bool = False  # Hidden in simple mode, shown in advanced
    commercial_ok: bool = True
    # Default generation parameters (can be overridden per-request)
    default_width: int = 512
    default_height: int = 768
    default_steps: int = 30
    default_cfg: float = 7.0
    default_sampler: str = "dpmpp_2m"
    default_scheduler: str = "karras"
    default_denoise: float = 1.0


# ---------------------------------------------------------------------------
# Complete preset registry — all 19 production workflows
# ---------------------------------------------------------------------------

PRESETS: Dict[str, WorkflowPreset] = {}


def _register(p: WorkflowPreset) -> WorkflowPreset:
    PRESETS[p.id] = p
    return p


# ═══════════════════════════════════════════════════════════════════════════
# 1. FACE IDENTITY GENERATION (Wizard Step 1)
# ═══════════════════════════════════════════════════════════════════════════

_register(WorkflowPreset(
    id="wf01_face_stylegan",
    step="FACE",
    label="Random Face (StyleGAN)",
    description="Generate random identity via StyleGAN2 FFHQ. Fast, no prompt needed.",
    graph_file="__stylegan__",  # Handled by avatar-service, not ComfyUI
    engine="UTILITY",
    commercial_ok=False,  # NVIDIA non-commercial license
    default_width=1024,
    default_height=1024,
))

_register(WorkflowPreset(
    id="wf02_face_diffusion",
    step="FACE",
    label="Diffusion Face (SD1.5)",
    description="Generate face portrait via SD1.5 diffusion model. Prompt-guided.",
    graph_file="avatar_txt2img.json",
    default_width=512,
    default_height=512,
    default_steps=25,
))

_register(WorkflowPreset(
    id="wf03_face_upload",
    step="FACE",
    label="Upload Face",
    description="Upload an existing photo as the identity anchor. No generation needed.",
    graph_file="__upload__",  # No ComfyUI graph — direct file upload
    engine="UTILITY",
))


# ═══════════════════════════════════════════════════════════════════════════
# 2. BODY BASE GENERATION (Wizard Step 2)
# ═══════════════════════════════════════════════════════════════════════════

_register(WorkflowPreset(
    id="wf04_body_anchor",
    step="BODY",
    label="Body Base (InstantID SDXL)",
    description="Generate full body from face reference. InstantID preserves facial identity. Uses SDXL.",
    graph_file="avatar_body_from_face.json",
    engine="SDXL",
    requires=("ref_image",),
    default_width=1024,
    default_height=1536,
    default_steps=30,
))

_register(WorkflowPreset(
    id="wf05_body_pose",
    step="BODY",
    label="Body + Pose (OpenPose SDXL)",
    description="Body generation with pose control via OpenPose ControlNet. Uses SDXL.",
    graph_file="avatar_body_pose.json",
    engine="SDXL",
    requires=("ref_image", "pose_image"),
    advanced=True,
    default_width=1024,
    default_height=1536,
    default_steps=30,
))

_register(WorkflowPreset(
    id="wf06_body_sdxl",
    step="BODY",
    label="Body Base (SDXL)",
    description="Higher quality body generation using SDXL models. Requires SDXL checkpoint.",
    graph_file="avatar_sdxl_body.json",
    engine="SDXL",
    requires=("ref_image",),
    advanced=True,
    default_width=1024,
    default_height=1536,
    default_steps=30,
))


# ═══════════════════════════════════════════════════════════════════════════
# 3. OUTFIT GENERATION (Wizard Step 3)
# ═══════════════════════════════════════════════════════════════════════════

_register(WorkflowPreset(
    id="wf07_outfit_default",
    step="OUTFIT",
    label="Outfit (InstantID SDXL)",
    description="Generate outfit variations preserving identity. Uses body anchor as reference. SDXL.",
    graph_file="avatar_outfit_instantid.json",
    engine="SDXL",
    requires=("ref_image",),
    default_width=1024,
    default_height=1536,
    default_steps=25,
))

_register(WorkflowPreset(
    id="wf08_outfit_photomaker",
    step="OUTFIT",
    label="Outfit (PhotoMaker)",
    description="Higher identity fidelity using PhotoMaker V2 encoder. Requires both face and body refs.",
    graph_file="avatar_photomaker.json",
    requires=("ref_image",),
    advanced=True,
))

_register(WorkflowPreset(
    id="wf09_outfit_sdxl",
    step="OUTFIT",
    label="Outfit (SDXL)",
    description="High-quality outfit generation using SDXL models.",
    graph_file="avatar_sdxl_body.json",  # Same graph, different prompt
    engine="SDXL",
    requires=("ref_image",),
    advanced=True,
    default_width=1024,
    default_height=1536,
    default_steps=25,
))


# ═══════════════════════════════════════════════════════════════════════════
# 4. IDENTITY REPAIR (Post-Generation Fixes)
# ═══════════════════════════════════════════════════════════════════════════

_register(WorkflowPreset(
    id="wf10_faceswap_repair",
    step="REPAIR_FACE",
    label="Face Swap Repair",
    description="Swap face from identity anchor onto a body image. Fixes identity drift.",
    graph_file="avatar_faceswap_repair.json",
    engine="UTILITY",
    requires=("subject_image", "ref_image"),
))

_register(WorkflowPreset(
    id="wf11_identity_reproject",
    step="REPAIR_FACE",
    label="Identity Reprojection",
    description="Subtle identity correction via img2img with InstantID. Low denoise preserves body/outfit. SDXL.",
    graph_file="avatar_identity_reproject.json",
    engine="SDXL",
    requires=("subject_image", "ref_image"),
    default_denoise=0.45,
    default_steps=20,
    default_cfg=5.0,
))


# ═══════════════════════════════════════════════════════════════════════════
# 5. EDITING WORKFLOWS (Avatar Studio Editor)
# ═══════════════════════════════════════════════════════════════════════════

_register(WorkflowPreset(
    id="wf12_inpaint_outfit",
    step="EDIT_OUTFIT",
    label="Inpaint Outfit",
    description="Replace clothing region with mask-guided inpainting. Preserves face and background.",
    graph_file="avatar_inpaint_outfit.json",
    requires=("subject_image", "mask_image"),
    default_denoise=0.85,
    default_steps=25,
))

_register(WorkflowPreset(
    id="wf13_bg_replace",
    step="EDIT_BG",
    label="Background Replace",
    description="Replace background while preserving character. Auto-segments with Rembg.",
    graph_file="__comfyui__/change_background.json",  # Uses global comfyui workflow
    requires=("subject_image",),
    default_denoise=1.0,
    default_steps=25,
    default_sampler="euler_ancestral",
    default_scheduler="normal",
))

_register(WorkflowPreset(
    id="wf14_expression_change",
    step="EDIT_EXPRESSION",
    label="Expression Change",
    description="Change facial expression via face-region inpainting. Low denoise for subtle changes.",
    graph_file="avatar_expression_change.json",
    requires=("subject_image", "mask_image"),
    default_denoise=0.55,
    default_steps=20,
    default_cfg=5.0,
    default_sampler="euler",
    default_scheduler="normal",
))

_register(WorkflowPreset(
    id="wf15_pose_adjust",
    step="EDIT_POSE",
    label="Pose Adjustment",
    description="Re-pose a character using OpenPose ControlNet. Moderate denoise to preserve identity.",
    graph_file="avatar_body_pose.json",  # Reuses pose workflow
    requires=("ref_image", "pose_image"),
    advanced=True,
    default_denoise=0.7,
))


# ═══════════════════════════════════════════════════════════════════════════
# 6. SPECIAL PIPELINES (Style Variants)
# ═══════════════════════════════════════════════════════════════════════════

_register(WorkflowPreset(
    id="wf16_portrait",
    step="PORTRAIT",
    label="Portrait Headshot",
    description="High-quality square portrait/headshot from face reference. Studio lighting. SDXL.",
    graph_file="avatar_portrait_instantid.json",
    engine="SDXL",
    requires=("ref_image",),
    default_width=1024,
    default_height=1024,
    default_steps=30,
))

_register(WorkflowPreset(
    id="wf17_studio_photoshoot",
    step="OUTFIT",
    label="Studio Photoshoot",
    description="Full body with professional lighting presets. Same as outfit but with lighting focus.",
    graph_file="avatar_outfit_instantid.json",  # Same graph, lighting in prompt
    requires=("ref_image",),
    advanced=True,
))

_register(WorkflowPreset(
    id="wf18_fantasy",
    step="OUTFIT",
    label="Fantasy Character",
    description="Fantasy/RPG style character using aZovya RPG Artist or similar checkpoint.",
    graph_file="avatar_outfit_instantid.json",  # Same graph, fantasy checkpoint
    requires=("ref_image",),
    advanced=True,
))

_register(WorkflowPreset(
    id="wf19_anime",
    step="OUTFIT",
    label="Anime Character",
    description="Anime-style character using Pony/NoobAI/MeinaMix checkpoints.",
    graph_file="avatar_outfit_instantid.json",  # Same graph, anime checkpoint
    requires=("ref_image",),
    advanced=True,
))


# ---------------------------------------------------------------------------
# Selector helpers
# ---------------------------------------------------------------------------

def get_preset(preset_id: str) -> WorkflowPreset:
    """Get a preset by ID. Raises KeyError if not found."""
    return PRESETS[preset_id]


def presets_for_step(step: Step, *, include_advanced: bool = False) -> list[WorkflowPreset]:
    """Return all presets for a given pipeline step."""
    return [
        p for p in PRESETS.values()
        if p.step == step and (include_advanced or not p.advanced)
    ]


def select_workflow(
    *,
    step: Step,
    wants_pose: bool = False,
    wants_sdxl: bool = False,
    wants_photomaker: bool = False,
    has_stylegan: bool = False,
) -> WorkflowPreset:
    """Auto-select the best workflow preset for a given step and capabilities.

    This is the default selector used by the wizard when the user doesn't
    explicitly choose a workflow.
    """
    if step == "FACE":
        if has_stylegan:
            return PRESETS["wf01_face_stylegan"]
        return PRESETS["wf02_face_diffusion"]

    if step == "BODY":
        if wants_pose:
            return PRESETS["wf05_body_pose"]
        if wants_sdxl:
            return PRESETS["wf06_body_sdxl"]
        return PRESETS["wf04_body_anchor"]

    if step == "OUTFIT":
        if wants_sdxl:
            return PRESETS["wf09_outfit_sdxl"]
        if wants_photomaker:
            return PRESETS["wf08_outfit_photomaker"]
        return PRESETS["wf07_outfit_default"]

    if step == "PORTRAIT":
        return PRESETS["wf16_portrait"]

    if step == "REPAIR_FACE":
        return PRESETS["wf11_identity_reproject"]

    if step == "EDIT_OUTFIT":
        return PRESETS["wf12_inpaint_outfit"]

    if step == "EDIT_BG":
        return PRESETS["wf13_bg_replace"]

    if step == "EDIT_EXPRESSION":
        return PRESETS["wf14_expression_change"]

    if step == "EDIT_POSE":
        return PRESETS["wf15_pose_adjust"]

    raise ValueError(f"Unsupported step: {step}")
