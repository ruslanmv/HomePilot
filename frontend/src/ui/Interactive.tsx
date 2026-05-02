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
import { LogIn, Play, Plus, Trash2, Workflow, Search, Filter, RefreshCw, Sparkles, GitBranch, Users } from "lucide-react";
import { createInteractiveApi } from "./interactive/api";
import type { Experience, ExperienceStatus, InteractionType } from "./interactive/types";
import { InteractiveApiError, resolveInteractionType } from "./interactive/types";
import {
  DangerButton,
  EmptyState,
  ErrorBanner,
  Modal,
  PrimaryButton,
  SecondaryButton,
  SkeletonCard,
  StatusBadge,
  ToastProvider,
  useAsyncResource,
  useToast,
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
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<FilterStatus>("all");
  const [confirmingDelete, setConfirmingDelete] = useState<Experience | null>(null);
  const [deleting, setDeleting] = useState(false);

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
  // Two non-alarming states we handle with a friendly panel
  // instead of the red error banner. We inspect the HTTP status
  // (always reliable) rather than regex over free-form messages,
  // so any server-side phrasing — 'no user', 'not authenticated',
  // 'session expired' — routes to the same empty state.
  const serviceOff = resource.errorStatus === 404
    || isInteractiveServiceOff(resource.error || "");
  const authRequired = resource.errorStatus === 401
    || resource.errorCode === "not_authenticated"
    || isInteractiveAuthRequired(resource.error || "");
  const items = resource.data || [];
  const hasProjects = items.length > 0;

  const onConfirmDelete = useCallback(async () => {
    const target = confirmingDelete;
    if (!target || deleting) return;
    setDeleting(true);
    // Optimistic: drop the row immediately; on failure put it back.
    const snapshot = resource.data || [];
    resource.setData((prev) => (prev || []).filter((e) => e.id !== target.id));
    try {
      await api.deleteExperience(target.id);
      toast.toast({
        variant: "success",
        title: "Project deleted",
        message: `"${target.title || "untitled"}" removed.`,
      });
    } catch (err) {
      resource.setData(snapshot);
      const e = err as InteractiveApiError;
      toast.toast({
        variant: "error",
        title: "Couldn't delete the project",
        message: e.message || "The project has been restored.",
      });
    } finally {
      setDeleting(false);
      setConfirmingDelete(null);
    }
  }, [api, confirmingDelete, deleting, resource, toast]);

  return (
    <div className="min-h-full bg-[#0f0f0f] text-[#f1f1f1]">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <Header
          onCreate={onCreateNew}
          onReload={resource.reload}
          reloading={resource.loading && !!resource.data}
          showReload={hasProjects}
          showCreate={hasProjects}
        />

        {/* Progressive disclosure: search + filter chips + "Showing
            N projects" only belong once the user actually has
            projects to search through. Empty / error / first-run
            states hide the toolbar so the hero empty panel is the
            singular focal point of the page. */}
        {hasProjects && (
          <Toolbar
            query={query}
            setQuery={setQuery}
            statusFilter={statusFilter}
            setStatusFilter={setStatusFilter}
            totalCount={totalCount}
            visibleCount={visibleCount}
          />
        )}

        <div className="mt-6">
          {resource.error && !serviceOff && !authRequired ? (
            <ErrorBanner
              title="Couldn't load your interactive projects"
              message={friendlyError(resource.error)}
              onRetry={resource.reload}
            />
          ) : authRequired ? (
            <AuthRequiredEmptyState onRetry={resource.reload} />
          ) : serviceOff ? (
            <ServiceOffEmptyState onCreate={onCreateNew} />
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
              onDelete={(exp) => setConfirmingDelete(exp)}
            />
          )}
        </div>
      </div>

      {/* Confirm destructive delete. Uses the shared Modal primitive
          with DangerButton so the red confirmation color is the
          single signal that this action can't be undone. */}
      <Modal
        open={!!confirmingDelete}
        onClose={() => !deleting && setConfirmingDelete(null)}
        title="Delete project?"
        footer={
          <>
            <SecondaryButton
              onClick={() => setConfirmingDelete(null)}
              disabled={deleting}
            >
              Cancel
            </SecondaryButton>
            <DangerButton
              onClick={onConfirmDelete}
              loading={deleting}
              icon={<Trash2 className="w-4 h-4" aria-hidden />}
            >
              Delete project
            </DangerButton>
          </>
        }
      >
        <p className="text-sm text-[#cfd8dc]">
          This permanently removes{" "}
          <span className="font-medium text-[#f1f1f1]">
            {confirmingDelete?.title || "(untitled)"}
          </span>{" "}
          and every scene, action, rule, publication, and analytics
          row it owns. Sessions already in flight keep running until
          they end, but no new sessions can start.
        </p>
        <p className="text-xs text-[#777] mt-3">
          This action can't be undone.
        </p>
      </Modal>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Header
// ────────────────────────────────────────────────────────────────

function Header({
  onCreate, onReload, reloading, showReload, showCreate,
}: {
  onCreate: () => void;
  onReload: () => void;
  reloading: boolean;
  /** Refresh button only makes sense when we have projects to refresh. */
  showReload: boolean;
  /** New-project button hides in empty state — the hero panel's CTA
   *  handles the action so there's only one focal point. */
  showCreate: boolean;
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
      {(showReload || showCreate) && (
        <div className="flex items-center gap-2 shrink-0">
          {showReload && (
            <SecondaryButton
              onClick={onReload}
              loading={reloading}
              icon={<RefreshCw className="w-4 h-4" aria-hidden />}
              aria-label="Refresh project list"
            >
              Refresh
            </SecondaryButton>
          )}
          {showCreate && (
            <PrimaryButton
              onClick={onCreate}
              icon={<Plus className="w-4 h-4" aria-hidden />}
              aria-label="Create new interactive project"
            >
              New project
            </PrimaryButton>
          )}
        </div>
      )}
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
  items, onOpen, onPlay, onDelete,
}: {
  items: Experience[];
  onOpen: (id: string) => void;
  onPlay: (id: string) => void;
  onDelete: (exp: Experience) => void;
}) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {items.map((exp) => (
        <ProjectCard
          key={exp.id}
          experience={exp}
          onOpen={() => onOpen(exp.id)}
          onPlay={() => onPlay(exp.id)}
          onDelete={() => onDelete(exp)}
        />
      ))}
    </div>
  );
}

