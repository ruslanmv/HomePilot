/**
 * HomePilotAccountProvider (Batch 2) — shared account + computers state.
 *
 * Design §11: one provider owns the signed-in account and the list of
 * computers, so individual components stop re-deriving it. This first cut is
 * ADDITIVE and READ-ONLY: it is backed by the EXISTING HomePilot auth token
 * (it does not change AuthScreen — that is strangled in Batch 7), and it does
 * NO network at all unless the Account & Computers feature flag is on.
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import { isAccountsUxEnabled } from './featureFlags'
import { MirrorError, mirrorClient } from './mirrorClient'
import type { MirrorNode, MirrorStatus } from './types'

export interface AccountContextValue {
  /** Whether the Account & Computers experience is enabled at all. */
  enabled: boolean
  /** BFF/cloud readiness; null until first probe. */
  status: MirrorStatus | null
  /** The account's computers (empty until loaded / when disabled). */
  computers: MirrorNode[]
  loading: boolean
  /** Human-readable error, or null. `notLinked` distinguishes the common
   *  "no cloud credential yet" case so the UI can show onboarding, not an error. */
  error: string | null
  notLinked: boolean
  lastUpdated: number | null
  /** Manually refetch status + computers. */
  refresh: () => void
}

const DEFAULT: AccountContextValue = {
  enabled: false,
  status: null,
  computers: [],
  loading: false,
  error: null,
  notLinked: false,
  lastUpdated: null,
  refresh: () => {},
}

const AccountCtx = createContext<AccountContextValue>(DEFAULT)

// Light presence poll while enabled and the tab is visible. Batch 4 replaces
// this with a push presence stream; kept modest here to avoid chatter.
const POLL_MS = 20_000

export function HomePilotAccountProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const enabled = isAccountsUxEnabled()

  const [status, setStatus] = useState<MirrorStatus | null>(null)
  const [computers, setComputers] = useState<MirrorNode[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notLinked, setNotLinked] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<number | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const tickRef = useRef(0)

  const load = useCallback(async () => {
    if (!enabled) return
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    try {
      const st = await mirrorClient.status(ctrl.signal)
      setStatus(st)
      if (!st.linked) {
        // Not linked yet is an expected onboarding state, not an error.
        setComputers([])
        setNotLinked(true)
        setError(null)
        setLastUpdated(Date.now())
        return
      }
      setNotLinked(false)
      const nodes = await mirrorClient.listNodes(ctrl.signal)
      setComputers(nodes)
      setError(null)
      setLastUpdated(Date.now())
    } catch (e) {
      if (ctrl.signal.aborted) return
      if (e instanceof MirrorError && e.isNotLinked) {
        setNotLinked(true)
        setComputers([])
        setError(null)
      } else {
        setError(e instanceof Error ? e.message : 'Failed to load computers')
      }
      setLastUpdated(Date.now())
    } finally {
      if (!ctrl.signal.aborted) setLoading(false)
    }
  }, [enabled])

  const refresh = useCallback(() => {
    tickRef.current += 1
    void load()
  }, [load])

  // Initial load + visibility-aware polling. Entirely inert when disabled.
  useEffect(() => {
    if (!enabled) return
    void load()
    let timer: ReturnType<typeof setInterval> | null = null
    const start = () => {
      if (timer) return
      timer = setInterval(() => {
        if (typeof document === 'undefined' || document.visibilityState === 'visible') void load()
      }, POLL_MS)
    }
    const stop = () => {
      if (timer) { clearInterval(timer); timer = null }
    }
    start()
    const onVis = () => {
      if (document.visibilityState === 'visible') { void load(); start() } else { stop() }
    }
    document.addEventListener('visibilitychange', onVis)
    return () => {
      stop()
      document.removeEventListener('visibilitychange', onVis)
      abortRef.current?.abort()
    }
  }, [enabled, load])

  const value = useMemo<AccountContextValue>(
    () => ({ enabled, status, computers, loading, error, notLinked, lastUpdated, refresh }),
    [enabled, status, computers, loading, error, notLinked, lastUpdated, refresh],
  )

  return <AccountCtx.Provider value={value}>{children}</AccountCtx.Provider>
}

/** Read the shared account state. Safe outside a provider (returns defaults). */
export function useAccount(): AccountContextValue {
  return useContext(AccountCtx)
}
