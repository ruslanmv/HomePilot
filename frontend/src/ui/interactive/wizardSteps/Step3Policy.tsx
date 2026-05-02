/**
 * Step 3 — Policy profile picker.
 *
 * The 6 built-in profiles mirror policy/profiles.py. Selecting
 * one decides the runtime guardrails (consent gates, region
 * blocks, narration moderation). For the mature_gated profile we
 * surface an extra warning banner so authors can't pick it
 * accidentally.
 */

import React from "react";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import type { WizardForm } from "../wizardState";

export interface Step3Props {
  form: WizardForm;
  setForm: (patch: Partial<WizardForm>) => void;
}

interface ProfileOption {
  id: string;
  label: string;
  short: string;
  long: string;
  mature: boolean;
}

const PROFILES: ProfileOption[] = [
  { id: "sfw_general", label: "SFW · General",
    short: "Safe for any audience.",
    long: "Default guardrails. No mature intents. No consent prompt.",
    mature: false },
  { id: "sfw_education", label: "SFW · Education",
    short: "Tutorials and lessons.",
    long: "Adds curriculum-friendly tone defaults; same SFW gates.",
    mature: false },
  { id: "language_learning", label: "Language learning",
    short: "Conversational practice.",
    long: "CEFR-aware progression; SFW gates with permissive tone presets.",
    mature: false },
  { id: "enterprise_training", label: "Enterprise training",
    short: "Onboarding & compliance.",
    long: "Strict tone profile + audit-friendly events. Region block enforced.",
    mature: false },
  { id: "social_romantic", label: "Social / Romantic",
    short: "Mood-aware companions.",
    long: "Allows flirty / affectionate intents. Universal-block intents stay blocked.",
    mature: false },
  { id: "mature_gated", label: "Mature (gated)",
    short: "Adults only — explicit consent required.",
    long: "Enables mature narration intents. REQUIRES consent + region check.",
    mature: true },
];

export function Step3Policy({ form, setForm }: Step3Props) {
  const selected = PROFILES.find((p) => p.id === form.policy_profile_id);

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {PROFILES.map((p) => {
          const isSelected = form.policy_profile_id === p.id;
          return (
            <button
              key={p.id}
              type="button"
              onClick={() => setForm({ policy_profile_id: p.id })}
              aria-pressed={isSelected}
              className={[
                "text-left bg-[#121212] border rounded-md p-3.5 transition-colors flex gap-3",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
                isSelected
                  ? "border-[#3ea6ff] bg-[rgba(62,166,255,0.08)] ring-1 ring-[#3ea6ff]"
                  : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
              ].join(" ")}
            >
              <div className="shrink-0 mt-0.5">
                {p.mature
                  ? <ShieldAlert className="w-5 h-5 text-amber-400" aria-hidden />
                  : <ShieldCheck className="w-5 h-5 text-emerald-400" aria-hidden />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-[#f1f1f1]">{p.label}</div>
                <div className="text-xs text-[#aaa] mt-0.5">{p.short}</div>
              </div>
            </button>
          );
        })}
      </div>

      {selected && (
        <div
          className={[
            "rounded-md border p-3 text-xs",
            selected.mature
              ? "border-amber-500/40 bg-amber-500/5 text-amber-200"
              : "border-[#3f3f3f] bg-[#121212] text-[#cfd8dc]",
          ].join(" ")}
          aria-live="polite"
        >
          <span className="font-semibold">{selected.label}.</span> {selected.long}
        </div>
      )}
    </div>
  );
}

/** Always valid — every option is a known profile. */
export function step3Valid(_f: WizardForm): boolean {
  return true;
}