// Per-interaction-type accent palette. Two families so the landing
// page reads like the main "Projects" tab — blue for branching
// scene-graph projects, violet for persona-anchored play. Pulled
// out as a const so future surfaces (player chrome, edit modal)
// can reuse the exact tokens.
const TYPE_ACCENTS: Record<
  InteractionType,
  {
    label: string;
    icon: typeof GitBranch;
    /** Top-of-card accent stripe color. */
    stripe: string;
    /** Hover border color. */
    border: string;
    /** Focus ring color. */
    ring: string;
    /** Badge background + border + text colors (Tailwind arbitrary
     *  rgba values so they read as soft pills, not solid blocks). */
    badgeBg: string;
    badgeBorder: string;
    badgeText: string;
  }
> = {
  standard_project: {
    label: "Standard",
    icon: GitBranch,
    stripe: "#3ea6ff",
    border: "#3ea6ff",
    ring: "#3ea6ff",
    badgeBg: "rgba(62,166,255,0.12)",
    badgeBorder: "rgba(62,166,255,0.30)",
    badgeText: "#7dd3fc",
  },
  persona_live_play: {
    label: "Persona Live",
    icon: Users,
    stripe: "#8b5cf6",
    border: "#8b5cf6",
    ring: "#8b5cf6",
    badgeBg: "rgba(139,92,246,0.12)",
    badgeBorder: "rgba(139,92,246,0.30)",
    badgeText: "#c4b5fd",
  },
};


function ProjectCard({
  experience, onOpen, onPlay, onDelete,
}: {
  experience: Experience;
  onOpen: () => void;
  onPlay: () => void;
  onDelete: () => void;
}) {
  const modeLabel = humanizeMode(experience.experience_mode);
  const interactionType = resolveInteractionType(experience);
  const accent = TYPE_ACCENTS[interactionType];
  const TypeIcon = accent.icon;
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
      style={{ "--card-accent": accent.stripe } as React.CSSProperties}
      className={[
        "relative text-left bg-[#1f1f1f] border border-[#3f3f3f] rounded-lg p-5 cursor-pointer",
        "hover:bg-[#282828] transition-colors",
        // Hover & focus colors come from the accent so Standard cards
        // glow blue and Persona Live cards glow violet — the visual
        // distinction is reinforced on every interaction.
        "hover:[border-color:var(--card-accent)]",
        "focus:outline-none focus-visible:ring-2 focus-visible:[--tw-ring-color:var(--card-accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0f0f0f]",
        "flex flex-col gap-3 group",
        // Top accent stripe — ::before-style via an inline element
        // (tailwind doesn't support ::before with CSS vars cleanly).
        "overflow-hidden",
      ].join(" ")}
    >
      {/* Accent stripe along the top edge. Uses the type color so
          the card reads as Standard / Persona Live at a glance. */}
      <div
        aria-hidden
        className="absolute inset-x-0 top-0 h-[3px]"
        style={{ background: accent.stripe }}
      />

      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-[#f1f1f1] truncate">
            {experience.title || "(untitled)"}
          </div>
          <div className="text-xs text-[#777] mt-0.5 truncate">{modeLabel}</div>
        </div>
        {/* Type badge (Standard / Persona Live) — primary visual ID
            for the card. Status badge moves below. */}
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-medium whitespace-nowrap"
          style={{
            background: accent.badgeBg,
            borderColor: accent.badgeBorder,
            color: accent.badgeText,
          }}
        >
          <TypeIcon className="w-3 h-3" aria-hidden />
          {accent.label}
        </span>
      </div>
      <div className="flex items-center justify-end -mt-1.5">
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

      {/* Floating action row (bottom-right), appears on hover/focus
          so the card's primary intent stays "open editor". Every
          button stops propagation so clicking them doesn't also
          open the editor. */}
      <div
        className={[
          "absolute bottom-3 right-3 inline-flex items-center gap-2",
          "opacity-0 group-hover:opacity-100 focus-within:opacity-100",
          "transition-opacity",
        ].join(" ")}
      >
        {/* Delete — ghost icon button. Triggers the parent's
            confirm modal instead of deleting outright. */}
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onDelete(); }}
          aria-label={`Delete ${experience.title || "project"}`}
          title="Delete project"
          className={[
            "w-7 h-7 rounded-full inline-flex items-center justify-center",
            "bg-white/5 border border-white/10 text-[#aaa]",
            "hover:bg-red-500/15 hover:border-red-500/40 hover:text-red-300",
            "transition-colors",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2 focus-visible:ring-offset-[#1f1f1f]",
          ].join(" ")}
        >
          <Trash2 className="w-3.5 h-3.5" aria-hidden />
        </button>

        {/* Play — primary pill. */}
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onPlay(); }}
          aria-label={`Play ${experience.title || "project"} live`}
          className={[
            "inline-flex items-center gap-1.5",
            "px-2.5 py-1 rounded-full text-xs font-medium",
            "bg-[#3ea6ff] text-black",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#1f1f1f]",
          ].join(" ")}
        >
          <Play className="w-3 h-3" aria-hidden />
          Play
        </button>
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Empty states
// ────────────────────────────────────────────────────────────────

function FirstRunEmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    // Onboarding focus: one icon, one headline, one secondary
    // line, one action. Matches Animate's empty-state rhythm so
    // both tabs feel like siblings under the HomePilot brand.
    <HeroEmptyPanel
      icon={<Workflow className="w-10 h-10" aria-hidden />}
      title="No projects yet"
      description="Create your first interactive experience — branching stories, training flows, or lessons."
      cta={
        <PrimaryButton onClick={onCreate} icon={<Plus className="w-4 h-4" aria-hidden />} size="lg">
          Create project
        </PrimaryButton>
      }
    />
  );
}

function ServiceOffEmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <HeroEmptyPanel
      icon={<Sparkles className="w-10 h-10" aria-hidden />}
      title="Your interactive gallery is empty"
      description={
        <>
          The interactive backend isn't enabled on this server yet.
          Ask an operator to set{" "}
          <code className="px-1 py-0.5 rounded bg-[#1a1a1a] border border-[#3f3f3f] text-[#cfd8dc]">
            INTERACTIVE_ENABLED=true
          </code>{" "}
          and restart the API. Meanwhile, you can still walk through the
          new-project flow to preview what it looks like.
        </>
      }
      cta={
        <PrimaryButton onClick={onCreate} icon={<Plus className="w-4 h-4" aria-hidden />} size="lg">
          Preview new project flow
        </PrimaryButton>
      }
    />
  );
}

function AuthRequiredEmptyState({ onRetry }: { onRetry: () => void }) {
  return (
    <HeroEmptyPanel
      icon={<LogIn className="w-10 h-10" aria-hidden />}
      title="Sign in to see your interactive projects"
      description="Projects are owner-scoped, so we need a signed-in user to show them. If you just signed in, retry below — the session cookie sometimes lands a moment late."
      cta={
        <SecondaryButton onClick={onRetry} icon={<RefreshCw className="w-4 h-4" aria-hidden />}>
          Try again
        </SecondaryButton>
      }
    />
  );
}

function HeroEmptyPanel({
  icon, title, description, cta,
}: {
  icon: React.ReactNode;
  title: string;
  description: React.ReactNode;
  cta: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-[#3f3f3f] bg-[#121212] px-6 py-12 text-center max-w-4xl mx-auto">
      {/* Icon tile picks up a subtle violet tint — matches the
          purple filmstrip that Animate uses for its empty state,
          so the two features visibly share a design language. */}
      <div className="w-16 h-16 mx-auto mb-5 rounded-2xl bg-[#8b5cf6]/15 border border-[#8b5cf6]/30 flex items-center justify-center text-[#c4b5fd]">
        {icon}
      </div>
      <h2 className="text-2xl font-semibold text-[#f1f1f1]">{title}</h2>
      <p className="text-sm text-[#aaa] mt-3 max-w-xl mx-auto leading-relaxed">{description}</p>
      <div className="mt-6 flex justify-center">{cta}</div>
    </section>
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

/** A 404 / not_found on /experiences means the interactive router
 *  isn't mounted — INTERACTIVE_ENABLED is off or the backend is an
 *  older build. Distinct from real errors so we can render a
 *  friendly empty state instead of a red alarm. */
function isInteractiveServiceOff(message: string): boolean {
  return /\b404\b|not[_ ]found/i.test(message);
}

/** A 401 / not_authenticated means the viewer resolver rejected
 *  the request — cookie missing, expired, or users table has a
 *  profile we can't auto-match. Renders a "sign in" empty state
 *  instead of a raw error. */
function isInteractiveAuthRequired(message: string): boolean {
  return /\b401\b|not[_ ]authenticated|unauthorized/i.test(message);
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
