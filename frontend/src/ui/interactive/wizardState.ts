/**
 * Form state for the new-project wizard.
 *
 * Lives in its own module so the step components and the parent
 * Wizard can both import the same type without circular deps.
 * The shape is wire-friendly: `toCreatePayload` and `toPlanPayload`
 * project this struct directly into the `/v1/interactive/*`
 * request bodies — no field renames at the boundary.
 */

import type { ExperienceMode } from "./types";

/**
 * Which ComfyUI workflow bucket the player calls per scene.
 *   "video"  — full Animate/SVD clip. Default. Higher VRAM.
 *   "image"  — still-image txt2img. Cheap on GPU; lets operators
 *              validate the whole interactive flow without owning
 *              a beefy video model.
 */
export type RenderMediaType = "video" | "image";

export interface WizardForm {
  // Interaction type (Step 0 header)
  interaction_type: "standard_project" | "persona_live_play";
  persona_project_id: string;
  persona_label: string;

  /** Scene render bucket — image or video. See RenderMediaType. */
  render_media_type: RenderMediaType;

  // Step 0
  title: string;
  prompt: string;
  experience_mode: ExperienceMode;

  // Step 1
  audience_role: string;
  audience_level: "beginner" | "intermediate" | "advanced";
  audience_language: string;
  audience_locale_hint: string;

  // Step 2
  branch_count: number;
  depth: number;
  scenes_per_branch: number;

  // Step 3
  policy_profile_id: string;
}

export const DEFAULT_WIZARD_FORM: WizardForm = {
  interaction_type: "standard_project",
  persona_project_id: "",
  persona_label: "",
  render_media_type: "video",
  title: "",
  prompt: "",
  experience_mode: "sfw_general",
  audience_role: "viewer",
  audience_level: "beginner",
  audience_language: "en",
  audience_locale_hint: "",
  branch_count: 3,
  depth: 3,
  scenes_per_branch: 3,
  policy_profile_id: "sfw_general",
};

export function toCreatePayload(f: WizardForm) {
  return {
    title: f.title.trim(),
    description: f.prompt.trim(),
    experience_mode: f.experience_mode,
    policy_profile_id: f.policy_profile_id,
    project_type: f.interaction_type === "persona_live_play" ? "persona_live" : "standard",
    audience_profile: {
      role: f.audience_role,
      level: f.audience_level,
      language: f.audience_language,
      locale_hint: f.audience_locale_hint,
      interaction_type: f.interaction_type,
      persona_project_id: f.persona_project_id || undefined,
      persona_label: f.persona_label || undefined,
      render_media_type: f.render_media_type,
    },
  };
}

export function toPlanPayload(f: WizardForm) {
  return {
    prompt: f.prompt.trim(),
    mode: f.experience_mode,
    audience_hints: {
      role: f.audience_role,
      level: f.audience_level,
      language: f.audience_language,
      locale_hint: f.audience_locale_hint,
      interaction_type: f.interaction_type,
      persona_project_id: f.persona_project_id || undefined,
      persona_label: f.persona_label || undefined,
      render_media_type: f.render_media_type,
    },
  };
}
