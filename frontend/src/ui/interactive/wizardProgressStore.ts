/**
 * Wizard progress store — module-level singleton that survives tab
 * unmounts.
 *
 * Why
 * ---
 * The Interactive wizard's "Generating scenes…" modal used to live as
 * local React state inside ``WizardAutoPreview``. When the user clicked
 * away to Chat / Imagine / Voice mid-generation, ``InteractiveHost``
 * unmounted, the wizard component went with it, the SSE stream got
 * cancelled, and the modal vanished — even though the backend was
 * still rendering scenes. Coming back showed nothing because the
 * AbortController fired on unmount and the new mount started fresh.
 *
 * What this gives us
 * ------------------
 * One store at module scope. State persists across mount/unmount of
 * any consumer. The SSE stream is owned here, not in any one
 * component, so navigating away doesn't tear it down. A single
 * ``<WizardProgressOverlay />`` rendered at App level reads the same
 * store and stays visible across tabs.
 *
 * Usage
 * -----
 * ```tsx
 * // From the wizard:
 * await wizardProgressStore.startGeneration({ api, payload, onDone });
 *
 * // From any component (incl. App):
 * const state = useWizardProgress();
 * if (state.active) <WizardProgressOverlay />;
 * ```
 *
 * The store is intentionally tiny — no Redux, no Zustand, no ts-pattern.
 * ``useSyncExternalStore`` is the React 18 primitive built for this.
 */
import { useSyncExternalStore } from "react";
import type { InteractiveApi } from "./api";
import type { AutoGenerateResult } from "./types";

type GenerateAllResult = AutoGenerateResult;

export type WizardProgressEventType =
  | "rendering_started"
  | "rendering_scene"
  | "scene_rendered"
  | "scene_skipped"
  | "scene_render_failed"
  | "library_build_started"
  | "library_asset_rendered"
  | "library_asset_failed"
  | "library_build_done"
  | "scene_linked"
  // Expert-mode chain-of-thought events. Forwarded as-is from the
  // backend planner / workflow runner so the expert log panel can
  // display CrewAI-style step traces.
  | "planner_thought"
  | "workflow_started"
  | "workflow_completed"
  | "step_started"
  | "step_completed"
  | "step_failed"
  | "llm_step_started"
  | "llm_step_completed"
  | "llm_step_failed";

export interface ExpertLogEntry {
  /** Sequential id, monotonic per ``startGeneration`` call. */
  id: number;
  /** Wall-clock millis when the entry was added. */
  ts: number;
  /** Raw SSE event type. */
  type: string;
  /** Short human-readable label derived from the event for display. */
  label: string;
  /** One-line summary built from the payload (e.g. preview text). */
  summary: string;
  /** Full payload for the "show details" expander. */
  payload: Record<string, unknown>;
  /** "thought" | "step" | "llm" | "phase" — used for visual grouping. */
  kind: "thought" | "step" | "llm" | "phase" | "render";
  /** Set when the event represents a failure path. */
  failed?: boolean;
}

export interface WizardProgressState {
  /** True from the moment ``startGeneration`` is called until the
   *  flow either resolves with a result or fails. */
  active: boolean;
  /** Active step index (0..N-1) into the wizard's GENERATE_STEPS. */
  genStep: number;
  /** Total number of scene targets reported by ``rendering_started``. */
  renderTotal: number;
  /** Number of scenes successfully rendered or skipped. */
  renderDone: number;
  /** Subset of ``renderDone`` that were skipped vs successful. */
  renderSkipped: number;
  /** Title of the scene currently being rendered (UI hint). */
  currentSceneTitle: string;
  /** Set when generation fails before producing a result. */
  error: string | null;
  /** Resolved when generation completes with a usable scene graph. */
  result: GenerateAllResult | null;
  /** The experience id created at the start of the run. The wizard
   *  reads this to navigate to the editor when the run finishes
   *  while the wizard is still mounted; when the user has navigated
   *  away the global overlay shows an "Open project" button that
   *  reuses this id. */
  experienceId: string | null;
  /** Persona library build phase events surfaced separately so the
   *  modal can show ("Tier 1: 5/9 ready") without conflating with
   *  the scene-render counter. */
  libraryTotal: number;
  libraryDone: number;
  libraryFailed: number;
  /** Expert-mode chain-of-thought log. Always populated regardless of
   *  whether the panel is visible — the toggle just decides display.
   *  Capped at MAX_EXPERT_LOG entries to keep memory bounded on long
   *  runs (a 60-scene render can emit 120+ events). */
  expertLog: ExpertLogEntry[];
}

const MAX_EXPERT_LOG = 200;

