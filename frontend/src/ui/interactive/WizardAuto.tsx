/**
 * WizardAuto — one-box entry for the AI-first project wizard.
 *
 * Replaces the 5-step form for new users. They type a single
 * sentence, hit 'Generate project', and the LLM populates every
 * field the old wizard asked for individually. The enterprise
 * waiting panel covers the input while the AI is thinking, then
 * the parent swaps this component for <WizardAutoPreview /> with
 * the pre-filled form.
 *
 * Flow:
 *
 *    [ sentence input ]
 *         ↓  Generate project
 *    [ GeneratingPanel steps: Planning → Ready ]
 *         ↓  PlanAutoResult
 *    onPlanned(result)
 *
 * Failure paths:
 *   - Empty / whitespace idea   → button disabled, no request
 *   - Backend 4xx               → inline error banner + retry
 *   - Network / LLM down        → backend's heuristic fallback
 *                                 still returns 200; result.source
 *                                 is 'heuristic' so the preview
 *                                 can quietly label the origin
 *
 * Power users can reveal the classic 5-step form via the
 * 'Advanced settings' affordance — wired in AUTO-9 at the
 * InteractiveHost level so one component handles both modes.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Sparkles, Users, Wand2 } from "lucide-react";
import { createInteractiveApi } from "./api";
import type { PlanAutoResult } from "./types";
import { InteractiveApiError } from "./types";
import { ErrorBanner, PrimaryButton } from "./ui";
import { GeneratingPanel } from "./GeneratingPanel";
import { LS_PERSONA_CACHE } from "../voice/personalityGating";
import { resolveBackendUrl } from "../lib/backendUrl";


const IDEA_PLACEHOLDER = "train new sales reps on pricing tiers";

const AI_STEPS = [
  { label: "Understanding your idea" },
  { label: "Picking mode + audience" },
  { label: "Drafting project shape" },
  { label: "Ready to review" },
];


/** Interaction mode + optional persona link, carried alongside the
 *  PlanAutoResult when the user moves from WizardAuto to Preview. */
export interface AutoInteractionSelection {
  interaction_type: "standard_project" | "persona_live_play";
  persona_project_id?: string;
  persona_label?: string;
  /**
   * Which scene-render pipeline the player uses:
   *   "video" — full Animate/SVD clips (default)
   *   "image" — still frames (fast feasibility path)
   */
  render_media_type?: "video" | "image";
}

export interface WizardAutoProps {
  backendUrl: string;
  apiKey?: string;
  /** Called when the LLM / heuristic returns a pre-filled form.
   *  The parent transitions to the editable preview step. */
  onPlanned: (
    result: PlanAutoResult,
    idea: string,
    interaction: AutoInteractionSelection,
  ) => void;
  /** Called when the user asks for the classic 5-step wizard. */
  onSwitchToAdvanced: () => void;
  /** Called when the user cancels / leaves the wizard. */
  onCancel: () => void;
}

