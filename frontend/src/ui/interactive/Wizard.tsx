/**
 * InteractiveWizard — orchestrates the 5-step new-project flow.
 *
 * Owns the shared form state, fetches /health once for branch-cap
 * limits, and chains the create + seed-graph calls on submit.
 * Each step body lives in its own file under ./wizardSteps so
 * individual steps can be tested / iterated in isolation.
 *
 * Submit semantics:
 *   1. POST /experiences            → new experience id
 *   2. POST /experiences/{id}/seed-graph (best-effort)
 *   3. onCreated(id)                 — parent swaps wizard → editor
 *
 * If seed-graph fails the project is still created — we surface a
 * warning toast and let the user open the editor anyway.
 */

import React, { useCallback, useMemo, useState } from "react";
import { Wand2 } from "lucide-react";
import type { InteractiveApi } from "./api";
import { createInteractiveApi } from "./api";
import type { HealthInfo } from "./types";
import { InteractiveApiError } from "./types";
import {
  ErrorBanner, useAsyncResource, useToast,
} from "./ui";
import { WizardShell, type StepDef } from "./WizardShell";
import {
  DEFAULT_WIZARD_FORM,
  toCreatePayload,
  toPlanPayload,
  type WizardForm,
} from "./wizardState";
import { Step0Prompt, step0Valid } from "./wizardSteps/Step0Prompt";
import { Step1Audience, step1Valid } from "./wizardSteps/Step1Audience";
import { Step2Branches, step2Valid } from "./wizardSteps/Step2Branches";
import { Step3Policy, step3Valid } from "./wizardSteps/Step3Policy";
import { Step4Review } from "./wizardSteps/Step4Review";

export interface InteractiveWizardProps {
  backendUrl: string;
  apiKey?: string;
  onCreated: (experienceId: string) => void;
  onCancel: () => void;
}

const STEPS: StepDef[] = [
  { key: "prompt",   label: "Prompt" },
  { key: "audience", label: "Audience" },
  { key: "branches", label: "Branches" },
  { key: "policy",   label: "Policy" },
  { key: "review",   label: "Review" },
];

export function InteractiveWizard({
  backendUrl, apiKey, onCreated, onCancel,
}: InteractiveWizardProps) {
  const api = useMemo<InteractiveApi>(
    () => createInteractiveApi(backendUrl, apiKey),
    [backendUrl, apiKey],
  );
  const toast = useToast();

  const [form, setFormState] = useState<WizardForm>(DEFAULT_WIZARD_FORM);
  const [step, setStep] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const setForm = useCallback(
    (patch: Partial<WizardForm>) => setFormState((prev) => ({ ...prev, ...patch })),
    [],
  );

  // /health gives us the branch-cap limits for step 2. If it
  // fails (service disabled / network), we fall back to
  // permissive defaults so the wizard stays usable.
  const health = useAsyncResource<HealthInfo>(
    (signal) => api.health(signal),
    [api],
  );

  const limits = useMemo(
    () => health.data?.limits || {
      max_branches: 12,
      max_depth: 6,
      max_nodes_per_experience: 200,
    },
    [health.data],
  );

  const stepValidators = [
    step0Valid, step1Valid, step2Valid, step3Valid, () => true,
  ];
  const canGoNext = stepValidators[step](form);
  const isLast = step === STEPS.length - 1;

  const goNext = useCallback(async () => {
    if (!isLast) {
      setStep((s) => Math.min(s + 1, STEPS.length - 1));
      return;
    }
    setSubmitting(true);
    try {
      const created = await api.createExperience(toCreatePayload(form));
      try {
        await api.seedGraph(created.id, toPlanPayload(form));
      } catch (seedErr) {
        const e = seedErr as InteractiveApiError;
        toast.toast({
          variant: "warning",
          title: "Project created, but seeding the graph failed",
          message: e.message || "You can re-run seeding from the editor.",
        });
      }
      toast.toast({
        variant: "success",
        title: "Project created",
        message: "Opening the editor…",
      });
      onCreated(created.id);
    } catch (err) {
      const e = err as InteractiveApiError;
      toast.toast({
        variant: "error",
        title: "Couldn't create the project",
        message: e.message || "Try again or check the backend.",
      });
      setSubmitting(false);
    }
  }, [api, form, isLast, onCreated, toast]);

  const goBack = useCallback(() => {
    if (step === 0) {
      onCancel();
      return;
    }
    setStep((s) => Math.max(0, s - 1));
  }, [step, onCancel]);

  const titles = [
    "Describe your interactive experience",
    "Who's going to watch?",
    "Shape the branching graph",
    "Pick the policy guardrails",
    "Review and create",
  ];
  const subtitles = [
    "A short brief and a target mode is enough to get started.",
    "Optional refinements that bias the planner toward your viewers.",
    "Numbers are capped to whatever your backend allows.",
    "Decides which guardrails the runtime enforces for every viewer turn.",
    "Verify the planner's interpretation, then we'll create + seed the graph.",
  ];

  return (
    <WizardShell
      steps={STEPS}
      activeIndex={step}
      title={titles[step]}
      subtitle={subtitles[step]}
      canGoBack
      canGoNext={canGoNext}
      submitting={submitting}
      nextLabel={isLast ? "Create project" : "Next"}
      onBack={goBack}
      onNext={goNext}
    >
      {health.error && step === 2 && (
        <div className="mb-4">
          <ErrorBanner
            title="Couldn't read backend caps"
            message={`${health.error} — using permissive defaults.`}
            onRetry={health.reload}
          />
        </div>
      )}

      {step === 0 && <Step0Prompt form={form} setForm={setForm} />}
      {step === 1 && <Step1Audience form={form} setForm={setForm} />}
      {step === 2 && <Step2Branches form={form} setForm={setForm} limits={limits} />}
      {step === 3 && <Step3Policy form={form} setForm={setForm} />}
      {step === 4 && <Step4Review form={form} api={api} />}

      {step === 0 && (
        <p className="mt-6 text-xs text-[#777] flex items-center gap-2">
          <Wand2 className="w-3.5 h-3.5 text-[#3ea6ff]" aria-hidden />
          The planner will turn this prompt into a branching scene graph
          you can then edit scene-by-scene.
        </p>
      )}
    </WizardShell>
  );
}
