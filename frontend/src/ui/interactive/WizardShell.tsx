/**
 * WizardShell — chrome for the multi-step new-project wizard.
 *
 * Renders the step indicator (numbered chips with completion
 * state), the page title for the current step, and the Back/Next
 * footer. The actual step body is passed in as `children`.
 *
 * Keyboard: Enter on the Next button submits; ESC is owned by the
 * surrounding host (back to landing).
 */

import React from "react";
import { Check, ChevronLeft, ChevronRight } from "lucide-react";
import { PrimaryButton } from "./ui";

export interface StepDef {
  key: string;
  label: string;
}

export interface WizardShellProps {
  steps: StepDef[];
  activeIndex: number;
  title: string;
  subtitle?: string;
  canGoBack: boolean;
  canGoNext: boolean;
  nextLabel?: string;
  submitting?: boolean;
  onBack: () => void;
  onNext: () => void;
  children: React.ReactNode;
}

export function WizardShell({
  steps, activeIndex, title, subtitle,
  canGoBack, canGoNext, nextLabel, submitting,
  onBack, onNext, children,
}: WizardShellProps) {
  return (
    // pb-20 reserves space for the sticky footer so the last form
    // field never sits flush under it.
    <div className="pt-8 flex flex-col gap-6 max-w-3xl mx-auto pb-20">
      <Stepper steps={steps} activeIndex={activeIndex} />
      <header>
        <h1 className="text-2xl font-medium">{title}</h1>
        {subtitle && <p className="text-sm text-[#aaa] mt-1">{subtitle}</p>}
      </header>
      <div>{children}</div>

      {/* Action bar — feels like page chrome, not a floating widget:
          no rounded corners, no drop-shadow, no fill border. Just a
          thin top rule + page-colored blurred background. Back is a
          ghost text button (secondary), Next is the prominent
          primary with a right-facing chevron so the forward motion
          reads at a glance. */}
      <footer
        className={[
          "sticky bottom-0 z-20",
          "flex items-center justify-between gap-3",
          "border-t border-[#2a2a2a]",
          "bg-[#0f0f0f]/95 backdrop-blur",
          "py-3",
        ].join(" ")}
      >
        <button
          type="button"
          onClick={onBack}
          disabled={!canGoBack || submitting}
          className={[
            "inline-flex items-center gap-1.5",
            "px-2.5 py-2 text-sm font-medium rounded",
            "text-[#aaa] hover:text-[#f1f1f1]",
            "disabled:text-[#555] disabled:cursor-not-allowed",
            "transition-colors focus:outline-none",
            "focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
          ].join(" ")}
        >
          <ChevronLeft className="w-4 h-4" aria-hidden />
          Back
        </button>
        <PrimaryButton
          onClick={onNext}
          disabled={!canGoNext}
          loading={submitting}
          size="lg"
        >
          <span>{nextLabel || "Next"}</span>
          {!submitting && <ChevronRight className="w-4 h-4" aria-hidden />}
        </PrimaryButton>
      </footer>
    </div>
  );
}

function Stepper({ steps, activeIndex }: { steps: StepDef[]; activeIndex: number }) {
  return (
    <ol
      aria-label="Wizard progress"
      className="flex items-center gap-2 overflow-x-auto"
    >
      {steps.map((s, i) => {
        const done = i < activeIndex;
        const active = i === activeIndex;
        return (
          <li key={s.key} className="flex items-center gap-2 shrink-0">
            <span
              aria-current={active ? "step" : undefined}
              className={[
                "w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold border",
                done && "bg-[#3ea6ff] border-[#3ea6ff] text-black",
                active && "bg-transparent border-[#3ea6ff] text-[#3ea6ff]",
                !done && !active && "bg-transparent border-[#3f3f3f] text-[#777]",
              ].filter(Boolean).join(" ")}
            >
              {done ? <Check className="w-3.5 h-3.5" aria-hidden /> : i + 1}
            </span>
            <span
              className={[
                "text-xs whitespace-nowrap",
                active ? "text-[#f1f1f1] font-medium" : "text-[#777]",
              ].join(" ")}
            >
              {s.label}
            </span>
            {i < steps.length - 1 && <span className="w-6 h-px bg-[#3f3f3f] mx-1" aria-hidden />}
          </li>
        );
      })}
    </ol>
  );
}
