/**
 * InteractiveWizard — placeholder component landing in UI-2b.
 *
 * UI-2a ships the host + editor shell so the new-project routing
 * works end-to-end. This placeholder lets the user confirm the
 * flow reaches the wizard slot — the full 5-step form (prompt,
 * audience, branches, policy, review) ships in the next commit.
 */

import React from "react";
import { Wand2 } from "lucide-react";
import { EmptyState, SecondaryButton } from "./ui";

export interface InteractiveWizardProps {
  backendUrl: string;
  apiKey?: string;
  /** Called with the new experience id once creation succeeds. */
  onCreated: (experienceId: string) => void;
  /** Called when the user cancels the wizard. */
  onCancel: () => void;
}

export function InteractiveWizard({ onCancel }: InteractiveWizardProps) {
  return (
    <div className="pt-8">
      <EmptyState
        icon={<Wand2 className="w-12 h-12" aria-hidden />}
        title="New-project wizard coming in UI-2b"
        description="This screen will walk you through a short prompt, audience hints, branch settings, policy profile, and a final review before seeding the branching scene graph."
        action={<SecondaryButton onClick={onCancel}>Back to projects</SecondaryButton>}
      />
    </div>
  );
}
