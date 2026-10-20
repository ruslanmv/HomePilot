import { useEffect, useRef, useState } from 'react'

export type ConnStatus = 'disconnected' | 'connecting' | 'connected' | 'lost'

/** Retry delays while a remembered connection is down: 5 s, 10 s, 20 s, 40 s, then every 60 s. */
export const RECONNECT_BACKOFF_MS = [5_000, 10_000, 20_000, 40_000, 60_000]
const FOCUS_RECHECK_GAP_MS = 15_000

/**
 * Keeps a connection honest: re-verifies it when the tab regains focus (at most
 * every 15 s) and, while it is `lost`, retries with exponential backoff until
 * the endpoint answers again. `verify` must not flip the status to
 * `connecting` — it resolves to `connected`, `lost` or `disconnected`.
 */
export function useReconnect(status: ConnStatus, verify: () => Promise<void>): void {
  const verifyRef = useRef(verify)
  verifyRef.current = verify
  const statusRef = useRef(status)
  statusRef.current = status
  const lastCheckRef = useRef(0)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const onWake = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      const s = statusRef.current
      if (s !== 'connected' && s !== 'lost') return
      const now = Date.now()
      if (now - lastCheckRef.current < FOCUS_RECHECK_GAP_MS) return
      lastCheckRef.current = now
      void verifyRef.current()
    }
    window.addEventListener('focus', onWake)
    document.addEventListener('visibilitychange', onWake)
    return () => {
      window.removeEventListener('focus', onWake)
      document.removeEventListener('visibilitychange', onWake)
    }
  }, [])

  useEffect(() => {
    if (status !== 'lost') {
      setAttempt(0)
      return
    }
    const delay = RECONNECT_BACKOFF_MS[Math.min(attempt, RECONNECT_BACKOFF_MS.length - 1)]
    const timer = setTimeout(() => {
      lastCheckRef.current = Date.now()
      void verifyRef.current().finally(() => setAttempt((a) => a + 1))
    }, delay)
    return () => clearTimeout(timer)
  }, [status, attempt])
}
