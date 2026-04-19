/**
 * InteractiveEditor — tabbed editor for one interactive experience.
 *
 * UI-2a placeholder — just renders the project header and a tab
 * strip with the six future sub-panels disabled. The real panel
 * bodies land in UI-3 / UI-4 / UI-5:
 *
 *   UI-3: Graph   — DAG visualizer over ix_nodes + ix_edges
 *         Catalog — action_catalog CRUD with level/scheme gates
 *   UI-4: Rules   — personalization-rule DSL builder
 *         QA      — run checks, render issues
 *         Publish — channel picker + publish flow
 *   UI-5: Analytics — experience + session rollups
 *
 * The editor owns the currently-selected tab in local state;
 * switching tabs never unmounts the project header so the
 * breadcrumb + status badge stay stable.
 */

import React, { useMemo, useState } from "react";
import {
  BarChart3, CheckSquare, GitBranch, ListChecks, Send, Sparkles,
} from "lucide-react";
import { createInteractiveApi } from "./interactive/api";
import { CatalogPanel } from "./interactive/CatalogPanel";
import { GraphPanel } from "./interactive/GraphPanel";
import { RulesPanel } from "./interactive/RulesPanel";
import type { Experience } from "./interactive/types";
import {
  ErrorBanner, Panel, StatusBadge, useAsyncResource,
} from "./interactive/ui";

export interface InteractiveEditorProps {
  backendUrl: string;
  apiKey?: string;
  projectId: string;
}

type TabKey = "graph" | "catalog" | "rules" | "qa" | "publish" | "analytics";

const TABS: Array<{ key: TabKey; label: string; icon: React.ReactNode; description: string }> = [
  { key: "graph",     label: "Graph",     icon: <GitBranch className="w-4 h-4" aria-hidden />,    description: "Scenes, branches, and transitions" },
  { key: "catalog",   label: "Catalog",   icon: <ListChecks className="w-4 h-4" aria-hidden />,   description: "Actions viewers can take" },
  { key: "rules",     label: "Rules",     icon: <Sparkles className="w-4 h-4" aria-hidden />,     description: "Personalization routing" },
  { key: "qa",        label: "QA",        icon: <CheckSquare className="w-4 h-4" aria-hidden />,  description: "Readiness checks" },
  { key: "publish",   label: "Publish",   icon: <Send className="w-4 h-4" aria-hidden />,         description: "Channels + versions" },
  { key: "analytics", label: "Analytics", icon: <BarChart3 className="w-4 h-4" aria-hidden />,    description: "Viewer engagement" },
];

