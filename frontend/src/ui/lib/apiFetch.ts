/**
 * JSON-safe fetch for HomePilot Settings API routes.
 *
 * Fetches a HomePilot API route and returns its parsed JSON, failing with an
 * actionable message instead of a raw ``Unexpected token '<', "<!doctype "…``
 * when a deployment serves the SPA ``index.html`` fallback where JSON was
 * expected.
 *
 * On ``homepilot.ruslanmv.com`` the frontend is served same-origin with the
 * backend, so a Settings API path that isn't forwarded to FastAPI (or a
 * relative request produced by an empty backend URL) resolves to the SPA
 * document. Parsing that as JSON is exactly what surfaced the confusing
 * ``Unexpected token '<'`` error in Settings → Providers. Checking the
 * content type first turns that into a clear deployment-routing message.
 */
export async function fetchApiJson(url: string): Promise<any> {
  const res = await fetch(url);
  const ctype = res.headers.get("content-type") || "";
  if (!ctype.includes("application/json")) {
    let path = url;
    try {
      const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost";
      path = new URL(url, origin).pathname;
    } catch {
      /* keep the raw url */
    }
    throw new Error(
      `The HomePilot providers API is unavailable on this deployment ` +
        `(HTTP ${res.status}). The request for ${path} returned ` +
        `${ctype || "an unknown content type"} instead of JSON — check that ` +
        `this route is forwarded to the backend and not the SPA fallback.`,
    );
  }
  if (!res.ok) {
    // A proper JSON error body — surface its message rather than a bare status.
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body?.message || body?.detail || detail;
    } catch {
      /* fall back to the HTTP status */
    }
    throw new Error(detail);
  }
  return res.json();
}
