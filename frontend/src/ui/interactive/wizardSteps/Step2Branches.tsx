/**
 * Step 2 — Branch shape: count, depth, scenes-per-branch.
 *
 * The wizard fetches `/health` once and passes the limits in via
 * props so the inputs hard-cap to whatever the backend allows.
 * The estimated total node count is recomputed live so users see
 * "≈18 nodes" before they ever press Create.
 */

import React, { useMemo } from "react";
import { AlertTriangle } from "lucide-react";
import type { WizardForm } from "../wizardState";

export interface Step2Props {
  form: WizardForm;
  setForm: (patch: Partial<WizardForm>) => void;
  limits: { max_branches: number; max_depth: number; max_nodes_per_experience: number };
}

export function Step2Branches({ form, setForm, limits }: Step2Props) {
  const estimatedNodes = useMemo(
    () => form.branch_count * form.depth * Math.max(1, form.scenes_per_branch),
    [form.branch_count, form.depth, form.scenes_per_branch],
  );
  const overCap = estimatedNodes > limits.max_nodes_per_experience;

  return (
    <div className="flex flex-col gap-5">
      <NumberField
        label="Branch count"
        hint="How many decision paths the experience offers."
        value={form.branch_count}
        min={1}
        max={limits.max_branches}
        onChange={(v) => setForm({ branch_count: v })}
      />
      <NumberField
        label="Depth"
        hint="How many decisions deep before the longest branch ends."
        value={form.depth}
        min={1}
        max={limits.max_depth}
        onChange={(v) => setForm({ depth: v })}
      />
      <NumberField
        label="Scenes per branch"
        hint="How many video scenes per branch leg, before merge."
        value={form.scenes_per_branch}
        min={1}
        max={20}
        onChange={(v) => setForm({ scenes_per_branch: v })}
      />

      <div
        className={[
          "rounded-md border p-3 text-sm flex items-start gap-3",
          overCap
            ? "border-amber-500/40 bg-amber-500/5 text-amber-300"
            : "border-[#3f3f3f] bg-[#121212] text-[#cfd8dc]",
        ].join(" ")}
        aria-live="polite"
      >
        {overCap && <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden />}
        <div>
          <div>
            Upper-bound estimate: <span className="font-semibold text-[#f1f1f1]">≈{estimatedNodes} nodes</span>
            {" "}(branches × depth × scenes; the merge collapser usually trims this).
          </div>
          {overCap && (
            <div className="mt-1 text-xs">
              Exceeds the configured cap of {limits.max_nodes_per_experience}. Reduce branches, depth, or scenes per branch — or the planner will cap it for you.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function NumberField({
  label, hint, value, min, max, onChange,
}: {
  label: string;
  hint?: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  const id = `ix_${label.replace(/\s+/g, "_").toLowerCase()}`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-xs font-medium text-[#cfd8dc]">{label}</label>
      {hint && <p className="text-xs text-[#777] -mt-0.5">{hint}</p>}
      <div className="flex items-center gap-3">
        <input
          id={id}
          type="range"
          min={min}
          max={max}
          step={1}
          value={value}
          onChange={(e) => onChange(parseInt(e.target.value, 10) || min)}
          className="flex-1 accent-[#3ea6ff]"
          aria-valuemin={min}
          aria-valuemax={max}
          aria-valuenow={value}
        />
        <input
          type="number"
          min={min}
          max={max}
          value={value}
          onChange={(e) => onChange(clamp(parseInt(e.target.value, 10) || min, min, max))}
          className="w-20 bg-[#121212] border border-[#3f3f3f] rounded-md px-2 py-1.5 text-sm text-center outline-none focus:border-[#3ea6ff]"
        />
        <span className="text-[11px] text-[#777]">/ {max} max</span>
      </div>
    </div>
  );
}

function clamp(n: number, lo: number, hi: number): number {
  if (n < lo) return lo;
  if (n > hi) return hi;
  return n;
}

/** Always valid — caps are enforced by the input components. */
export function step2Valid(_f: WizardForm): boolean {
  return true;
}
