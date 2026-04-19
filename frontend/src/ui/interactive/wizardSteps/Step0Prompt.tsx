/**
 * Step 0 — Prompt + mode selection.
 *
 * Two required inputs (title, prompt) and one mode picker. Mode
 * options are static here to avoid a network roundtrip on first
 * paint; the planner backend tolerates any of the six known mode
 * strings and falls back to sfw_general otherwise.
 */

import React from "react";
import type { ExperienceMode } from "../types";
import type { WizardForm } from "../wizardState";

export interface Step0Props {
  form: WizardForm;
  setForm: (patch: Partial<WizardForm>) => void;
}

const MODE_OPTIONS: Array<{ value: ExperienceMode; label: string; hint: string }> = [
  { value: "sfw_general",         label: "General (SFW)",        hint: "Safe-for-work default — broad audiences." },
  { value: "sfw_education",       label: "Education",            hint: "Lessons, tutorials, explanations." },
  { value: "language_learning",   label: "Language learning",    hint: "CEFR-aware exercises and conversation." },
  { value: "enterprise_training", label: "Enterprise training",  hint: "Onboarding, compliance, certification." },
  { value: "social_romantic",     label: "Social / Romantic",    hint: "Casual social play, mood-aware companions." },
  { value: "mature_gated",        label: "Mature (gated)",       hint: "Requires explicit viewer consent + region check." },
];

export function Step0Prompt({ form, setForm }: Step0Props) {
  return (
    <div className="flex flex-col gap-5">
      <FieldLabel htmlFor="ix_title" label="Project title" required>
        <input
          id="ix_title"
          type="text"
          value={form.title}
          onChange={(e) => setForm({ title: e.target.value })}
          placeholder="e.g. Onboard new sales reps to our pricing tiers"
          maxLength={120}
          className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2.5 text-sm outline-none focus:border-[#3ea6ff] focus:ring-1 focus:ring-[#3ea6ff]/50"
        />
      </FieldLabel>

      <FieldLabel htmlFor="ix_prompt" label="Prompt" required hint="Describe the experience in plain language. The planner uses this to design branches and pick scene topics.">
        <textarea
          id="ix_prompt"
          rows={5}
          value={form.prompt}
          onChange={(e) => setForm({ prompt: e.target.value })}
          placeholder="e.g. Walk a new hire through our 3 pricing tiers in 4 branches; each branch ends with a quiz question."
          className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2.5 text-sm outline-none focus:border-[#3ea6ff] focus:ring-1 focus:ring-[#3ea6ff]/50 resize-y"
        />
        <PromptCounter value={form.prompt} />
      </FieldLabel>

      <FieldLabel label="Experience mode" hint="Selects the policy profile + scene templates downstream.">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {MODE_OPTIONS.map((m) => {
            const selected = form.experience_mode === m.value;
            return (
              <button
                key={m.value}
                type="button"
                onClick={() => setForm({ experience_mode: m.value, policy_profile_id: m.value })}
                aria-pressed={selected}
                className={[
                  "text-left bg-[#121212] border rounded-md p-3 transition-colors",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
                  selected
                    ? "border-[#3ea6ff] bg-[rgba(62,166,255,0.08)] ring-1 ring-[#3ea6ff]"
                    : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
                ].join(" ")}
              >
                <div className="text-sm font-medium text-[#f1f1f1]">{m.label}</div>
                <div className="text-xs text-[#aaa] mt-0.5">{m.hint}</div>
              </button>
            );
          })}
        </div>
      </FieldLabel>
    </div>
  );
}

function FieldLabel({
  label, hint, required, htmlFor, children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-[#cfd8dc]">
        {label}
        {required && <span className="text-[#3ea6ff] ml-0.5" aria-label="required">*</span>}
      </label>
      {hint && <p className="text-xs text-[#777] -mt-0.5">{hint}</p>}
      {children}
    </div>
  );
}

function PromptCounter({ value }: { value: string }) {
  const len = value.trim().length;
  const ok = len >= 10;
  return (
    <div className="mt-0.5" aria-live="polite">
      <div className={["text-[11px]", ok ? "text-[#777]" : "text-amber-400"].join(" ")}>
        {len} / 10 minimum {ok ? "✓" : "characters"}
      </div>
      {!ok && (
        // Spelled-out hint surfaces the exact unblock condition so
        // users never wonder why Next is dimmed on step 1.
        <div className="text-[11px] text-[#777] mt-1">
          Add at least 10 prompt characters to enable the Next button.
        </div>
      )}
    </div>
  );
}

/** Validation hook used by the parent Wizard to enable Next. */
export function step0Valid(f: WizardForm): boolean {
  return f.title.trim().length >= 3 && f.prompt.trim().length >= 10;
}
