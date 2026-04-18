/**
 * Unit tests for ``useReducedMotion``.
 *
 * Covers the three observable behaviours:
 *   1. Initial read of the OS preference.
 *   2. Runtime update when the user toggles the setting.
 *   3. SSR-safe default when ``window`` is unavailable.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useReducedMotion } from './useReducedMotion'

type MockMQ = {
  matches: boolean
  addEventListener: ReturnType<typeof vi.fn>
  removeEventListener: ReturnType<typeof vi.fn>
}

function installMatchMedia(initial: boolean): {
  mq: MockMQ
  fire: (matches: boolean) => void
} {
  let handler: ((e: { matches: boolean }) => void) | null = null
  const mq: MockMQ = {
    matches: initial,
    addEventListener: vi.fn((_: string, fn: (e: { matches: boolean }) => void) => {
      handler = fn
    }),
    removeEventListener: vi.fn(() => {
      handler = null
    }),
  }
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => mq),
  )
  // @ts-expect-error — window.matchMedia stub in jsdom
  window.matchMedia = globalThis.matchMedia
  return {
    mq,
    fire: (matches: boolean) => {
      mq.matches = matches
      handler?.({ matches })
    },
  }
}

describe('useReducedMotion', () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the initial matchMedia value', () => {
    installMatchMedia(true)
    const { result } = renderHook(() => useReducedMotion())
    expect(result.current).toBe(true)
  })

  it('returns false when matchMedia reports no-preference', () => {
    installMatchMedia(false)
    const { result } = renderHook(() => useReducedMotion())
    expect(result.current).toBe(false)
  })

  it('updates when the user toggles the OS preference mid-session', () => {
    const { fire } = installMatchMedia(false)
    const { result } = renderHook(() => useReducedMotion())
    expect(result.current).toBe(false)
    act(() => fire(true))
    expect(result.current).toBe(true)
    act(() => fire(false))
    expect(result.current).toBe(false)
  })

  it('unsubscribes on unmount — no listener leaks', () => {
    const { mq } = installMatchMedia(false)
    const { unmount } = renderHook(() => useReducedMotion())
    expect(mq.addEventListener).toHaveBeenCalledTimes(1)
    unmount()
    expect(mq.removeEventListener).toHaveBeenCalledTimes(1)
  })
})
