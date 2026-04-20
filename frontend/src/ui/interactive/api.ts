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
  AutoGenerateResult,
  AutoGenerateStreamEvent,
  CatalogItemView,
  ChatResult,
  EdgeItem,
  Experience,
  ExperienceMode,
  HealthInfo,
  InteractiveApiError,
  NodeItem,
  PendingResult,
  PlanAutoResult,
  PlanIntent,
  PlanningPreset,
  ProgressSnapshot,
  PublishResult,
  Publication,
  QAResult,
  ResolveResult,
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
  planAuto(req: { idea: string }): Promise<PlanAutoResult>;
  autoGenerate(id: string): Promise<AutoGenerateResult>;
  /**
   * SSE variant of ``autoGenerate`` (PIPE-2). ``onEvent`` fires
   * once per phase event the backend emits (started,
   * generating_graph, persisting_nodes, ..., running_qa) so the
   * wizard spinner can surface real progress. Resolves with the
   * final ``result`` payload, matching the POST /auto-generate
   * body. Aborts via ``signal``.
   */
  autoGenerateStream(
    id: string,
    opts: {
      onEvent?: (ev: AutoGenerateStreamEvent) => void;
      signal?: AbortSignal;
    },
  ): Promise<AutoGenerateResult>;
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
  startSession(req: {
    experience_id: string;
    viewer_ref?: string;
    language?: string;
    personalization?: Record<string, unknown>;
  }): Promise<{ id: string; experience_id: string; current_node_id: string }>;
  chat(sessionId: string, req: { text: string; viewer_region?: string }): Promise<ChatResult>;
  pending(
    sessionId: string,
    opts?: { since_id?: string; limit?: number },
    signal?: AbortSignal,
  ): Promise<PendingResult>;
  getCatalog(sessionId: string, signal?: AbortSignal): Promise<CatalogItemView[]>;
  getProgress(sessionId: string, signal?: AbortSignal): Promise<ProgressSnapshot>;
  resolveTurn(
    sessionId: string,
    req: { action_id?: string; free_text?: string; viewer_region?: string },
  ): Promise<ResolveResult>;
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
      // credentials: 'include' forwards the homepilot_session cookie
      // on cross-origin dev + same-origin packaged builds, so the
      // backend's viewer resolver can authenticate the request. Without
      // this, every /v1/interactive/* call 401s in dev and produces a
      // confusing error on the landing page.
      res = await fetch(`${base}${path}`, {
        ...init, headers, signal, credentials: "include",
      });
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

    planAuto: (req) =>
      call<PlanAutoResult & { ok: boolean }>("/plan-auto", {
        method: "POST",
        body: JSON.stringify(req),
      }),

    autoGenerate: (id) =>
      call<AutoGenerateResult & { ok: boolean }>(
        `/experiences/${encodeURIComponent(id)}/auto-generate`,
        { method: "POST", body: JSON.stringify({}) },
      ),

    autoGenerateStream: async (id, opts) => {
      // Custom SSE reader via fetch + ReadableStream so we can
      // honour the shared credentials:'include' policy (native
      // EventSource can't send cookies cross-origin). Parses the
      // ``data: {...}\n\n`` frames, routes events to ``onEvent``,
      // and resolves with the ``result`` frame's payload.
      const url = `${base}/experiences/${encodeURIComponent(id)}/auto-generate/stream`;
      const resp = await fetch(url, {
        method: "GET",
        credentials: "include",
        headers: { Accept: "text/event-stream", ...authHeaders },
        signal: opts.signal,
      });
      if (!resp.ok || !resp.body) {
        const detail = await resp.text().catch(() => "");
        throw new InteractiveApiError(
          detail || `auto-generate stream failed (${resp.status})`,
          resp.status,
        );
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let finalResult: AutoGenerateResult | null = null;
      let errorMessage: string | null = null;

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE frames are separated by blank lines.
        let idx: number;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, idx).trim();
          buffer = buffer.slice(idx + 2);
          if (!raw.startsWith("data:")) continue;
          const body = raw.slice("data:".length).trim();
          if (!body) continue;
          let frame: AutoGenerateStreamEvent;
          try {
            frame = JSON.parse(body) as AutoGenerateStreamEvent;
          } catch {
            continue;
          }
          if (opts.onEvent) {
            try { opts.onEvent(frame); } catch { /* hook must not kill stream */ }
          }
          if (frame.type === "result") {
            finalResult = (frame.payload as unknown as AutoGenerateResult) || null;
          }
          if (frame.type === "error") {
            const payload = (frame.payload || {}) as Record<string, unknown>;
            errorMessage = typeof payload.reason === "string"
              ? payload.reason
              : "auto-generate failed";
          }
          if (frame.type === "done") {
            break;
          }
        }
      }

      if (errorMessage) {
        throw new InteractiveApiError(errorMessage, 0);
      }
      if (!finalResult) {
        throw new InteractiveApiError("stream ended without a result frame", 0);
      }
      return finalResult;
    },

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

    startSession: (req) =>
      call<{ session: { id: string; experience_id: string; current_node_id: string } }>(
        "/play/sessions",
        { method: "POST", body: JSON.stringify(req) },
      ).then((r) => r.session),

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

    getCatalog: (sessionId, signal) =>
      call<{ items: CatalogItemView[] }>(
        `/play/sessions/${encodeURIComponent(sessionId)}/catalog`,
        { method: "GET" }, signal,
      ).then((r) => r.items),

    getProgress: (sessionId, signal) =>
      call<ProgressSnapshot & { ok: boolean }>(
        `/play/sessions/${encodeURIComponent(sessionId)}/progress`,
        { method: "GET" }, signal,
      ),

    resolveTurn: (sessionId, req) =>
      call<{ resolved: ResolveResult }>(
        `/play/sessions/${encodeURIComponent(sessionId)}/resolve`,
        { method: "POST", body: JSON.stringify(req) },
      ).then((r) => r.resolved),
  };
}
