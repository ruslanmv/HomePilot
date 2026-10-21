/**
 * The chat's Fast / Expert / Heavy path falls back to the standard chat when this HomePilot
 * has no Expert at all (lib/expertRoute.ts) — the Space answered every "Hello" with HTTP 405.
 */
import { describe, expect, it } from 'vitest'

import { isMissingRoute } from '../ui/lib/expertRoute'

describe('a missing Expert route', () => {
  it('is a 404, or the 405 a GET-only catch-all gives a POST', () => {
    expect(isMissingRoute(new Error('HTTP 405 Method Not Allowed: {"detail":"Method Not Allowed"}'))).toBe(true)
    expect(isMissingRoute(new Error('HTTP 404 Not Found: {"detail":"Not Found","path":"/v1/expert/chat"}'))).toBe(true)
  })

  it('is not an Expert error, a network failure or anything else', () => {
    expect(isMissingRoute(new Error('HTTP 500 Internal Server Error: no local model'))).toBe(false)
    expect(isMissingRoute(new Error('HTTP 401 Unauthorized'))).toBe(false)
    expect(isMissingRoute(new TypeError('Failed to fetch'))).toBe(false)
    expect(isMissingRoute('HTTP 4040')).toBe(false)
    expect(isMissingRoute(null)).toBe(false)
  })
})
