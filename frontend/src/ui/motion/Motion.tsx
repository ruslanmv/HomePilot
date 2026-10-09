/**
 * Motion primitives — small, dependency-free components over motion.css.
 *
 * Each renders something meaningful with motion switched off (a readable label,
 * a static bar, the final content), so an animation is never the only signal.
 */
import React, { useEffect, useRef, useState } from 'react'
import { motionAllowed, useMotionPrefs } from './prefs'

type Tag = 'span' | 'div' | 'p'

/** 1 — A working label with a moving band of light ("Searching the web…"). */
export function ShimmerText({ children, className = '', as: As = 'span' }: { children: React.ReactNode; className?: string; as?: Tag }) {
  return <As className={`hp-shimmer-text ${className}`}>{children}</As>
}

/** 2 — A label that gently brightens and dims ("Saving…"). */
export function PulseText({ children, className = '', as: As = 'span' }: { children: React.ReactNode; className?: string; as?: Tag }) {
  return <As className={`hp-pulse-text ${className}`}>{children}</As>
}

/** 4 — The cursor shown while text is still arriving. Decorative. */
export function TypingCursor({ className = '' }: { className?: string }) {
  return <span className={`hp-caret ${className}`} aria-hidden="true" />
}

/** 5 — Three dots that ripple. Announced once as `label`. */
export function LoadingDots({ label = 'Loading', className = '' }: { label?: string; className?: string }) {
  return (
    <span className={`hp-dots ${className}`} role="img" aria-label={label}>
      <span />
      <span />
      <span />
    </span>
  )
}

/** 6 — An inline spinner sized to the text around it. */
export function Spinner({ size = 16, label, className = '' }: { size?: number; label?: string; className?: string }) {
  return (
    <span
      className={`hp-spin ${className}`}
      style={{ ['--hp-spin-size' as string]: `${size}px` }}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  )
}

/** 7 — Placeholder blocks with a light sweep while content loads. */
export function Skeleton({
  lines = 1,
  width = '100%',
  height = 12,
  gap = 8,
  radius = 8,
  className = '',
}: {
  lines?: number
  width?: number | string
  height?: number
  gap?: number
  radius?: number
  className?: string
}) {
  return (
    <span className={`flex flex-col ${className}`} style={{ gap }} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <span
          key={i}
          className="hp-skeleton"
          // The last line of a paragraph is shorter, as real text would be.
          style={{ width: lines > 1 && i === lines - 1 ? '62%' : width, height, borderRadius: radius }}
        />
      ))}
    </span>
  )
}

/** 22 — Progress: determinate when `value` (0..1) is known, otherwise a sweep. */
export function ProgressBar({ value, label, className = '' }: { value?: number | null; label: string; className?: string }) {
  const known = typeof value === 'number' && Number.isFinite(value)
  const pct = known ? Math.round(Math.max(0, Math.min(1, value as number)) * 100) : undefined
  return (
    <span
      className={`hp-progress ${className}`}
      role="progressbar"
      aria-label={label}
      aria-valuemin={known ? 0 : undefined}
      aria-valuemax={known ? 100 : undefined}
      aria-valuenow={pct}
      data-indeterminate={known ? 'false' : 'true'}
    >
      <span style={known ? { width: `${pct}%` } : undefined} />
    </span>
  )
}

/** 12/13 — Content that opens and closes smoothly. Closed content is hidden from everyone. */
export function Collapsible({ open, children, id, className = '' }: { open: boolean; children: React.ReactNode; id?: string; className?: string }) {
  return (
    <div id={id} className={`hp-collapsible ${className}`} data-open={open ? 'true' : 'false'} aria-hidden={open ? undefined : true}>
      <div>{children}</div>
    </div>
  )
}

/**
 * 17 — A status line that changes ("Searching" → "Reading 3 sources" → "Writing").
 * The previous label leaves upward while the new one arrives; while work is
 * under way the label shimmers. Screen readers hear each new label once.
 */
