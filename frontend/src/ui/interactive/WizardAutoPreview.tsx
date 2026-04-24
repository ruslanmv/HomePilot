// frontend/src/ui/interactive/WizardAutoPreview.tsx

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
 *
 * Production fixes in this version:
 *   - Persona-linked experiences now persist the exact selected
 *     persona image URLs when available.
 *   - Persona live defaults to image rendering for lower-VRAM /
 *     faster first-run behavior unless explicitly overridden.
 *   - Payload generation is centralized and trimmed consistently.
 */

import React, { useCallback, useMemo, useState } from "react";
import { ArrowLeft, Check, ChevronDown, ChevronUp, Sparkles } from "lucide-react";
import { createInteractiveApi } from "./api";
import type {
  ExperienceMode,
  HealthInfo,
  PlanAutoForm,
  PlanAutoResult,
} from "./types";
import { InteractiveApiError } from "./types";
import {
  ErrorBanner,
  PrimaryButton,
  useAsyncResource,
  useToast,
} from "./ui";
import {
  startGeneration,
  useWizardProgress,
  dismissOverlay,
} from "./wizardProgressStore";

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
  en: "English",
  es: "Spanish",
  fr: "French",
  de: "German",
  it: "Italian",
  pt: "Portuguese",
  ja: "Japanese",
  zh: "Chinese",
};

const GENERATE_STEPS = [
  { label: "Saving your project" },
  { label: "Drafting the scene graph" },
  { label: "Writing dialogue + choices" },
  { label: "Rendering scenes" },
  { label: "Opening the editor" },
];

export interface InteractionSelection {
  interaction_type: "standard_project" | "persona_live_play";
  persona_project_id?: string;
  persona_label?: string;
  persona_avatar_url?: string;
  persona_portrait_url?: string;
  persona_image_fit?: "cover" | "contain";
  persona_image_position?: string;
  render_media_type?: "video" | "image";
}

export interface WizardAutoPreviewProps {
  backendUrl: string;
  apiKey?: string;
  initial: PlanAutoResult;
  originalIdea: string;
  interaction: InteractionSelection;
  onCreated: (experienceId: string) => void;
  onStartOver: () => void;
}

