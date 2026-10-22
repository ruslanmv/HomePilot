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
// Vite takes the next free port when one is busy ("Port 3000 is in use,
// trying another one…"), so 3000-3010 and 5173-5180 all count as dev ports.
const DEV_VITE_PORTS = new Set<string>([
  ...Array.from({ length: 11 }, (_, i) => String(3000 + i)),
  ...Array.from({ length: 8 }, (_, i) => String(5173 + i)),
]);

function isLocalHost(hostname: string): boolean {
  return LOCAL_HOSTS.has(hostname);
}

function parsedHostname(url: string): string | null {
  try {
    return new URL(url).hostname;
  } catch {
    return null;
  }
}

/** Best default when nothing else is configured — based on current location. */
export function getDefaultBackendUrl(): string {
  if (typeof window === "undefined") {
    return "http://localhost:8000";
  }
  const env = (import.meta.env?.VITE_API_URL as string | undefined)?.trim();
  if (env) return stripTrailingSlash(env);

  const { hostname, origin, port } = window.location;
  // On the Vite dev server the backend is a separate process on :8000.
  // import.meta.env.DEV is true only under the Vite dev server, whatever port
  // it ended up on; production builds served by the backend keep same-origin.
  if (isLocalHost(hostname) && (DEV_VITE_PORTS.has(port) || !!import.meta.env?.DEV)) {
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
export function resolveBackendUrl(override?: string | null): string {
  if (typeof override === "string" && override.trim()) {
    return followMovedDevBackend(stripTrailingSlash(override.trim()));
  }
  if (typeof window !== "undefined") {
    try {
      const stored = window.localStorage.getItem("homepilot_backend_url");
      if (stored && stored.trim()) {
        const clean = stripTrailingSlash(stored.trim());
        const pageIsRemote = !isLocalHost(window.location.hostname);
        const storedUrl = (() => { try { return new URL(clean); } catch { return null; } })();
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
        // …unless the build itself names that address (VITE_API_URL pointing
        // at a Vite dev server that proxies the API): a configured value is
        // not stale, and rewriting it made every reload unreachable.
        const configured = (import.meta.env?.VITE_API_URL as string | undefined)?.trim();
        if (storedIsLocal && DEV_VITE_PORTS.has(storedPort) && clean !== stripTrailingSlash(configured || "")) {
          // The default backend: :8000, or wherever `make start` put it.
          return getDefaultBackendUrl();
        }
        // An address `make start` picked (saved because it was the default then) is not a
        // choice: it follows the backend to wherever this start put it. Without this, a run
        // that moved the backend to :8002 left every later run — back on :8000 — unreachable.
        if (storedIsLocal && wasAutomatic(clean)) {
          return getDefaultBackendUrl();
        }
        return followMovedDevBackend(clean);
      }
    } catch {
      /* localStorage unavailable — fall through to default */
    }
  }
  return getDefaultBackendUrl();
}

function stripTrailingSlash(url: string): string {
  return url.replace(/\/+$/, "");
}

/** Whether the saved backend address was the user's choice or the default at the time. */
const ORIGIN_KEY = "homepilot_backend_url_origin";

/**
 * The saved address was the automatic one, not a choice: marked so when it was saved. An
 * address saved before the mark existed is kept as it is — a custom local port is a choice
 * too often to guess otherwise.
 */
function wasAutomatic(clean: string): boolean {
  let origin: string | null = null;
  try {
    origin = window.localStorage.getItem(ORIGIN_KEY);
  } catch {
    origin = null;
  }
  if (origin !== "auto") return false;
  return clean !== getDefaultBackendUrl();
}

/**
 * Save the backend address. `chosenByUser` is true for Settings → Save; the app's own
 * persistence of the address it resolved passes false. The default address is always marked
 * automatic, so it keeps following `make start`; a typed one is kept as typed.
 */
export function saveBackendUrl(url: string, chosenByUser: boolean): void {
  try {
    const clean = stripTrailingSlash((url || "").trim());
    if (!clean) return;
    window.localStorage.setItem("homepilot_backend_url", clean);
    const previous = window.localStorage.getItem(ORIGIN_KEY);
    const origin = clean === getDefaultBackendUrl() ? "auto" : chosenByUser ? "user" : previous === "user" ? "user" : "auto";
    window.localStorage.setItem(ORIGIN_KEY, origin);
  } catch {
    /* storage unavailable */
  }
}

/**
 * `make start` moves the backend off :8000 when another program holds that port, and
 * tells the dev server where it went (VITE_API_URL, e.g. http://localhost:8002). A saved
 * or passed `localhost:8000` is then the old default rather than a choice, so it follows
 * the backend. Any other saved address — a remote server, a custom local port — is kept.
 */
export function followMovedDevBackend(url: string): string {
  const configured = stripTrailingSlash(((import.meta.env?.VITE_API_URL as string | undefined) || "").trim());
  if (!configured || url === configured) return url;
  try {
    const target = new URL(configured);
    const current = new URL(url);
    if (isLocalHost(target.hostname) && isLocalHost(current.hostname) && current.port === "8000") {
      return configured;
    }
  } catch {
    /* not URLs — leave as given */
  }
  return url;
}

