/**
 * MirrorDevPanel (Batch 2) — dev-only proof that the spine works.
 *
 * Renders nothing unless the mirror debug flag is on (`?mirrorDebug=1` or
 * `localStorage.homepilot_mirror_debug = '1'`). When visible it lists the
 * account's computers with live online state, sourced entirely through
 * MirrorClient → BFF → cloud. This satisfies the Batch-2 exit criterion without
 * touching any product UI.
 *
 * Self-contained inline styles so it never depends on (or perturbs) the app's
 * design system.
 */
import React from 'react'

import { isMirrorDebug } from './featureFlags'
import { useAccount } from './HomePilotAccountProvider'
import { useComputer } from './ComputerContext'
import type { PresenceState } from './types'

const DOT: Record<PresenceState, string> = {
  online: '#22c55e',
  offline: '#6b7280',
  attention: '#f59e0b',
  unknown: '#6b7280',
}

export function MirrorDevPanel(): JSX.Element | null {
  if (!isMirrorDebug()) return null
  return <MirrorDevPanelInner />
}

function MirrorDevPanelInner(): JSX.Element {
  const { enabled, status, computers, loading, error, notLinked, lastUpdated, refresh } = useAccount()
  const { selectedComputerId, selectionMode, selectComputer, presenceOf } = useComputer()

  return (
    <div style={{
      position: 'fixed', right: 12, bottom: 12, zIndex: 99999, width: 320,
      background: 'rgba(17,17,20,0.96)', color: '#e5e7eb', border: '1px solid rgba(255,255,255,0.12)',
      borderRadius: 12, padding: 12, font: '12px/1.4 ui-monospace, monospace',
      boxShadow: '0 8px 30px rgba(0,0,0,0.5)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <strong style={{ fontSize: 12 }}>Mirror · Computers</strong>
        <button
          onClick={refresh}
          style={{ background: 'rgba(255,255,255,0.08)', color: '#e5e7eb', border: '1px solid rgba(255,255,255,0.15)',
                   borderRadius: 6, padding: '2px 8px', cursor: 'pointer' }}
        >
          {loading ? '…' : 'Refresh'}
        </button>
      </div>

      <div style={{ opacity: 0.7, marginBottom: 8 }}>
        flag:{enabled ? 'on' : 'off'} · linked:{status ? String(status.linked) : '?'} · mode:{selectionMode}
        {lastUpdated ? ` · ${new Date(lastUpdated).toLocaleTimeString()}` : ''}
      </div>

      {!enabled && <div style={{ opacity: 0.7 }}>Account UX flag is off — set localStorage.homepilot_accounts_ux=1</div>}
      {enabled && notLinked && <div style={{ opacity: 0.8 }}>No cloud account linked yet.</div>}
      {enabled && error && <div style={{ color: '#f87171' }}>Error: {error}</div>}
      {enabled && !notLinked && !error && computers.length === 0 && !loading && (
        <div style={{ opacity: 0.7 }}>No computers found.</div>
      )}

      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {computers.map((c) => {
          const state: PresenceState = presenceOf(c.node_id)
          const selected = c.node_id === selectedComputerId
          return (
            <li
              key={c.node_id}
              onClick={() => selectComputer(selected ? null : c.node_id)}
              title={c.node_id}
              style={{
                display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', cursor: 'pointer',
                borderRadius: 8, marginTop: 4,
                background: selected ? 'rgba(139,92,246,0.18)' : 'rgba(255,255,255,0.03)',
                border: selected ? '1px solid rgba(139,92,246,0.5)' : '1px solid transparent',
              }}
            >
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: DOT[state], flex: '0 0 auto' }} />
              <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {c.node_name || c.node_id}
              </span>
              <span style={{ opacity: 0.6 }}>{c.platform || '—'}</span>
              <span style={{ opacity: 0.6 }}>{state}</span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
