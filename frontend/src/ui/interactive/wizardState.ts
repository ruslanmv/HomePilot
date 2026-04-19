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

export interface WizardForm {
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
    audience_profile: {
      role: f.audience_role,
      level: f.audience_level,
      language: f.audience_language,
      locale_hint: f.audience_locale_hint,
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
    },
  };
}
