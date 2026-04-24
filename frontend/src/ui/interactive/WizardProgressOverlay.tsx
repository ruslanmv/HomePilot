/**
 * Global wizard-progress overlay.
 *
 * Mounted once at App level so the "Generating scenes…" modal
 * persists across tab switches. WizardAutoPreview used to render
 * this inline, which meant clicking Chat / Imagine / Voice mid-
 * generation unmounted the wizard and the modal vanished even
 * though the SSE stream was still running on the backend.
 *
 * State lives in ``wizardProgressStore`` (module-level singleton);
 * this component is a pure consumer.
 *
 * Renders nothing when ``state.active === false``. When active, it
 * portals a fixed-position overlay over the entire viewport so it
 * stays on top of whatever route the user has navigated to.
 */
import React, { useMemo } from "react";
import { createPortal } from "react-dom";

import { GeneratingPanel } from "./GeneratingPanel";
import {
  useWizardProgress,
  dismissOverlay,
  type WizardProgressState,
} from "./wizardProgressStore";

const GENERATE_STEPS = [
  { label: "Saving your project" },
  { label: "Drafting the scene graph" },
  { label: "Writing dialogue + choices" },
  { label: "Rendering scenes" },
  { label: "Opening the editor" },
] as const;

function _panelTitle(s: WizardProgressState, renderEnabled: boolean): string {
  if (s.error) return "Generation failed";
  if (s.renderTotal > 0 && s.renderDone < s.renderTotal) {
    return `Rendering scenes · ${s.renderDone + 1} of ${s.renderTotal}`;
  }
  if (s.libraryTotal > 0 && s.libraryDone < s.libraryTotal) {
    return `Building persona library · ${s.libraryDone + 1} of ${s.libraryTotal}`;
  }
  if (s.genStep >= GENERATE_STEPS.length - 1) return "Opening the editor";
  return GENERATE_STEPS[Math.max(0, Math.min(s.genStep, GENERATE_STEPS.length - 1))].label;
}

function _panelDescription(s: WizardProgressState): string {
  if (s.error) return s.error;
  if (s.currentSceneTitle && s.renderTotal > 0 && s.renderDone < s.renderTotal) {
    return `Now rendering: ${s.currentSceneTitle}`;
  }
  if (s.libraryTotal > 0 && s.libraryDone < s.libraryTotal) {
    return "Pre-generating the persona's reaction pack — this is a one-time pass per persona.";
  }
  if (s.genStep === GENERATE_STEPS.length - 1) {
    return "Almost ready — opening the editor.";
  }
  return "AI is working — this usually takes a few seconds.";
}


export function WizardProgressOverlay(): React.ReactElement | null {
  const state = useWizardProgress();

  const showProgressBar = useMemo(
    () => state.renderTotal > 0,
    [state.renderTotal],
  );
  const progressPct = useMemo(() => {
    if (!showProgressBar) return undefined;
    return Math.round((state.renderDone / Math.max(1, state.renderTotal)) * 100);
  }, [showProgressBar, state.renderDone, state.renderTotal]);
  const progressLabel = useMemo(() => {
    if (!showProgressBar) return undefined;
    return `${state.renderDone} / ${state.renderTotal} scenes${
      state.renderSkipped > 0 ? ` · ${state.renderSkipped} skipped` : ""
    }`;
  }, [showProgressBar, state.renderDone, state.renderTotal, state.renderSkipped]);

  // Hide when nothing's running. Errors are shown for ~5 s after the
  // run fails so the user has a moment to read them before the
  // overlay clears (ushered out by the wizard's inline retry button).
  if (!state.active && !state.error) {
    return null;
  }

  // The wizard route renders its own GeneratingPanel inline. We don't
  // want two stacked modals when the user IS on the wizard route —
  // detect that by looking for the wizard's container in the DOM.
  // Cheap, race-free: we render at App level only when no inline
  // overlay is mounted by WizardAutoPreview.
  //
  // Implementation: WizardAutoPreview no longer renders its own panel
  // (the inline render is now this component), so always show the
  // overlay when the store says we're active.

  const node = (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Project generation progress"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9000,
        background: "rgba(0,0,0,0.55)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
      }}
    >
      <div style={{ maxWidth: 480, width: "100%" }}>
        <GeneratingPanel
          title={_panelTitle(state, true)}
          description={_panelDescription(state)}
          steps={GENERATE_STEPS as unknown as Array<{ label: string }>}
          activeStep={state.genStep}
          accentClassName="text-[#c4b5fd]"
          spinnerSize="large"
          progress={progressPct}
          progressLabel={progressLabel}
        />
        {state.error && (
          <div
            style={{
              marginTop: "0.75rem",
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
            <button
              type="button"
              onClick={() => dismissOverlay()}
              style={{
                padding: "0.5rem 1rem",
                background: "#1f2937",
                color: "#f1f1f1",
                border: "1px solid #374151",
                borderRadius: 6,
                cursor: "pointer",
              }}
            >
              Dismiss
            </button>
          </div>
        )}
      </div>
    </div>
  );

  // Portal to body so this floats above the entire app shell
  // regardless of which route is active when the user navigates.
  return typeof document !== "undefined"
    ? createPortal(node, document.body)
    : null;
}
