/**
 * InteractiveView — landing page for the "Interactive" tab.
 *
 * Sits alongside Animate and Studio as a first-class top-level
 * tab. Renders a responsive grid of existing interactive-video
 * experiences (one card each) with:
 *
 *   - Skeleton grid while fetching
 *   - Typed error banner with retry on failure
 *   - Empty state with primary CTA on zero results
 *   - Toolbar with search + status filter + "New project" button
 *   - Keyboard-navigable project cards
 *   - Responsive columns (1 / 2 / 3 at md / lg breakpoints)
 *
 * Data source: GET /v1/interactive/experiences (owner-scoped).
 * Clicking a card hands the experience id up to the parent so
 * App.tsx can mount <InteractiveHost projectId=... /> on top of
 * this view. Creating from the "New project" button switches
 * directly to the wizard without navigating away.
 *
 * The landing view deliberately does no project-level mutation —
 * rename / delete / duplicate live inside the editor where the
 * destructive action is surfaced with a confirmation modal.
 */

import React, { useMemo, useState, useCallback } from "react";
import { Play, Plus, Workflow, Search, Filter, RefreshCw } from "lucide-react";
import { createInteractiveApi } from "./interactive/api";
import type { Experience, ExperienceStatus } from "./interactive/types";
import { InteractiveApiError } from "./interactive/types";
import {
  EmptyState,
  ErrorBanner,
  PrimaryButton,
  SecondaryButton,
  SkeletonCard,
  StatusBadge,
  ToastProvider,
  useAsyncResource,
} from "./interactive/ui";

type FilterStatus = "all" | ExperienceStatus;

interface Props {
  backendUrl: string;
  apiKey?: string;
  /** Called when the user opens an existing project card (editor). */
  onOpenProject: (id: string) => void;
  /** Called when the user hits the "New project" primary button. */
  onCreateNew: () => void;
  /** Called when the user hits the "Play" action on a card. */
  onPlayProject: (id: string) => void;
}

export default function InteractiveView(props: Props) {
  return (
    <ToastProvider>
      <InteractiveViewBody {...props} />
    </ToastProvider>
  );
}

