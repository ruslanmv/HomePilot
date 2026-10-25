/**
 * Models → provider "Hugging Face": the models Inference Providers serve right now for this
 * model type (chat, multimodal, image, video), trending first, each with "Use".
 *
 * "Use" makes it the model for that type — the app sets the provider and model in Settings
 * (event ``homepilot:use-model``). Calls are billed to the account linked in Settings →
 * Connectors; without one, the list still shows and says how to link.
 */
import React, { useEffect, useState } from 'react'
import { Check, Heart, Loader2 } from 'lucide-react'
import { resolveBackendUrl } from '../lib/backendUrl'

export type HfModelType = 'chat' | 'multimodal' | 'image' | 'video'

type Row = { id: string; name: string; likes: number; downloads: number }

export const HF_TYPES: HfModelType[] = ['chat', 'multimodal', 'image', 'video']

const LABEL: Record<HfModelType, string> = { chat: 'chat', multimodal: 'multimodal', image: 'images', video: 'video' }

export function useModelFor(type: HfModelType, model: string) {
  window.dispatchEvent(new CustomEvent('homepilot:use-model', { detail: { type, provider: 'huggingface', model } }))
}

function authHeaders(): Record<string, string> {
  const token = (() => { try { return localStorage.getItem('homepilot_auth_token') || '' } catch { return '' } })()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export default function HfModelPicker({
  backendUrl,
  type,
  activeModel,
  onOpenConnectors,
}: {
  backendUrl?: string
  type: HfModelType
  /** The model already in use for this type, if it is a Hugging Face one. */
  activeModel?: string
  onOpenConnectors?: () => void
}) {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [connected, setConnected] = useState(true)
  const [error, setError] = useState('')
  const [using, setUsing] = useState(activeModel || '')

  useEffect(() => { setUsing(activeModel || '') }, [activeModel])

  useEffect(() => {
    let alive = true
    setRows(null)
    setError('')
    const base = resolveBackendUrl(backendUrl).replace(/\/+$/, '')
    fetch(`${base}/v1/connectors/huggingface/models?type=${type}`, { headers: authHeaders(), credentials: 'include' })
      .then(async (res) => {
        const body = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`)
        if (!alive) return
        setConnected(!!body.connected)
        setRows(body.models || [])
      })
      .catch((e) => { if (alive) { setError(e instanceof Error ? e.message : 'Could not load models.'); setRows([]) } })
    return () => { alive = false }
  }, [backendUrl, type])

  return (
    <div className="space-y-3">
      {!connected && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-amber-400/20 bg-amber-400/[0.06] px-4 py-3">
          <p className="text-[13px] text-amber-100/90">Connect your Hugging Face account to use these models.</p>
          {onOpenConnectors ? (
            <button type="button" onClick={onOpenConnectors}
              className="min-h-[36px] rounded-full bg-white px-4 text-[13px] font-semibold text-black">Open Connectors</button>
          ) : <span className="text-[12px] text-amber-100/70">Settings → Connectors</span>}
        </div>
      )}

      {error ? <p className="text-[13px] text-red-300">{error}</p> : null}
      {rows === null ? (
        <div className="flex items-center gap-2 py-6 text-[13px] text-white/50"><Loader2 size={16} className="animate-spin" /> Loading Hugging Face models…</div>
      ) : null}

      {rows && rows.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.03] divide-y divide-white/[0.06]">
          {rows.map((m) => {
            const active = using === m.id
            const [org, ...rest] = m.name.split('/')
            return (
              <div key={m.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[15px] font-medium text-white">{rest.join('/') || m.name}</div>
                  <div className="flex items-center gap-3 text-[12px] text-white/45">
                    <span className="truncate">{org}</span>
                    {m.likes ? <span className="inline-flex items-center gap-1"><Heart size={11} aria-hidden /> {m.likes.toLocaleString()}</span> : null}
                  </div>
                </div>
                <button
                  type="button"
                  disabled={!connected}
                  onClick={() => { useModelFor(type, m.id); setUsing(m.id) }}
                  aria-label={`Use ${m.name} for ${LABEL[type]}`}
                  className={`flex min-h-[36px] shrink-0 items-center gap-1.5 rounded-full px-4 text-[13px] font-semibold disabled:opacity-40 ${
                    active ? 'border border-emerald-400/30 bg-emerald-400/15 text-emerald-200' : 'bg-white text-black hover:bg-white/90'
                  }`}
                >
                  {active ? <><Check size={14} aria-hidden /> In use</> : 'Use'}
                </button>
              </div>
            )
          })}
        </div>
      )}
      {rows && rows.length === 0 && !error ? (
        <p className="text-[13px] text-white/45">No Hugging Face models for {LABEL[type]} right now.</p>
      ) : null}
    </div>
  )
}
