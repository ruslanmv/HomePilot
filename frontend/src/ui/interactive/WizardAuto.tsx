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

import React, { useCallback, useMemo, useState } from "react";
import { Sparkles, Wand2 } from "lucide-react";
import { createInteractiveApi } from "./api";
import type { PlanAutoResult } from "./types";
import { InteractiveApiError } from "./types";
import { ErrorBanner, PrimaryButton } from "./ui";
import { GeneratingPanel } from "./GeneratingPanel";


const IDEA_PLACEHOLDER = "train new sales reps on pricing tiers";

const AI_STEPS = [
  { label: "Understanding your idea" },
  { label: "Picking mode + audience" },
  { label: "Drafting project shape" },
  { label: "Ready to review" },
];


export interface WizardAutoProps {
  backendUrl: string;
  apiKey?: string;
  /** Called when the LLM / heuristic returns a pre-filled form.
   *  The parent transitions to the editable preview step. */
  onPlanned: (result: PlanAutoResult, idea: string) => void;
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

  const canSubmit = idea.trim().length > 0 && !generating;

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
      onPlanned(result, text);
    } catch (err) {
      window.clearInterval(tick);
      const apiErr = err as InteractiveApiError;
      setError(apiErr.message || "Couldn't generate a plan — try again.");
      setGenerating(false);
    }
  }, [api, canSubmit, idea, onPlanned]);

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
              Describe your interactive video
            </h1>
            <p className="text-sm text-[#aaa] mt-2 max-w-md mx-auto leading-relaxed">
              A single sentence is enough. The planner will expand it into a
              full project — title, audience, branching shape, policy — that
              you can tweak before creating.
            </p>
          </header>

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