export function InteractiveEditor({ backendUrl, apiKey, projectId }: InteractiveEditorProps) {
  const api = useMemo(() => createInteractiveApi(backendUrl, apiKey), [backendUrl, apiKey]);
  const [activeTab, setActiveTab] = useState<TabKey>("graph");

  const exp = useAsyncResource<Experience>(
    (signal) => api.getExperience(projectId, signal),
    [api, projectId],
  );

  return (
    <div className="pt-6 flex flex-col gap-6">
      {exp.error ? (
        <ErrorBanner
          title="Couldn't load this project"
          message={exp.error}
          onRetry={exp.reload}
        />
      ) : exp.loading || !exp.data ? (
        <ProjectHeaderSkeleton />
      ) : (
        <ProjectHeader experience={exp.data} />
      )}

      <TabStrip active={activeTab} onChange={setActiveTab} />

      <div>
        {activeTab === "graph" ? (
          <GraphPanel api={api} projectId={projectId} />
        ) : activeTab === "catalog" ? (
          <CatalogPanel api={api} projectId={projectId} />
        ) : activeTab === "rules" ? (
          <RulesPanel api={api} projectId={projectId} />
        ) : (
          // Placeholder for tabs that haven't shipped yet. Each
          // panel gets its own batch (UI-3b Catalog, UI-4 Rules /
          // QA / Publish, UI-5 Analytics).
          <Panel
            title={TABS.find((t) => t.key === activeTab)?.label}
            subtitle={TABS.find((t) => t.key === activeTab)?.description}
          >
            <ComingSoonPanel tab={activeTab} projectId={projectId} />
          </Panel>
        )}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Project header (title, status, description)
// ────────────────────────────────────────────────────────────────

function ProjectHeader({ experience }: { experience: Experience }) {
  return (
    <header className="flex items-start justify-between gap-4 flex-wrap">
      <div className="min-w-0">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-2xl font-medium truncate">
            {experience.title || "(untitled)"}
          </h1>
          <StatusBadge status={experience.status} />
        </div>
        {(experience.description || experience.objective) && (
          <p className="text-sm text-[#aaa] mt-1 max-w-2xl">
            {experience.description || experience.objective}
          </p>
        )}
        <div className="mt-2 text-xs text-[#777] flex flex-wrap gap-3">
          <span>mode: <span className="text-[#cfd8dc]">{experience.experience_mode}</span></span>
          <span>profile: <span className="text-[#cfd8dc]">{experience.policy_profile_id}</span></span>
          {typeof experience.branch_count === "number" && (
            <span>{experience.branch_count} {experience.branch_count === 1 ? "branch" : "branches"}</span>
          )}
          {typeof experience.max_depth === "number" && (
            <span>depth {experience.max_depth}</span>
          )}
        </div>
      </div>
    </header>
  );
}

function ProjectHeaderSkeleton() {
  return (
    <div className="flex flex-col gap-2 animate-pulse" aria-busy="true">
      <div className="h-7 bg-[#1f1f1f] rounded w-2/3 max-w-md" />
      <div className="h-4 bg-[#1f1f1f] rounded w-full max-w-2xl" />
      <div className="h-3 bg-[#1f1f1f] rounded w-1/3 max-w-xs mt-1" />
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Tab strip
// ────────────────────────────────────────────────────────────────

function TabStrip({
  active, onChange,
}: {
  active: TabKey;
  onChange: (key: TabKey) => void;
}) {
  return (
    <nav
      aria-label="Editor sections"
      className="flex gap-1 border-b border-[#3f3f3f] overflow-x-auto -mx-2 px-2"
    >
      {TABS.map((tab) => {
        const selected = active === tab.key;
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(tab.key)}
            className={[
              "inline-flex items-center gap-2 px-3 py-2 text-sm font-medium whitespace-nowrap",
              "border-b-2 -mb-px transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
              selected
                ? "border-[#3ea6ff] text-[#3ea6ff]"
                : "border-transparent text-[#aaa] hover:text-[#f1f1f1] hover:border-[#555]",
            ].join(" ")}
          >
            {tab.icon}
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
}

// ────────────────────────────────────────────────────────────────
// Placeholder panel — every tab renders this until its batch lands
// ────────────────────────────────────────────────────────────────

function ComingSoonPanel({ tab, projectId }: { tab: TabKey; projectId: string }) {
  const upcoming: Record<TabKey, string> = {
    graph: "UI-3 — DAG visualizer with zoomable canvas.",
    catalog: "UI-3 — action-catalog CRUD with level / cooldown / XP fields.",
    rules: "UI-4 — personalization rule DSL builder with live validation.",
    qa: "UI-4 — run checks, render severity-sorted issues, retry individual checks.",
    publish: "UI-4 — channel picker + publish flow with manifest diff preview.",
    analytics: "UI-5 — experience + session rollups, completion rate, action popularity.",
  };
  return (
    <div className="text-sm text-[#aaa]">
      <p>This tab lands in an upcoming batch.</p>
      <p className="mt-2 text-xs text-[#777]">
        Next up: {upcoming[tab]}
      </p>
      <p className="mt-3 text-xs text-[#777]">
        Project id (debug): <code className="text-[#cfd8dc]">{projectId}</code>
      </p>
    </div>
  );
}
