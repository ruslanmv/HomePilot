/**
 * AnalyticsPanel — experience-wide rollups.
 *
 * The runtime logs every turn to ix_session_events; the backend's
 * /analytics endpoint aggregates those into:
 *
 *   session_count        – distinct viewer sessions
 *   completion_rate      – fraction that hit an 'ending' node
 *   total_turns          – sum of ix_session_turns rows
 *   block_rate           – fraction of turns the policy blocked
 *   popular_actions      – top-N action_ids by use count
 *
 * We render four stat cards on top, a popularity bar list below,
 * plus a refresh button with a live "last fetched" timestamp so
 * authors know how stale the number they're looking at is.
 */

import React, { useCallback, useMemo, useState } from "react";
import { BarChart3, RefreshCw } from "lucide-react";
import type { InteractiveApi } from "./api";
import type { AnalyticsSummary } from "./types";
import {
  EmptyState,
  ErrorBanner,
  Panel,
  SecondaryButton,
  SkeletonRow,
  useAsyncResource,
} from "./ui";

export interface AnalyticsPanelProps {
  api: InteractiveApi;
  projectId: string;
}

export function AnalyticsPanel({ api, projectId }: AnalyticsPanelProps) {
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);

  const resource = useAsyncResource<AnalyticsSummary>(
    async (signal) => {
      const data = await api.experienceAnalytics(projectId, signal);
      setFetchedAt(new Date());
      return data;
    },
    [api, projectId],
  );

  const fetchedLabel = useMemo(() => {
    if (!fetchedAt) return "";
    return `updated ${formatHm(fetchedAt)}`;
  }, [fetchedAt]);

  const reload = useCallback(() => resource.reload(), [resource]);

  return (
    <div className="flex flex-col gap-6">
      <Panel
        title="Engagement summary"
        subtitle="Rollups across every viewer session of this experience."
        actions={
          <div className="flex items-center gap-2">
            {fetchedLabel && <span className="text-[11px] text-[#777]">{fetchedLabel}</span>}
            <SecondaryButton
              onClick={reload}
              size="sm"
              loading={resource.loading}
              icon={<RefreshCw className="w-4 h-4" aria-hidden />}
            >
              Refresh
            </SecondaryButton>
          </div>
        }
      >
        {resource.error ? (
          <ErrorBanner
            title="Couldn't load analytics"
            message={resource.error}
            onRetry={resource.reload}
          />
        ) : resource.loading && !resource.data ? (
          <StatGridSkeleton />
        ) : resource.data ? (
          <StatGrid data={resource.data} />
        ) : null}
      </Panel>

      <Panel title="Most-used actions" subtitle="Top 10 actions by use count across every session.">
        {resource.loading && !resource.data ? (
          <div className="flex flex-col gap-2" aria-busy="true">
            {Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} />)}
          </div>
        ) : resource.data && resource.data.popular_actions.length > 0 ? (
          <PopularActionsList actions={resource.data.popular_actions} />
        ) : !resource.error ? (
          <EmptyState
            icon={<BarChart3 className="w-12 h-12" aria-hidden />}
            title="No action usage yet"
            description="Once viewers start taking actions in sessions, the most-used ones will rank here."
          />
        ) : null}
      </Panel>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Stat cards
// ────────────────────────────────────────────────────────────────

function StatGrid({ data }: { data: AnalyticsSummary }) {
  const completionPct = Math.round(data.completion_rate * 100);
  const blockPct = Math.round(data.block_rate * 100);
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <StatCard label="Sessions" value={String(data.session_count)} sub={`${data.completed_sessions} completed`} />
      <StatCard
        label="Completion rate"
        value={`${completionPct}%`}
        sub={data.session_count > 0 ? "of started sessions" : "(no sessions yet)"}
        emphasis={completionPct >= 50 ? "good" : completionPct > 0 ? "neutral" : "dim"}
      />
      <StatCard label="Total turns" value={String(data.total_turns)} sub="viewer actions + free-text turns" />
      <StatCard
        label="Policy block rate"
        value={`${blockPct}%`}
        sub="fraction of turns blocked"
        emphasis={blockPct > 20 ? "warn" : "dim"}
      />
    </div>
  );
}

function StatCard({
  label, value, sub, emphasis,
}: {
  label: string;
  value: string;
  sub?: string;
  emphasis?: "good" | "warn" | "neutral" | "dim";
}) {
  const valueClass = {
    good: "text-emerald-300",
    warn: "text-amber-300",
    neutral: "text-[#f1f1f1]",
    dim: "text-[#f1f1f1]",
  }[emphasis || "neutral"];
  return (
    <div className="bg-[#121212] border border-[#3f3f3f] rounded-md p-3.5">
      <div className="text-[11px] text-[#777] uppercase tracking-wide">{label}</div>
      <div className={["text-2xl font-semibold mt-1 tabular-nums", valueClass].join(" ")}>{value}</div>
      {sub && <div className="text-[11px] text-[#aaa] mt-0.5">{sub}</div>}
    </div>
  );
}

function StatGridSkeleton() {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3" aria-busy="true">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="bg-[#121212] border border-[#3f3f3f] rounded-md p-3.5 animate-pulse">
          <div className="h-2.5 bg-[#2a2a2a] rounded w-16" />
          <div className="h-6 bg-[#2a2a2a] rounded w-20 mt-2" />
          <div className="h-2 bg-[#2a2a2a] rounded w-24 mt-2" />
        </div>
      ))}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Popular actions list (relative-width bars)
// ────────────────────────────────────────────────────────────────

function PopularActionsList({
  actions,
}: {
  actions: AnalyticsSummary["popular_actions"];
}) {
  const max = actions.reduce((m, a) => Math.max(m, a.uses), 0) || 1;
  return (
    <ul className="flex flex-col gap-2">
      {actions.map((a) => {
        const pct = Math.max(4, Math.round((a.uses / max) * 100));
        return (
          <li key={a.action_id} className="bg-[#121212] border border-[#3f3f3f] rounded-md p-3">
            <div className="flex items-center justify-between gap-3 mb-1.5">
              <code className="text-xs text-[#cfd8dc] truncate">{a.action_id}</code>
              <span className="text-xs text-[#f1f1f1] font-semibold tabular-nums shrink-0">{a.uses}</span>
            </div>
            <div className="h-1.5 rounded-full bg-[#1f1f1f] overflow-hidden">
              <div
                className="h-full bg-[#3ea6ff]"
                style={{ width: `${pct}%` }}
                aria-hidden
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function formatHm(d: Date): string {
  const h = d.getHours().toString().padStart(2, "0");
  const m = d.getMinutes().toString().padStart(2, "0");
  return `${h}:${m}`;
}
