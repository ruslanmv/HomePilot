/**
 * Motion preferences — how much HomePilot animates, kept per device.
 *
 * Two independent choices:
 *   level   enterprise  every animation in the motion system (the default)
 *           minimal     quiet: fades and pulses only, no sweeps, slides or press scaling
 *           off         no animation at all (same effect as the OS "reduce motion")
 *   reveal  stream      a new answer is revealed progressively with a typing cursor
 *           fade        a new answer fades in whole (HomePilot's previous behaviour)
 *           instant     a new answer appears at once
 *
 * The choice lives in localStorage (it describes this screen, not the account),
 * is mirrored onto <html data-hp-motion data-hp-reveal> so CSS can follow it,
 * and is announced with a `hp:motion-change` event so open views update live.
 * The operating system's "reduce motion" setting always wins.
 */
import { useEffect, useReducer, useState } from 'react'

export type MotionLevel = 'enterprise' | 'minimal' | 'off'
export type RevealStyle = 'stream' | 'fade' | 'instant'
export type MotionPrefs = { level: MotionLevel; reveal: RevealStyle }

export const MOTION_STORAGE_KEY = 'homepilot_motion'
export const MOTION_EVENT = 'hp:motion-change'
export const DEFAULT_MOTION_PREFS: MotionPrefs = { level: 'enterprise', reveal: 'stream' }

const LEVELS: readonly MotionLevel[] = ['enterprise', 'minimal', 'off']
const REVEALS: readonly RevealStyle[] = ['stream', 'fade', 'instant']
const REDUCED_QUERY = '(prefers-reduced-motion: reduce)'

export function readMotionPrefs(): MotionPrefs {
  try {
    const raw = localStorage.getItem(MOTION_STORAGE_KEY)
    if (!raw) return { ...DEFAULT_MOTION_PREFS }
    const parsed = JSON.parse(raw) ?? {}
    return {
      level: LEVELS.includes(parsed.level) ? parsed.level : DEFAULT_MOTION_PREFS.level,
      reveal: REVEALS.includes(parsed.reveal) ? parsed.reveal : DEFAULT_MOTION_PREFS.reveal,
    }
  } catch {
    return { ...DEFAULT_MOTION_PREFS }
  }
}

/** Mirror the preference onto <html> so stylesheets can follow it. */
export function applyMotionPrefs(prefs: MotionPrefs = readMotionPrefs()): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.dataset.hpMotion = prefs.level
  root.dataset.hpReveal = prefs.reveal
}

export function writeMotionPrefs(next: Partial<MotionPrefs>): MotionPrefs {
  const merged: MotionPrefs = { ...readMotionPrefs(), ...next }
  try {
    localStorage.setItem(MOTION_STORAGE_KEY, JSON.stringify(merged))
  } catch {
    /* private mode / storage full — the choice still applies to this page */
  }
  applyMotionPrefs(merged)
  if (typeof window !== 'undefined') window.dispatchEvent(new CustomEvent(MOTION_EVENT, { detail: merged }))
  return merged
}

export function prefersReducedMotion(): boolean {
  try {
    return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(REDUCED_QUERY).matches
  } catch {
    return false
  }
}

/**
 * Unit tests run in jsdom, which has no layout and no real animation frames.
 * Components render their final state there, so tests see what a person sees
 * once an animation has finished.
 */
function isTestDom(): boolean {
  return typeof navigator !== 'undefined' && /jsdom/i.test(navigator.userAgent || '')
}

/** Whether time-based animation (progressive reveal, exit transitions) should run. */
export function motionAllowed(prefs: MotionPrefs = readMotionPrefs()): boolean {
  return prefs.level !== 'off' && !prefersReducedMotion() && !isTestDom()
}

/** The current preference, kept up to date when it changes here, in another tab, or in the OS. */
export function useMotionPrefs(): MotionPrefs {
  const [prefs, setPrefs] = useState<MotionPrefs>(readMotionPrefs)
  const [, rerender] = useReducer((n: number) => n + 1, 0)
  useEffect(() => {
    const sync = () => setPrefs(readMotionPrefs())
    const onStorage = (e: StorageEvent) => {
      if (e.key === MOTION_STORAGE_KEY) {
        applyMotionPrefs()
        sync()
      }
    }
    window.addEventListener(MOTION_EVENT, sync)
    window.addEventListener('storage', onStorage)
    let mq: MediaQueryList | null = null
    try {
      mq = typeof window.matchMedia === 'function' ? window.matchMedia(REDUCED_QUERY) : null
      mq?.addEventListener?.('change', rerender)
    } catch {
      mq = null
    }
    return () => {
      window.removeEventListener(MOTION_EVENT, sync)
      window.removeEventListener('storage', onStorage)
      mq?.removeEventListener?.('change', rerender)
    }
  }, [])
  return prefs
}
