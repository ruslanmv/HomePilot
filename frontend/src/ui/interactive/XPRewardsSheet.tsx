/**
 * XPRewardsSheet — per-scheme progress bars + "how to earn" tips.
 *
 * Mirrors the "XP Rewards" screenshot: a large level indicator,
 * the current/next threshold values, a progress bar, and a
 * collapsible explainer. Backend already produces a
 * ``LevelDescription`` per active scheme (xp_level, mastery,
 * cefr, affinity_tier, certification) from
 * progression.describe_level, so this component is a thin renderer.
 */

import React, { useCallback, useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Info } from "lucide-react";
import type { InteractiveApi } from "./api";
import type { LevelDescriptionView, ProgressSnapshot } from "./types";
import { BottomSheet } from "./BottomSheet";
import {
  ErrorBanner, SecondaryButton, SkeletonRow, useAsyncResource,
} from "./ui";

export interface XPRewardsSheetProps {
  open: boolean;
  onClose: () => void;
  api: InteractiveApi;
  sessionId: string;
}

export function XPRewardsSheet({
  open, onClose, api, sessionId,
}: XPRewardsSheetProps) {
  const resource = useAsyncResource<ProgressSnapshot>(
    (signal) => (open
      ? api.getProgress(sessionId, signal)
      : Promise.resolve({ progress: {}, descriptions: {}, mood: "", affinity_score: 0 })),
    [api, sessionId, open],
  );

  const schemes = useMemo(() => {
    const d = resource.data?.descriptions || {};
    return Object.entries(d) as Array<[string, LevelDescriptionView]>;
  }, [resource.data]);

  return (
    <BottomSheet
      open={open}
      onClose={onClose}
      title="XP Rewards"
      subtitle="Level up by chatting, trying actions, and completing moments."
      actions={
        <SecondaryButton onClick={onClose} size="sm">
          Done
        </SecondaryButton>
      }
    >
      {resource.error ? (
        <ErrorBanner
          title="Couldn't load progress"
          message={resource.error}
          onRetry={resource.reload}
        />
      ) : resource.loading && !resource.data ? (
        <div className="flex flex-col gap-2" aria-busy="true">
          {Array.from({ length: 2 }).map((_, i) => <SkeletonRow key={i} />)}
        </div>
      ) : schemes.length === 0 ? (
        <DefaultLevelPanel />
      ) : (
        <div className="flex flex-col gap-4">
          {schemes.map(([scheme, desc]) => (
            <SchemeCard key={scheme} scheme={scheme} desc={desc} />
          ))}
        </div>
      )}
      <HowToEarn />
    </BottomSheet>
  );
}

// ────────────────────────────────────────────────────────────────

function DefaultLevelPanel() {
  // Before the session has any progress rows, render a static
  // Level 1 card so the sheet still looks populated.
  return (
    <SchemeCard
      scheme="xp_level"
      desc={{
        level: 1, label: "Level 1",
        display: "Level 1  0 / 35 XP → Level 2",
        current_value: 0, next_threshold: 35,
      }}
    />
  );
}

function SchemeCard({
  scheme, desc,
}: { scheme: string; desc: LevelDescriptionView }) {
  const current = Number(desc.current_value || 0);
  const target = Number(desc.next_threshold || 0);
  const pct = target > 0 ? Math.min(100, Math.round((current / target) * 100)) : 0;
  const nextLevel = desc.level + 1;
  return (
    <section className="bg-[#121212] border border-[#3f3f3f] rounded-lg p-4">
      <header className="flex items-center gap-3">
        <LevelBadge level={desc.level} />
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[#f1f1f1]">{desc.label}</div>
          <div className="text-[11px] text-[#777] uppercase tracking-wide">{scheme.replace(/_/g, " ")}</div>
        </div>
      </header>
      <div className="mt-3 h-2 rounded-full bg-[#1f1f1f] overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-[#3ea6ff] to-[#6366f1]"
          style={{ width: `${pct}%` }}
          aria-hidden
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-[#aaa]">
        <span>{formatProgress(current, target)} XP</span>
        <span>Level {nextLevel}</span>
      </div>
    </section>
  );
}

function LevelBadge({ level }: { level: number }) {
  return (
    <span className="inline-flex items-center justify-center w-11 h-11 rounded-full bg-black border border-white/15 text-base font-bold text-[#f1f1f1]">
      {level}
    </span>
  );
}

function HowToEarn() {
  const [open, setOpen] = useState(false);
  const toggle = useCallback(() => setOpen((p) => !p), []);
  return (
    <section className="mt-4 bg-[#121212] border border-[#3f3f3f] rounded-lg">
      <button
        type="button"
        onClick={toggle}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-[#f1f1f1] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] rounded-lg"
        aria-expanded={open}
      >
        <span className="inline-flex items-center gap-2">
          <Info className="w-4 h-4 text-[#3ea6ff]" aria-hidden />
          How to earn XP
        </span>
        {open ? <ChevronUp className="w-4 h-4 text-[#aaa]" aria-hidden />
              : <ChevronDown className="w-4 h-4 text-[#aaa]" aria-hidden />}
      </button>
      {open && (
        <ul className="px-4 pb-4 text-xs text-[#cfd8dc] space-y-1.5 list-disc ml-5">
          <li>Send chat messages — each earns small amounts.</li>
          <li>Use unlocked Live Actions — XP award shown on each row.</li>
          <li>Compliment or flirt to bump mood + affinity.</li>
          <li>Hit story beats (endings, decisions) for bigger rewards.</li>
        </ul>
      )}
    </section>
  );
}

function formatProgress(current: number, target: number): string {
  if (target <= 0) return `${current}`;
  // mastery / affinity return 0..1 floats; xp_level returns integers
  const bothInts = Number.isInteger(current) && Number.isInteger(target);
  if (bothInts) return `${current} / ${target}`;
  return `${current.toFixed(2)} / ${target.toFixed(2)}`;
}
