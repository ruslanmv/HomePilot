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
import { InteractiveApiError, } from "./types";
/**
 * Shared SSE reader for /auto-generate/stream and
 * /generate-all/stream. Parses ``data: {...}\n\n`` frames,
 * forwards each to ``onEvent``, and resolves with the ``result``
 * frame payload. Rejects with InteractiveApiError on HTTP
 * failures or an explicit ``error`` frame. Native EventSource
 * can't honour credentials:'include' across origins — hence the
 * hand-rolled fetch+ReadableStream reader.
 */
async function _consumeGenerationStream(url, authHeaders, opts) {
    const resp = await fetch(url, {
        method: "GET",
        credentials: "include",
        headers: { Accept: "text/event-stream", ...authHeaders },
        signal: opts.signal,
    });
    if (!resp.ok || !resp.body) {
        const detail = await resp.text().catch(() => "");
        throw new InteractiveApiError(detail || `generation stream failed (${resp.status})`, resp.status);
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    let finalResult = null;
    let errorMessage = null;
    // eslint-disable-next-line no-constant-condition
    while (true) {
        const { value, done } = await reader.read();
        if (done)
            break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
            const raw = buffer.slice(0, idx).trim();
            buffer = buffer.slice(idx + 2);
            if (!raw.startsWith("data:"))
                continue;
            const body = raw.slice("data:".length).trim();
            if (!body)
                continue;
            let frame;
            try {
                frame = JSON.parse(body);
            }
            catch {
                continue;
            }
            if (opts.onEvent) {
                try {
                    opts.onEvent(frame);
                }
                catch { /* hook must not kill stream */ }
            }
            if (frame.type === "result") {
                finalResult = frame.payload || null;
            }
            if (frame.type === "error") {
                const payload = (frame.payload || {});
                errorMessage = typeof payload.reason === "string"
                    ? payload.reason
                    : "generation failed";
            }
            if (frame.type === "done")
                break;
        }
    }
    if (errorMessage)
        throw new InteractiveApiError(errorMessage, 0);
    if (!finalResult)
        throw new InteractiveApiError("stream ended without a result frame", 0);
    return finalResult;
}
export function createInteractiveApi(backendUrl, apiKey) {
    const base = backendUrl.replace(/\/+$/, "") + "/v1/interactive";
    const authHeaders = apiKey
        ? { "x-api-key": apiKey.trim() }
        : {};
    async function call(path, init = {}, signal) {
        const headers = {
            "Content-Type": "application/json",
            ...authHeaders,
            ...init.headers,
        };
        let res;
        try {
            // credentials: 'include' forwards the homepilot_session cookie
            // on cross-origin dev + same-origin packaged builds, so the
            // backend's viewer resolver can authenticate the request. Without
            // this, every /v1/interactive/* call 401s in dev and produces a
            // confusing error on the landing page.
            res = await fetch(`${base}${path}`, {
                ...init, headers, signal, credentials: "include",
            });
        }
        catch (err) {
            if (err.name === "AbortError")
                throw err;
            throw new InteractiveApiError(`Network error contacting ${path}: ${err.message}`, 0, "network_error");
        }
        const contentType = res.headers.get("content-type") || "";
        const isJson = contentType.includes("application/json");
        const body = isJson ? await res.json().catch(() => ({})) : await res.text();
        if (!res.ok) {
            const detail = (isJson && body.detail) || body;
            if (detail && typeof detail === "object") {
                const d = detail;
                throw new InteractiveApiError(d.error || `HTTP ${res.status}`, res.status, d.code || "http_error", d.data || {});
            }
            throw new InteractiveApiError(typeof detail === "string" ? detail : `HTTP ${res.status}`, res.status, "http_error");
        }
        return body;
    }
    return {
        health: (signal) => call("/health", { method: "GET" }, signal),
        listPresets: (signal) => call("/presets", { method: "GET" }, signal)
            .then((r) => r.items),
        listExperiences: (signal) => call("/experiences", { method: "GET" }, signal)
            .then((r) => r.items),
        getExperience: (id, signal) => call(`/experiences/${encodeURIComponent(id)}`, { method: "GET" }, signal)
            .then((r) => r.experience),
        createExperience: (input) => call("/experiences", {
            method: "POST",
            body: JSON.stringify(input),
        }).then((r) => r.experience),
        patchExperience: (id, patch) => call(`/experiences/${encodeURIComponent(id)}`, {
            method: "PATCH",
            body: JSON.stringify(patch),
        }).then((r) => r.experience),
        deleteExperience: (id) => call(`/experiences/${encodeURIComponent(id)}`, { method: "DELETE" })
            .then(() => undefined),
        plan: (req) => call("/plan", {
            method: "POST",
            body: JSON.stringify(req),
        }).then((r) => r.intent),
        planAuto: (req) => call("/plan-auto", {
            method: "POST",
            body: JSON.stringify(req),
        }),
        autoGenerate: (id) => call(`/experiences/${encodeURIComponent(id)}/auto-generate`, { method: "POST", body: JSON.stringify({}) }),
        autoGenerateStream: (id, opts) => _consumeGenerationStream(`${base}/experiences/${encodeURIComponent(id)}/auto-generate/stream`, authHeaders, opts),
        generateAllStream: (id, opts) => _consumeGenerationStream(`${base}/experiences/${encodeURIComponent(id)}/generate-all/stream`, authHeaders, opts),
        renderSingleScene: (experienceId, nodeId) => call(`/experiences/${encodeURIComponent(experienceId)}/nodes/${encodeURIComponent(nodeId)}/render`, { method: "POST", body: JSON.stringify({}) }),
        patchNode: (nodeId, patch) => call(`/nodes/${encodeURIComponent(nodeId)}`, { method: "PATCH", body: JSON.stringify(patch) }).then((r) => r.node),
        resolveAssetUrl: (assetId, signal) => call(`/assets/${encodeURIComponent(assetId)}/url`, { method: "GET" }, signal).then((r) => r.url),
        seedGraph: (id, req) => call(`/experiences/${encodeURIComponent(id)}/seed-graph`, { method: "POST", body: JSON.stringify(req) }),
        listNodes: (id, signal) => call(`/experiences/${encodeURIComponent(id)}/nodes`, { method: "GET" }, signal).then((r) => r.items),
        listEdges: (id, signal) => call(`/experiences/${encodeURIComponent(id)}/edges`, { method: "GET" }, signal).then((r) => r.items),
        listActions: (id, signal) => call(`/experiences/${encodeURIComponent(id)}/actions`, { method: "GET" }, signal).then((r) => r.items),
        createAction: (id, payload) => call(`/experiences/${encodeURIComponent(id)}/actions`, { method: "POST", body: JSON.stringify(payload) }).then((r) => r.action),
        deleteAction: (actionId) => call(`/actions/${encodeURIComponent(actionId)}`, { method: "DELETE" })
            .then(() => undefined),
        listRules: (id, signal) => call(`/experiences/${encodeURIComponent(id)}/rules`, { method: "GET" }, signal).then((r) => r.items),
        createRule: (id, payload) => call(`/experiences/${encodeURIComponent(id)}/rules`, { method: "POST", body: JSON.stringify(payload) }).then((r) => r.rule),
        deleteRule: (ruleId) => call(`/rules/${encodeURIComponent(ruleId)}`, { method: "DELETE" })
            .then(() => undefined),
        runQa: (id) => call(`/experiences/${encodeURIComponent(id)}/qa-run`, { method: "POST" }),
        latestReport: (id, signal) => call(`/experiences/${encodeURIComponent(id)}/qa-reports`, { method: "GET" }, signal),
        publish: (id, channel) => call(`/experiences/${encodeURIComponent(id)}/publish`, { method: "POST", body: JSON.stringify({ channel }) }),
        listPublications: (id, signal) => call(`/experiences/${encodeURIComponent(id)}/publications`, { method: "GET" }, signal).then((r) => r.items),
        experienceAnalytics: (id, signal) => call(`/experiences/${encodeURIComponent(id)}/analytics`, { method: "GET" }, signal),
        startSession: (req) => call("/play/sessions", { method: "POST", body: JSON.stringify(req) }).then((r) => ({
            ...r.session,
            initial_scene: r.initial_scene || null,
            opening_turn: r.opening_turn,
            persona_portrait_url: r.persona_portrait_url,
            render_media_type: r.render_media_type,
        })),
        chat: (sessionId, req) => call(`/play/sessions/${encodeURIComponent(sessionId)}/chat`, { method: "POST", body: JSON.stringify(req) }),
        pending: (sessionId, opts, signal) => {
            const params = new URLSearchParams();
            if (opts?.since_id)
                params.set("since_id", opts.since_id);
            if (opts?.limit !== undefined)
                params.set("limit", String(opts.limit));
            const suffix = params.toString() ? `?${params.toString()}` : "";
            return call(`/play/sessions/${encodeURIComponent(sessionId)}/pending${suffix}`, { method: "GET" }, signal);
        },
        getCatalog: (sessionId, signal) => call(`/play/sessions/${encodeURIComponent(sessionId)}/catalog`, { method: "GET" }, signal).then((r) => r.items),
        getProgress: (sessionId, signal) => call(`/play/sessions/${encodeURIComponent(sessionId)}/progress`, { method: "GET" }, signal),
        resolveTurn: (sessionId, req) => call(`/play/sessions/${encodeURIComponent(sessionId)}/resolve`, { method: "POST", body: JSON.stringify(req) }).then((r) => r.resolved),
        personaLiveGenerate: (req) => call("/persona-live/generate", { method: "POST", body: JSON.stringify(req) }),
        personaLiveStart: (req) => call("/persona-live/start", { method: "POST", body: JSON.stringify(req) }).then((r) => r.session),
        personaLiveSession: (sessionId) => call(`/persona-live/session/${encodeURIComponent(sessionId)}`, { method: "GET" }),
        personaLiveAction: (sessionId, req) => call(`/persona-live/session/${encodeURIComponent(sessionId)}/action`, { method: "POST", body: JSON.stringify(req) }),
        personaLiveJob: (jobId) => call(`/persona-live/jobs/${encodeURIComponent(jobId)}`, { method: "GET" }),
        personaLiveRestore: (sessionId, versionId) => call(`/persona-live/session/${encodeURIComponent(sessionId)}/restore`, { method: "POST", body: JSON.stringify({ version_id: versionId }) }),
        personaLiveChat: (sessionId, message) => call(`/persona-live/session/${encodeURIComponent(sessionId)}/chat`, { method: "POST", body: JSON.stringify({ message }) }).then((r) => ({
            dialogue: r.dialogue,
            scene_context: r.scene_context,
            scene_memory: r.scene_memory,
            emotional_state: r.emotional_state,
            optional_action_suggestion: r.optional_action_suggestion,
        })),
    };
}
