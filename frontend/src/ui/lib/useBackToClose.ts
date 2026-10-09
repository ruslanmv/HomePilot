/**
 * useBackToClose — the phone's Back gesture closes the open layer (drawer,
 * full-screen settings) instead of leaving HomePilot.
 *
 * While `open`, one history entry is added for the layer. Back pops it and
 * `onClose` runs; closing the layer any other way removes the entry again.
 * Layers stack: each records its depth, and Back only closes layers above the
 * entry it lands on — so Back from Settings opened over the drawer closes
 * Settings and leaves the drawer open.
 *
 * If the owner declines to close (e.g. "Discard unsaved changes?" → Cancel),
 * the entry is restored so the next Back is caught again.
 */
import { useEffect, useRef } from 'react'

type LayerState = { hpLayer?: number }

function depthOf(state: unknown): number {
  const d = (state as LayerState | null)?.hpLayer
  return typeof d === 'number' ? d : 0
}

export function useBackToClose(open: boolean, onClose: () => void): void {
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    if (!open || typeof window === 'undefined' || !window.history?.pushState) return
    let alive = true
    let pushed = false
    let depth = 0

    const push = () => {
      depth = depthOf(window.history.state) + 1
      window.history.pushState({ ...(window.history.state || {}), hpLayer: depth }, '')
      pushed = true
    }
    // Deferred one tick so React StrictMode's mount → unmount → mount in
    // development doesn't leave a stray entry behind.
    const startTimer = window.setTimeout(() => {
      if (alive) push()
    }, 0)

    const onPop = (e: PopStateEvent) => {
      if (!pushed || depthOf(e.state) >= depth) return
      pushed = false
      closeRef.current()
      // Still open after asking to close → the owner kept it; catch the next Back too.
      window.setTimeout(() => {
        if (alive && !pushed) push()
      }, 0)
    }
    window.addEventListener('popstate', onPop)

    return () => {
      alive = false
      window.clearTimeout(startTimer)
      window.removeEventListener('popstate', onPop)
      if (pushed && depthOf(window.history.state) === depth) window.history.back()
    }
  }, [open])
}

export default useBackToClose