const initialState: WizardProgressState = {
  active: false,
  genStep: 0,
  renderTotal: 0,
  renderDone: 0,
  renderSkipped: 0,
  currentSceneTitle: "",
  error: null,
  result: null,
  experienceId: null,
  libraryTotal: 0,
  libraryDone: 0,
  libraryFailed: 0,
  expertLog: [],
};

let expertLogSeq = 0;

function _classifyEvent(type: string): ExpertLogEntry["kind"] {
  if (type === "planner_thought") return "thought";
  if (type.startsWith("llm_step")) return "llm";
  if (type === "workflow_started" || type === "workflow_completed"
      || type === "step_started" || type === "step_completed"
      || type === "step_failed") return "step";
  if (type.startsWith("rendering_") || type.startsWith("scene_")
      || type.startsWith("library_")) return "render";
  return "phase";
}

function _summarizeEvent(
  type: string, payload: Record<string, unknown>,
): { label: string; summary: string } {
  const p = payload || {};
  const peek = (k: string): string => {
    const v = p[k];
    return typeof v === "string" ? v : v == null ? "" : String(v);
  };
  switch (type) {
    case "planner_thought":
      return { label: peek("label") || "Planner thinking",
               summary: [peek("path"), peek("error")].filter(Boolean).join(" · ") };
    case "workflow_started":
      return { label: `Workflow → ${peek("workflow") || "?"}`,
               summary: `${(p.step_ids as unknown[] || []).length} step(s)` };
    case "workflow_completed":
      return { label: `Workflow ${peek("ok") === "true" || p.ok ? "complete" : "ended"}`,
               summary: `${peek("duration_ms") || "?"} ms` };
    case "step_started":
      return { label: `Step → ${peek("step_id") || peek("prompt_id") || "?"}`,
               summary: `prompt=${peek("prompt_id") || "?"}` };
    case "step_completed":
      return { label: `Step ✓ ${peek("step_id") || "?"}`,
               summary: peek("preview") || `${peek("duration_ms") || "?"} ms` };
    case "step_failed":
      return { label: `Step ✗ ${peek("step_id") || "?"}`,
               summary: peek("reason") || "failed" };
    case "llm_step_started":
      return { label: `LLM call → ${peek("step_id") || "?"}`,
               summary: peek("user_preview") || peek("system_preview") || "" };
    case "llm_step_completed":
      return { label: `LLM ✓ ${peek("step_id") || "?"}`,
               summary: peek("preview") || `${peek("output_chars") || "?"} chars` };
    case "llm_step_failed":
      return { label: `LLM ✗ ${peek("step_id") || "?"}`,
               summary: peek("reason") || "failed" };
    case "rendering_scene":
      return { label: `Rendering scene ${peek("index") || ""}/${peek("total") || ""}`,
               summary: peek("title") };
    case "scene_rendered":
      return { label: "Scene rendered", summary: peek("title") || peek("scene_id") };
    case "scene_skipped":
      return { label: "Scene skipped", summary: peek("title") || peek("reason") || "" };
    case "scene_render_failed":
      return { label: "Scene render failed",
               summary: peek("reason") || peek("title") };
    default:
      return { label: type, summary: "" };
  }
}

function _appendExpertLog(
  type: string, payload: Record<string, unknown>,
): void {
  const { label, summary } = _summarizeEvent(type, payload);
  const entry: ExpertLogEntry = {
    id: ++expertLogSeq,
    ts: Date.now(),
    type,
    label,
    summary,
    payload,
    kind: _classifyEvent(type),
    failed: type.endsWith("_failed"),
  };
  const next = state.expertLog.length >= MAX_EXPERT_LOG
    ? [...state.expertLog.slice(-MAX_EXPERT_LOG + 1), entry]
    : [...state.expertLog, entry];
  setState({ expertLog: next });
}

let state: WizardProgressState = { ...initialState };
const subscribers = new Set<() => void>();

function emit(): void {
  subscribers.forEach((fn) => {
    try { fn(); }
    catch { /* a subscriber bug must not crash the store */ }
  });
}

function setState(patch: Partial<WizardProgressState>): void {
  state = { ...state, ...patch };
  emit();
}

function subscribe(fn: () => void): () => void {
  subscribers.add(fn);
  return () => { subscribers.delete(fn); };
}

function getSnapshot(): WizardProgressState {
  return state;
}

/**
 * Subscribe to the store from a React component.
 *
 * The component re-renders whenever any field on the state changes.
 * Cheap because we never mutate the state object — every update goes
 * through ``setState`` which produces a new reference.
 */
export function useWizardProgress(): WizardProgressState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

