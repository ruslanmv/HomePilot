/**
 * Whether a failed call to Expert (POST /v1/expert/chat) means the route is not there at all
 * — a HomePilot without the Expert package, such as a packaged image that did not ship it —
 * as opposed to Expert answering with an error.
 *
 * A missing route is a 404, or a 405: on the Hugging Face Space a GET-only catch-all served
 * the React app for every path, so a POST to an unregistered path came back "Method Not
 * Allowed". Either way the standard chat (/chat) answers instead.
 */
export function isMissingRoute(err: unknown): boolean {
  const message = err instanceof Error ? err.message : String(err ?? '')
  return /^HTTP (404|405)\b/.test(message)
}
