/**
 * GeneratingPanel — reusable enterprise-grade waiting overlay
 * used across Interactive surfaces.
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
 * Two progress styles (mixable):
 *   - `steps[]`        — vertical checklist; promotes each stage
 *                        "pending → running → done" as activeStep
 *                        advances. Best for a small fixed set of
 *                        phases (plan → graph → ready).
 *   - `progress` + `progressLabel` — linear gradient progress bar
 *                        with text below. Best for long-running
 *                        batch ops (render scene 5 / 12).
 *
 * ``spinnerSize="large"`` switches the 32px Loader2 for a 64px
 * dual-ring spinner (outer static ring + rotating inner arc),
 * matching the visual weight of a full-screen creation modal.
 * ``iconOverride`` swaps the central Sparkles for per-phase icons
 * (e.g. ImageIcon while rendering stills, Film while rendering
 * clips) so the user sees what phase we're in at a glance.
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
  /** 0–100 linear progress. Renders the gradient bar + label
   *  under the title. Omit for spinner-only indeterminate mode. */
  progress?: number;
  /** Small text under the progress bar (e.g. "5 / 12 scenes"). */
  progressLabel?: React.ReactNode;
  /** Tint color for the spinner + running-step indicator. Accepts
   *  a Tailwind arbitrary-value color class (e.g. "text-[#3ea6ff]"
   *  or "text-purple-400"). Default matches Animate (purple). */
  accentClassName?: string;
  /** "small" = 32px Loader2 (default, legacy look).
   *  "large" = 64px dual-ring spinner (Studio-style modal). */
  spinnerSize?: "small" | "large";
  /** Replace the decorative Sparkles with a phase-specific icon
   *  (ImageIcon, Film, Gamepad2…). Sits centered inside the
   *  dual-ring when spinnerSize='large', or next to the 32px
   *  loader when 'small'. */
  iconOverride?: React.ReactNode;
  /** Footer pill copy. Default: "AI is working — this usually
   *  takes a few seconds." Pass null to hide the pill entirely. */
  footerHint?: React.ReactNode | null;
}

export function GeneratingPanel({
  title,
  description,
  variant = "overlay",
  steps,
  activeStep = 0,
  progress,
  progressLabel,
  accentClassName = "text-purple-400",
  spinnerSize = "small",
  iconOverride,
  footerHint,
}: GeneratingPanelProps) {
  const clamped = typeof progress === "number"
    ? Math.max(0, Math.min(100, progress))
    : undefined;
  const hasProgress = clamped !== undefined;

  const spinner = spinnerSize === "large"
    ? <LargeSpinner accentClassName={accentClassName} icon={iconOverride} />
    : <SmallSpinner accentClassName={accentClassName} icon={iconOverride} />;

  const body = (
    <div className="flex flex-col items-center justify-center max-w-md text-center px-6">
      {spinner}

      <div className="text-white/95 text-sm font-semibold">{title}</div>
      {description && (
        <div className="text-white/60 text-xs mt-1.5 leading-relaxed">
          {description}
        </div>
      )}

      {hasProgress && (
        <div className="mt-4 w-full max-w-xs">
          <div
            className="h-2 bg-white/10 rounded-full overflow-hidden"
            role="progressbar"
            aria-valuenow={clamped}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={typeof progressLabel === "string" ? progressLabel : "Progress"}
          >
            <div
              className="h-full bg-gradient-to-r from-[#3ea6ff] to-[#6366f1] transition-[width] duration-500 ease-out"
              style={{ width: `${clamped}%` }}
            />
          </div>
          {progressLabel && (
            <div className="text-[11px] text-white/50 mt-2 tabular-nums">
              {progressLabel}
            </div>
          )}
        </div>
      )}

      {steps && steps.length > 0 && (
        <ol
          className={[
            "w-full max-w-xs text-left flex flex-col gap-2",
            hasProgress ? "mt-4" : "mt-5",
          ].join(" ")}
          aria-label="Progress"
        >
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

      {footerHint !== null && (
        <div className="mt-5 px-3 py-1 rounded-full bg-black/60 border border-white/10 text-white/70 text-[11px]">
          {footerHint ?? "AI is working — this usually takes a few seconds."}
        </div>
      )}
    </div>
  );

  if (variant === "overlay") {
    return (
      <div
        role="status"
        aria-live="polite"
        className="absolute inset-0 z-20 flex items-center justify-center bg-black/70 backdrop-blur-sm"
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


// ── Spinner variants ────────────────────────────────────────────

function SmallSpinner({
  accentClassName, icon,
}: { accentClassName: string; icon?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-center gap-2 mb-4">
      <Loader2 size={32} className={`${accentClassName} animate-spin`} aria-hidden />
      <span className={`${accentClassName} opacity-80`} aria-hidden>
        {icon ?? <Sparkles size={18} />}
      </span>
    </div>
  );
}


function LargeSpinner({
  accentClassName, icon,
}: { accentClassName: string; icon?: React.ReactNode }) {
  // Studio-inspired dual-ring: a faint static outer ring plus a
  // bright rotating arc on top, with the phase icon planted dead
  // center. Keeps the visual weight enterprise-y for long waits
  // without depending on any Studio code.
  return (
    <div className="relative w-20 h-20 mb-5" aria-hidden>
      {/* Static base ring — signals "work in progress" even when
          the animated layer is occluded. */}
      <div className={`absolute inset-0 rounded-full border-4 ${accentToBorder(accentClassName, "/20")}`} />
      {/* Rotating arc. Using the built-in animate-spin on a partial
          border rather than a keyframe gradient so the look stays
          crisp at any screen DPR. */}
      <div
        className={`absolute inset-0 rounded-full border-4 border-transparent ${accentToBorder(accentClassName, "")} animate-spin`}
        style={{
          // Show only the top-right quarter of the ring so it
          // reads as a clear moving arc instead of a fuzzy halo.
          borderRightColor: "transparent",
          borderBottomColor: "transparent",
          borderLeftColor: "transparent",
        }}
      />
      {/* Center phase icon. */}
      <div className={`absolute inset-0 flex items-center justify-center ${accentClassName}`}>
        {icon ?? <Sparkles size={26} />}
      </div>
    </div>
  );
}


/**
 * Derive a Tailwind border-color class from an accent text-color
 * class so the dual-ring picks up whatever brand tint the caller
 * passed. Falls back to white/20 + white for unknown prefixes so
 * the component still renders sensibly with custom colors.
 */
function accentToBorder(textClass: string, opacitySuffix: string): string {
  // "text-purple-400" → "border-purple-400", "text-[#3ea6ff]" →
  // "border-[#3ea6ff]". We keep opacity as a raw suffix so callers
  // can pass an empty string for the solid ring + "/20" for the
  // faint base. Tailwind JIT will emit both forms safely.
  const colorPart = textClass.replace(/^text-/, "");
  if (!colorPart) return `border-white${opacitySuffix || ""}`;
  return `border-${colorPart}${opacitySuffix}`;
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
