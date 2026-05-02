/**
 * Step 1 — Audience hints.
 *
 * Optional refinements that bias the planner: who the viewer is,
 * what level they're at, and what language to author in. The
 * defaults work fine — the wizard's "Next" stays enabled even
 * when nothing's been touched.
 */

import React from "react";
import type { WizardForm } from "../wizardState";

export interface Step1Props {
  form: WizardForm;
  setForm: (patch: Partial<WizardForm>) => void;
}

const ROLE_OPTIONS = [
  { value: "viewer", label: "Viewer", hint: "Generic audience." },
  { value: "learner", label: "Learner", hint: "Student / trainee." },
  { value: "customer", label: "Customer", hint: "Buyer / prospect." },
  { value: "trainee", label: "Employee trainee", hint: "Onboarding / compliance." },
  { value: "lead", label: "Sales lead", hint: "Demo / discovery." },
];

const LEVEL_OPTIONS: Array<{ value: WizardForm["audience_level"]; label: string }> = [
  { value: "beginner",     label: "Beginner" },
  { value: "intermediate", label: "Intermediate" },
  { value: "advanced",     label: "Advanced" },
];

const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "es", label: "Spanish" },
  { value: "fr", label: "French" },
  { value: "de", label: "German" },
  { value: "it", label: "Italian" },
  { value: "pt", label: "Portuguese" },
  { value: "ja", label: "Japanese" },
  { value: "zh", label: "Chinese" },
];

export function Step1Audience({ form, setForm }: Step1Props) {
  return (
    <div className="flex flex-col gap-5">
      <Field label="Viewer role" hint="Drives the persona of branch narration.">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {ROLE_OPTIONS.map((r) => (
            <ChoiceCard
              key={r.value}
              selected={form.audience_role === r.value}
              onClick={() => setForm({ audience_role: r.value })}
              label={r.label}
              hint={r.hint}
            />
          ))}
        </div>
      </Field>

      <Field label="Skill level" hint="Pacing and vocabulary baseline.">
        <div className="inline-flex border border-[#3f3f3f] bg-[#121212] rounded-md p-1" role="group" aria-label="Skill level">
          {LEVEL_OPTIONS.map((lv) => {
            const selected = form.audience_level === lv.value;
            return (
              <button
                key={lv.value}
                type="button"
                onClick={() => setForm({ audience_level: lv.value })}
                aria-pressed={selected}
                className={[
                  "px-3 py-1.5 rounded text-sm transition-colors",
                  "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
                  selected
                    ? "bg-[#3ea6ff] text-black font-medium"
                    : "text-[#aaa] hover:text-[#f1f1f1] hover:bg-[#1f1f1f]",
                ].join(" ")}
              >
                {lv.label}
              </button>
            );
          })}
        </div>
      </Field>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Field htmlFor="ix_lang" label="Authoring language">
          <select
            id="ix_lang"
            value={form.audience_language}
            onChange={(e) => setForm({ audience_language: e.target.value })}
            className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2.5 text-sm outline-none focus:border-[#3ea6ff] focus:ring-1 focus:ring-[#3ea6ff]/50"
          >
            {LANGUAGE_OPTIONS.map((l) => (
              <option key={l.value} value={l.value}>{l.label} ({l.value})</option>
            ))}
          </select>
        </Field>

        <Field htmlFor="ix_locale" label="Locale hint" hint="Optional: country / region cue, e.g. 'us-west', 'italy'.">
          <input
            id="ix_locale"
            type="text"
            value={form.audience_locale_hint}
            onChange={(e) => setForm({ audience_locale_hint: e.target.value })}
            placeholder="(optional)"
            maxLength={32}
            className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2.5 text-sm outline-none focus:border-[#3ea6ff] focus:ring-1 focus:ring-[#3ea6ff]/50"
          />
        </Field>
      </div>
    </div>
  );
}

function Field({
  label, hint, htmlFor, children,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-xs font-medium text-[#cfd8dc]">{label}</label>
      {hint && <p className="text-xs text-[#777] -mt-0.5">{hint}</p>}
      {children}
    </div>
  );
}

function ChoiceCard({
  selected, onClick, label, hint,
}: {
  selected: boolean;
  onClick: () => void;
  label: string;
  hint?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={selected}
      className={[
        "text-left bg-[#121212] border rounded-md p-2.5 transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
        selected
          ? "border-[#3ea6ff] bg-[rgba(62,166,255,0.08)] ring-1 ring-[#3ea6ff]"
          : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
      ].join(" ")}
    >
      <div className="text-sm font-medium text-[#f1f1f1]">{label}</div>
      {hint && <div className="text-[11px] text-[#aaa] mt-0.5">{hint}</div>}
    </button>
  );
}

/** Audience step has no hard requirements — defaults are fine. */
export function step1Valid(_f: WizardForm): boolean {
  return true;
}
