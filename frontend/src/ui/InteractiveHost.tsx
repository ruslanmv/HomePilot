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

import React from "react";
import { ArrowLeft } from "lucide-react";
import { InteractiveEditor } from "./InteractiveEditor";
import { InteractiveWizard } from "./interactive/Wizard";
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

export function InteractiveHost({
  backendUrl, apiKey, projectId, onExit, onCreated,
}: InteractiveHostProps) {
  return (
    <ToastProvider>
      <div className="min-h-full bg-[#0f0f0f] text-[#f1f1f1]">
        <TopBar onExit={onExit} label={projectId ? "Back to projects" : "Cancel"} />
        <div className="max-w-6xl mx-auto px-6 pb-10">
          {projectId ? (
            <InteractiveEditor
              backendUrl={backendUrl}
              apiKey={apiKey}
              projectId={projectId}
            />
          ) : (
            <InteractiveWizard
              backendUrl={backendUrl}
              apiKey={apiKey}
              onCreated={onCreated}
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
    <div className="sticky top-0 z-10 bg-[#0f0f0f]/90 backdrop-blur border-b border-[#3f3f3f]">
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
