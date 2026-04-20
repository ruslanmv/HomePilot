/**
 * WizardAutoPreview — editable review of the AI-filled plan.
 *
 * Second step of the AUTO wizard. Receives a PlanAutoResult from
 * WizardAuto (the one-box entry), renders every field as an
 * editable control, then on 'Create project':
 *
 *   1. POST /experiences         with the final edited values
 *   2. POST /experiences/{id}/auto-generate
 *   3. onCreated(id)             → InteractiveHost swaps to editor
 *
 * Rename rules follow the UX spec:
 *   - Branches         → Choices
 *   - Depth            → Steps
 *   - Scenes per branch → Scenes per path
 *
 * The 'source' badge shows 'AI' when the LLM composed the plan,
 * 'Smart defaults' when the heuristic fallback fired — honest
 * labeling so the viewer knows what's editable versus generated.
 *
 * Failure modes:
 *   - Create fails  → inline error, stay on preview.
 *   - Generate fails → project still exists (created in step 1);
 *                      we surface a toast + still transition the
 *                      editor so the user can seed manually.
 */

import React, { useCallback, useMemo, useState } from "react";
import { ArrowLeft, Check, ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import { createInteractiveApi } from "./api";
import type {
  ExperienceMode, HealthInfo, PlanAutoForm, PlanAutoResult,
} from "./types";
import { InteractiveApiError } from "./types";
import {
  ErrorBanner, PrimaryButton, useAsyncResource, useToast,
} from "./ui";
import { GeneratingPanel } from "./GeneratingPanel";


const MODE_LABELS: Record<ExperienceMode, string> = {
  sfw_general: "General (safe for work)",
  sfw_education: "Education",
  language_learning: "Language learning",
  enterprise_training: "Enterprise training",
  social_romantic: "Social / romantic",
  mature_gated: "Mature (gated)",
};

const LEVEL_LABELS: Record<PlanAutoForm["audience_level"], string> = {
  beginner: "Beginner",
  intermediate: "Intermediate",
  advanced: "Advanced",
};

const LANG_LABELS: Record<string, string> = {
  en: "English", es: "Spanish", fr: "French", de: "German",
  it: "Italian", pt: "Portuguese", ja: "Japanese", zh: "Chinese",
};

// Five-phase checklist matching the events the backend emits on
// /generate-all/stream. Last step ("Opening the editor") is
// marked done after the ``result`` frame arrives so the modal
// visibly ticks the final checkmark before unmounting.
const GENERATE_STEPS = [
  { label: "Saving your project" },
  { label: "Drafting the scene graph" },
  { label: "Writing dialogue + choices" },
  { label: "Rendering scenes" },
  { label: "Opening the editor" },
];

/** Interaction mode + optional persona link threaded through from
 *  WizardAuto so createExperience can stamp both on audience_profile. */
export interface InteractionSelection {
  interaction_type: "standard_project" | "persona_live_play";
  persona_project_id?: string;
  persona_label?: string;
  /**
   * Scene-render pipeline. "video" (default) uses Animate/SVD;
   * "image" swaps to the txt2img workflow for feasibility tests
   * on low-VRAM setups.
   */
  render_media_type?: "video" | "image";
}

export interface WizardAutoPreviewProps {
  backendUrl: string;
  apiKey?: string;
  initial: PlanAutoResult;
  originalIdea: string;
  interaction: InteractionSelection;
  /** Called with the freshly-created experience id so the host can
   *  swap this component for the editor. */
  onCreated: (experienceId: string) => void;
  /** Called when the user wants to re-generate from scratch. */
  onStartOver: () => void;
}

export function WizardAutoPreview({
  backendUrl, apiKey, initial, originalIdea, interaction, onCreated, onStartOver,
}: WizardAutoPreviewProps) {
  const api = useMemo(
    () => createInteractiveApi(backendUrl, apiKey),
    [backendUrl, apiKey],
  );
  const toast = useToast();

  const [form, setForm] = useState<PlanAutoForm>(initial.form);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [genStep, setGenStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  // BATCH B/C: live scene-render progress pulled off the SSE
  // stream so the modal can show "6 / 12 scenes" as they finish.
  const [renderTotal, setRenderTotal] = useState(0);
  const [renderDone, setRenderDone] = useState(0);
  const [renderSkipped, setRenderSkipped] = useState(0);
  const [currentSceneTitle, setCurrentSceneTitle] = useState<string>("");

  // EDIT-5: fetch the backend's playback-flag readout so the
  // modal can tell the user up-front whether scene rendering is
  // actually enabled. When it's off, we replace the "Rendering
  // scenes" step copy with a call-to-action pointing at the
  // Editor's regenerate controls, instead of showing a fake
  // full progress bar while every scene silently skips.
  const health = useAsyncResource<HealthInfo>(
    (signal) => api.health(signal),
    [api],
  );
  const renderEnabled = health.data?.playback?.render_enabled !== false;

  const patch = useCallback(<K extends keyof PlanAutoForm>(
    key: K, value: PlanAutoForm[K],
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  }, []);

  const onSubmit = useCallback(async () => {
    setError(null);
    setSubmitting(true);
    setGenStep(0);

    try {
      // Step 1: create the experience. Interaction type + any
      // linked persona ride along on audience_profile so the
      // backend + future routes can branch on them (live-play
      // preview in particular needs the persona id).
      const created = await api.createExperience({
        title: form.title,
        description: form.prompt,
        experience_mode: form.experience_mode,
        policy_profile_id: form.policy_profile_id,
        audience_profile: {
          role: form.audience_role,
          level: form.audience_level,
          language: form.audience_language,
          locale_hint: form.audience_locale_hint,
          interaction_type: interaction.interaction_type,
          persona_project_id: interaction.persona_project_id,
          persona_label: interaction.persona_label,
          render_media_type: interaction.render_media_type || "video",
        },
      });
      setGenStep(1);

      // Step 2: full-project generation via the new SSE stream.
      // Orchestrates plan + graph + per-scene render in one
      // subscription so the modal stays up through the entire
      // lifecycle and progress mirrors real backend work.
      try {
        const gen = await api.generateAllStream(created.id, {
          onEvent: (ev) => {
            const idx = _stepIndexForPhase(ev.type);
            if (idx !== null) {
              setGenStep((prev) => Math.max(prev, idx));
            }
            // Scene-render progress: capture total + current index
            // so the modal's progress bar + "Rendering scene X of Y"
            // label can track reality.
            if (ev.type === "rendering_started") {
              const total = Number((ev.payload as any)?.total || 0);
              setRenderTotal(total);
              setRenderDone(0);
            }
            if (ev.type === "rendering_scene") {
              const title = String((ev.payload as any)?.title || "");
              if (title) setCurrentSceneTitle(title);
            }
            if (ev.type === "scene_rendered") {
              setRenderDone((prev) => prev + 1);
            }
            if (
              ev.type === "scene_skipped"
              || ev.type === "scene_render_failed"
            ) {
              setRenderDone((prev) => prev + 1);
              setRenderSkipped((prev) => prev + 1);
            }
          },
        });
        // Step 4 = "Opening the editor". Bumping to 4 marks every
        // earlier row as done in the GeneratingPanel checklist.
        setGenStep(GENERATE_STEPS.length - 1);
        toast.toast({
          variant: gen.source === "llm" ? "success" : "info",
          title: gen.source === "existing"
            ? "Project already has scenes"
            : "Project ready",
          message: gen.source === "existing"
            ? "Opening the editor."
            : `${gen.node_count} scenes · ${gen.edge_count} transitions${
                gen.action_count > 0 ? ` · ${gen.action_count} choices` : ""
              }`,
        });
      } catch (genErr) {
        const e = genErr as InteractiveApiError;
        setGenStep(GENERATE_STEPS.length - 1);
        toast.toast({
          variant: "warning",
          title: "Project created, but scene graph not generated",
          message: e.message || "Open the Graph tab to seed it manually.",
        });
      }

      // Tiny beat so the last checkmark is visible before the
      // host swaps this component for the editor.
      await new Promise((r) => window.setTimeout(r, 220));
      onCreated(created.id);
    } catch (err) {
      const e = err as InteractiveApiError;
      setError(e.message || "Couldn't create the project.");
      setSubmitting(false);
      setGenStep(0);
      setRenderTotal(0);
      setRenderDone(0);
      setRenderSkipped(0);
    }
  }, [api, form, interaction, onCreated, toast]);

  return (
    <div className="relative flex flex-col h-full w-full">
      {/* Scrollable body */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-6 py-8">
          <header className="flex items-center justify-between gap-4 mb-6">
            <button
              type="button"
              onClick={onStartOver}
              disabled={submitting}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-[#aaa] hover:text-[#f1f1f1] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] rounded px-1 py-0.5 disabled:opacity-50"
            >
              <ArrowLeft className="w-3.5 h-3.5" aria-hidden />
              Start over
            </button>
            <SourceBadge source={initial.source} />
          </header>

          <h1 className="text-xl font-semibold text-[#f1f1f1]">
            Review your project
          </h1>
          <p className="text-sm text-[#aaa] mt-1.5 leading-relaxed">
            The AI turned{" "}
            <span className="text-[#cfd8dc]">"{originalIdea.slice(0, 80)}{originalIdea.length > 80 ? "…" : ""}"</span>
            {" "}into the draft below. Edit anything you'd like before creating.
          </p>

          {error && (
            <div className="mt-5">
              <ErrorBanner
                title="Couldn't create the project"
                message={error}
                onRetry={onSubmit}
              />
            </div>
          )}

          <div className="mt-6 flex flex-col gap-5">
            <Field label="Title">
              <input
                type="text"
                value={form.title}
                onChange={(e) => patch("title", e.target.value)}
                maxLength={80}
                disabled={submitting}
                className={INPUT_CLS}
              />
            </Field>

            <Field label="What it covers"
                   hint="Short brief the planner uses as the story seed.">
              <textarea
                rows={3}
                value={form.prompt}
                onChange={(e) => patch("prompt", e.target.value)}
                disabled={submitting}
                className={`${INPUT_CLS} resize-y leading-relaxed`}
              />
            </Field>

            <div className="grid grid-cols-2 gap-4">
              <Field label="Mode">
                <select
                  value={form.experience_mode}
                  onChange={(e) => {
                    const next = e.target.value as ExperienceMode;
                    patch("experience_mode", next);
                    patch("policy_profile_id", next);
                  }}
                  disabled={submitting}
                  className={INPUT_CLS}
                >
                  {(Object.keys(MODE_LABELS) as ExperienceMode[]).map((m) => (
                    <option key={m} value={m}>{MODE_LABELS[m]}</option>
                  ))}
                </select>
              </Field>

              <Field label="Audience level">
                <select
                  value={form.audience_level}
                  onChange={(e) => patch("audience_level", e.target.value as PlanAutoForm["audience_level"])}
                  disabled={submitting}
                  className={INPUT_CLS}
                >
                  {(Object.keys(LEVEL_LABELS) as PlanAutoForm["audience_level"][]).map((lv) => (
                    <option key={lv} value={lv}>{LEVEL_LABELS[lv]}</option>
                  ))}
                </select>
              </Field>
            </div>

            {/* Shape — renamed per the UX spec */}
            <Field label="Shape">
              <div className="grid grid-cols-3 gap-2">
                <NumberPill
                  label="Choices"
                  value={form.branch_count}
                  min={1} max={6}
                  onChange={(n) => patch("branch_count", n)}
                  disabled={submitting}
                />
                <NumberPill
                  label="Steps"
                  value={form.depth}
                  min={1} max={4}
                  onChange={(n) => patch("depth", n)}
                  disabled={submitting}
                />
                <NumberPill
                  label="Scenes per path"
                  value={form.scenes_per_branch}
                  min={1} max={6}
                  onChange={(n) => patch("scenes_per_branch", n)}
                  disabled={submitting}
                />
              </div>
              <p className="text-[11px] text-[#777] mt-1.5">
                About <span className="text-[#cfd8dc]">{form.branch_count * form.depth * form.scenes_per_branch}</span> scenes total (before the graph merges overlaps).
              </p>
            </Field>

            <AdvancedBlock
              open={advancedOpen}
              onToggle={() => setAdvancedOpen((v) => !v)}
              form={form}
              patch={patch}
              disabled={submitting}
            />
          </div>

          {/* Planner preview (read-only, LLM telemetry) */}
          {(initial.objective || initial.topic || initial.seed_intents.length > 0) && (
            <div className="mt-6 rounded-lg border border-[#2a2a2a] bg-[#121212]/60 px-4 py-3 text-[11px] leading-relaxed">
              <div className="text-[#cfd8dc] font-medium mb-1">Planner preview</div>
              <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-0.5 text-[#aaa]">
                {initial.objective && (
                  <><dt>Objective</dt><dd className="text-[#cfd8dc]">{initial.objective}</dd></>
                )}
                {initial.topic && (
                  <><dt>Topic</dt><dd className="text-[#cfd8dc]">{initial.topic}</dd></>
                )}
                {initial.success_metric && (
                  <><dt>Success</dt><dd className="text-[#cfd8dc]">{initial.success_metric}</dd></>
                )}
                {initial.seed_intents.length > 0 && (
                  <><dt>Seeds</dt>
                  <dd className="flex flex-wrap gap-1">
                    {initial.seed_intents.map((s) => (
                      <code key={s} className="text-[#cfd8dc] bg-[#1f1f1f] border border-[#3f3f3f] rounded px-1.5 py-0.5 text-[10px]">{s}</code>
                    ))}
                  </dd></>
                )}
              </dl>
            </div>
          )}
        </div>
      </div>

      {/* Fixed bottom action bar */}
      <footer className="shrink-0 border-t border-[#2a2a2a] bg-[#0f0f0f] py-3">
        <div className="max-w-2xl mx-auto px-6 flex items-center justify-end gap-3">
          <PrimaryButton
            onClick={onSubmit}
            disabled={submitting || !form.title.trim()}
            loading={submitting}
            size="lg"
            icon={!submitting ? <Check className="w-4 h-4" aria-hidden /> : undefined}
          >
            Create project
          </PrimaryButton>
        </div>
      </footer>

      {/* Enterprise waiting overlay — stays up through the full
          plan → graph → render → ready lifecycle so the user
          never watches a stale blank screen while heavy asset
          generation runs. Progress bar + per-scene label kick in
          once the backend reaches the rendering phase.
          EDIT-5: when backend reports render_enabled=false, swap
          the progress bar for an amber "rendering off" hint so
          we don't fake success the user has to discover later. */}
      {submitting && (
        <GeneratingPanel
          title={_panelTitle(genStep, renderTotal, renderDone, renderEnabled)}
          description={_panelDescription(
            genStep, currentSceneTitle, renderEnabled,
          )}
          steps={GENERATE_STEPS}
          activeStep={genStep}
          accentClassName="text-[#c4b5fd]"
          spinnerSize="large"
          progress={renderEnabled && renderTotal > 0
            ? Math.round((renderDone / renderTotal) * 100)
            : undefined}
          progressLabel={renderEnabled && renderTotal > 0
            ? `${renderDone} / ${renderTotal} scenes${
                renderSkipped > 0 ? ` · ${renderSkipped} skipped` : ""
              }`
            : undefined}
          footerHint={!renderEnabled && genStep >= 3
            ? "Scene rendering is off. You can turn it on in Settings → Providers and regenerate from the Editor."
            : undefined}
        />
      )}
    </div>
  );
}

// ── Smaller building blocks ────────────────────────────────────

const INPUT_CLS = [
  "w-full bg-[#121212] border border-[#3f3f3f] rounded-md",
  "px-3 py-2 text-sm outline-none",
  "focus:border-[#3ea6ff] focus:ring-1 focus:ring-[#3ea6ff]/50",
  "disabled:opacity-60 disabled:cursor-not-allowed",
].join(" ");


function Field({
  label, hint, children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-xs font-medium text-[#cfd8dc]">{label}</label>
      {hint && <p className="text-[11px] text-[#777] -mt-0.5">{hint}</p>}
      {children}
    </div>
  );
}


function NumberPill({
  label, value, min, max, onChange, disabled,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (n: number) => void;
  disabled?: boolean;
}) {
  const dec = () => onChange(Math.max(min, value - 1));
  const inc = () => onChange(Math.min(max, value + 1));
  return (
    <div className="bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2">
      <div className="text-[10px] text-[#777] uppercase tracking-wide">{label}</div>
      <div className="mt-1 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={dec}
          disabled={disabled || value <= min}
          aria-label={`Decrease ${label}`}
          className="w-6 h-6 rounded-md bg-white/5 hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed text-[#cfd8dc] text-sm font-medium"
        >−</button>
        <span className="text-lg font-semibold text-[#f1f1f1] tabular-nums">{value}</span>
        <button
          type="button"
          onClick={inc}
          disabled={disabled || value >= max}
          aria-label={`Increase ${label}`}
          className="w-6 h-6 rounded-md bg-white/5 hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed text-[#cfd8dc] text-sm font-medium"
        >+</button>
      </div>
    </div>
  );
}


function AdvancedBlock({
  open, onToggle, form, patch, disabled,
}: {
  open: boolean;
  onToggle: () => void;
  form: PlanAutoForm;
  patch: <K extends keyof PlanAutoForm>(k: K, v: PlanAutoForm[K]) => void;
  disabled: boolean;
}) {
  return (
    <section className="rounded-lg border border-[#2a2a2a] bg-[#121212]/60">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-[#f1f1f1] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] rounded-lg"
      >
        <span className="inline-flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-[#c4b5fd]" aria-hidden />
          Advanced
        </span>
        {open ? <ChevronUp className="w-4 h-4 text-[#aaa]" aria-hidden />
              : <ChevronDown className="w-4 h-4 text-[#aaa]" aria-hidden />}
      </button>
      {open && (
        <div className="px-4 pb-4 grid grid-cols-2 gap-3 text-sm">
          <Field label="Viewer role">
            <input
              type="text"
              value={form.audience_role}
              onChange={(e) => patch("audience_role", e.target.value)}
              disabled={disabled}
              className={INPUT_CLS}
            />
          </Field>
          <Field label="Language">
            <select
              value={form.audience_language}
              onChange={(e) => patch("audience_language", e.target.value)}
              disabled={disabled}
              className={INPUT_CLS}
            >
              {Object.entries(LANG_LABELS).map(([v, l]) => (
                <option key={v} value={v}>{l} ({v})</option>
              ))}
            </select>
          </Field>
          <Field label="Locale hint" hint="Optional region cue.">
            <input
              type="text"
              value={form.audience_locale_hint}
              onChange={(e) => patch("audience_locale_hint", e.target.value)}
              placeholder="(optional, e.g. us-west)"
              maxLength={32}
              disabled={disabled}
              className={INPUT_CLS}
            />
          </Field>
          <Field label="Policy profile">
            <input
              type="text"
              value={form.policy_profile_id}
              onChange={(e) => patch("policy_profile_id", e.target.value)}
              disabled={disabled}
              className={INPUT_CLS}
            />
          </Field>
        </div>
      )}
    </section>
  );
}


/**
 * Map a generate-all stream phase (BATCH B) to a GENERATE_STEPS
 * index so the spinner advances on real backend events.
 *
 *   GENERATE_STEPS:
 *     0 — "Saving your project"      (already done when we subscribe)
 *     1 — "Drafting the scene graph" (generating_graph .. graph_generated)
 *     2 — "Writing dialogue + choices" (persisting_* + seeding_rule + qa)
 *     3 — "Rendering scenes"         (rendering_started .. rendering_done)
 *     4 — "Opening the editor"       (result / done)
 *
 * Unknown phase names return null so the spinner holds its
 * current step — forward-compatible with future backend events.
 */
function _panelTitle(
  step: number, renderTotal: number, renderDone: number,
  renderEnabled: boolean,
): string {
  // Copy the user sees in the big heading. Evolves with the
  // active step so the modal feels like it's doing something
  // concrete rather than a generic "loading…".
  if (step <= 1) return "Drafting your scene graph";
  if (step === 2) return "Writing dialogue + choices";
  if (step === 3) {
    if (!renderEnabled) return "Scene graph ready";
    if (renderTotal > 0) {
      return `Rendering scenes · ${renderDone} of ${renderTotal}`;
    }
    return "Rendering scenes";
  }
  return "Opening your project";
}


function _panelDescription(
  step: number, currentScene: string, renderEnabled: boolean,
): string {
  if (step <= 1) return "Turning your idea into a branching scene graph.";
  if (step === 2) return "Populating scenes with narration, choices, and actions.";
  if (step === 3) {
    if (!renderEnabled) {
      return "Skipping asset generation — your scenes are ready to edit.";
    }
    if (currentScene) return `Now rendering: ${currentScene}`;
    return "Producing scene assets — this is the slowest phase.";
  }
  return "Everything's ready. Opening the editor.";
}


function _stepIndexForPhase(phase: string): number | null {
  switch (phase) {
    case "started":
    case "already_generated":
      return 1;
    case "generating_graph":
    case "graph_generated":
      return 1;
    case "persisting_nodes":
    case "persisting_edges":
    case "persisting_actions":
    case "seeding_rule":
    case "running_qa":
    case "qa_done":
      return 2;
    case "rendering_started":
    case "rendering_scene":
    case "scene_rendered":
    case "scene_skipped":
    case "scene_render_failed":
    case "rendering_done":
      return 3;
    case "result":
    case "done":
      return 4;
    default:
      return null;
  }
}


function SourceBadge({ source }: { source: "llm" | "heuristic" }) {
  if (source === "llm") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-[#8b5cf6]/15 border border-[#8b5cf6]/30 text-[#c4b5fd] text-[11px] font-medium px-2.5 py-1">
        <Sparkles className="w-3 h-3" aria-hidden />
        AI-generated draft
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-white/5 border border-white/10 text-[#aaa] text-[11px] font-medium px-2.5 py-1">
      Smart defaults
    </span>
  );
}
