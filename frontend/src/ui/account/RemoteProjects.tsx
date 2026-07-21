/**
 * RemoteProjects (Batch 9) — projects stored on your other computers.
 *
 * Lists each online node's projects (mirror `projects.list`) with a
 * "Stored on Studio PC" badge, honest offline state (Batch 6), and an Open
 * action that selects that computer so chat runs on it (Batch 5). Read-only
 * over existing whitelisted RPC — NO project data is copied to the cloud.
 *
 * ADDITIVE and flag-gated: renders null when the Account & Computers flag is
 * off, so the Projects page is unchanged by default.
 */
import React, { useEffect, useMemo, useState } from 'react'
import { FolderKanban, RefreshCw } from 'lucide-react'

import { isAccountsUxEnabled } from './featureFlags'
import { useAccount } from './HomePilotAccountProvider'
import { useComputer } from './ComputerContext'
import { MirrorError, mirrorClient } from './mirrorClient'

interface RemoteProject { id?: string; name?: string; project_type?: string }
interface Row { hpuri: string; nodeId: string; nodeName: string; online: boolean; id: string; name: string; type: string }

export function RemoteProjects(): JSX.Element | null {
  if (!isAccountsUxEnabled()) return null
  return <RemoteProjectsInner />
}

function RemoteProjectsInner(): JSX.Element | null {
  const { computers, loading, refresh } = useAccount()
  const { selectComputer } = useComputer()
  const [byNode, setByNode] = useState<Record<string, RemoteProject[] | null>>({})

  useEffect(() => {
    let cancelled = false
    computers.filter((c) => c.online && byNode[c.node_id] === undefined).forEach(async (c) => {
      try {
        const list = await mirrorClient.rpc<RemoteProject[]>(c.node_id, 'projects.list', {})
        if (!cancelled) setByNode((p) => ({ ...p, [c.node_id]: Array.isArray(list) ? list : [] }))
      } catch (e) {
        if (!(e instanceof MirrorError && e.isNodeOffline) && !cancelled) {
          setByNode((p) => ({ ...p, [c.node_id]: null }))
        }
      }
    })
    return () => { cancelled = true }
  }, [computers, byNode])

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = []
    for (const c of computers) {
      for (const p of byNode[c.node_id] || []) {
        if (!p.id) continue
        out.push({
          hpuri: `hpnode://${c.node_id}/project/${p.id}`,
          nodeId: c.node_id, nodeName: c.node_name || c.node_id, online: c.online,
          id: p.id, name: p.name || p.id, type: p.project_type || 'project',
        })
      }
    }
    return out
  }, [computers, byNode])

  const openRemote = (r: Row) => {
    // Open = run on the owning computer. Select it (Batch-5 routes chat there)
    // and remember the project context. No cloud copy is made.
    selectComputer(r.nodeId)
    try { localStorage.setItem('homepilot_current_project', r.id) } catch { /* ignore */ }
    window.dispatchEvent(new CustomEvent('homepilot:open-remote-project', {
      detail: { nodeId: r.nodeId, projectId: r.id },
    }))
  }

  // Nothing to show unless at least one computer exists.
  if (computers.length === 0) return null

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 mb-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <FolderKanban size={16} className="text-white/60" />
          <h3 className="text-sm font-semibold text-white/80">Projects on your computers</h3>
        </div>
        <button onClick={refresh} className="text-[11px] px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/60 inline-flex items-center gap-1">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      {/* Offline computers: honest state, never a silent downgrade. */}
      {computers.filter((c) => !c.online).map((c) => (
        <div key={c.node_id} className="text-[11px] text-amber-200/70 mb-1.5">
          {c.node_name || c.node_id} is offline — its projects are available when you turn it on.
        </div>
      ))}

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        {rows.map((r) => (
          <button
            key={r.hpuri}
            onClick={() => openRemote(r)}
            disabled={!r.online}
            className="text-left rounded-xl border border-white/10 bg-white/[0.02] hover:bg-white/[0.05] px-3 py-2.5 disabled:opacity-50"
          >
            <div className="text-[13px] text-white/90 truncate">{r.name}</div>
            <div className="text-[10px] text-white/45 capitalize">
              {r.type} · Stored on {r.nodeName}{r.online ? '' : ' · offline'}
            </div>
          </button>
        ))}
      </div>
      {rows.length === 0 && (
        <div className="text-xs text-white/45 py-3 text-center">
          {loading ? 'Loading…' : 'No projects found on your online computers.'}
        </div>
      )}
    </div>
  )
}
