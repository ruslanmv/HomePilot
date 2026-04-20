"""
Tests for the Persona Live Play edit-recipe router.

Contract:
* ``pick_recipe(hint)`` returns a baseline recipe per hint; unknown
  hints fall back to ``default`` (plain img2img, low denoise).
* ``allow_explicit=False`` strips NSFW-tagged LoRAs from any
  caller-supplied stack and clamps body-mask denoise.
* ``recipe_to_variables`` produces a flat dict suitable for
  ComfyUI workflow variables — each field prefixed with ``edit_``.
* The personaplay composer picks a recipe from the LLM's
  ``edit_hint`` output; missing / invalid hints leave
  ``edit_recipe=None`` so the standard txt2img path runs.
"""
from __future__ import annotations

from typing import Any, Dict


def test_pick_recipe_returns_baselines_for_each_hint():
    from app.interactive.playback.edit_recipes import EDIT_HINTS, pick_recipe
    for hint in EDIT_HINTS:
        recipe = pick_recipe(hint, allow_explicit=True)
        assert recipe.workflow_id, f"{hint} must map to a workflow"
        assert recipe.edit_hint == hint
        assert 0.0 < recipe.denoise <= 1.0
        assert 1 <= recipe.steps <= 80


def test_unknown_hint_falls_back_to_default():
    from app.interactive.playback.edit_recipes import pick_recipe
    recipe = pick_recipe("wildcard_nonsense", allow_explicit=True)
    assert recipe.edit_hint == "default"
    assert recipe.workflow_id == "edit"


def test_safety_strips_nsfw_lora_when_not_allowed():
    from app.interactive.playback.edit_recipes import LoRAEntry, pick_recipe
    stack = [
        LoRAEntry(name="pretty_face", weight=0.6, tag="general"),
        LoRAEntry(name="undressing_sd15", weight=0.8, tag="nsfw"),
    ]
    recipe = pick_recipe("outfit", allow_explicit=False, lora_stack=stack)
    names = [lo.name for lo in recipe.loras]
    assert "undressing_sd15" not in names
    assert "pretty_face" in names


def test_safety_keeps_nsfw_lora_when_allowed():
    from app.interactive.playback.edit_recipes import LoRAEntry, pick_recipe
    stack = [LoRAEntry(name="undressing_sd15", weight=0.8, tag="nsfw")]
    recipe = pick_recipe("outfit", allow_explicit=True, lora_stack=stack)
    assert len(recipe.loras) == 1
    assert recipe.loras[0].name == "undressing_sd15"


def test_safety_downgrades_body_mask_denoise_when_not_allowed():
    from app.interactive.playback.edit_recipes import pick_recipe
    permissive = pick_recipe("outfit", allow_explicit=True)
    strict = pick_recipe("outfit", allow_explicit=False)
    assert strict.denoise <= permissive.denoise
    assert strict.denoise <= 0.45


def test_recipe_to_variables_is_flat_and_prefixed():
    from app.interactive.playback.edit_recipes import pick_recipe, recipe_to_variables
    recipe = pick_recipe("pose", allow_explicit=True)
    vars_ = recipe_to_variables(recipe)
    for key in (
        "edit_mode", "edit_steps", "edit_cfg", "edit_denoise",
        "edit_controlnet", "edit_mask_kind", "edit_lora_stack",
    ):
        assert key in vars_, f"missing {key}: {vars_}"
    assert isinstance(vars_["edit_lora_stack"], list)


def test_quick_fixes_overlay_steps_and_upscale():
    from app.interactive.playback.edit_recipes import pick_recipe
    recipe = pick_recipe("pose", allow_explicit=True, quick_fixes={
        "steps": 18, "upscale": 2, "fix_faces": True,
    })
    assert recipe.steps == 18
    assert recipe.upscale == 2
    assert recipe.enhance_face is True


def test_invalid_upscale_clamped_to_zero():
    from app.interactive.playback.edit_recipes import pick_recipe
    recipe = pick_recipe("pose", allow_explicit=True, quick_fixes={"upscale": 7})
    assert recipe.upscale == 0


# ── LLM composer wiring ────────────────────────────────────────

def _payload(hint: str) -> Dict[str, Any]:
    return {
        "reply_text": "Hey.",
        "narration": "Hey.",
        "scene_prompt": "portrait, soft light, casual",
        "duration_sec": 5,
        "mood_shift": "neutral",
        "affinity_delta": 0.02,
        "edit_hint": hint,
    }


def _memory():
    from app.interactive.playback.scene_memory import SceneMemory
    return SceneMemory(
        session_id="s1", experience_id="e1", persona_id="",
        current_node_id="", mood="neutral", affinity_score=0.3,
        outfit_state={}, recent_turns=[], total_turns=0,
        synopsis="", turns_since_synopsis=0,
    )


def test_composer_attaches_recipe_from_valid_edit_hint():
    from app.interactive.playback.llm_composer import _to_scene_plan
    from app.interactive.policy.classifier import IntentMatch
    plan = _to_scene_plan(
        payload=_payload("pose"), memory=_memory(), text="dance for me",
        classification=IntentMatch(intent_code="request", confidence=0.5, matched_pattern=""),
        duration_sec=5, allow_explicit=True,
    )
    assert plan is not None
    assert plan.edit_recipe is not None
    assert plan.edit_recipe.workflow_id == "avatar_body_pose"


def test_composer_drops_unknown_hint_and_leaves_recipe_none():
    from app.interactive.playback.llm_composer import _to_scene_plan
    from app.interactive.policy.classifier import IntentMatch
    plan = _to_scene_plan(
        payload=_payload("wildcard_nonsense"), memory=_memory(), text="hi",
        classification=IntentMatch(intent_code="smalltalk", confidence=0.5, matched_pattern=""),
        duration_sec=5, allow_explicit=True,
    )
    assert plan is not None
    assert plan.edit_recipe is None


def test_composer_passes_safety_through_to_recipe():
    from app.interactive.playback.llm_composer import _to_scene_plan
    from app.interactive.policy.classifier import IntentMatch
    plan = _to_scene_plan(
        payload=_payload("outfit"), memory=_memory(), text="wear X",
        classification=IntentMatch(intent_code="request", confidence=0.5, matched_pattern=""),
        duration_sec=5, allow_explicit=False,
    )
    assert plan is not None and plan.edit_recipe is not None
    assert plan.edit_recipe.denoise <= 0.45
