/**
 * Backend URL resolution.
 *
 * On a local dev machine (vite dev server on :5173) the backend runs on a
 * different port, so we default to ``http://localhost:8000``.
 *
 * On a deployed environment (Hugging Face Space, Docker, etc.) the backend
 * and frontend share the same origin, so we default to ``window.location.origin``.
 *
 * Priority (first match wins):
 *   1. Explicit user setting (``localStorage.homepilot_backend_url``) —
 *      ignored when it points at a local dev host but the page is served
 *      from a remote host (stale leftover from an earlier session).
 *   2. Build-time env (``VITE_API_URL``)
 *   3. Current origin when served from a non-dev host
 *   4. ``http://localhost:8000`` fallback
 *
 * Always returns a value with no trailing slash.
 */
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"]);
// Vite dev ports used across the repo. The Makefile's `make start` target
// launches vite with --port 3000; earlier tooling used Vite's defaults
// 5173/5174. All of them must route API traffic to the backend at :8000
// rather than to the Vite origin (which would SPA-fallback every request
// to index.html and break JSON.parse).
const DEV_VITE_PORTS = new Set(["3000", "5173", "5174"]);
function isLocalHost(hostname) {
    return LOCAL_HOSTS.has(hostname);
}
function parsedHostname(url) {
    try {
        return new URL(url).hostname;
    }
    catch {
        return null;
    }
}
/** Best default when nothing else is configured — based on current location. */
export function getDefaultBackendUrl() {
    if (typeof window === "undefined") {
        return "http://localhost:8000";
    }
    const env = import.meta.env?.VITE_API_URL?.trim();
    if (env)
        return stripTrailingSlash(env);
    const { hostname, origin, port } = window.location;
    // On the Vite dev server the backend is a separate process on :8000.
    if (isLocalHost(hostname) && DEV_VITE_PORTS.has(port)) {
        return "http://localhost:8000";
    }
    // Everywhere else — deployed Spaces, Docker, preview builds — the frontend
    // is served by the backend itself, so same-origin is always correct.
    return stripTrailingSlash(origin);
}
/**
 * Resolve the user-configured or default backend URL. Use this anywhere the
 * old hardcoded fallback ``'http://localhost:8000'`` was written.
 *
 * Robustness: if the stored value points at a localhost backend but the
 * page itself is served from a remote host (common after upgrades), we
 * ignore the stale setting and fall through to the current origin. This
 * fixes the "Failed to fetch" storm users hit after first deploy.
 */
export function resolveBackendUrl(override) {
    if (typeof override === "string" && override.trim()) {
        return stripTrailingSlash(override.trim());
    }
    if (typeof window !== "undefined") {
        try {
            const stored = window.localStorage.getItem("homepilot_backend_url");
            if (stored && stored.trim()) {
                const clean = stripTrailingSlash(stored.trim());
                const pageIsRemote = !isLocalHost(window.location.hostname);
                const storedUrl = (() => { try {
                    return new URL(clean);
                }
                catch {
                    return null;
                } })();
                const storedHost = storedUrl?.hostname ?? null;
                const storedPort = storedUrl?.port ?? "";
                const storedIsLocal = storedHost !== null && isLocalHost(storedHost);
                if (pageIsRemote && storedIsLocal) {
                    // Stale setting from a previous local dev session. Ignore it and
                    // let getDefaultBackendUrl() take over (same origin).
                    return getDefaultBackendUrl();
                }
                // Stale setting pointing at a Vite DEV port on localhost (3000 / 5173
                // / 5174). The frontend origin serves the SPA — POSTing JSON there
                // SPA-falls-back to index.html and the caller sees a 404, which the
                // voice-call path reads as "feature unavailable" and flips to the
                // chat-REST fallback. Redirect to :8000 (the default backend port)
                // so the stored preference doesn't silently break voice-call
                // session creation.
                if (storedIsLocal && DEV_VITE_PORTS.has(storedPort)) {
                    return "http://localhost:8000";
                }
                return clean;
            }
        }
        catch {
            /* localStorage unavailable — fall through to default */
        }
    }
    return getDefaultBackendUrl();
}
function stripTrailingSlash(url) {
    return url.replace(/\/+$/, "");
}
