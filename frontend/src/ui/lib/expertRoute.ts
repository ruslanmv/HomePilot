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

export type ExpertFailure = {
  /** What went wrong: a thrown error, or the message of the stream's `error` event. */
  err: unknown
  /** Answer text already shown in the bubble. */
  shownText: string
  /** The user pressed Stop. */
  aborted: boolean
  /** This HomePilot is the hosted web edition (GET /v1/edition). */
  isWeb: boolean
  /** The chat's reasoning mode for this turn. */
  reasoningMode: string
}

/**
 * Whether this turn should be answered by the standard chat (/chat) after Expert failed.
 *
 * Always when Expert is not there (isMissingRoute). On the web edition also when a plain Fast
 * turn failed before any of the answer arrived: the Space's bundled model answers /chat, and
 * a visitor typing "hello" must get a reply, not an Expert error (the Space showed "error 4").
 * Never after part of the answer was shown (the reply would come twice), after a Stop, or for
 * Expert / Heavy / Deep, whose errors mean something the user asked for did not happen.
 */
export function shouldAnswerWithChat(f: ExpertFailure): boolean {
  if (f.aborted || f.shownText) return false
  if (isMissingRoute(f.err)) return true
  return f.isWeb && f.reasoningMode === 'fast'
}
