/**
 * The chat's Fast / Expert / Heavy path falls back to the standard chat when this HomePilot
 * has no Expert at all (lib/expertRoute.ts) — the Space answered every "Hello" with HTTP 405.
 */
import { describe, expect, it } from 'vitest'

import { isMissingRoute, shouldAnswerWithChat, type ExpertFailure } from '../ui/lib/expertRoute'

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

describe('answering a failed Expert turn with the standard chat', () => {
  const base: ExpertFailure = {
    err: new Error('4'), shownText: '', aborted: false, isWeb: true, reasoningMode: 'fast',
  }

  it('answers a web-edition Fast turn that failed before any text (the Space\'s "error 4")', () => {
    expect(shouldAnswerWithChat(base)).toBe(true)
    expect(shouldAnswerWithChat({ ...base, err: new Error('HTTP 500 Internal Server Error') })).toBe(true)
    expect(shouldAnswerWithChat({ ...base, err: new TypeError('Failed to fetch') })).toBe(true)
  })

  it('answers a missing Expert route in any edition and mode', () => {
    const missing = new Error('HTTP 404 Not Found')
    expect(shouldAnswerWithChat({ ...base, err: missing, isWeb: false, reasoningMode: 'heavy' })).toBe(true)
    expect(shouldAnswerWithChat({ ...base, err: new Error('HTTP 405 Method Not Allowed'), isWeb: false })).toBe(true)
  })

  it('never answers twice, after a Stop, or in place of Expert / Heavy / Deep', () => {
    expect(shouldAnswerWithChat({ ...base, shownText: 'Hel' })).toBe(false)
    expect(shouldAnswerWithChat({ ...base, err: new Error('HTTP 404 Not Found'), shownText: 'Hel' })).toBe(false)
    expect(shouldAnswerWithChat({ ...base, aborted: true })).toBe(false)
    for (const reasoningMode of ['expert', 'heavy', 'deep']) {
      expect(shouldAnswerWithChat({ ...base, reasoningMode })).toBe(false)
    }
  })

  it('leaves Expert errors to show on a local install', () => {
    expect(shouldAnswerWithChat({ ...base, isWeb: false })).toBe(false)
  })
})
