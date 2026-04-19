/**
 * GeneratingPanel — reusable enterprise-grade waiting overlay.
 *
 * Mirrors the pattern Animate uses on its video-card processing
 * overlay (see Animate.tsx — bg-black/50 backdrop-blur-sm,
 * Loader2 size=32 animate-spin, text-white/90 sm font-medium
 * label, optional pill under it for extra context) so the two
 * features feel like siblings under the HomePilot brand.
 *
 * Two modes:
 *   - `variant="overlay"` fills its positioned parent (use inside
 *     a ``relative`` container; the form beneath stays in the DOM
 *     and the overlay sits above it).
 *   - `variant="panel"` renders a self-contained block for places
 *     that don't have a host to overlay.
 *
 * Optional ``steps`` turns the label into a vertical checklist
 * where each stage promotes to "pending → running → done" as
 * the caller advances the activeStep index. That gives multi-phase
 * AI ops (plan → generate) a clear sense of progress instead of
 * a flat spin for tens of seconds.
 */

import React from "react";
import { Check, Loader2, Sparkles } from "lucide-react";

export interface GeneratingStep {
  label: string;
}

export interface GeneratingPanelProps {
  /** Big heading above the spinner, e.g. "Generating project". */
  title: string;
  /** One-line hint below the title. Optional. */
  description?: React.ReactNode;
  /** Variant picks full-parent overlay vs self-contained block. */
  variant?: "overlay" | "panel";
  /** Ordered stages the caller walks through. */
  steps?: GeneratingStep[];
  /** Which step is currently running. Earlier ones render as done;
   *  later ones render as pending. Default 0. */
  activeStep?: number;
  /** Tint color for the spinner + running-step indicator. Accepts
   *  a Tailwind arbitrary-value color class (e.g. "text-[#3ea6ff]"
   *  or "text-purple-400"). Default matches Animate (purple). */
  accentClassName?: string;
}

export function GeneratingPanel({
  title,
  description,
  variant = "overlay",
  steps,
  activeStep = 0,
  accentClassName = "text-purple-400",
}: GeneratingPanelProps) {
  const body = (
    <div className="flex flex-col items-center justify-center max-w-md text-center px-6">
      <div className="flex items-center justify-center gap-2 mb-4">
        <Loader2 size={32} className={`${accentClassName} animate-spin`} aria-hidden />
        <Sparkles size={18} className={`${accentClassName} opacity-80`} aria-hidden />
      </div>

      <div className="text-white/95 text-sm font-semibold">{title}</div>
      {description && (
        <div className="text-white/60 text-xs mt-1.5 leading-relaxed">
          {description}
        </div>
      )}

      {steps && steps.length > 0 && (
        <ol className="mt-5 w-full max-w-xs text-left flex flex-col gap-2" aria-label="Progress">
          {steps.map((s, i) => {
            const done = i < activeStep;
            const running = i === activeStep;
            return (
              <li
                key={`${i}-${s.label}`}
                className={[
                  "flex items-center gap-2.5 text-xs",
                  done ? "text-white/90"
                    : running ? "text-white/95"
                    : "text-white/40",
                ].join(" ")}
              >
                <StepIndicator
                  state={done ? "done" : running ? "running" : "pending"}
                  accentClassName={accentClassName}
                />
                <span>{s.label}</span>
              </li>
            );
          })}
        </ol>
      )}

      <div className="mt-5 px-3 py-1 rounded-full bg-black/60 border border-white/10 text-white/70 text-[11px]">
        AI is working — this usually takes a few seconds.
      </div>
    </div>
  );

  if (variant === "overlay") {
    return (
      <div
        role="status"
        aria-live="polite"
        className="absolute inset-0 z-20 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      >
        {body}
      </div>
    );
  }
  return (
    <div
      role="status"
      aria-live="polite"
      className="rounded-2xl border border-[#3f3f3f] bg-[#121212] px-6 py-12 flex items-center justify-center"
    >
      {body}
    </div>
  );
}

function StepIndicator({
  state, accentClassName,
}: {
  state: "pending" | "running" | "done";
  accentClassName: string;
}) {
  if (state === "done") {
    return (
      <span className="w-4 h-4 rounded-full bg-emerald-500/20 border border-emerald-500/40 flex items-center justify-center shrink-0">
        <Check className="w-2.5 h-2.5 text-emerald-400" aria-hidden />
      </span>
    );
  }
  if (state === "running") {
    return (
      <span className="w-4 h-4 rounded-full border border-white/20 flex items-center justify-center shrink-0">
        <Loader2 className={`w-2.5 h-2.5 ${accentClassName} animate-spin`} aria-hidden />
      </span>
    );
  }
  return (
    <span className="w-4 h-4 rounded-full border border-white/15 shrink-0" aria-hidden />
  );
}
