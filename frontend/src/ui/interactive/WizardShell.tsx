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
import { PrimaryButton, SecondaryButton } from "./ui";

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
    // pb-28 reserves space at the bottom of the scrolling container
    // so the sticky footer never covers the last field in a step.
    <div className="pt-8 flex flex-col gap-6 max-w-3xl mx-auto pb-28">
      <Stepper steps={steps} activeIndex={activeIndex} />
      <header>
        <h1 className="text-2xl font-medium">{title}</h1>
        {subtitle && <p className="text-sm text-[#aaa] mt-1">{subtitle}</p>}
      </header>
      <div>{children}</div>
      {/* Sticky footer: Back/Next stay pinned to the viewport bottom
          so users on short screens (laptops, small-tab windows) can
          always see the Next button without scrolling hunt. */}
      <footer
        className={[
          "sticky bottom-4 z-10 flex items-center justify-between gap-3",
          "rounded-xl border border-[#3f3f3f] bg-[#121212]/95 backdrop-blur",
          "px-4 py-3 shadow-[0_8px_30px_rgba(0,0,0,0.4)]",
        ].join(" ")}
      >
        <SecondaryButton
          onClick={onBack}
          disabled={!canGoBack || submitting}
          icon={<ChevronLeft className="w-4 h-4" aria-hidden />}
        >
          Back
        </SecondaryButton>
        <PrimaryButton
          onClick={onNext}
          disabled={!canGoNext}
          loading={submitting}
          icon={!submitting ? <ChevronRight className="w-4 h-4" aria-hidden /> : undefined}
        >
          {nextLabel || "Next"}
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