export function StatusText({ text, working = true, className = '' }: { text: string; working?: boolean; className?: string }) {
  const prefs = useMotionPrefs()
  const [current, setCurrent] = useState(text)
  const [leaving, setLeaving] = useState<string | null>(null)
  const timer = useRef<number | null>(null)
  const lastChange = useRef(0)

  useEffect(() => {
    if (text === current) return
    // Animate only calm changes. A status that flips several times a second
    // (a voice detector toggling between two states) swaps instantly — two
    // labels sliding past each other all the time read as overlapping text.
    const now = Date.now()
    const calm = now - lastChange.current > 700
    lastChange.current = now
    if (timer.current) window.clearTimeout(timer.current)
    if (calm && motionAllowed(prefs)) {
      setLeaving(current)
      timer.current = window.setTimeout(() => setLeaving(null), 260)
    } else {
      setLeaving(null)
    }
    setCurrent(text)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text])
  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current) }, [])

  const label = working ? <ShimmerText>{current}</ShimmerText> : <span>{current}</span>
  return (
    <span className={`hp-status-swap ${className}`} role="status" aria-live="polite">
      {leaving ? (
        <span key={`out-${leaving}`} className="hp-status-swap__out" aria-hidden="true">
          {leaving}
        </span>
      ) : null}
      <span key={current} className={leaving ? 'hp-status-swap__in' : undefined}>
        {label}
      </span>
    </span>
  )
}

/**
 * 8–11 — Keeps content mounted long enough to animate out.
 * `variant` picks fade, slide from the left (panels) or slide up (sheets).
 */
export function Presence({
  show,
  children,
  variant = 'fade',
  className = '',
}: {
  show: boolean
  children: React.ReactNode
  variant?: 'fade' | 'slide-left' | 'slide-up'
  className?: string
}) {
  const prefs = useMotionPrefs()
  const [mounted, setMounted] = useState(show)
  const [leaving, setLeaving] = useState(false)
  useEffect(() => {
    if (show) {
      setMounted(true)
      setLeaving(false)
      return
    }
    if (!mounted) return
    if (!motionAllowed(prefs)) {
      setMounted(false)
      return
    }
    setLeaving(true)
    const t = window.setTimeout(() => {
      setMounted(false)
      setLeaving(false)
    }, 180)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [show])
  if (!mounted) return null
  const enter = variant === 'slide-left' ? 'hp-enter-slide-left' : variant === 'slide-up' ? 'hp-enter-slide-up' : 'hp-enter-fade'
  const exit = variant === 'slide-left' ? 'hp-exit-slide-left' : variant === 'slide-up' ? 'hp-exit-slide-down' : 'hp-exit-fade'
  return <div className={`${leaving ? exit : enter} ${className}`} aria-hidden={leaving || undefined}>{children}</div>
}

export type OrbState = 'idle' | 'listening' | 'thinking' | 'speaking' | 'off'

/** 18 — The voice orb: breathes when idle, follows your voice, orbits while thinking, rings while speaking. */
export function VoiceOrb({ state, level = 0, size = 128, className = '' }: { state: OrbState; level?: number; size?: number; className?: string }) {
  const lvl = Math.max(0, Math.min(1, Number.isFinite(level) ? level : 0))
  return (
    <div
      className={`hp-orb ${className}`}
      data-state={state}
      style={{ ['--hp-level' as string]: state === 'listening' || state === 'speaking' ? lvl.toFixed(3) : '0', ['--hp-orb-size' as string]: `${size}px` }}
      aria-hidden="true"
    />
  )
}

/** Bar weights: tallest in the middle, like a voice envelope. */
export function waveformWeights(count: number): number[] {
  const n = Math.max(1, Math.floor(count))
  return Array.from({ length: n }, (_, i) => {
    const x = n === 1 ? 0 : (i / (n - 1)) * 2 - 1 // -1..1
    return 0.35 + 0.65 * Math.cos((x * Math.PI) / 2) ** 2
  })
}

/** 19 — An audio waveform whose bars follow the live level. */
export function AudioWaveform({
  level = 0,
  active = true,
  bars = 24,
  height = 28,
  className = '',
}: {
  level?: number
  active?: boolean
  bars?: number
  height?: number
  className?: string
}) {
  const lvl = Math.max(0, Math.min(1, Number.isFinite(level) ? level : 0))
  const weights = React.useMemo(() => waveformWeights(bars), [bars])
  return (
    <span className={`hp-wave ${className}`} data-active={active ? 'true' : 'false'} style={{ ['--hp-wave-h' as string]: `${height}px` }} aria-hidden="true">
      {weights.map((w, i) => {
        // A floor keeps the shape visible at silence; the level lifts every bar by its weight.
        const s = active ? 0.14 + (0.18 + lvl * 0.82) * w * 0.86 : 0.12 + w * 0.08
        return <span key={i} style={{ transform: `scaleY(${s.toFixed(3)})`, animationDelay: `${(i % 6) * -0.17}s` }} />
      })}
    </span>
  )
}
