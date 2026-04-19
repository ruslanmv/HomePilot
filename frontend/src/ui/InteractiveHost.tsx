/**
 * InteractiveHost — wizard / editor shell for one interactive project.
 *
 * Mirrors CreatorStudioHost's two-mode contract:
 *   - `mode="wizard"`  when creating a new project
 *   - `mode="editor"`  when opening an existing project id
 *
 * The host owns the transition: when the wizard finishes it hands
 * the new experience id to `onCreated`, which App.tsx uses to
 * swap the host from wizard mode to editor mode without tearing
 * down the parent tab.
 *
 * Both sub-views share the same page chrome — dark background,
 * back button top-left, toast provider mounted once at the root so
 * every panel can surface success/error toasts uniformly.
 */

import React, { useState } from "react";
import { ArrowLeft } from "lucide-react";
import { InteractiveEditor } from "./InteractiveEditor";
import { InteractiveWizard } from "./interactive/Wizard";
import { WizardAuto, type AutoInteractionSelection } from "./interactive/WizardAuto";
import { WizardAutoPreview } from "./interactive/WizardAutoPreview";
import type { PlanAutoResult } from "./interactive/types";
import { SecondaryButton, ToastProvider } from "./interactive/ui";

export interface InteractiveHostProps {
  backendUrl: string;
  apiKey?: string;
  /** When set, host renders the editor for this experience id. */
  projectId?: string | null;
  /** Called when the user leaves the host (back to landing grid). */
  onExit: () => void;
  /** Called when the wizard creates a new project. */
  onCreated: (experienceId: string) => void;
}

/**
 * Wizard stages the host walks through when no project is open.
 *
 *   auto     One-box WizardAuto (default). AI drafts the project
 *            from a single sentence.
 *   preview  Editable AI draft. User tweaks fields and creates.
 *   advanced Classic 5-step InteractiveWizard (power-user escape
 *            hatch; all original behaviour preserved).
 */
type WizardStage = "auto" | "preview" | "advanced";

export function InteractiveHost({
  backendUrl, apiKey, projectId, onExit, onCreated,
}: InteractiveHostProps) {
  const [stage, setStage] = useState<WizardStage>("auto");
  const [planResult, setPlanResult] = useState<PlanAutoResult | null>(null);
  const [originalIdea, setOriginalIdea] = useState<string>("");
  const [interaction, setInteraction] = useState<AutoInteractionSelection>({
    interaction_type: "standard_project",
  });

  // Enterprise shell: full viewport height, three stacked rows.
  //   [0] TopBar — fixed 'Cancel / Back to projects' button.
  //   [1] Body   — wizard or editor, filling the remaining space.
  //                Each mode manages its own internal scroll.
  //   Nothing scrolls at the page level; layout is owned by the
  //   sub-views so Back / Next never drift offscreen.
  return (
    <ToastProvider>
      <div className="flex flex-col h-screen bg-[#0f0f0f] text-[#f1f1f1]">
        <TopBar onExit={onExit} label={projectId ? "Back to projects" : "Cancel"} />
        <div className="flex-1 min-h-0 flex flex-col">
          {projectId ? (
            <InteractiveEditor
              backendUrl={backendUrl}
              apiKey={apiKey}
              projectId={projectId}
            />
          ) : stage === "advanced" ? (
            // Classic 5-step wizard stays intact for power users.
            // Nothing inside it was touched by the AUTO-* batches.
            <InteractiveWizard
              backendUrl={backendUrl}
              apiKey={apiKey}
              onCreated={onCreated}
              onCancel={onExit}
            />
          ) : stage === "preview" && planResult ? (
            <WizardAutoPreview
              backendUrl={backendUrl}
              apiKey={apiKey}
              initial={planResult}
              originalIdea={originalIdea}
              interaction={interaction}
              onCreated={onCreated}
              onStartOver={() => {
                setPlanResult(null);
                setStage("auto");
              }}
            />
          ) : (
            <WizardAuto
              backendUrl={backendUrl}
              apiKey={apiKey}
              onPlanned={(result, idea, selection) => {
                setPlanResult(result);
                setOriginalIdea(idea);
                setInteraction(selection);
                setStage("preview");
              }}
              onSwitchToAdvanced={() => setStage("advanced")}
              onCancel={onExit}
            />
          )}
        </div>
      </div>
    </ToastProvider>
  );
}

function TopBar({ onExit, label }: { onExit: () => void; label: string }) {
  return (
    <div className="shrink-0 bg-[#0f0f0f] border-b border-[#3f3f3f]">
      <div className="max-w-6xl mx-auto px-6 py-3">
        <SecondaryButton
          onClick={onExit}
          size="sm"
          icon={<ArrowLeft className="w-3.5 h-3.5" aria-hidden />}
          aria-label={label}
        >
          {label}
        </SecondaryButton>
      </div>
    </div>
  );
}