// ── Phase-name → step-index map ──────────────────────────────────
//
// Mirrors the GENERATE_STEPS labels in WizardAutoPreview so the
// modal's progress dots advance as the SSE feed reports phase events.
// Kept here so the store doesn't need to import WizardAutoPreview.
const STEP_INDEX_BY_PHASE: Record<string, number> = {
  started: 0,
  generating_graph: 1,
  graph_generated: 2,
  persisting_nodes: 2,
  persisting_edges: 2,
  persisting_actions: 2,
  seeding_rule: 2,
  running_qa: 2,
  qa_done: 2,
  rendering_started: 3,
  rendering_scene: 3,
  scene_rendered: 3,
  scene_skipped: 3,
  scene_render_failed: 3,
  scene_deferred: 3,
  rendering_done: 3,
  library_build_started: 3,
  library_rendering_asset: 3,
  library_asset_rendered: 3,
  library_asset_failed: 3,
  library_build_done: 3,
  scene_linked: 4,
  done: 4,
  result: 4,
};

function _stepIndexForPhase(phase: string): number | null {
  const idx = STEP_INDEX_BY_PHASE[phase];
  return typeof idx === "number" ? idx : null;
}

// ── Public entry point ──────────────────────────────────────────

interface StartGenerationArgs {
  api: InteractiveApi;
  payload: Parameters<InteractiveApi["createExperience"]>[0];
  onCreated?: (experienceId: string) => void;
  /** Total number of phases the wizard renders as steps. The store
   *  caps ``genStep`` so the final state visible after completion
   *  still reads "Opening the editor" (last step). */
  totalSteps: number;
}

/**
 * Run the full create-experience + generate-all SSE flow against the
 * backend. Updates the store as events arrive. Resolves when the run
 * finishes (success or fail).
 *
 * Safe to call again after a previous run finishes — the store is
 * reset to the initial state at the top of each call. NOT safe to
 * call concurrently — the second call will clobber the first run's
 * counters. The wizard's submit button is disabled while
 * ``state.active`` is true; that's the gate.
 */
export async function startGeneration(
  args: StartGenerationArgs,
): Promise<GenerateAllResult | null> {
  expertLogSeq = 0;
  setState({
    ...initialState,
    active: true,
  });

  let createdId: string | null = null;
  try {
    const created = await args.api.createExperience(args.payload);
    createdId = created.id;
    setState({ experienceId: created.id, genStep: 1 });
    args.onCreated?.(created.id);

    const result = await args.api.generateAllStream(created.id, {
      onEvent: (ev) => {
        // Always append to the expert log first — the panel is the
        // most useful when the run is failing, and tossing entries
        // before phase logic short-circuits would lose evidence.
        _appendExpertLog(
          ev.type,
          (ev.payload as Record<string, unknown>) || {},
        );

        const idx = _stepIndexForPhase(ev.type);
        if (idx !== null) {
          setState({ genStep: Math.max(state.genStep, idx) });
        }

        if (ev.type === "rendering_started") {
          const total = Number((ev.payload as any)?.total || 0);
          setState({ renderTotal: total, renderDone: 0, renderSkipped: 0 });
        }

        if (ev.type === "rendering_scene") {
          const title = String((ev.payload as any)?.title || "");
          if (title) setState({ currentSceneTitle: title });
        }

        if (ev.type === "scene_rendered") {
          setState({ renderDone: state.renderDone + 1 });
        }

        if (ev.type === "scene_skipped" || ev.type === "scene_render_failed") {
          setState({
            renderDone: state.renderDone + 1,
            renderSkipped: state.renderSkipped + 1,
          });
        }

        // Persona library build events — surfaced under a separate
        // counter so a 5-asset library build doesn't pollute the
        // scene-render percentage that drives the main progress bar.
        if (ev.type === "library_build_started") {
          const total = Number((ev.payload as any)?.total || 0);
          setState({ libraryTotal: total, libraryDone: 0, libraryFailed: 0 });
        }
        if (ev.type === "library_asset_rendered") {
          setState({ libraryDone: state.libraryDone + 1 });
        }
        if (ev.type === "library_asset_failed") {
          setState({
            libraryDone: state.libraryDone + 1,
            libraryFailed: state.libraryFailed + 1,
          });
        }
      },
    });

    setState({
      genStep: Math.max(state.genStep, args.totalSteps - 1),
      result,
      active: false,
    });
    return result;
  } catch (err) {
    const message =
      err instanceof Error ? err.message : "Generation failed.";
    setState({
      error: message,
      active: false,
      experienceId: createdId,
    });
    return null;
  }
}

/**
 * Drop the result + error AFTER the wizard has consumed them. The
 * global overlay listens for ``state.active===false && state.result``
 * to show the "Done" state with an Open Project button; once the
 * wizard navigates to the editor, it calls this so a future run
 * doesn't show stale state.
 */
export function clearGeneration(): void {
  state = { ...initialState };
  emit();
}

/**
 * Reset just the active flag without losing the result — used when
 * the wizard navigates the user to the editor after the SSE finished.
 */
export function dismissOverlay(): void {
  setState({ active: false });
}
