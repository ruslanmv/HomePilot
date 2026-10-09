/**
 * StreamReveal — reveals a newly arrived answer progressively, with a typing
 * cursor riding the end of the last line (animations 3, 4 and 16).
 *
 * HomePilot receives an answer whole, so this is presentation only: the full
 * text is already in state, copy works on all of it, and a tap shows the rest
 * at once. The reveal is paced by length — short replies settle in about half
 * a second, long ones never take more than ~1.6 s — so it reads as lively
 * rather than slow.
 *
 * With `active` false (history, the "fade"/"instant" preference, motion off,
 * reduced motion) it renders the final content in the same element, so
 * switching between the two never remounts what is on screen.
 */
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { motionAllowed } from './prefs'

const MIN_MS = 450
const MAX_MS = 1600
const MS_PER_WORD = 14
const FRAME_MS = 33 // ~30 fps is plenty for text and keeps Markdown re-renders cheap

/** Character offsets at which the visible text may end: after each word. */
export function revealStops(text: string): number[] {
  const stops: number[] = []
  const re = /\S+\s*/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) stops.push(m.index + m[0].length)
  if (!stops.length || stops[stops.length - 1] !== text.length) stops.push(text.length)
  return stops
}

export function revealDuration(words: number): number {
  return Math.max(MIN_MS, Math.min(MAX_MS, words * MS_PER_WORD))
}

/**
 * The text to render for a partial reveal. An unfinished code fence is closed
 * so the partial answer still renders as code rather than as a paragraph of
 * backticks.
 */
export function partialMarkdown(text: string, end: number): string {
  const head = text.slice(0, end)
  const fences = head.match(/^\s*(```|~~~)/gm)?.length ?? 0
  return fences % 2 === 1 ? `${head}\n\`\`\`` : head
}

/** The element that should carry the cursor: the deepest last text block. */
function caretHost(root: HTMLElement): HTMLElement | null {
  let el: Element | null = root
  let host: HTMLElement | null = null
  while (el && el.lastElementChild) {
    el = el.lastElementChild
    if (el.matches('p, li, h1, h2, h3, h4, h5, h6, td, th, blockquote, code')) host = el as HTMLElement
  }
  return host
}

export function StreamReveal({
  text,
  active: requested,
  render,
  onProgress,
  onDone,
  className = '',
}: {
  text: string
  active: boolean
  render: (visibleText: string) => React.ReactNode
  onProgress?: () => void
  onDone?: () => void
  className?: string
}) {
  // Never animate where motion can't or shouldn't run (Settings → Motion off,
  // the OS reduce-motion setting, unit tests): show the answer whole.
  const active = requested && motionAllowed()
  const [end, setEnd] = useState<number>(() => (active ? 0 : text.length))
  const [running, setRunning] = useState(active)
  const rootRef = useRef<HTMLDivElement>(null)
  const rafRef = useRef(0)
  const doneRef = useRef(onDone)
  const progressRef = useRef(onProgress)
  doneRef.current = onDone
  progressRef.current = onProgress

  useEffect(() => {
    if (!active) {
      setEnd(text.length)
      setRunning(false)
      return
    }
    const stops = revealStops(text)
    const total = revealDuration(stops.length)
    const started = performance.now()
    let last = 0
    setRunning(true)
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / total)
      if (t >= 1) {
        setEnd(text.length)
        setRunning(false)
        doneRef.current?.()
        return
      }
      if (now - last >= FRAME_MS) {
        last = now
        // Ease out: quick start, gentle finish.
        const eased = 1 - (1 - t) ** 2
        setEnd(stops[Math.min(stops.length - 1, Math.floor(eased * stops.length))])
        progressRef.current?.()
      }
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [active, text])

  // Put the cursor at the end of the last line that is showing.
  useLayoutEffect(() => {
    const root = rootRef.current
    if (!root) return
    root.querySelectorAll('[data-hp-caret]').forEach((el) => el.removeAttribute('data-hp-caret'))
    if (running) caretHost(root)?.setAttribute('data-hp-caret', '')
  })

  const finish = () => {
    if (!running) return
    cancelAnimationFrame(rafRef.current)
    setEnd(text.length)
    setRunning(false)
    doneRef.current?.()
  }

  return (
    <div
      ref={rootRef}
      className={`${running ? 'hp-stream' : ''} ${className}`}
      aria-busy={running || undefined}
      onClick={running ? finish : undefined}
      title={running ? 'Show the whole answer' : undefined}
    >
      {render(running ? partialMarkdown(text, end) : text)}
    </div>
  )
}

export default StreamReveal
