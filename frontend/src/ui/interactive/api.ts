/**
 * Typed HTTP client for the interactive service.
 *
 * One reason to keep this in a dedicated module:
 *   - All routes live under `/v1/interactive/*`
 *   - All error shapes are the uniform `{code, error, data}` dict
 *     produced by `routes/_common.http_error_from`
 *   - Downstream components can import `createInteractiveApi` and
 *     never touch `fetch`, so swapping auth / retry / tracing
 *     becomes a one-file edit.
 *
 * Design notes:
 *   - The client accepts `backendUrl` + `apiKey` up-front so hook
 *     callers don't re-build it on every render.
 *   - Every method returns a `Promise<T>` with a typed shape.
 *   - Failures are normalized to `InteractiveApiError` with the
 *     backend `code` preserved so callers can branch on it
 *     (e.g. `err.code === "invalid_input"`).
 *   - `AbortSignal` threaded through so React effects can cancel
 *     in-flight requests on unmount.
 */

import {
  ActionItem,
  AnalyticsSummary,
  ChatResult,
  EdgeItem,
  Experience,
  ExperienceMode,
  HealthInfo,
  InteractiveApiError,
  NodeItem,
  PendingResult,
  PlanIntent,
  PlanningPreset,
  PublishResult,
  Publication,
  QAResult,
  RuleItem,
} from "./types";

export interface InteractiveApi {
  // Meta
  health(signal?: AbortSignal): Promise<HealthInfo>;
  listPresets(signal?: AbortSignal): Promise<PlanningPreset[]>;

  // Experiences
  listExperiences(signal?: AbortSignal): Promise<Experience[]>;
  getExperience(id: string, signal?: AbortSignal): Promise<Experience>;
  createExperience(input: Partial<Experience>): Promise<Experience>;
  patchExperience(id: string, patch: Partial<Experience>): Promise<Experience>;
  deleteExperience(id: string): Promise<void>;

  // Planner
  plan(req: { prompt: string; mode: ExperienceMode; audience_hints?: Record<string, unknown> }): Promise<PlanIntent>;
  seedGraph(
    id: string,
    req: { prompt: string; mode: ExperienceMode; audience_hints?: Record<string, unknown> },
  ): Promise<{ already_seeded: boolean; node_count: number; edge_count: number }>;

  // Graph
  listNodes(id: string, signal?: AbortSignal): Promise<NodeItem[]>;
  listEdges(id: string, signal?: AbortSignal): Promise<EdgeItem[]>;

  // Catalog
  listActions(id: string, signal?: AbortSignal): Promise<ActionItem[]>;
  createAction(id: string, payload: Partial<ActionItem> & { label: string }): Promise<ActionItem>;
  deleteAction(actionId: string): Promise<void>;

  // Rules
  listRules(id: string, signal?: AbortSignal): Promise<RuleItem[]>;
  createRule(
    id: string,
    payload: { name: string; condition: Record<string, unknown>; action: Record<string, unknown>; priority?: number; enabled?: boolean },
  ): Promise<RuleItem>;
  deleteRule(ruleId: string): Promise<void>;

  // QA + Publish
  runQa(id: string): Promise<QAResult>;
  latestReport(id: string, signal?: AbortSignal): Promise<{ report: Record<string, unknown> }>;
  publish(id: string, channel: string): Promise<PublishResult>;
  listPublications(id: string, signal?: AbortSignal): Promise<Publication[]>;

  // Analytics
  experienceAnalytics(id: string, signal?: AbortSignal): Promise<AnalyticsSummary>;

  // Live-play (PLAY-*)
  chat(sessionId: string, req: { text: string; viewer_region?: string }): Promise<ChatResult>;
  pending(
    sessionId: string,
    opts?: { since_id?: string; limit?: number },
    signal?: AbortSignal,
  ): Promise<PendingResult>;
}