function InteractiveViewBody({
  backendUrl, apiKey, onOpenProject, onCreateNew, onPlayProject,
}: Props) {
  const api = useMemo(() => createInteractiveApi(backendUrl, apiKey), [backendUrl, apiKey]);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<FilterStatus>("all");

  const resource = useAsyncResource<Experience[]>(
    (signal) => api.listExperiences(signal),
    [api],
  );

  const filtered = useMemo(() => {
    const items = resource.data || [];
    const q = query.trim().toLowerCase();
    return items.filter((e) => {
      if (statusFilter !== "all" && e.status !== statusFilter) return false;
      if (!q) return true;
      const haystack = [
        e.title || "", e.description || "", e.experience_mode || "",
      ].join(" ").toLowerCase();
      return haystack.includes(q);
    });
  }, [resource.data, query, statusFilter]);

  const totalCount = resource.data?.length ?? 0;
  const visibleCount = filtered.length;

  return (
    <div className="min-h-full bg-[#0f0f0f] text-[#f1f1f1]">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <Header
          onCreate={onCreateNew}
          onReload={resource.reload}
          reloading={resource.loading && !!resource.data}
        />

        <Toolbar
          query={query}
          setQuery={setQuery}
          statusFilter={statusFilter}
          setStatusFilter={setStatusFilter}
          totalCount={totalCount}
          visibleCount={visibleCount}
        />

        <div className="mt-6">
          {resource.error ? (
            <ErrorBanner
              title="Couldn't load your interactive projects"
              message={friendlyError(resource.error)}
              onRetry={resource.reload}
            />
          ) : resource.loading && !resource.data ? (
            <LoadingGrid />
          ) : (resource.data || []).length === 0 ? (
            <FirstRunEmptyState onCreate={onCreateNew} />
          ) : filtered.length === 0 ? (
            <FilteredEmptyState onClear={() => { setQuery(""); setStatusFilter("all"); }} />
          ) : (
            <Grid
              items={filtered}
              onOpen={onOpenProject}
              onPlay={onPlayProject}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Header
// ────────────────────────────────────────────────────────────────

function Header({
  onCreate, onReload, reloading,
}: {
  onCreate: () => void;
  onReload: () => void;
  reloading: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 flex-wrap">
      <div>
        <h1 className="text-2xl font-medium flex items-center gap-3">
          <Workflow className="w-6 h-6 text-[#3ea6ff]" aria-hidden />
          Interactive
        </h1>
        <p className="text-sm text-[#aaa] mt-1 max-w-2xl">
          Branching AI video experiences — scripts, scenes, and viewer choices
          that adapt in real time. One workflow for education, training,
          language practice, and social storytelling.
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <SecondaryButton
          onClick={onReload}
          loading={reloading}
          icon={<RefreshCw className="w-4 h-4" aria-hidden />}
          aria-label="Refresh project list"
        >
          Refresh
        </SecondaryButton>
        <PrimaryButton
          onClick={onCreate}
          icon={<Plus className="w-4 h-4" aria-hidden />}
          aria-label="Create new interactive project"
        >
          New project
        </PrimaryButton>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Toolbar (search + status filter)
// ────────────────────────────────────────────────────────────────

const STATUS_FILTER_LABELS: Array<{ value: FilterStatus; label: string }> = [
  { value: "all", label: "All" },
  { value: "draft", label: "Draft" },
  { value: "in_review", label: "In review" },
  { value: "approved", label: "Approved" },
  { value: "published", label: "Published" },
  { value: "archived", label: "Archived" },
];

function Toolbar({
  query, setQuery, statusFilter, setStatusFilter, totalCount, visibleCount,
}: {
  query: string;
  setQuery: (v: string) => void;
  statusFilter: FilterStatus;
  setStatusFilter: (v: FilterStatus) => void;
  totalCount: number;
  visibleCount: number;
}) {
  return (
    <div className="mt-6 flex flex-col md:flex-row gap-3 md:items-center md:justify-between">
      <div className="flex gap-3 flex-1 min-w-0">
        <label className="relative flex-1 min-w-0 max-w-md">
          <span className="sr-only">Search projects</span>
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#777]" aria-hidden />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by title, mode, or description"
            className="w-full bg-[#121212] border border-[#3f3f3f] rounded-md pl-9 pr-3 py-2 text-sm outline-none focus:border-[#3ea6ff] focus:ring-1 focus:ring-[#3ea6ff]/50 transition-colors"
            aria-label="Search projects"
          />
        </label>
        <div
          className="flex items-center gap-1 border border-[#3f3f3f] bg-[#121212] rounded-md p-1"
          role="group" aria-label="Filter by status"
        >
          <Filter className="w-4 h-4 text-[#777] mx-1" aria-hidden />
          {STATUS_FILTER_LABELS.map((f) => (
            <button
              key={f.value}
              type="button"
              onClick={() => setStatusFilter(f.value)}
              aria-pressed={statusFilter === f.value}
              className={[
                "px-2.5 py-1 rounded text-xs transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff]",
                statusFilter === f.value
                  ? "bg-[#3ea6ff] text-black font-medium"
                  : "text-[#aaa] hover:text-[#f1f1f1] hover:bg-[#1f1f1f]",
              ].join(" ")}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>
      <div className="text-xs text-[#777] shrink-0" aria-live="polite">
        Showing <span className="text-[#f1f1f1] font-medium">{visibleCount}</span>
        {totalCount > 0 && totalCount !== visibleCount && (
          <> of <span className="text-[#f1f1f1] font-medium">{totalCount}</span></>
        )}
        {" "}{totalCount === 1 ? "project" : "projects"}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Grid + cards
// ────────────────────────────────────────────────────────────────

function Grid({
  items, onOpen, onPlay,
}: {
  items: Experience[];
  onOpen: (id: string) => void;
  onPlay: (id: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {items.map((exp) => (
        <ProjectCard
          key={exp.id}
          experience={exp}
          onOpen={() => onOpen(exp.id)}
          onPlay={() => onPlay(exp.id)}
        />
      ))}
    </div>
  );
}

function ProjectCard({
  experience, onOpen, onPlay,
}: {
  experience: Experience;
  onOpen: () => void;
  onPlay: () => void;
}) {
  const modeLabel = humanizeMode(experience.experience_mode);
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      onOpen();
    }
  };
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={onKeyDown}
      aria-label={`Open ${experience.title || "untitled project"} in editor`}
      className={[
        "relative text-left bg-[#1f1f1f] border border-[#3f3f3f] rounded-lg p-5 cursor-pointer",
        "hover:bg-[#282828] hover:border-[#555] transition-colors",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0f0f0f]",
        "flex flex-col gap-3 group",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-[#f1f1f1] truncate">
            {experience.title || "(untitled)"}
          </div>
          <div className="text-xs text-[#777] mt-0.5 truncate">{modeLabel}</div>
        </div>
        <StatusBadge status={experience.status} />
      </div>

      <p className="text-xs text-[#aaa] line-clamp-2 min-h-[2.25rem]">
        {experience.description || experience.objective || "No description yet."}
      </p>

      <div className="mt-auto flex items-center gap-3 text-[11px] text-[#777]">
        <span>
          <span className="text-[#cfd8dc] font-medium">{experience.branch_count ?? 0}</span>{" "}
          {experience.branch_count === 1 ? "branch" : "branches"}
        </span>
        <span className="text-[#3f3f3f]">•</span>
        <span>
          depth <span className="text-[#cfd8dc] font-medium">{experience.max_depth ?? 0}</span>
        </span>
        {experience.updated_at && (
          <>
            <span className="text-[#3f3f3f]">•</span>
            <span className="truncate">updated {relativeTime(experience.updated_at)}</span>
          </>
        )}
      </div>

      {/* Play action — floating bottom-right, appears on hover/focus
          so the card's primary intent stays "open editor". Stops
          propagation so clicking Play doesn't also open the editor. */}
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); onPlay(); }}
        aria-label={`Play ${experience.title || "project"} live`}
        className={[
          "absolute bottom-3 right-3 inline-flex items-center gap-1.5",
          "px-2.5 py-1 rounded-full text-xs font-medium",
          "bg-[#3ea6ff] text-black",
          "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
          "transition-opacity",
          "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#1f1f1f]",
        ].join(" ")}
      >
        <Play className="w-3 h-3" aria-hidden />
        Play
      </button>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Empty states
// ────────────────────────────────────────────────────────────────

function FirstRunEmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <EmptyState
      icon={<Workflow className="w-12 h-12" />}
      title="No interactive projects yet"
      description="Start from a prompt — we'll plan the branches, seed the scene graph, and let you edit actions, rules, and policy before publishing."
      action={
        <PrimaryButton onClick={onCreate} icon={<Plus className="w-4 h-4" aria-hidden />} size="lg">
          Create your first project
        </PrimaryButton>
      }
    />
  );
}

function FilteredEmptyState({ onClear }: { onClear: () => void }) {
  return (
    <EmptyState
      icon={<Search className="w-12 h-12" />}
      title="No projects match your filters"
      description="Try clearing the search query or switching status filters to see more."
      action={<SecondaryButton onClick={onClear}>Clear filters</SecondaryButton>}
    />
  );
}

// ────────────────────────────────────────────────────────────────
// Loading grid (first paint)
// ────────────────────────────────────────────────────────────────

function LoadingGrid() {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" aria-busy="true">
      {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Helpers
// ────────────────────────────────────────────────────────────────

function humanizeMode(mode: string): string {
  const map: Record<string, string> = {
    sfw_general: "General",
    sfw_education: "Education",
    language_learning: "Language learning",
    enterprise_training: "Enterprise training",
    social_romantic: "Social / Romantic",
    mature_gated: "Mature (gated)",
  };
  return map[mode] || mode.replace(/_/g, " ");
}

function friendlyError(message: string): string {
  if (!message) return "Unexpected error.";
  if (/NetworkError|Failed to fetch|Network error/i.test(message)) {
    return "Couldn't reach the backend. Check your connection or server URL and try again.";
  }
  if (/401|not_authenticated/i.test(message)) {
    return "You're signed out or your API key is missing. Open Settings to fix it.";
  }
  if (/503|service_disabled/i.test(message)) {
    return "The interactive service is currently disabled on this backend.";
  }
  return message;
}

function relativeTime(iso: string): string {
  const then = Date.parse(iso);
  if (!then || Number.isNaN(then)) return "";
  const diffMs = Date.now() - then;
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months}mo ago`;
  const years = Math.floor(months / 12);
  return `${years}y ago`;
}

export { InteractiveApiError };
