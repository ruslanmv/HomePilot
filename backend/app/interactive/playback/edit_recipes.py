"""
Edit-recipe router for Persona Live Play.

Every Live Action click (or per-turn scene edit) picks one of the
existing HomePilot edit workflows on disk and runs the persona's
canonical portrait through it with a small param override. The
router maps ``(edit_hint, safety)`` → ``EditRecipe`` — a tiny typed
bundle the render adapter feeds straight into ComfyUI.

Why a router at all:
* ``txt2img`` drifts off-model between turns; img2img / inpaint on
  a fixed portrait does not. Identity stays locked for free.
* Different prompts need different workflows (expression vs pose
  vs outfit vs background) — trying to do all of them with a
  single workflow JSON loses quality.
* LoRA stacks should be chosen by the action kind, not trusted
  from a chat-derived prompt. The router is the one place we get
  to enforce that.

Safety:
* When ``safety.allow_explicit == false`` the router strips any
  LoRA tagged NSFW and downgrades denoise on body-mask recipes.
* The set of recipes a viewer can trigger is closed — a chat
  prompt can't escape to an arbitrary workflow by string match.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# Canonical edit-hint vocabulary. The LLM's ``turn_compose`` prompt
# is constrained to one of these values via the YAML system text;
# anything else falls through to ``default`` (plain img2img).
EDIT_HINTS: Tuple[str, ...] = (
    "expression",
    "pose",
    "outfit",
    "bg",
    "composition",
    "identity_reproject",
    "outpaint",
    "default",
)


@dataclass(frozen=True)
class LoRAEntry:
    name: str
    weight: float = 0.8
    # Manifest tag — the router strips ``nsfw`` loras when safety
    # disallows explicit content.
    tag: str = ""


@dataclass(frozen=True)
class EditRecipe:
    """A fully-resolved edit plan for a single Persona Live Play
    render. Every field is something the render adapter can pass
    straight into the ComfyUI variables dict.

    ``workflow_id`` is a short symbolic name (not a full path) so
    the adapter can swap between ``workflows/avatar/…`` and
    ``comfyui/workflows/…`` without the router having to know.
    """

    workflow_id: str
    edit_hint: str
    steps: int = 30
    cfg: float = 5.5
    denoise: float = 0.55
    seed_locked: bool = False
    controlnet: str = ""           # "" | "openpose" | "canny" | "depth"
    mask_kind: str = ""            # "" | "face" | "outfit" | "bg"
    loras: List[LoRAEntry] = field(default_factory=list)
    enhance_face: bool = False
    upscale: int = 0               # 0 | 2 | 4


# Baseline recipes. Keep numbers tight; operator overrides live in
# env and aren't part of this table. Advanced tuning (per-action
# denoise sliders in the wizard) can layer on later.
_BASELINE: Dict[str, EditRecipe] = {
    "expression": EditRecipe(
        workflow_id="avatar_expression_change",
        edit_hint="expression",
        steps=24, cfg=5.0, denoise=0.35,
        mask_kind="face", enhance_face=True,
    ),
    "pose": EditRecipe(
        workflow_id="avatar_body_pose",
        edit_hint="pose",
        steps=30, cfg=5.5, denoise=0.55,
        controlnet="openpose",
    ),
    "outfit": EditRecipe(
        workflow_id="avatar_inpaint_outfit",
        edit_hint="outfit",
        steps=30, cfg=5.5, denoise=0.55,
        mask_kind="outfit",
    ),
    "bg": EditRecipe(
        workflow_id="change_background",
        edit_hint="bg",
        steps=24, cfg=5.0, denoise=0.45,
        mask_kind="bg",
    ),
    "composition": EditRecipe(
        workflow_id="edit_inpaint_cn",
        edit_hint="composition",
        steps=30, cfg=5.5, denoise=0.65,
    ),
    "identity_reproject": EditRecipe(
        workflow_id="avatar_identity_reproject",
        edit_hint="identity_reproject",
        steps=30, cfg=5.5, denoise=0.5,
        enhance_face=True,
    ),
    "outpaint": EditRecipe(
        workflow_id="outpaint",
        edit_hint="outpaint",
        steps=24, cfg=4.5, denoise=0.8,
    ),
    "default": EditRecipe(
        workflow_id="edit",
        edit_hint="default",
        steps=30, cfg=5.5, denoise=0.45,
    ),
}

# Deterministic action-id/category recipe map used by persona_live
# action endpoints. This is intentionally explicit so rendering is
# always Action -> Recipe and never inferred from free-form text.
ACTION_RECIPES: Dict[str, Dict[str, Any]] = {
    "tease": {
        "workflow_id": "avatar_expression_change",
        "category": "expression",
        "params": {"mode": "img2img", "steps": 24, "cfg": 5.0, "denoise": 0.35},
        "locks": ["face"],
    },
    "smirk": {
        "workflow_id": "avatar_expression_change",
        "category": "expression",
        "params": {"mode": "img2img", "steps": 24, "cfg": 5.0, "denoise": 0.30},
        "locks": ["face"],
    },
    "blush": {
        "workflow_id": "avatar_expression_change",
        "category": "expression",
        "params": {"mode": "img2img", "steps": 24, "cfg": 5.0, "denoise": 0.30},
        "locks": ["face"],
    },
    "ahegao": {
        "workflow_id": "avatar_expression_change",
        "category": "expression",
        "params": {"mode": "img2img", "steps": 30, "cfg": 5.5, "denoise": 0.45},
        "locks": ["face"],
    },
    "dance": {
        "workflow_id": "avatar_body_pose",
        "category": "pose",
        "params": {"mode": "img2img", "steps": 30, "cfg": 5.5, "denoise": 0.55},
        "controlnet": "openpose",
    },
    "closer_pose": {
        "workflow_id": "avatar_body_pose",
        "category": "pose",
        "params": {"mode": "img2img", "steps": 28, "cfg": 5.2, "denoise": 0.50},
        "controlnet": "openpose",
    },
    "turn_around": {
        "workflow_id": "avatar_body_pose",
        "category": "pose",
        "params": {"mode": "img2img", "steps": 30, "cfg": 5.5, "denoise": 0.58},
        "controlnet": "openpose",
    },
    "outfit_change": {
        "workflow_id": "avatar_inpaint_outfit",
        "category": "outfit",
        "params": {"mode": "inpaint", "steps": 30, "cfg": 5.5, "denoise": 0.55},
        "locks": ["face", "background"],
    },
    "move_to_beach": {
        "workflow_id": "change_background_premask",
        "category": "scene",
        "params": {"mode": "change_bg", "steps": 24, "cfg": 5.0, "denoise": 0.45},
        "locks": ["subject"],
    },
    "make_it_rain": {
        "workflow_id": "change_background",
        "category": "scene",
        "params": {"mode": "change_bg", "steps": 24, "cfg": 5.0, "denoise": 0.45},
        "locks": ["subject"],
    },
    "zoom_out": {
        "workflow_id": "outpaint",
        "category": "scene",
        "params": {"mode": "outpaint", "steps": 24, "cfg": 4.5, "denoise": 0.8},
        "locks": ["existing_pixels"],
    },
}


def pick_recipe(
    edit_hint: str,
    *,
    allow_explicit: bool = False,
    lora_stack: Optional[List[LoRAEntry]] = None,
    quick_fixes: Optional[Dict[str, object]] = None,
) -> EditRecipe:
    """Build the final recipe for a turn.

    ``edit_hint`` is the LLM-suggested kind; unknown values fall
    back to ``default``. ``lora_stack`` is the caller's stack
    (usually derived from the Live Action the viewer clicked) —
    the router filters it against the safety flag so a chat-level
    manipulation can never smuggle an NSFW LoRA onto a PG-13
    persona. ``quick_fixes`` lets the caller opt into the upscale/
    face-restore tail pass per render.
    """
    key = (edit_hint or "").strip().lower()
    base = _BASELINE.get(key) or _BASELINE["default"]

    # Filter the LoRA stack through the safety gate.
    safe_loras: List[LoRAEntry] = []
    for entry in list(lora_stack or []):
        if not isinstance(entry, LoRAEntry):
            continue
        if (entry.tag or "").strip().lower() == "nsfw" and not allow_explicit:
            continue
        safe_loras.append(entry)

    # Downgrade denoise on body-mask recipes when explicit content
    # is disallowed: it reduces the chance a body-mask inpaint
    # reveals anatomy the persona's safety profile forbids.
    denoise = base.denoise
    if not allow_explicit and base.mask_kind in ("outfit",):
        denoise = min(denoise, 0.45)

    fixes = quick_fixes or {}
    enhance_face = bool(fixes.get("fix_faces", base.enhance_face))
    upscale_val = _coerce_upscale(fixes.get("upscale", base.upscale))

    return EditRecipe(
        workflow_id=base.workflow_id,
        edit_hint=base.edit_hint,
        steps=int(fixes.get("steps", base.steps) or base.steps),
        cfg=float(fixes.get("cfg", base.cfg) or base.cfg),
        denoise=float(fixes.get("denoise", denoise) or denoise),
        seed_locked=bool(fixes.get("seed_locked", base.seed_locked)),
        controlnet=base.controlnet,
        mask_kind=base.mask_kind,
        loras=safe_loras,
        enhance_face=enhance_face,
        upscale=upscale_val,
    )


def _coerce_upscale(value: object) -> int:
    try:
        v = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    if v in (0, 2, 4):
        return v
    return 0


def default_recipe() -> Dict[str, Any]:
    return {
        "workflow_id": "edit",
        "params": {"mode": "img2img", "steps": 24, "cfg": 5.0, "denoise": 0.40},
    }


def recipe_for_action(
    action: Any,
    edit_hint: Optional[str] = None,
    *,
    mode: str = "image",
) -> Dict[str, Any]:
    """Deterministic recipe router for persona_live actions.

    Priority:
      1) per-action edit_recipe override
      2) hardcoded ACTION_RECIPES by action intent/category
      3) safe default recipe
    """
    override = getattr(action, "edit_recipe", None) or {}
    if isinstance(override, dict) and override:
        out = dict(override)
        out.setdefault("params", {})
        out["params"].setdefault("mode", "img2img")
        return out

    intent_key = str(getattr(action, "intent_code", "") or "").strip().lower()
    category_key = str(getattr(action, "category", "") or "").strip().lower()
    base = ACTION_RECIPES.get(intent_key) or ACTION_RECIPES.get(category_key)
    if not base:
        return default_recipe()

    recipe = {
        "workflow_id": str(base.get("workflow_id") or "edit"),
        "category": str(base.get("category") or category_key or "expression"),
        "params": dict(base.get("params") or {}),
        "locks": list(base.get("locks") or []),
    }
    if base.get("controlnet"):
        recipe["controlnet"] = base["controlnet"]

    # Video-mode workflow overrides keep the same deterministic
    # action map while swapping only the workflow target.
    if mode == "video" and intent_key == "dance":
        recipe["workflow_id"] = "avatar_body_pose_video"

    if edit_hint == "expression":
        recipe.setdefault("params", {})
        recipe["params"]["denoise"] = 0.35
    recipe.setdefault("params", {})
    recipe["params"].setdefault("mode", "img2img")
    recipe.setdefault("quick_fixes", {
        "enhance": True,
        "fix_faces": True,
        "upscale": 0,
    })
    return recipe


def recipe_to_variables(recipe: EditRecipe) -> Dict[str, object]:
    """Flatten a recipe to the extra ComfyUI variables the render
    adapter should overlay on top of the base txt2img variables.

    Workflow templates silently ignore variables they don't
    reference, so sending every recipe field is safe even when the
    picked workflow only consumes a subset.
    """
    return {
        "edit_mode": recipe.edit_hint,
        "edit_steps": recipe.steps,
        "edit_cfg": recipe.cfg,
        "edit_denoise": recipe.denoise,
        "edit_seed_locked": recipe.seed_locked,
        "edit_controlnet": recipe.controlnet,
        "edit_mask_kind": recipe.mask_kind,
        "edit_lora_stack": [
            {"name": lo.name, "weight": lo.weight} for lo in recipe.loras
        ],
        "edit_enhance_face": recipe.enhance_face,
        "edit_upscale": recipe.upscale,
    }


__all__ = [
    "ACTION_RECIPES",
    "EDIT_HINTS",
    "EditRecipe",
    "LoRAEntry",
    "default_recipe",
    "pick_recipe",
    "recipe_for_action",
    "recipe_to_variables",
]
