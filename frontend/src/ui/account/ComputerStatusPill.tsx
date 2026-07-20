/**
 * ComputerStatusPill (Batch 4) — the header "Studio PC · Online" control.
 *
 * Binds to the Batch-2 spine (ComputerContext + HomePilotAccountProvider) and
 * shows live presence WITHOUT a manual Refresh — the account provider already
 * polls `/v1/account/mirror/nodes` on an interval (a cloud SSE presence stream
 * will make this <10s in a later cloud batch). Clicking opens the Journey-B
 * picker (Automatic / a specific computer); selection updates ComputerContext
 * only — it does NOT route execution yet (that is Batch 5).
 *
 * ADDITIVE: renders `null` unless the Account & Computers flag is on and there
 * is at least one computer, so dropping it into the header changes nothing by
 * default.
 */
import React, { useEffect, useRef, useState } from 'react'
import { ChevronDown, Monitor } from 'lucide-react'

import { useAccount } from './HomePilotAccountProvider'
import { useComputer } from './ComputerContext'
import type { PresenceState } from './types'

function dotClass(state: PresenceState): string {
  return state === 'online' ? 'bg-emerald-400'
    : state === 'attention' ? 'bg-amber-400'
      : 'bg-white/30'
}

export function ComputerStatusPill(): JSX.Element | null {
  const { enabled, computers, loading, refresh } = useAccount()
  const { selectedComputer, selectionMode, presenceOf, anyOnline, selectComputer, setSelectionMode } = useComputer()

  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  // Additive: invisible unless enabled and there is something to show.
  if (!enabled || computers.length === 0) return null

  // Resolve the pill's label + presence.
  let label: string
  let state: PresenceState
  if (selectionMode === 'fixed' && selectedComputer) {
    label = selectedComputer.node_name || selectedComputer.node_id
    state = presenceOf(selectedComputer.node_id) // offline fixed pick → 'offline' (attention)
    if (state === 'offline') state = 'attention'
  } else if (computers.length === 1) {
    const c = computers[0]
    label = c.node_name || c.node_id
    state = presenceOf(c.node_id)
  } else {
    label = 'Automatic'
    state = anyOnline ? 'online' : 'offline'
  }

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => { if (!open) refresh(); setOpen((v) => !v) }}
        className="h-9 pl-2.5 pr-2 flex items-center gap-1.5 rounded-full bg-white/5 border border-white/10 text-white/70 hover:bg-white/10 hover:text-white transition-colors max-w-[220px]"
        title="Where AI tasks run"
        aria-haspopup="menu"
        aria-expanded={open}
      >
        <span className={`w-2 h-2 rounded-full ${dotClass(state)} shrink-0`} />
        <span className="text-[12px] truncate">{label}</span>
        <ChevronDown size={14} className="text-white/40 shrink-0" />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-64 rounded-2xl border border-white/10 bg-[#17181a] shadow-2xl p-1.5 z-[60]"
        >
          <button
            role="menuitem"
            onClick={() => { setSelectionMode('automatic'); setOpen(false) }}
            className={`w-full text-left px-3 py-2 rounded-xl flex items-center gap-2 text-[13px] ${
              selectionMode !== 'fixed' ? 'bg-violet-500/15 text-white' : 'text-white/70 hover:bg-white/5'
            }`}
          >
            <span className={`w-2 h-2 rounded-full ${anyOnline ? 'bg-emerald-400' : 'bg-white/30'}`} />
            <span className="flex-1">Automatic</span>
            <span className="text-[10px] text-white/40">recommended</span>
          </button>

          <div className="my-1 h-px bg-white/10" />

          {computers.map((c) => {
            const st = presenceOf(c.node_id)
            const active = selectionMode === 'fixed' && selectedComputer?.node_id === c.node_id
            return (
              <button
                key={c.node_id}
                role="menuitem"
                onClick={() => { selectComputer(c.node_id); setOpen(false) }}
                className={`w-full text-left px-3 py-2 rounded-xl flex items-center gap-2 text-[13px] ${
                  active ? 'bg-violet-500/15 text-white' : 'text-white/70 hover:bg-white/5'
                }`}
              >
                <span className={`w-2 h-2 rounded-full ${dotClass(st)} shrink-0`} />
                <Monitor size={13} className="text-white/40 shrink-0" />
                <span className="flex-1 truncate">{c.node_name || c.node_id}</span>
                <span className="text-[10px] text-white/40">{st === 'online' ? 'Online' : 'Offline'}</span>
              </button>
            )
          })}

          <div className="px-3 pt-1.5 pb-1 text-[10px] text-white/30">
            {loading ? 'Updating…' : 'Updates automatically'}
          </div>
        </div>
      )}
    </div>
  )
}
