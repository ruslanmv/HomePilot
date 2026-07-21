/**
 * UnifiedModelCatalog (Batch 8) — one catalog of the models on your computers.
 *
 * Presents the chat/image/video models advertised by each linked node
 * (mirror `models.list`) as a single list with source badges
 * ("Installed on Studio PC"), keyed by canonical `hpnode://<node>/model/<id>`
 * identifiers so identically-named models on different computers never collide.
 *
 * "Use for chat" selects that computer + model, so Batch-5 routing runs the
 * completion there — no manual provider setup. Pure presentation over existing
 * RPC; ADDITIVE and flag-gated. Renders null when the flag is off.
 */
import React, { useEffect, useMemo, useState } from 'react'
import { Boxes, Check, Cpu, RefreshCw } from 'lucide-react'

import { isAccountsUxEnabled } from './featureFlags'
import { useAccount } from './HomePilotAccountProvider'
import { useComputer } from './ComputerContext'
import { MirrorError, mirrorClient } from './mirrorClient'
import type { MirrorNode } from './types'

interface ModelEntry { id?: string; display_name?: string; status?: string }
interface ModelsList { chat_models?: ModelEntry[]; image_models?: ModelEntry[]; video_models?: ModelEntry[] }
type Kind = 'chat' | 'image' | 'video'

interface Row {
  hpuri: string
  nodeId: string
  nodeName: string
  online: boolean
  kind: Kind
  id: string
  label: string
}

function modelIds(list: ModelsList | null | undefined, key: keyof ModelsList): ModelEntry[] {
  const arr = list?.[key]
  return Array.isArray(arr) ? arr : []
}

export function UnifiedModelCatalog(): JSX.Element | null {
  if (!isAccountsUxEnabled()) return null
  return <UnifiedModelCatalogInner />
}

function UnifiedModelCatalogInner(): JSX.Element {
  const { computers, loading, refresh } = useAccount()
  const { selectComputer, selectedComputerId } = useComputer()
  const [byNode, setByNode] = useState<Record<string, ModelsList | null>>({})
  const [filter, setFilter] = useState<Kind>('chat')
  const [activeModel, setActiveModel] = useState<string>(() => {
    try { return localStorage.getItem('homepilot_model_chat') || '' } catch { return '' }
  })

  // Fetch models.list for each online node (cached; offline nodes skipped).
  useEffect(() => {
    let cancelled = false
    computers.filter((c) => c.online && byNode[c.node_id] === undefined).forEach(async (c) => {
      try {
        const list = await mirrorClient.rpc<ModelsList>(c.node_id, 'models.list', {})
        if (!cancelled) setByNode((p) => ({ ...p, [c.node_id]: list }))
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
    const keyFor: Record<Kind, keyof ModelsList> = { chat: 'chat_models', image: 'image_models', video: 'video_models' }
    for (const c of computers as MirrorNode[]) {
      const list = byNode[c.node_id]
      for (const entry of modelIds(list, keyFor[filter])) {
        const id = entry.id
        if (!id) continue
        out.push({
          hpuri: `hpnode://${c.node_id}/model/${id}`,
          nodeId: c.node_id,
          nodeName: c.node_name || c.node_id,
          online: c.online,
          kind: filter,
          id,
          label: entry.display_name || id,
        })
      }
    }
    return out
  }, [computers, byNode, filter])

  const useForChat = (r: Row) => {
    selectComputer(r.nodeId)                 // Batch-5 routes chat to this node
    try { localStorage.setItem('homepilot_model_chat', r.id) } catch { /* ignore */ }
    setActiveModel(r.id)
  }

  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 mb-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Boxes size={16} className="text-white/60" />
          <h3 className="text-sm font-semibold text-white/80">Models on your computers</h3>
        </div>
        <button onClick={refresh} className="text-[11px] px-2.5 py-1 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white/60 inline-flex items-center gap-1">
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="flex gap-1.5 mb-3">
        {(['chat', 'image', 'video'] as Kind[]).map((k) => (
          <button
            key={k}
            onClick={() => setFilter(k)}
            className={`text-[11px] px-2.5 py-1 rounded-full border ${filter === k ? 'bg-violet-500/15 border-violet-400/40 text-white' : 'bg-white/[0.02] border-white/10 text-white/50 hover:text-white/80'}`}
          >
            {k[0].toUpperCase() + k.slice(1)}
          </button>
        ))}
      </div>

      <div className="space-y-1.5 max-h-72 overflow-y-auto">
        {rows.map((r) => {
          const active = r.kind === 'chat' && r.id === activeModel && r.nodeId === selectedComputerId
          return (
            <div key={r.hpuri} className="flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.02] px-3 py-2">
              <Cpu size={14} className="text-white/40 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-[13px] text-white/90 truncate">{r.label}</div>
                <div className="text-[10px] text-white/45">
                  Installed on {r.nodeName}{r.online ? '' : ' · offline'}
                </div>
              </div>
              {r.kind === 'chat' ? (
                <button
                  onClick={() => useForChat(r)}
                  disabled={!r.online}
                  className={`text-[11px] px-2.5 py-1 rounded-lg border inline-flex items-center gap-1 disabled:opacity-40 ${active ? 'bg-emerald-500/15 border-emerald-400/40 text-emerald-200' : 'bg-white/5 border-white/10 text-white/70 hover:bg-white/10'}`}
                >
                  {active ? <><Check size={12} /> Active</> : 'Use for chat'}
                </button>
              ) : (
                <span className="text-[10px] text-white/40">on {r.nodeName}</span>
              )}
            </div>
          )
        })}
        {rows.length === 0 && (
          <div className="text-xs text-white/45 py-4 text-center">
            {loading ? 'Loading…' : 'No models advertised by your online computers.'}
          </div>
        )}
      </div>
    </div>
  )
}
