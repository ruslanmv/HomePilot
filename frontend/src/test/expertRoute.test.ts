/**
 * The chat's Fast / Expert / Heavy path falls back to the standard chat when this HomePilot
 * has no Expert at all (lib/expertRoute.ts) — the Space answered every "Hello" with HTTP 405.
 * On the web edition, Fast also falls back when Expert fails before any token.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { isMissingRoute, shouldFallbackToLegacyChat } from '../ui/lib/expertRoute'

const appSource = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../ui/App.tsx'), 'utf8')

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

describe('web Fast falls back to /chat only before any token', () => {
  const base = { webEdition: true, reasoningMode: 'fast', assistantText: '' }

  it('falls back on an immediate local failure, a 404 and a 405', () => {
    expect(shouldFallbackToLegacyChat({ ...base, error: new Error('4') })).toBe(true)
    expect(shouldFallbackToLegacyChat({ ...base, error: new Error('Expert pipeline error: 4') })).toBe(true)
    expect(shouldFallbackToLegacyChat({ ...base, error: new Error('HTTP 404 Not Found') })).toBe(true)
    expect(shouldFallbackToLegacyChat({ ...base, error: new Error('HTTP 405 Method Not Allowed') })).toBe(true)
  })

  it('does not fall back after tokens, off Fast, or on the local edition', () => {
    expect(shouldFallbackToLegacyChat({ ...base, assistantText: 'Hi', error: new Error('4') })).toBe(false)
    expect(shouldFallbackToLegacyChat({ ...base, reasoningMode: 'expert', error: new Error('4') })).toBe(false)
    expect(shouldFallbackToLegacyChat({ ...base, reasoningMode: 'heavy', error: new Error('4') })).toBe(false)
    expect(shouldFallbackToLegacyChat({ ...base, reasoningMode: 'deep', error: new Error('4') })).toBe(false)
    expect(shouldFallbackToLegacyChat({ ...base, webEdition: false, error: new Error('4') })).toBe(false)
    expect(shouldFallbackToLegacyChat({ ...base, error: null })).toBe(false)
  })

  it('still uses /chat when Expert is missing, including after a partial answer is refused', () => {
    expect(shouldFallbackToLegacyChat({
      webEdition: false, reasoningMode: 'expert', assistantText: '', error: new Error('HTTP 405 Method Not Allowed'),
    })).toBe(true)
    expect(shouldFallbackToLegacyChat({
      webEdition: true, reasoningMode: 'fast', assistantText: 'Hello', error: new Error('HTTP 404 Not Found'),
    })).toBe(false)
  })

  it('keeps the typed user turn when the assistant turn fails', () => {
    const catchAt = appSource.indexOf('const errorText = `Error:')
    expect(catchAt).toBeGreaterThan(0)
    const handler = appSource.slice(catchAt, catchAt + 900)
    expect(handler).toContain('m.id === tmpId')
    expect(handler).not.toContain('setInput(')
    expect(handler).not.toContain("role === 'user'")
  })
})