export function createInteractiveApi(
  backendUrl: string, apiKey?: string,
): InteractiveApi {
  const base = backendUrl.replace(/\/+$/, "") + "/v1/interactive";
  const authHeaders: Record<string, string> = apiKey
    ? { "x-api-key": apiKey.trim() }
    : {};

  async function call<T>(
    path: string,
    init: RequestInit = {},
    signal?: AbortSignal,
  ): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...authHeaders,
      ...(init.headers as Record<string, string> | undefined),
    };
    let res: Response;
    try {
      res = await fetch(`${base}${path}`, { ...init, headers, signal });
    } catch (err) {
      if ((err as Error).name === "AbortError") throw err;
      throw new InteractiveApiError(
        `Network error contacting ${path}: ${(err as Error).message}`,
        0, "network_error",
      );
    }
    const contentType = res.headers.get("content-type") || "";
    const isJson = contentType.includes("application/json");
    const body = isJson ? await res.json().catch(() => ({})) : await res.text();
    if (!res.ok) {
      const detail = (isJson && (body as { detail?: unknown }).detail) || body;
      if (detail && typeof detail === "object") {
        const d = detail as { code?: string; error?: string; data?: Record<string, unknown> };
        throw new InteractiveApiError(
          d.error || `HTTP ${res.status}`,
          res.status, d.code || "http_error", d.data || {},
        );
      }
      throw new InteractiveApiError(
        typeof detail === "string" ? detail : `HTTP ${res.status}`,
        res.status, "http_error",
      );
    }
    return body as T;
  }

  return {
    health: (signal) => call<HealthInfo>("/health", { method: "GET" }, signal),

    listPresets: (signal) =>
      call<{ items: PlanningPreset[] }>("/presets", { method: "GET" }, signal)
        .then((r) => r.items),

    listExperiences: (signal) =>
      call<{ items: Experience[] }>("/experiences", { method: "GET" }, signal)
        .then((r) => r.items),

    getExperience: (id, signal) =>
      call<{ experience: Experience }>(`/experiences/${encodeURIComponent(id)}`, { method: "GET" }, signal)
        .then((r) => r.experience),

    createExperience: (input) =>
      call<{ experience: Experience }>("/experiences", {
        method: "POST",
        body: JSON.stringify(input),
      }).then((r) => r.experience),

    patchExperience: (id, patch) =>
      call<{ experience: Experience }>(`/experiences/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      }).then((r) => r.experience),

    deleteExperience: (id) =>
      call<{ ok: boolean }>(`/experiences/${encodeURIComponent(id)}`, { method: "DELETE" })
        .then(() => undefined),

    plan: (req) =>
      call<{ intent: PlanIntent }>("/plan", {
        method: "POST",
        body: JSON.stringify(req),
      }).then((r) => r.intent),

    seedGraph: (id, req) =>
      call<{ already_seeded: boolean; node_count: number; edge_count: number }>(
        `/experiences/${encodeURIComponent(id)}/seed-graph`,
        { method: "POST", body: JSON.stringify(req) },
      ),

    listNodes: (id, signal) =>
      call<{ items: NodeItem[] }>(
        `/experiences/${encodeURIComponent(id)}/nodes`, { method: "GET" }, signal,
      ).then((r) => r.items),

    listEdges: (id, signal) =>
      call<{ items: EdgeItem[] }>(
        `/experiences/${encodeURIComponent(id)}/edges`, { method: "GET" }, signal,
      ).then((r) => r.items),

    listActions: (id, signal) =>
      call<{ items: ActionItem[] }>(
        `/experiences/${encodeURIComponent(id)}/actions`, { method: "GET" }, signal,
      ).then((r) => r.items),

    createAction: (id, payload) =>
      call<{ action: ActionItem }>(
        `/experiences/${encodeURIComponent(id)}/actions`,
        { method: "POST", body: JSON.stringify(payload) },
      ).then((r) => r.action),

    deleteAction: (actionId) =>
      call<{ ok: boolean }>(`/actions/${encodeURIComponent(actionId)}`, { method: "DELETE" })
        .then(() => undefined),

    listRules: (id, signal) =>
      call<{ items: RuleItem[] }>(
        `/experiences/${encodeURIComponent(id)}/rules`, { method: "GET" }, signal,
      ).then((r) => r.items),

    createRule: (id, payload) =>
      call<{ rule: RuleItem }>(
        `/experiences/${encodeURIComponent(id)}/rules`,
        { method: "POST", body: JSON.stringify(payload) },
      ).then((r) => r.rule),

    deleteRule: (ruleId) =>
      call<{ ok: boolean }>(`/rules/${encodeURIComponent(ruleId)}`, { method: "DELETE" })
        .then(() => undefined),

    runQa: (id) =>
      call<QAResult & { ok: boolean }>(
        `/experiences/${encodeURIComponent(id)}/qa-run`, { method: "POST" },
      ),

    latestReport: (id, signal) =>
      call<{ report: Record<string, unknown> }>(
        `/experiences/${encodeURIComponent(id)}/qa-reports`, { method: "GET" }, signal,
      ),

    publish: (id, channel) =>
      call<PublishResult & { ok: boolean }>(
        `/experiences/${encodeURIComponent(id)}/publish`,
        { method: "POST", body: JSON.stringify({ channel }) },
      ),

    listPublications: (id, signal) =>
      call<{ items: Publication[] }>(
        `/experiences/${encodeURIComponent(id)}/publications`, { method: "GET" }, signal,
      ).then((r) => r.items),

    experienceAnalytics: (id, signal) =>
      call<AnalyticsSummary & { ok: boolean }>(
        `/experiences/${encodeURIComponent(id)}/analytics`, { method: "GET" }, signal,
      ),

    chat: (sessionId, req) =>
      call<ChatResult & { ok: boolean }>(
        `/play/sessions/${encodeURIComponent(sessionId)}/chat`,
        { method: "POST", body: JSON.stringify(req) },
      ),

    pending: (sessionId, opts, signal) => {
      const params = new URLSearchParams();
      if (opts?.since_id) params.set("since_id", opts.since_id);
      if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
      const suffix = params.toString() ? `?${params.toString()}` : "";
      return call<PendingResult & { ok: boolean }>(
        `/play/sessions/${encodeURIComponent(sessionId)}/pending${suffix}`,
        { method: "GET" }, signal,
      );
    },
  };
}
