/**
 * Step 0 — Prompt + mode selection.
 *
 * Two required inputs (title, prompt) and one mode picker. Mode
 * options are static here to avoid a network roundtrip on first
 * paint; the planner backend tolerates any of the six known mode
 * strings and falls back to sfw_general otherwise.
 */

import React, { useMemo } from "react";
import { Users } from "lucide-react";
import type { ExperienceMode } from "../types";
import type { WizardForm } from "../wizardState";
import { LS_PERSONA_CACHE } from "../../voice/personalityGating";

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
  const personaOptions = useMemo(() => {
    try {
      const raw = localStorage.getItem(LS_PERSONA_CACHE);
      if (!raw) return [];
      const parsed = JSON.parse(raw) as Array<{ id?: unknown; label?: unknown }>;
      return parsed
        .map((item) => ({
          id: typeof item.id === "string" ? item.id : "",
          label: typeof item.label === "string" ? item.label : "",
        }))
        .filter((item) => item.id && item.label);
    } catch {
      return [];
    }
  }, []);

  return (
    <div className="flex flex-col gap-5">
      {/* Interaction type picker — mirrors the Animate/Voice dual-card
          pattern so Interactive inherits the same visual rhythm. */}
      <FieldLabel label="Interaction type" hint="Choose what kind of interactive video to build.">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <button
            type="button"
            onClick={() => setForm({
              interaction_type: "standard_project",
              persona_project_id: "",
              persona_label: "",
            })}
            aria-pressed={form.interaction_type === "standard_project"}
            className={[
              "text-left bg-[#121212] border rounded-md p-3 transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
              form.interaction_type === "standard_project"
                ? "border-[#3ea6ff] bg-[rgba(62,166,255,0.08)] ring-1 ring-[#3ea6ff]"
                : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
            ].join(" ")}
          >
            <div className="text-sm font-medium text-[#f1f1f1]">Standard interactive project</div>
            <div className="text-xs text-[#aaa] mt-0.5">
              Branching AI video with planner-generated scenes and choices.
            </div>
          </button>

          <button
            type="button"
            onClick={() => setForm({ interaction_type: "persona_live_play" })}
            aria-pressed={form.interaction_type === "persona_live_play"}
            className={[
              "text-left bg-[#121212] border rounded-md p-3 transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
              form.interaction_type === "persona_live_play"
                ? "border-[#8b5cf6] bg-[rgba(139,92,246,0.08)] ring-1 ring-[#8b5cf6]"
                : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
            ].join(" ")}
          >
            <div className="text-sm font-medium text-[#f1f1f1] inline-flex items-center gap-1.5">
              <Users className="w-3.5 h-3.5 text-[#c4b5fd]" aria-hidden />
              Persona live play
            </div>
            <div className="text-xs text-[#aaa] mt-0.5">
              Pick one of your personas — video + chat revolve around them.
            </div>
          </button>
        </div>
      </FieldLabel>

      {form.interaction_type === "persona_live_play" && (
        <FieldLabel
          htmlFor="ix_persona_pick"
          label="Persona"
          required
          hint="Select the persona that should drive live-play animation and conversation."
        >
          <select
            id="ix_persona_pick"
            value={form.persona_project_id}
            onChange={(e) => {
              const selected = personaOptions.find((p) => p.id === e.target.value);
              setForm({
                persona_project_id: e.target.value,
                persona_label: selected?.label || "",
              });
            }}
            className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2.5 text-sm outline-none focus:border-[#8b5cf6] focus:ring-1 focus:ring-[#8b5cf6]/50"
          >
            <option value="">Select persona…</option>
            {personaOptions.map((persona) => (
              <option key={persona.id} value={persona.id}>{persona.label}</option>
            ))}
          </select>
          {personaOptions.length === 0 && (
            <p className="text-[11px] text-amber-300 mt-1">
              No personas yet. Create one under the Persona workspace, then come back.
            </p>
          )}
        </FieldLabel>
      )}

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
  const ok = len >= 1;
  return (
    <div className="mt-0.5" aria-live="polite">
      <div className={["text-[11px]", ok ? "text-[#777]" : "text-amber-400"].join(" ")}>
        {len} characters{ok ? " ✓" : ""}
      </div>
      {!ok && (
        <div className="text-[11px] text-[#777] mt-1">
          Type at least one character to enable the Next button.
        </div>
      )}
    </div>
  );
}

/** Validation hook used by the parent Wizard to enable Next. */
export function step0Valid(f: WizardForm): boolean {
  // Persona live play additionally requires a persona selection so
  // the live-play engine has a character to animate + chat as.
  if (f.interaction_type === "persona_live_play" && !f.persona_project_id.trim()) {
    return false;
  }
  return f.title.trim().length >= 3 && f.prompt.trim().length >= 1;
}
