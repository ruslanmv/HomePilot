/**
 * ComputerContext (Batch 2) — where AI work should run.
 *
 * Design §11: a shared context holding `selectedComputer`, `selectionMode`, and
 * per-computer presence/capabilities. This first cut is READ-ONLY toward the
 * backend: it only reflects the account's computers (from HomePilotAccountProvider)
 * and remembers a local selection preference. It does not yet route execution
 * (that is Batch 5) or mutate anything server-side.
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'

import { getCurrentUserId, userScopedKey } from '../lib/userScopedStorage'
import { useAccount } from './HomePilotAccountProvider'
import type { MirrorNode, PresenceState, SelectionMode } from './types'

const LS_SELECTED = 'homepilot_selected_computer'
const LS_MODE = 'homepilot_selection_mode'

function readScoped(baseKey: string): string | null {
  try {
    const uid = getCurrentUserId()
    return localStorage.getItem(uid ? userScopedKey(baseKey, uid) : `${baseKey}:user:anon`)
  } catch {
    return null
  }
}
function writeScoped(baseKey: string, value: string | null): void {
  try {
    const uid = getCurrentUserId()
    const key = uid ? userScopedKey(baseKey, uid) : `${baseKey}:user:anon`
    if (value == null) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    /* ignore */
  }
}

export interface ComputerContextValue {
  /** All linked computers (mirrors the account provider). */
  computers: MirrorNode[]
  /** The node_id the user picked, or null in automatic/ask mode. */
  selectedComputerId: string | null
  /** The resolved selected computer object, if online & known. */
  selectedComputer: MirrorNode | null
  selectionMode: SelectionMode
  /** Presence lookup by node_id. */
  presenceOf: (nodeId: string) => PresenceState
  /** True if at least one computer is online. */
  anyOnline: boolean
  /** Pick a specific computer (switches mode to 'fixed'). */
  selectComputer: (nodeId: string | null) => void
  setSelectionMode: (mode: SelectionMode) => void
}

const DEFAULT: ComputerContextValue = {
  computers: [],
  selectedComputerId: null,
  selectedComputer: null,
  selectionMode: 'automatic',
  presenceOf: () => 'unknown',
  anyOnline: false,
  selectComputer: () => {},
  setSelectionMode: () => {},
}

const ComputerCtx = createContext<ComputerContextValue>(DEFAULT)

export function ComputerProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const { computers, enabled } = useAccount()

  const [selectedComputerId, setSelectedId] = useState<string | null>(() => readScoped(LS_SELECTED))
  const [selectionMode, setModeState] = useState<SelectionMode>(() => {
    const m = readScoped(LS_MODE)
    return m === 'fixed' || m === 'ask' || m === 'automatic' ? m : 'automatic'
  })

  const selectComputer = useCallback((nodeId: string | null) => {
    setSelectedId(nodeId)
    writeScoped(LS_SELECTED, nodeId)
    // Choosing a specific machine implies a fixed preference.
    const nextMode: SelectionMode = nodeId ? 'fixed' : 'automatic'
    setModeState(nextMode)
    writeScoped(LS_MODE, nextMode)
  }, [])

  const setSelectionMode = useCallback((mode: SelectionMode) => {
    setModeState(mode)
    writeScoped(LS_MODE, mode)
    if (mode !== 'fixed') {
      setSelectedId(null)
      writeScoped(LS_SELECTED, null)
    }
  }, [])

  // If the selected computer disappears from the account, drop the stale pick.
  useEffect(() => {
    if (!enabled) return
    if (selectedComputerId && computers.length > 0 &&
        !computers.some((c) => c.node_id === selectedComputerId)) {
      selectComputer(null)
    }
  }, [enabled, computers, selectedComputerId, selectComputer])

  const presenceOf = useCallback((nodeId: string): PresenceState => {
    const c = computers.find((x) => x.node_id === nodeId)
    if (!c) return 'unknown'
    return c.online ? 'online' : 'offline'
  }, [computers])

  const selectedComputer = useMemo(
    () => computers.find((c) => c.node_id === selectedComputerId) ?? null,
    [computers, selectedComputerId],
  )
  const anyOnline = useMemo(() => computers.some((c) => c.online), [computers])

  const value = useMemo<ComputerContextValue>(() => ({
    computers,
    selectedComputerId,
    selectedComputer,
    selectionMode,
    presenceOf,
    anyOnline,
    selectComputer,
    setSelectionMode,
  }), [computers, selectedComputerId, selectedComputer, selectionMode, presenceOf, anyOnline, selectComputer, setSelectionMode])

  return <ComputerCtx.Provider value={value}>{children}</ComputerCtx.Provider>
}

/** Read the shared computer-selection state. Safe outside a provider. */
export function useComputer(): ComputerContextValue {
  return useContext(ComputerCtx)
}
