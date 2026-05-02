/**
 * Expert Mode log panel.
 *
 * Displays a CrewAI-style chain-of-thought trace of the planner /
 * workflow runner / LLM calls happening on the backend during the
 * wizard's generate-all SSE run. Reads ``expertLog`` from
 * ``wizardProgressStore`` — the store appends every SSE frame as
 * a structured entry, regardless of whether this panel is mounted.
 *
 * Visibility is gated by ``useExpertMode()`` (a ``localStorage``-
 * backed boolean). When off, this component renders nothing — the
 * log is still being collected, so flipping the toggle mid-run shows
 * the full history.
 *
 * The panel is meant to live inside ``WizardProgressOverlay`` as a
 * collapsible side rail. Authoring contexts that surface a smaller
 * inline trace (e.g. a debug drawer) can mount the same component
 * elsewhere — it's pure.
 */
import React, { useEffect, useMemo, useState } from "react";
import { useWizardProgress, type ExpertLogEntry } from "./wizardProgressStore";

const STORAGE_KEY = "homepilot_expert_mode";

/**
 * localStorage-backed boolean for "show the expert log".
 *
 * Module-scoped subscriber set so multiple components stay in sync
 * within the same tab without a context provider — toggling the
 * setting from anywhere updates every consumer.
 */
const expertModeListeners = new Set<() => void>();

function readExpertMode(): boolean {
  try {
    return globalThis.localStorage?.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setExpertMode(next: boolean): void {
  try {
    if (next) {
      globalThis.localStorage?.setItem(STORAGE_KEY, "1");
    } else {
      globalThis.localStorage?.removeItem(STORAGE_KEY);
    }
  } catch {
    /* private browsing / quota — non-fatal */
  }
  expertModeListeners.forEach((fn) => {
    try { fn(); } catch { /* swallow */ }
  });
}

export function useExpertMode(): [boolean, (next: boolean) => void] {
  const [enabled, setEnabled] = useState<boolean>(() => readExpertMode());
  useEffect(() => {
    const sync = () => setEnabled(readExpertMode());
    expertModeListeners.add(sync);
    // Cross-tab sync — pure bonus, costs nothing.
    const storage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) sync();
    };
    globalThis.addEventListener?.("storage", storage);
    return () => {
      expertModeListeners.delete(sync);
      globalThis.removeEventListener?.("storage", storage);
    };
  }, []);
  return [enabled, setExpertMode];
}

const KIND_ICON: Record<ExpertLogEntry["kind"], string> = {
  thought: "💭",
  step: "▸",
  llm: "✨",
  render: "▦",
  phase: "•",
};

const KIND_COLOR: Record<ExpertLogEntry["kind"], string> = {
  thought: "text-[#c4b5fd]",
  step: "text-[#3ea6ff]",
  llm: "text-[#fbbf24]",
  render: "text-[#9f7fd1]",
  phase: "text-[#aaa]",
};

function formatTime(ts: number, baseline: number): string {
  const seconds = Math.max(0, (ts - baseline) / 1000);
  return `+${seconds.toFixed(1)}s`;
}

function ExpertLogRow({
  entry,
  baseline,
}: {
  entry: ExpertLogEntry;
  baseline: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasPayload = Object.keys(entry.payload || {}).length > 0;
  return (
    <div
      className={[
        "flex flex-col gap-0.5 px-2 py-1.5 text-[11px]",
        "border-l-2",
        entry.failed
          ? "border-[#ef4444]/60 bg-[#ef4444]/5"
          : "border-[#2a2a2a] hover:border-[#3f3f3f]",
      ].join(" ")}
    >
      <div className="flex items-baseline gap-2 leading-tight">
        <span
          className={[KIND_COLOR[entry.kind], "select-none w-3 text-center"].join(" ")}
          aria-hidden
        >
          {KIND_ICON[entry.kind]}
        </span>
        <span className="text-[#777] tabular-nums w-12 flex-shrink-0">
          {formatTime(entry.ts, baseline)}
        </span>
        <span
          className={[
            "font-medium flex-shrink-0",
            entry.failed ? "text-[#fca5a5]" : "text-[#cfd8dc]",
          ].join(" ")}
        >
          {entry.label}
        </span>
        {hasPayload && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="ml-auto text-[10px] text-[#777] hover:text-[#cfd8dc] flex-shrink-0"
            aria-expanded={expanded}
          >
            {expanded ? "hide" : "details"}
          </button>
        )}
      </div>
      {entry.summary && (
        <div className="text-[#aaa] pl-[4.5rem] truncate" title={entry.summary}>
          {entry.summary}
        </div>
      )}
      {expanded && hasPayload && (
        <pre className="mt-1 ml-[4.5rem] max-h-40 overflow-auto rounded bg-[#0a0a0a] border border-[#2a2a2a] px-2 py-1 text-[10px] text-[#cfd8dc] leading-relaxed whitespace-pre-wrap break-words">
          {JSON.stringify(entry.payload, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function ExpertLogPanel({
  className,
  emptyHint,
}: {
  className?: string;
  emptyHint?: string;
}): React.ReactElement {
  const state = useWizardProgress();
  const entries = state.expertLog;
  const baseline = useMemo(
    () => (entries.length > 0 ? entries[0].ts : Date.now()),
    [entries.length > 0 ? entries[0].id : null], // re-baseline only on reset
  );

  const containerRef = React.useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    // Auto-scroll to bottom as new entries arrive — same affordance
    // as a terminal log; users can still scroll up to read history.
    const el = containerRef.current;
    if (!el) return;
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (isNearBottom) {
      el.scrollTop = el.scrollHeight;
    }
  }, [entries.length]);

  return (
    <div
      className={[
        "rounded-md border border-[#2a2a2a] bg-[#0f0f0f]/80 flex flex-col",
        className || "",
      ].join(" ")}
    >
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-[#2a2a2a]">
        <div className="flex items-center gap-2 text-[11px] uppercase tracking-wider text-[#9f7fd1]">
          <span aria-hidden>✨</span>
          Expert log
        </div>
        <div className="text-[10px] text-[#777] tabular-nums">
          {entries.length} event{entries.length === 1 ? "" : "s"}
        </div>
      </div>
      <div
        ref={containerRef}
        className="flex-1 min-h-0 overflow-y-auto"
        role="log"
        aria-live="polite"
        aria-label="Backend chain-of-thought trace"
      >
        {entries.length === 0 ? (
          <div className="px-3 py-4 text-[11px] text-[#777] leading-relaxed">
            {emptyHint
              || "Waiting for the planner. Steps, LLM calls and reasoning will appear here as the run progresses."}
          </div>
        ) : (
          entries.map((entry) => (
            <ExpertLogRow key={entry.id} entry={entry} baseline={baseline} />
          ))
        )}
      </div>
    </div>
  );
}

export function ExpertModeToggle({
  className,
}: {
  className?: string;
}): React.ReactElement {
  const [enabled, setEnabled] = useExpertMode();
  return (
    <label
      className={[
        "inline-flex items-center gap-2 cursor-pointer select-none",
        "text-[11px] text-[#aaa] hover:text-[#cfd8dc]",
        className || "",
      ].join(" ")}
    >
      <input
        type="checkbox"
        checked={enabled}
        onChange={(e) => setEnabled(e.target.checked)}
        className="accent-[#8b5cf6]"
      />
      Expert mode
      <span className="text-[10px] text-[#777]">
        (show backend chain-of-thought)
      </span>
    </label>
  );
}
