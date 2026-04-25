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

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Check,
  ChevronDown,
  ChevronUp,
  Clock,
  Compass,
  Heart,
  Pencil,
  Sparkles,
  Target,
} from "lucide-react";
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
  // Persona-live default view is the Approve hero; Customize is an
  // inline expansion that reveals the existing fields. Non-persona-
  // live keeps the legacy single-form layout.
  const [customizeOpen, setCustomizeOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Resolve the persona's portrait when the interaction selection
  // didn't include one. Same pattern Step 0 uses (`Step0Prompt.tsx`)
  // — the LS persona cache that feeds these screens doesn't store
  // ``avatar_url`` reliably (App.tsx writers omit it), so we hit
  // ``GET /projects/{id}`` and pull ``persona_appearance.selected_filename``
  // to build a working ``/files/...`` URL. Without this, the persona
  // preview card on the WizardAutoPreview surface kept rendering an
  // empty grey square + the bare label — operators couldn't tell at
  // a glance whose persona they had selected.
  const [resolvedAvatar, setResolvedAvatar] = useState<string>("");
  const [resolvedArchetype, setResolvedArchetype] = useState<string>("");
  // Pulled from the persona project so the Render plan panel can
  // show the right Tier-2 library count (17 SFW, 23 with NSFW).
  const [personaAllowExplicit, setPersonaAllowExplicit] = useState<boolean>(false);
  const [libraryAlreadyBuilt, setLibraryAlreadyBuilt] = useState<number>(0);

  useEffect(() => {
    const pid = interaction.persona_project_id;
    if (!pid) return;
    const ctrl = new AbortController();
    const base = backendUrl.replace(/\/+$/, "");
    fetch(`${base}/projects/${encodeURIComponent(pid)}`, {
      signal: ctrl.signal,
      credentials: "include",
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (!body || !body.ok || !body.project) return;
        const project = body.project as {
          persona_appearance?: {
            selected_filename?: unknown;
            asset_library?: Record<string, unknown>;
          };
          persona_agent?: {
            persona_class?: unknown;
            response_style?: { tone?: unknown };
            safety?: { allow_explicit?: unknown };
          };
        };
        const filename = String(
          project.persona_appearance?.selected_filename || "",
        ).trim();
        if (filename && !interaction.persona_avatar_url) {
          setResolvedAvatar(`${base}/files/${filename}`);
        }
        // Allow_explicit drives the NSFW Tier 2 row count (+6 specs).
        setPersonaAllowExplicit(
          Boolean(project.persona_agent?.safety?.allow_explicit),
        );
        // Already-built library count — Phase 3 build is idempotent
        // so this many specs will SKIP rendering on this run. Lets
        // the Render plan show "23 planned · 11 already cached → 12
        // new renders this run" instead of misleading the operator
        // about how long the wizard will take.
        const lib = project.persona_appearance?.asset_library;
        if (lib && typeof lib === "object") {
          setLibraryAlreadyBuilt(Object.keys(lib).length);
        }
        const archetype =
          String(project.persona_agent?.persona_class || "").trim() ||
          String(project.persona_agent?.response_style?.tone || "").trim();
        if (archetype) setResolvedArchetype(archetype);
      })
      .catch(() => { /* swallow — card falls back to monogram */ });
    return () => ctrl.abort();
  }, [backendUrl, interaction.persona_project_id, interaction.persona_avatar_url]);

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

          <h1 className="text-xl font-semibold text-[#f1f1f1] flex items-center gap-2">
            {personaLive && (
              <Sparkles className="w-5 h-5 text-[#c4b5fd]" aria-hidden />
            )}
            {personaLive ? "Your experience is ready" : "Review your project"}
          </h1>
          <p className="text-sm text-[#aaa] mt-1.5 leading-relaxed">
            {personaLive ? (
              <>
                AI shaped{" "}
                <span className="text-[#cfd8dc]">
                  "{originalIdea.slice(0, 80)}
                  {originalIdea.length > 80 ? "…" : ""}"
                </span>{" "}
                into a persona-centered setup. Approve to launch, or customize first.
              </>
            ) : (
              <>
                The AI turned{" "}
                <span className="text-[#cfd8dc]">
                  "{originalIdea.slice(0, 80)}
                  {originalIdea.length > 80 ? "…" : ""}"
                </span>
                {" "}into the draft below. Edit anything you'd like before creating.
              </>
            )}
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
            {personaLive ? (
              <ApproveHero
                form={form}
                initial={initial}
                avatarUrl={interaction.persona_avatar_url || resolvedAvatar}
                personaLabel={interaction.persona_label || "Selected persona"}
                archetype={resolvedArchetype || "Persona companion"}
                disabled={submitting}
                onTitleChange={(v) => patch("title", v)}
              />
            ) : (
              <StandardApproveHero
                form={form}
                initial={initial}
                disabled={submitting}
                onTitleChange={(v) => patch("title", v)}
              />
            )}

            {!customizeOpen && (
              <div className="flex justify-center">
                <button
                  type="button"
                  onClick={() => setCustomizeOpen(true)}
                  disabled={submitting}
                  className="text-xs font-medium text-[#9f7fd1] hover:text-[#c4b5fd] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] rounded px-2 py-1 disabled:opacity-50"
                >
                  Customize (optional)
                </button>
              </div>
            )}

            {customizeOpen && personaLive && (
              <CustomizePanel
                form={form}
                initial={initial}
                patch={patch}
                disabled={submitting}
                advancedOpen={advancedOpen}
                onToggleAdvanced={() => setAdvancedOpen((v) => !v)}
                renderEnabled={renderEnabled}
                personaAllowExplicit={personaAllowExplicit}
                libraryAlreadyBuilt={libraryAlreadyBuilt}
                onClose={() => setCustomizeOpen(false)}
              />
            )}

            {customizeOpen && !personaLive && (
              <StandardCustomizePanel
                form={form}
                initial={initial}
                patch={patch}
                disabled={submitting}
                advancedOpen={advancedOpen}
                onToggleAdvanced={() => setAdvancedOpen((v) => !v)}
                renderEnabled={renderEnabled}
                onClose={() => setCustomizeOpen(false)}
              />
            )}
          </div>
          {/* Planner preview moved into the Customize panel for both
              flows — it's noise on the default Approve view. */}
        </div>
      </div>

      {/*
       * Render plan panel — shown right above the Create CTA so the
       * operator can see exactly how many GPU renders this wizard
       * run will fire before clicking. Three numbers:
       *
       *   * Scene graph     — fixed at 7 for Persona Live (intro +
       *                       4 reactions + followup + ending);
       *                       branch_count × depth × scenes_per_branch
       *                       for Standard.
       *   * Persona library — 17 (SFW) or 23 (NSFW + allow_explicit)
       *                       at Tier 2. Persona Live only.
       *   * Already cached  — library rows that exist on the persona
       *                       from a prior run; idempotent skip.
       *
       * "Total this run" subtracts already-cached so the wizard
       * progress bar lines up with the count shown here.
       */}
      {/* RenderPlanPanel now lives inside the Customize panel for
          both flows. The default Approve view is render-cost-free
          to keep the 80% path zero-noise. */}

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

// ── Render plan constants ────────────────────────────────────────────────
//
// Mirrors the persona_asset_library Tier 2 manifest. Kept in sync with
// ``backend/app/interactive/playback/persona_asset_library.py`` —
// changing the manifest there should bump these counts here too.
//
// Tier 2 SFW: 9 (Tier 1 base) + 6 (extra outfits / poses / cameras)
//             + 2 (outfit×expression composites) = 17
// Tier 2 NSFW: +6 (2 expr at Tier 1, 2 pose at Tier 2,
//                 2 outfit at Tier 2) = 23 total when allow_explicit
const PERSONA_LIBRARY_TIER2_SFW_COUNT = 17;
const PERSONA_LIBRARY_TIER2_NSFW_COUNT = 23;
// Persona Live's scene graph is deterministic (lina_intro_start +
// 4 reaction scenes + lina_followup + lina_epilogue = 7). See
// ``backend/app/interactive/planner/autogen_llm._persona_live_graph``.
const PERSONA_LIVE_SCENE_COUNT = 7;


function RenderPlanPanel({
  personaLive,
  renderEnabled,
  sceneCount,
  libraryPlanned,
  libraryAlreadyBuilt,
}: {
  personaLive: boolean;
  renderEnabled: boolean;
  sceneCount: number;
  libraryPlanned: number;
  libraryAlreadyBuilt: number;
}) {
  // Library renders use the persona portrait as anchor, so for non-
  // Persona-Live projects there's no library pass at all.
  const libraryToBuild = personaLive
    ? Math.max(0, libraryPlanned - libraryAlreadyBuilt)
    : 0;
  // Scene-graph renders only fire when the playback render flag is
  // on AND the project type uses scene assets. Persona Live skips
  // scene rendering entirely (the live runtime serves library
  // images, not the scene tree).
  const sceneRendersThisRun = personaLive
    ? 0
    : (renderEnabled ? sceneCount : 0);
  const totalThisRun = sceneRendersThisRun + libraryToBuild;

  return (
    <div className="shrink-0 border-t border-[#2a2a2a] bg-[#121212]/60">
      <div className="max-w-2xl mx-auto px-6 py-3">
        <div className="text-[11px] uppercase tracking-wider text-[#9f7fd1] mb-2">
          Render plan
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
          <PlanStat
            label="Scene graph"
            value={sceneCount}
            unit={sceneCount === 1 ? "scene" : "scenes"}
            hint={
              personaLive
                ? "Authored spine — the live runtime doesn't traverse this."
                : (renderEnabled
                    ? "All rendered as images / video clips."
                    : "Scene render is OFF — no GPU work this pass.")
            }
          />
          {personaLive && (
            <PlanStat
              label="Persona library"
              value={libraryPlanned}
              unit={libraryPlanned === 1 ? "image" : "images"}
              hint={
                libraryAlreadyBuilt > 0
                  ? `${libraryAlreadyBuilt} already cached → ${libraryToBuild} new this run.`
                  : "Pre-rendered once per persona; reused on every session."
              }
            />
          )}
          <PlanStat
            label="Total this run"
            value={totalThisRun}
            unit={totalThisRun === 1 ? "render" : "renders"}
            emphasised
            hint={
              totalThisRun === 0
                ? "No renders queued — wizard finishes in seconds."
                : "Each render typically takes 3–8 s on a capable GPU."
            }
          />
        </div>
      </div>
    </div>
  );
}


// ── Persona-live layered preview ────────────────────────────────────────
//
// Three layers mapped to the spec:
//   1. ApproveHero       — the default Approve view (1-click create)
//   2. CustomizePanel    — inline expansion (mode, vibe, story bits,
//                          generation preview, advanced)
//   3. (deferred)        — Edit story details lives off Customize once
//                          the planner emits scene drafts pre-create.
//
// Non-persona-live projects keep the legacy single-form layout above.

const SEED_TO_STAGE: Record<string, string> = {
  greeting: "Curiosity",
  flirt: "Flirt",
  compliment: "Connection",
  tease: "Playfulness",
  ask_personal: "Intimacy",
  followup: "Reflection",
  learn: "Discovery",
  question: "Discovery",
  challenge: "Tension",
};

function titleCase(s: string): string {
  return s
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function journeyFromSeeds(seeds: string[]): string[] {
  if (!seeds || seeds.length === 0) return [];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of seeds) {
    const key = String(raw || "").trim().toLowerCase();
    if (!key) continue;
    const stage = SEED_TO_STAGE[key] || titleCase(key);
    if (!seen.has(stage)) {
      seen.add(stage);
      out.push(stage);
    }
  }
  return out;
}

type IconType = React.ComponentType<React.SVGProps<SVGSVGElement>>;

function SummaryRow({
  icon: Icon,
  label,
  value,
}: {
  icon: IconType;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-start gap-2.5 text-sm">
      <Icon className="w-4 h-4 text-[#9f7fd1] mt-0.5 flex-shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 leading-relaxed">
        <span className="text-[#9f7fd1] font-medium">{label}:</span>{" "}
        <span className="text-[#cfd8dc]">{value}</span>
      </div>
    </div>
  );
}

function PersonaHeroCard({
  avatarUrl,
  personaLabel,
  archetype,
}: {
  avatarUrl: string;
  personaLabel: string;
  archetype: string;
}) {
  return (
    <div
      className={[
        "rounded-lg border border-[#3a2a58]",
        "bg-gradient-to-br from-[#130f1f] to-[#1a0f24]",
        "p-4 flex flex-col sm:flex-row gap-4",
        "shadow-[0_0_24px_-12px_rgba(139,92,246,0.4)]",
      ].join(" ")}
    >
      {avatarUrl ? (
        <img
          src={avatarUrl}
          alt={personaLabel}
          className={[
            "w-32 h-32 rounded-md object-cover object-top",
            "border-2 border-[#51347f]",
            "shadow-md flex-shrink-0",
            "self-center sm:self-start bg-black",
          ].join(" ")}
        />
      ) : (
        <div
          className={[
            "w-32 h-32 rounded-md bg-[#24173a]",
            "border-2 border-[#51347f]",
            "flex-shrink-0 self-center sm:self-start",
            "flex items-center justify-center",
            "text-[#7c3aed] text-2xl font-semibold",
          ].join(" ")}
          aria-label="No portrait available"
        >
          {(personaLabel || "?").trim().charAt(0).toUpperCase()}
        </div>
      )}
      <div className="min-w-0 flex flex-col justify-center gap-1">
        <div className="text-[11px] uppercase tracking-wider text-[#9f7fd1]">
          Persona
        </div>
        <div className="text-base font-medium text-[#f1f1f1] truncate">
          {personaLabel}
        </div>
        <div className="text-xs text-[#b59ed9] truncate">{archetype}</div>
        <div className="text-[11px] text-[#7c3aed] mt-2">
          Portrait is frozen into this experience for consistent playback.
        </div>
      </div>
    </div>
  );
}

function ApproveHero({
  form,
  initial,
  avatarUrl,
  personaLabel,
  archetype,
  disabled,
  onTitleChange,
}: {
  form: PlanAutoForm;
  initial: PlanAutoResult;
  avatarUrl: string;
  personaLabel: string;
  archetype: string;
  disabled: boolean;
  onTitleChange: (next: string) => void;
}) {
  const journey = journeyFromSeeds(initial.seed_intents);
  const modeLabel = MODE_LABELS[form.experience_mode] || form.experience_mode;
  const goal = (initial.objective || "").trim()
    || "Build rapport through a branching conversation";
  const vibe = (form.prompt || "").trim()
    || "Open, curious, easygoing";

  return (
    <div className="flex flex-col gap-5">
      {/* Title — looks like a heading, edits inline. Kept editable
          (rather than click-to-edit) so the field is discoverable
          without a hover hint. */}
      <div className="flex items-center gap-2">
        <Pencil
          className="w-4 h-4 text-[#777] flex-shrink-0"
          aria-hidden
        />
        <input
          type="text"
          value={form.title}
          onChange={(e) => onTitleChange(e.target.value)}
          maxLength={80}
          disabled={disabled}
          placeholder="Name your experience"
          aria-label="Experience title"
          className={[
            "flex-1 bg-transparent border-b border-transparent",
            "hover:border-[#3f3f3f] focus:border-[#3ea6ff] focus:outline-none",
            "text-xl font-semibold text-[#f1f1f1] py-1",
            "disabled:opacity-60 disabled:cursor-not-allowed",
            "placeholder:text-[#555]",
          ].join(" ")}
        />
      </div>

      <PersonaHeroCard
        avatarUrl={avatarUrl}
        personaLabel={personaLabel}
        archetype={archetype}
      />

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-5 gap-y-2.5">
        <SummaryRow icon={Target} label="Goal" value={goal} />
        <SummaryRow icon={Heart} label="Vibe" value={vibe} />
        <SummaryRow icon={Sparkles} label="Mode" value={modeLabel} />
        <SummaryRow icon={Clock} label="Length" value="~5–7 min experience" />
      </div>

      {journey.length > 0 && (
        <div className="rounded-lg border border-[#2a2a2a] bg-[#121212]/60 px-4 py-3">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-[#9f7fd1] mb-2">
            <Compass className="w-3.5 h-3.5" aria-hidden />
            Emotional journey
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-[#cfd8dc]">
            {journey.map((stage, i) => (
              <React.Fragment key={`${stage}-${i}`}>
                {i > 0 && (
                  <span className="text-[#555]" aria-hidden>
                    →
                  </span>
                )}
                <span>{stage}</span>
              </React.Fragment>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CustomizePanel({
  form,
  initial,
  patch,
  disabled,
  advancedOpen,
  onToggleAdvanced,
  renderEnabled,
  personaAllowExplicit,
  libraryAlreadyBuilt,
  onClose,
}: {
  form: PlanAutoForm;
  initial: PlanAutoResult;
  patch: <K extends keyof PlanAutoForm>(k: K, v: PlanAutoForm[K]) => void;
  disabled: boolean;
  advancedOpen: boolean;
  onToggleAdvanced: () => void;
  renderEnabled: boolean;
  personaAllowExplicit: boolean;
  libraryAlreadyBuilt: number;
  onClose: () => void;
}) {
  const libraryPlanned = personaAllowExplicit
    ? PERSONA_LIBRARY_TIER2_NSFW_COUNT
    : PERSONA_LIBRARY_TIER2_SFW_COUNT;

  return (
    <section
      className="rounded-lg border border-[#2a2a2a] bg-[#121212]/60 px-4 py-4 flex flex-col gap-4"
      aria-label="Customize your experience"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-medium text-[#f1f1f1]">
          <Sparkles className="w-4 h-4 text-[#c4b5fd]" aria-hidden />
          Customize your experience
        </div>
        <button
          type="button"
          onClick={onClose}
          disabled={disabled}
          className="text-[11px] text-[#aaa] hover:text-[#f1f1f1] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] rounded px-1 py-0.5 disabled:opacity-50"
        >
          Hide
        </button>
      </div>

      <Field label="Mode">
        <select
          value={form.experience_mode}
          onChange={(e) => {
            const next = e.target.value as ExperienceMode;
            patch("experience_mode", next);
            patch("policy_profile_id", next);
          }}
          disabled={disabled}
          className={INPUT_CLS}
        >
          {(Object.keys(MODE_LABELS) as ExperienceMode[]).map((m) => (
            <option key={m} value={m}>
              {MODE_LABELS[m]}
            </option>
          ))}
        </select>
      </Field>

      <Field
        label="Session vibe"
        hint="Short brief the planner uses to flavor the conversation."
      >
        <textarea
          rows={3}
          value={form.prompt}
          onChange={(e) => patch("prompt", e.target.value)}
          disabled={disabled}
          className={`${INPUT_CLS} resize-y leading-relaxed`}
        />
      </Field>

      {initial.seed_intents.length > 0 && (
        <Field
          label="Story elements"
          hint="Seeds the planner uses for branches. Edit raw seeds in Advanced."
        >
          <div className="flex flex-wrap gap-1.5">
            {initial.seed_intents.map((s) => (
              <span
                key={s}
                className="inline-flex items-center gap-1 rounded-full bg-[#1f1f1f] border border-[#3f3f3f] text-[#cfd8dc] text-[11px] font-medium px-2 py-0.5"
              >
                <Check className="w-3 h-3 text-[#9f7fd1]" aria-hidden />
                {titleCase(s)}
              </span>
            ))}
          </div>
        </Field>
      )}

      <Field label="Generation preview">
        <RenderPlanPanel
          personaLive={true}
          renderEnabled={renderEnabled}
          sceneCount={PERSONA_LIVE_SCENE_COUNT}
          libraryPlanned={libraryPlanned}
          libraryAlreadyBuilt={libraryAlreadyBuilt}
        />
      </Field>

      {(initial.objective || initial.topic || initial.success_metric) && (
        <div className="rounded-md border border-[#2a2a2a] bg-[#0f0f0f]/60 px-3 py-2.5 text-[11px] leading-relaxed">
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
          </dl>
        </div>
      )}

      <AdvancedBlock
        open={advancedOpen}
        onToggle={onToggleAdvanced}
        form={form}
        patch={patch}
        disabled={disabled}
        personaLive={true}
      />
    </section>
  );
}

function PlanStat({
  label,
  value,
  unit,
  hint,
  emphasised,
}: {
  label: string;
  value: number;
  unit: string;
  hint?: string;
  emphasised?: boolean;
}) {
  return (
    <div
      className={[
        "rounded-md border px-3 py-2",
        emphasised
          ? "border-[#8b5cf6]/50 bg-[#8b5cf6]/10"
          : "border-[#2a2a2a] bg-[#0f0f0f]/60",
      ].join(" ")}
    >
      <div className="text-[10px] uppercase tracking-wider text-[#777]">
        {label}
      </div>
      <div className="flex items-baseline gap-1.5 mt-0.5">
        <span
          className={[
            "font-semibold",
            emphasised ? "text-[#c4b5fd] text-lg" : "text-[#f1f1f1] text-base",
          ].join(" ")}
        >
          {value}
        </span>
        <span className="text-[11px] text-[#aaa]">{unit}</span>
      </div>
      {hint && (
        <div className="text-[10px] text-[#777] mt-1 leading-snug">
          {hint}
        </div>
      )}
    </div>
  );
}

// ── Standard interactive layered preview ────────────────────────────────
//
// Same Approve / Customize / (deferred) Edit-flow split as persona-live,
// but the framing is "structure of an interactive story" instead of a
// single emotional arc. The Shape knobs (branch_count, depth,
// scenes_per_branch) are mapped to friendly preset radios in Customize
// — operators rarely understand "3 × 2 × 2", they understand
// "Standard choices · Medium length · Balanced branching".

type ChoicesPreset = "simple" | "standard" | "complex";
type LengthPreset = "short" | "medium" | "long";
type DepthPreset = "light" | "balanced" | "deep";

const CHOICES_VALUES: Record<ChoicesPreset, number> = {
  simple: 2,
  standard: 3,
  complex: 5,
};
const LENGTH_VALUES: Record<LengthPreset, number> = {
  short: 1,
  medium: 2,
  long: 4,
};
const DEPTH_VALUES: Record<DepthPreset, number> = {
  light: 1,
  balanced: 2,
  deep: 4,
};

const CHOICES_LABELS: Record<ChoicesPreset, string> = {
  simple: "Simple (2 choices)",
  standard: "Standard (3–4 choices)",
  complex: "Complex (5+ choices)",
};
const LENGTH_LABELS: Record<LengthPreset, string> = {
  short: "Short (4–5 scenes)",
  medium: "Medium (6–8 scenes)",
  long: "Long (10+ scenes)",
};
const DEPTH_LABELS: Record<DepthPreset, string> = {
  light: "Light branching",
  balanced: "Balanced",
  deep: "Deep branching",
};

function inferChoicesPreset(branch: number): ChoicesPreset {
  if (branch <= 2) return "simple";
  if (branch <= 4) return "standard";
  return "complex";
}
function inferLengthPreset(scenes_per_branch: number): LengthPreset {
  if (scenes_per_branch <= 1) return "short";
  if (scenes_per_branch <= 3) return "medium";
  return "long";
}
function inferDepthPreset(depth: number): DepthPreset {
  if (depth <= 1) return "light";
  if (depth <= 2) return "balanced";
  return "deep";
}

function estimateSceneTotal(form: PlanAutoForm): number {
  return Math.max(1, form.branch_count * form.depth * form.scenes_per_branch);
}

function estimatePlaytime(scenes: number): string {
  // Rough: ~1 minute of reading + choice per scene. Range gives the
  // viewer a feel without false precision.
  const lo = Math.max(2, Math.round(scenes * 0.75));
  const hi = Math.max(lo + 1, Math.round(scenes * 1.1));
  return `~${lo}–${hi} min interactive experience`;
}

function StandardApproveHero({
  form,
  initial,
  disabled,
  onTitleChange,
}: {
  form: PlanAutoForm;
  initial: PlanAutoResult;
  disabled: boolean;
  onTitleChange: (next: string) => void;
}) {
  const totalScenes = estimateSceneTotal(form);
  const modeLabel = MODE_LABELS[form.experience_mode] || form.experience_mode;
  const levelLabel = LEVEL_LABELS[form.audience_level] || form.audience_level;
  const goal = (initial.objective || "").trim()
    || "Build rapport through choices";
  const vibe = (form.prompt || "").trim()
    || "An interactive scene-by-scene story";
  const journey = journeyFromSeeds(initial.seed_intents);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex items-center gap-2">
        <Pencil
          className="w-4 h-4 text-[#777] flex-shrink-0"
          aria-hidden
        />
        <input
          type="text"
          value={form.title}
          onChange={(e) => onTitleChange(e.target.value)}
          maxLength={80}
          disabled={disabled}
          placeholder="Name your project"
          aria-label="Project title"
          className={[
            "flex-1 bg-transparent border-b border-transparent",
            "hover:border-[#3f3f3f] focus:border-[#3ea6ff] focus:outline-none",
            "text-xl font-semibold text-[#f1f1f1] py-1",
            "disabled:opacity-60 disabled:cursor-not-allowed",
            "placeholder:text-[#555]",
          ].join(" ")}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-5 gap-y-2.5">
        <SummaryRow
          icon={Sparkles}
          label="Mode"
          value={`${modeLabel} · ${levelLabel}`}
        />
        <SummaryRow
          icon={Clock}
          label="Length"
          value={estimatePlaytime(totalScenes)}
        />
        <SummaryRow icon={Target} label="Goal" value={goal} />
        <SummaryRow icon={Heart} label="What players experience" value={vibe} />
      </div>

      <div className="rounded-lg border border-[#2a2a2a] bg-[#121212]/60 px-4 py-3">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-[#9f7fd1] mb-2">
          <Compass className="w-3.5 h-3.5" aria-hidden />
          Structure
        </div>
        <div className="text-sm text-[#cfd8dc]">
          ~{totalScenes} scene{totalScenes === 1 ? "" : "s"} ·{" "}
          {form.branch_count} choice{form.branch_count === 1 ? "" : "s"} per step ·{" "}
          {form.depth}-step path{form.depth === 1 ? "" : "s"}
        </div>
        {journey.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[#cfd8dc]">
            <span className="text-[#9f7fd1]">Players will:</span>
            {journey.map((stage, i) => (
              <React.Fragment key={`${stage}-${i}`}>
                {i > 0 && (
                  <span className="text-[#555]" aria-hidden>
                    →
                  </span>
                )}
                <span>{stage}</span>
              </React.Fragment>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PresetRadio<T extends string>({
  legend,
  value,
  options,
  labels,
  onChange,
  disabled,
}: {
  legend: string;
  value: T;
  options: T[];
  labels: Record<T, string>;
  onChange: (next: T) => void;
  disabled: boolean;
}) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="text-xs font-medium text-[#cfd8dc]">{legend}</legend>
      <div className="flex flex-col gap-1">
        {options.map((opt) => {
          const selected = value === opt;
          return (
            <label
              key={opt}
              className={[
                "flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-sm cursor-pointer",
                "transition-colors",
                selected
                  ? "border-[#8b5cf6]/60 bg-[#8b5cf6]/10 text-[#f1f1f1]"
                  : "border-[#2a2a2a] bg-[#0f0f0f]/60 text-[#cfd8dc] hover:border-[#3f3f3f]",
                disabled ? "opacity-60 cursor-not-allowed" : "",
              ].join(" ")}
            >
              <input
                type="radio"
                name={legend}
                value={opt}
                checked={selected}
                onChange={() => onChange(opt)}
                disabled={disabled}
                className="accent-[#8b5cf6]"
              />
              <span>{labels[opt]}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

function StoryFlowPreview({
  form,
  initial,
}: {
  form: PlanAutoForm;
  initial: PlanAutoResult;
}) {
  // Procedural outline derived from the planner's depth + seeds. We
  // don't have actual scene drafts pre-create, so the outline names
  // generic phases ("Opening", "Reaction", "Connection builds") and
  // pulls choices from initial.seed_intents. This gives the operator a
  // human-readable feel for the branching without surfacing the graph.
  const sceneNames = [
    "Opening scene",
    "Reaction",
    "Connection builds",
    "Turning point",
    "Resolution",
  ];
  const choices = initial.seed_intents.length > 0
    ? initial.seed_intents.slice(0, form.branch_count)
    : ["Be playful", "Be sincere", "Stay reserved"].slice(0, form.branch_count);
  const stepCount = Math.max(1, Math.min(form.depth, sceneNames.length - 1));

  return (
    <div className="rounded-md border border-[#2a2a2a] bg-[#0f0f0f]/60 px-3 py-3">
      <div className="text-[11px] uppercase tracking-wider text-[#9f7fd1] mb-2">
        Story flow preview
      </div>
      <ol className="flex flex-col gap-1 text-xs text-[#cfd8dc] leading-relaxed">
        <li className="text-[#777] uppercase tracking-wider text-[10px]">
          Start
        </li>
        {Array.from({ length: stepCount }).map((_, idx) => (
          <React.Fragment key={idx}>
            <li className="text-[#555]" aria-hidden>↓</li>
            <li>
              <span className="text-[#9f7fd1]">Scene {idx + 1}</span> —{" "}
              {sceneNames[idx] || `Beat ${idx + 1}`}
            </li>
            <li className="text-[#555]" aria-hidden>↓</li>
            <li>
              <span className="text-[#9f7fd1]">Choose:</span>
              <ul className="mt-0.5 ml-3 flex flex-col gap-0.5">
                {choices.map((c) => (
                  <li key={`${idx}-${c}`} className="text-[#cfd8dc]">
                    • {titleCase(c)}
                  </li>
                ))}
              </ul>
            </li>
          </React.Fragment>
        ))}
        <li className="text-[#555]" aria-hidden>↓</li>
        <li className="text-[#777] uppercase tracking-wider text-[10px]">
          Ending
        </li>
      </ol>
    </div>
  );
}

function StandardCustomizePanel({
  form,
  initial,
  patch,
  disabled,
  advancedOpen,
  onToggleAdvanced,
  renderEnabled,
  onClose,
}: {
  form: PlanAutoForm;
  initial: PlanAutoResult;
  patch: <K extends keyof PlanAutoForm>(k: K, v: PlanAutoForm[K]) => void;
  disabled: boolean;
  advancedOpen: boolean;
  onToggleAdvanced: () => void;
  renderEnabled: boolean;
  onClose: () => void;
}) {
  const choicesPreset = inferChoicesPreset(form.branch_count);
  const lengthPreset = inferLengthPreset(form.scenes_per_branch);
  const depthPreset = inferDepthPreset(form.depth);

  return (
    <section
      className="rounded-lg border border-[#2a2a2a] bg-[#121212]/60 px-4 py-4 flex flex-col gap-4"
      aria-label="Customize your project"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-medium text-[#f1f1f1]">
          <Sparkles className="w-4 h-4 text-[#c4b5fd]" aria-hidden />
          Customize your project
        </div>
        <button
          type="button"
          onClick={onClose}
          disabled={disabled}
          className="text-[11px] text-[#aaa] hover:text-[#f1f1f1] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] rounded px-1 py-0.5 disabled:opacity-50"
        >
          Hide
        </button>
      </div>

      <div className="flex flex-col gap-3">
        <div className="text-[11px] uppercase tracking-wider text-[#9f7fd1]">
          Title & concept
        </div>
        <Field label="Title">
          <input
            type="text"
            value={form.title}
            onChange={(e) => patch("title", e.target.value)}
            maxLength={80}
            disabled={disabled}
            className={INPUT_CLS}
          />
        </Field>
        <Field
          label="Concept"
          hint="Short brief the planner uses as the story seed."
        >
          <textarea
            rows={3}
            value={form.prompt}
            onChange={(e) => patch("prompt", e.target.value)}
            disabled={disabled}
            className={`${INPUT_CLS} resize-y leading-relaxed`}
          />
        </Field>
      </div>

      <div className="flex flex-col gap-3">
        <div className="text-[11px] uppercase tracking-wider text-[#9f7fd1]">
          Audience & mode
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Mode">
            <select
              value={form.experience_mode}
              onChange={(e) => {
                const next = e.target.value as ExperienceMode;
                patch("experience_mode", next);
                patch("policy_profile_id", next);
              }}
              disabled={disabled}
              className={INPUT_CLS}
            >
              {(Object.keys(MODE_LABELS) as ExperienceMode[]).map((m) => (
                <option key={m} value={m}>
                  {MODE_LABELS[m]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Audience level">
            <select
              value={form.audience_level}
              onChange={(e) =>
                patch(
                  "audience_level",
                  e.target.value as PlanAutoForm["audience_level"],
                )
              }
              disabled={disabled}
              className={INPUT_CLS}
            >
              {(Object.keys(LEVEL_LABELS) as PlanAutoForm["audience_level"][]).map((lv) => (
                <option key={lv} value={lv}>
                  {LEVEL_LABELS[lv]}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <div className="text-[11px] uppercase tracking-wider text-[#9f7fd1]">
          Experience structure
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <PresetRadio<ChoicesPreset>
            legend="Choices per step"
            value={choicesPreset}
            options={["simple", "standard", "complex"]}
            labels={CHOICES_LABELS}
            onChange={(next) => patch("branch_count", CHOICES_VALUES[next])}
            disabled={disabled}
          />
          <PresetRadio<LengthPreset>
            legend="Story length"
            value={lengthPreset}
            options={["short", "medium", "long"]}
            labels={LENGTH_LABELS}
            onChange={(next) => patch("scenes_per_branch", LENGTH_VALUES[next])}
            disabled={disabled}
          />
          <PresetRadio<DepthPreset>
            legend="Path depth"
            value={depthPreset}
            options={["light", "balanced", "deep"]}
            labels={DEPTH_LABELS}
            onChange={(next) => patch("depth", DEPTH_VALUES[next])}
            disabled={disabled}
          />
        </div>
        <p className="text-[11px] text-[#777]">
          About{" "}
          <span className="text-[#cfd8dc]">{estimateSceneTotal(form)}</span>{" "}
          scenes total (the graph merges overlapping branches).
        </p>
      </div>

      <StoryFlowPreview form={form} initial={initial} />

      {initial.seed_intents.length > 0 && (
        <Field
          label="Player interactions"
          hint="Action types the planner can use. Edit raw seeds in Advanced."
        >
          <div className="flex flex-wrap gap-1.5">
            {initial.seed_intents.map((s) => (
              <span
                key={s}
                className="inline-flex items-center gap-1 rounded-full bg-[#1f1f1f] border border-[#3f3f3f] text-[#cfd8dc] text-[11px] font-medium px-2 py-0.5"
              >
                <Check className="w-3 h-3 text-[#9f7fd1]" aria-hidden />
                {titleCase(s)}
              </span>
            ))}
          </div>
        </Field>
      )}

      <Field label="Render plan">
        <RenderPlanPanel
          personaLive={false}
          renderEnabled={renderEnabled}
          sceneCount={estimateSceneTotal(form)}
          libraryPlanned={0}
          libraryAlreadyBuilt={0}
        />
      </Field>

      {(initial.objective || initial.topic || initial.success_metric) && (
        <div className="rounded-md border border-[#2a2a2a] bg-[#0f0f0f]/60 px-3 py-2.5 text-[11px] leading-relaxed">
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
          </dl>
        </div>
      )}

      <AdvancedBlock
        open={advancedOpen}
        onToggle={onToggleAdvanced}
        form={form}
        patch={patch}
        disabled={disabled}
        personaLive={false}
      />
    </section>
  );
}