export function WizardAutoPreview({
  backendUrl,
  apiKey,
  initial,
  originalIdea,
  interaction,
  onCreated,
  onStartOver,
}: WizardAutoPreviewProps) {
  const api = useMemo(
    () => createInteractiveApi(backendUrl, apiKey),
    [backendUrl, apiKey],
  );
  const toast = useToast();

  const [form, setForm] = useState<PlanAutoForm>({
    ...initial.form,
    render_media_type:
      initial.form.render_media_type ||
      interaction.render_media_type ||
      (interaction.interaction_type === "persona_live_play" ? "image" : "video"),
  });

  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Progress lives in a module-level store so the modal survives
  // tab switches mid-generation. WizardAutoPreview unmounts when
  // the user clicks Chat / Imagine / Voice; the SSE stream and
  // counters keep running, and the global overlay rendered at App
  // level (see App.tsx) stays visible the whole time.
  const progress = useWizardProgress();
  const submitting = progress.active;
  const genStep = progress.genStep;
  const renderTotal = progress.renderTotal;
  const renderDone = progress.renderDone;
  const renderSkipped = progress.renderSkipped;
  const currentSceneTitle = progress.currentSceneTitle;

  const personaLive = interaction.interaction_type === "persona_live_play";

  const health = useAsyncResource<HealthInfo>(
    (signal) => api.health(signal),
    [api],
  );
  const renderEnabled = health.data?.playback?.render_enabled !== false;

  const patch = useCallback(
    <K extends keyof PlanAutoForm>(key: K, value: PlanAutoForm[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const buildCreatePayload = useCallback(() => {
    const renderMediaType =
      form.render_media_type ||
      interaction.render_media_type ||
      (personaLive ? "image" : "video");

    return {
      title: (form.title || "").trim(),
      description: (form.prompt || "").trim(),
      experience_mode: form.experience_mode,
      policy_profile_id: form.policy_profile_id,
      project_type: personaLive ? "persona_live" : "standard",
      audience_profile: {
        role: form.audience_role,
        level: form.audience_level,
        language: form.audience_language,
        locale_hint: (form.audience_locale_hint || "").trim(),
        interaction_type: interaction.interaction_type,
        persona_project_id: cleanOptional(interaction.persona_project_id),
        persona_label: cleanOptional(interaction.persona_label),
        persona_avatar_url: cleanOptional(interaction.persona_avatar_url),
        persona_portrait_url: cleanOptional(interaction.persona_portrait_url),
        persona_image_fit: interaction.persona_image_fit || (personaLive ? "contain" : undefined),
        persona_image_position: cleanOptional(
          interaction.persona_image_position || (personaLive ? "center" : undefined),
        ),
        render_media_type: renderMediaType,
      },
    };
  }, [form, interaction, personaLive]);

  const onSubmit = useCallback(async () => {
    setError(null);

    // Delegate to the module-level store. The store owns the SSE
    // stream + all progress counters; this lets the global overlay
    // keep showing the modal even if the user navigates to another
    // tab while generation is in flight. WizardAutoPreview just
    // observes via useWizardProgress() and waits for completion.
    let createdId = "";
    const result = await startGeneration({
      api,
      payload: buildCreatePayload(),
      totalSteps: GENERATE_STEPS.length,
      onCreated: (id) => { createdId = id; },
    });

    if (!result) {
      // Generation failed — pull the error out of the store so the
      // wizard's inline error banner can show it. The overlay also
      // renders the failure state, but the in-form banner gives
      // the user a "Retry" button without leaving the wizard.
      const errMsg =
        useWizardProgressStateError() || "Couldn't create the project.";
      setError(errMsg);
      return;
    }

    toast.toast({
      variant: result.source === "llm" ? "success" : "info",
      title:
        result.source === "existing"
          ? "Project already has scenes"
          : "Project ready",
      message:
        result.source === "existing"
          ? "Opening the editor."
          : `${result.node_count} scenes · ${result.edge_count} transitions${
              result.action_count > 0 ? ` · ${result.action_count} choices` : ""
            }`,
    });

    await new Promise((r) => window.setTimeout(r, 220));
    if (createdId) {
      // Dismiss the overlay BEFORE navigating so the GeneratingPanel
      // doesn't briefly flash on the editor screen.
      dismissOverlay();
      onCreated(createdId);
    }
  }, [api, buildCreatePayload, onCreated, toast]);

  // Tiny helper — reads the store's error one-shot for the toast above.
  // Defined inside the component so it never participates in subscription
  // loops (the main `progress` hook already subscribes for re-renders).
  function useWizardProgressStateError(): string | null {
    return progress.error;
  }

  return (
    <div className="relative flex flex-col h-full w-full">
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
            {personaLive ? "Review your live play session" : "Review your project"}
          </h1>
          <p className="text-sm text-[#aaa] mt-1.5 leading-relaxed">
            The AI turned{" "}
            <span className="text-[#cfd8dc]">
              "{originalIdea.slice(0, 80)}
              {originalIdea.length > 80 ? "…" : ""}"
            </span>
            {personaLive
              ? " into a persona-centered setup. Edit anything before launch."
              : " into the draft below. Edit anything you'd like before creating."}
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
            {!personaLive && (
              <>
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

                <Field
                  label="What it covers"
                  hint="Short brief the planner uses as the story seed."
                >
                  <textarea
                    rows={3}
                    value={form.prompt}
                    onChange={(e) => patch("prompt", e.target.value)}
                    disabled={submitting}
                    className={`${INPUT_CLS} resize-y leading-relaxed`}
                  />
                </Field>
              </>
            )}

            {personaLive && (
              <Field label="Persona card">
                <div className="rounded-lg border border-[#3a2a58] bg-[#130f1f] p-3">
                  <div className="flex items-start gap-3">
                    {interaction.persona_avatar_url ? (
                      <img
                        src={interaction.persona_avatar_url}
                        alt=""
                        className="w-12 h-12 rounded-full object-cover object-top border border-white/10 bg-black shrink-0"
                      />
                    ) : null}
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-[#f1f1f1]">
                        {interaction.persona_label || "Selected persona"}
                      </div>
                      <div className="text-xs text-[#b59ed9] mt-1">
                        Session vibe: {form.prompt}
                      </div>
                      <div className="text-[11px] text-[#8f7ab0] mt-2">
                        Portrait is frozen into this experience for consistent playback.
                      </div>
                    </div>
                  </div>
                </div>
              </Field>
            )}

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
                    <option key={m} value={m}>
                      {MODE_LABELS[m]}
                    </option>
                  ))}
                </select>
              </Field>

              {!personaLive && (
                <Field label="Audience level">
                  <select
                    value={form.audience_level}
                    onChange={(e) =>
                      patch(
                        "audience_level",
                        e.target.value as PlanAutoForm["audience_level"],
                      )
                    }
                    disabled={submitting}
                    className={INPUT_CLS}
                  >
                    {(Object.keys(LEVEL_LABELS) as PlanAutoForm["audience_level"][]).map((lv) => (
                      <option key={lv} value={lv}>
                        {LEVEL_LABELS[lv]}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
            </div>

            {!personaLive && (
              <Field label="Shape">
                <div className="grid grid-cols-3 gap-2">
                  <NumberPill
                    label="Choices"
                    value={form.branch_count}
                    min={1}
                    max={6}
                    onChange={(n) => patch("branch_count", n)}
                    disabled={submitting}
                  />
                  <NumberPill
                    label="Steps"
                    value={form.depth}
                    min={1}
                    max={4}
                    onChange={(n) => patch("depth", n)}
                    disabled={submitting}
                  />
                  <NumberPill
                    label="Scenes per path"
                    value={form.scenes_per_branch}
                    min={1}
                    max={6}
                    onChange={(n) => patch("scenes_per_branch", n)}
                    disabled={submitting}
                  />
                </div>
                <p className="text-[11px] text-[#777] mt-1.5">
                  About{" "}
                  <span className="text-[#cfd8dc]">
                    {form.branch_count * form.depth * form.scenes_per_branch}
                  </span>{" "}
                  scenes total (before the graph merges overlaps).
                </p>
              </Field>
            )}

            <AdvancedBlock
              open={advancedOpen}
              onToggle={() => setAdvancedOpen((v) => !v)}
              form={form}
              patch={patch}
              disabled={submitting}
              personaLive={personaLive}
            />
          </div>

          {(initial.objective || initial.topic || initial.seed_intents.length > 0) && (
            <div className="mt-6 rounded-lg border border-[#2a2a2a] bg-[#121212]/60 px-4 py-3 text-[11px] leading-relaxed">
              <div className="text-[#cfd8dc] font-medium mb-1">Planner preview</div>
              <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-0.5 text-[#aaa]">
                {initial.objective && (
                  <>
                    <dt>Objective</dt>
                    <dd className="text-[#cfd8dc]">{initial.objective}</dd>
                  </>
                )}
                {initial.topic && (
                  <>
                    <dt>Topic</dt>
                    <dd className="text-[#cfd8dc]">{initial.topic}</dd>
                  </>
                )}
                {initial.success_metric && (
                  <>
                    <dt>Success</dt>
                    <dd className="text-[#cfd8dc]">{initial.success_metric}</dd>
                  </>
                )}
                {initial.seed_intents.length > 0 && (
                  <>
                    <dt>Seeds</dt>
                    <dd className="flex flex-wrap gap-1">
                      {initial.seed_intents.map((s) => (
                        <code
                          key={s}
                          className="text-[#cfd8dc] bg-[#1f1f1f] border border-[#3f3f3f] rounded px-1.5 py-0.5 text-[10px]"
                        >
                          {s}
                        </code>
                      ))}
                    </dd>
                  </>
                )}
              </dl>
            </div>
          )}
        </div>
      </div>

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

      {/*
       * The "Generating scenes…" modal used to render here as a local
       * <GeneratingPanel>. It now lives in <WizardProgressOverlay>
       * mounted at App.tsx — which makes it a global overlay portaled
       * to document.body. That's the fix for the
       * "modal disappears when I switch tabs" bug: when the user
       * navigates from Interactive → Chat mid-generation, this
       * component unmounts (along with its local state) but the
       * module-level wizardProgressStore keeps the SSE running and
       * the global overlay keeps showing on top of the new route.
       */}
    </div>
  );
}

const INPUT_CLS = [
  "w-full bg-[#121212] border border-[#3f3f3f] rounded-md",
  "px-3 py-2 text-sm outline-none",
  "focus:border-[#3ea6ff] focus:ring-1 focus:ring-[#3ea6ff]/50",
  "disabled:opacity-60 disabled:cursor-not-allowed",
].join(" ");

function Field({
  label,
  hint,
  children,
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
  label,
  value,
  min,
  max,
  onChange,
  disabled,
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
        >
          −
        </button>
        <span className="text-lg font-semibold text-[#f1f1f1] tabular-nums">{value}</span>
        <button
          type="button"
          onClick={inc}
          disabled={disabled || value >= max}
          aria-label={`Increase ${label}`}
          className="w-6 h-6 rounded-md bg-white/5 hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed text-[#cfd8dc] text-sm font-medium"
        >
          +
        </button>
      </div>
    </div>
  );
}

function AdvancedBlock({
  open,
  onToggle,
  form,
  patch,
  disabled,
  personaLive,
}: {
  open: boolean;
  onToggle: () => void;
  form: PlanAutoForm;
  patch: <K extends keyof PlanAutoForm>(k: K, v: PlanAutoForm[K]) => void;
  disabled: boolean;
  personaLive: boolean;
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
        {open ? (
          <ChevronUp className="w-4 h-4 text-[#aaa]" aria-hidden />
        ) : (
          <ChevronDown className="w-4 h-4 text-[#aaa]" aria-hidden />
        )}
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
                <option key={v} value={v}>
                  {l} ({v})
                </option>
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

          <Field label="Render media">
            <select
              value={form.render_media_type || (personaLive ? "image" : "video")}
              onChange={(e) => patch("render_media_type", e.target.value as "image" | "video")}
              disabled={disabled}
              className={INPUT_CLS}
            >
              <option value="image">Image</option>
              <option value="video">Video</option>
            </select>
          </Field>
        </div>
      )}
    </section>
  );
}

// Note: _panelTitle / _panelDescription / _stepIndexForPhase used to
// live here. They moved into wizardProgressStore + WizardProgressOverlay
// when progress state was lifted out of this component. The store owns
// step→phase mapping; the overlay owns title/description rendering.

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

function cleanOptional(value?: string) {
  const v = String(value || "").trim();
  return v ? v : undefined;
}