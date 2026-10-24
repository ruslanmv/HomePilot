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

/**
 * Ordinary Fast chat on the web edition falls back to POST /chat when Expert fails
 * before any assistant token. A partial stream is left as-is so the visitor never
 * sees two answers. Local HomePilot still falls back only when Expert is missing
 * (404 or 405). Expert, Heavy and Deep keep their own errors.
 */
export function shouldFallbackToLegacyChat(opts: {
  webEdition: boolean
  reasoningMode: string
  error: unknown
  assistantText: string
}): boolean {
  if (opts.assistantText.trim()) return false
  if (isMissingRoute(opts.error)) return true
  if (!opts.webEdition || opts.reasoningMode !== 'fast') return false
  if (opts.error == null) return false
  const message = opts.error instanceof Error ? opts.error.message : String(opts.error)
  return message.trim().length > 0
}