export function WizardAuto({
  backendUrl, apiKey, onPlanned, onSwitchToAdvanced, onCancel,
}: WizardAutoProps) {
  const api = useMemo(
    () => createInteractiveApi(backendUrl, apiKey),
    [backendUrl, apiKey],
  );

  const [idea, setIdea] = useState("");
  const [generating, setGenerating] = useState(false);
  const [step, setStep] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Interaction type — defaults to the standard path. 'persona_live_play'
  // unlocks the persona selector and gates generation on picking one.
  const [interactionType, setInteractionType] =
    useState<"standard_project" | "persona_live_play">("standard_project");
  const [personaId, setPersonaId] = useState("");
  const [personaLabel, setPersonaLabel] = useState("");
  // Image vs video scene render. Orthogonal to interactionType —
  // both persona and standard projects can run either pipeline;
  // image mode is the feasibility path for low-VRAM setups.
  const [renderMediaType, setRenderMediaType] =
    useState<"video" | "image">("video");

  // Persona dropdown sources, merged on id:
  //
  //   1. ``LS_PERSONA_CACHE`` — cheap synchronous read, populated by
  //      Voice / Session Hub when the user enters a persona there.
  //      Lets the dropdown render something on first paint.
  //
  //   2. ``GET /projects`` filtered to ``project_type === "persona"``
  //      — the AUTHORITATIVE list. Without this fallback, users who
  //      created personas via the main Projects workspace but never
  //      opened them in Voice mode saw "No personas yet." here even
  //      though their personas were visible everywhere else.
  //
  // Mirrors the Step0Prompt loader so the one-box wizard and the
  // classic 5-step wizard agree on which personas are selectable.
  const cacheOptions = useMemo(() => {
    try {
      const raw = localStorage.getItem(LS_PERSONA_CACHE);
      if (!raw) return [];
      const parsed = JSON.parse(raw) as Array<{
        id?: unknown; label?: unknown; avatar_url?: unknown; archetype?: unknown;
      }>;
      return parsed
        .map((item) => ({
          id: typeof item.id === "string" ? item.id : "",
          label: typeof item.label === "string" ? item.label : "",
          avatar_url: typeof item.avatar_url === "string" ? item.avatar_url : "",
          archetype: typeof item.archetype === "string" ? item.archetype : "",
        }))
        .filter((item) => item.id && item.label);
    } catch {
      return [];
    }
  }, []);

  const [backendOptions, setBackendOptions] = useState<Array<{
    id: string;
    label: string;
    avatar_url: string;
    archetype: string;
  }>>([]);

  useEffect(() => {
    const ctrl = new AbortController();
    const backend = (backendUrl && backendUrl.trim()) || resolveBackendUrl();
    fetch(`${backend}/projects`, {
      signal: ctrl.signal,
      credentials: "include",
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        // ``/projects`` returns either ``{projects: [...]}`` or just
        // ``[...]`` depending on the auth wrapper — handle both.
        const list: Array<Record<string, unknown>> = Array.isArray(body)
          ? body
          : Array.isArray(body?.projects)
          ? body.projects
          : [];
        const personas = list
          .filter((p) => String(p.project_type || "").trim().toLowerCase() === "persona")
          .map((p) => {
            const agent = (p.persona_agent && typeof p.persona_agent === "object")
              ? (p.persona_agent as Record<string, unknown>)
              : {};
            const appearance = (p.persona_appearance && typeof p.persona_appearance === "object")
              ? (p.persona_appearance as Record<string, unknown>)
              : {};
            const filename = String(appearance.selected_filename || "").trim();
            return {
              id: String(p.id || "").trim(),
              label: String(p.name || agent.label || "Persona").trim() || "Persona",
              avatar_url: filename ? `${backend}/files/${filename}` : "",
              archetype: String(agent.persona_class || "").trim() || "Persona companion",
            };
          })
          .filter((p) => p.id);
        if (!ctrl.signal.aborted) setBackendOptions(personas);
      })
      .catch(() => { /* swallow — dropdown falls back to cache */ });
    return () => ctrl.abort();
  }, [backendUrl]);

  const personaOptions = useMemo(() => {
    const byId = new Map<string, {
      id: string;
      label: string;
      avatar_url: string;
      archetype: string;
    }>();
    for (const p of cacheOptions) byId.set(p.id, p);
    // Backend wins — authoritative + carries avatar/archetype.
    for (const p of backendOptions) byId.set(p.id, p);
    return Array.from(byId.values()).sort((a, b) => a.label.localeCompare(b.label));
  }, [cacheOptions, backendOptions]);

  const needsPersona = interactionType === "persona_live_play" && !personaId;
  const canSubmit = idea.trim().length > 0 && !generating && !needsPersona;

  const runPlan = useCallback(async () => {
    if (!canSubmit) return;
    const text = idea.trim();
    setError(null);
    setGenerating(true);
    setStep(0);

    // Advance the visible 'steps' list on a light timer so the
    // user feels progress even when the LLM is a one-shot call.
    // Does not fake completion — the real plan response
    // overwrites the timer-driven value below.
    const tick = window.setInterval(() => {
      setStep((s) => Math.min(s + 1, AI_STEPS.length - 2));
    }, 900);

    try {
      const result = await api.planAuto({ idea: text });
      window.clearInterval(tick);
      setStep(AI_STEPS.length - 1);
      // Tiny beat so the final "Ready to review" tick is visible.
      await new Promise((r) => window.setTimeout(r, 180));
      onPlanned(result, text, {
        interaction_type: interactionType,
        persona_project_id: personaId || undefined,
        persona_label: personaLabel || undefined,
        render_media_type: renderMediaType,
      });
    } catch (err) {
      window.clearInterval(tick);
      const apiErr = err as InteractiveApiError;
      setError(apiErr.message || "Couldn't generate a plan — try again.");
      setGenerating(false);
    }
  }, [api, canSubmit, idea, interactionType, personaId, personaLabel, renderMediaType, onPlanned]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        runPlan();
      }
    },
    [runPlan],
  );

  return (
    <div className="relative flex flex-col h-full w-full">
      {/* Scrollable body (three-row wizard shell pattern) */}
      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-6 py-10">
          <header className="text-center mb-8">
            <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-[#8b5cf6]/15 border border-[#8b5cf6]/30 flex items-center justify-center">
              <Wand2 className="w-7 h-7 text-[#c4b5fd]" aria-hidden />
            </div>
            <h1 className="text-2xl font-semibold text-[#f1f1f1]">
              {interactionType === "persona_live_play"
                ? "Describe the vibe of this live play session"
                : "Describe your interactive video"}
            </h1>
            <p className="text-sm text-[#aaa] mt-2 max-w-md mx-auto leading-relaxed">
              {interactionType === "persona_live_play"
                ? "Use a short vibe prompt (teasing, playful, romantic, etc). We'll build a persona-centered progression session."
                : "A single sentence is enough. The planner will expand it into a full project — title, audience, branching shape, policy — that you can tweak before creating."}
            </p>
          </header>

          {/* Interaction type — compact two-card picker so the user
              can switch between the standard branching project and
              the persona live-play flow before generating. */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mb-5">
            <button
              type="button"
              onClick={() => {
                setInteractionType("standard_project");
                setPersonaId("");
                setPersonaLabel("");
              }}
              aria-pressed={interactionType === "standard_project"}
              disabled={generating}
              className={[
                "text-left bg-[#121212] border rounded-lg p-3 transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
                "disabled:opacity-60 disabled:cursor-not-allowed",
                interactionType === "standard_project"
                  ? "border-[#3ea6ff] bg-[rgba(62,166,255,0.08)] ring-1 ring-[#3ea6ff]"
                  : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
              ].join(" ")}
            >
              <div className="text-sm font-medium text-[#f1f1f1]">
                Standard interactive project
              </div>
              <div className="text-[11px] text-[#aaa] mt-0.5">
                Branching AI video with scenes, choices, and endings.
              </div>
            </button>
            <button
              type="button"
              onClick={() => setInteractionType("persona_live_play")}
              aria-pressed={interactionType === "persona_live_play"}
              disabled={generating}
              className={[
                "text-left bg-[#121212] border rounded-lg p-3 transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#8b5cf6]",
                "disabled:opacity-60 disabled:cursor-not-allowed",
                interactionType === "persona_live_play"
                  ? "border-[#8b5cf6] bg-[rgba(139,92,246,0.08)] ring-1 ring-[#8b5cf6]"
                  : "border-[#3f3f3f] hover:border-[#555] hover:bg-[#1a1a1a]",
              ].join(" ")}
            >
              <div className="text-sm font-medium text-[#f1f1f1] inline-flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-[#c4b5fd]" aria-hidden />
                Persona live play
              </div>
              <div className="text-[11px] text-[#aaa] mt-0.5">
                Pick one of your personas — chat + video revolve around them.
              </div>
            </button>
          </div>

          {/* Render-media toggle — small dropdown that lets operators
              flip between the full video pipeline and the still-image
              feasibility path without leaving the one-box flow. */}
          <div className="mb-5 flex items-center justify-between gap-3 bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2.5">
            <div className="min-w-0">
              <div className="text-xs font-medium text-[#cfd8dc]">Render media</div>
              <div className="text-[11px] text-[#777] truncate">
                Image = fast still frames (low GPU). Video = full Animate/SVD clips.
              </div>
            </div>
            <select
              aria-label="Render media type"
              value={renderMediaType}
              onChange={(e) => setRenderMediaType(
                (e.target.value === "image" ? "image" : "video") as "video" | "image",
              )}
              disabled={generating}
              className="shrink-0 bg-[#0f0f0f] border border-[#3f3f3f] rounded-md px-2 py-1.5 text-xs outline-none focus:border-[#8b5cf6] focus:ring-1 focus:ring-[#8b5cf6]/50 disabled:opacity-60"
            >
              <option value="video">Video (full)</option>
              <option value="image">Image (feasibility)</option>
            </select>
          </div>

          {interactionType === "persona_live_play" && (
            <div className="mb-5">
              <label htmlFor="ix_auto_persona" className="text-xs font-medium text-[#cfd8dc]">
                Persona <span className="text-[#8b5cf6] ml-0.5" aria-label="required">*</span>
              </label>
              <select
                id="ix_auto_persona"
                value={personaId}
                onChange={(e) => {
                  const selected = personaOptions.find((p) => p.id === e.target.value);
                  setPersonaId(e.target.value);
                  setPersonaLabel(selected?.label || "");
                }}
                disabled={generating}
                className="mt-1.5 w-full bg-[#121212] border border-[#3f3f3f] rounded-md px-3 py-2.5 text-sm outline-none focus:border-[#8b5cf6] focus:ring-1 focus:ring-[#8b5cf6]/50 disabled:opacity-60"
              >
                <option value="">Select persona…</option>
                {personaOptions.map((p) => (
                  <option key={p.id} value={p.id}>{p.label}</option>
                ))}
              </select>
              {personaOptions.length === 0 && (
                <p className="text-[11px] text-amber-300 mt-1.5">
                  No personas yet. Create one in the Avatar tab, then come back — this mode needs a
                  persona to anchor the chat + animation.
                </p>
              )}
              {personaId && (() => {
                const selected = personaOptions.find((p) => p.id === personaId);
                if (!selected) return null;
                return (
                  <div className="mt-2.5 flex items-center gap-2.5 rounded-md border border-[#3a2a58] bg-[#130f1f] p-2.5">
                    {selected.avatar_url ? (
                      <img src={selected.avatar_url} alt={selected.label} className="w-12 h-12 rounded-md object-cover border border-[#51347f]" />
                    ) : (
                      <div className="w-12 h-12 rounded-md bg-[#24173a] border border-[#51347f]" />
                    )}
                    <div className="min-w-0">
                      <div className="text-xs font-medium text-[#f1f1f1] truncate">{selected.label}</div>
                      <div className="text-[11px] text-[#b59ed9] truncate">{selected.archetype || "Persona companion"}</div>
                    </div>
                  </div>
                );
              })()}
            </div>
          )}

          <label htmlFor="ix_auto_idea" className="sr-only">
            Your interactive video idea
          </label>
          <textarea
            id="ix_auto_idea"
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={`e.g. ${IDEA_PLACEHOLDER}`}
            rows={4}
            disabled={generating}
            className={[
              "w-full bg-[#121212] border border-[#3f3f3f] rounded-xl",
              "px-5 py-4 text-base outline-none resize-y leading-relaxed",
              "focus:border-[#8b5cf6] focus:ring-2 focus:ring-[#8b5cf6]/30",
              "disabled:opacity-60 disabled:cursor-not-allowed",
              "placeholder:text-[#555]",
            ].join(" ")}
          />
          <p className="text-xs text-[#777] mt-2">
            Tip: press <kbd className="px-1.5 py-0.5 rounded border border-[#3f3f3f] bg-[#1a1a1a] text-[#cfd8dc] font-mono text-[10px]">⌘/Ctrl</kbd> + <kbd className="px-1.5 py-0.5 rounded border border-[#3f3f3f] bg-[#1a1a1a] text-[#cfd8dc] font-mono text-[10px]">Enter</kbd> to submit.
          </p>

          {error && (
            <div className="mt-5">
              <ErrorBanner
                title="Couldn't plan your project"
                message={error}
                onRetry={runPlan}
              />
            </div>
          )}

          <div className="mt-6 flex items-center justify-between">
            <button
              type="button"
              onClick={onSwitchToAdvanced}
              className="text-xs font-medium text-[#aaa] hover:text-[#f1f1f1] transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] rounded px-1"
            >
              Advanced settings →
            </button>
            <PrimaryButton
              onClick={runPlan}
              disabled={!canSubmit}
              loading={generating}
              size="lg"
              icon={!generating ? <Sparkles className="w-4 h-4" aria-hidden /> : undefined}
            >
              Generate project
            </PrimaryButton>
          </div>

          <div className="mt-10 rounded-lg border border-[#2a2a2a] bg-[#121212]/60 px-4 py-3 text-[11px] text-[#777] leading-relaxed">
            <div className="text-[#cfd8dc] font-medium mb-1">Examples that work well</div>
            <ul className="space-y-0.5 list-disc ml-4">
              <li>teach beginners basic Spanish conversation practice</li>
              <li>walk new sales reps through our 3 pricing tiers with quizzes</li>
              <li>explain photosynthesis with a short branching story</li>
              <li>compliance onboarding for a new hire — 4 decisions, 3 endings</li>
            </ul>
          </div>
        </div>
      </div>

      {/* Footer spacer so the scrollable area never butts against
          the host's fixed Cancel bar. */}
      <div className="shrink-0 h-3" />

      {/* Enterprise waiting overlay */}
      {generating && (
        <GeneratingPanel
          title="Generating your project"
          description={
            <>
              Turning <span className="text-white/80">"{idea.trim().slice(0, 70)}{idea.trim().length > 70 ? "…" : ""}"</span>
              {" "}into a complete starting point.
            </>
          }
          steps={AI_STEPS}
          activeStep={step}
          accentClassName="text-[#c4b5fd]"
        />
      )}

      {/* Hidden button for the host's TopBar Cancel affordance to
          reference if the embed wants to hook into onCancel from
          outside. Not visually rendered — onCancel is the exported
          hook. Kept so the component's prop surface stays declared. */}
      <span className="sr-only" aria-hidden>
        <button type="button" onClick={onCancel}>cancel</button>
      </span>
    </div>
  );
}
