/**
 * Models → provider "Hugging Face": the models Inference Providers serve live for this model
 * type (chat, multimodal, image, video), ranked the way FitLab's inference lane ranks them.
 *
 *   Popular    likes, downloads, trend and freshness together (the default)
 *   Most liked ranked by the people
 *   Trending   what is rising on the Hub this week
 *   Newest     most recently published
 *   Rising     new in the last few months, by trend — models a likes order would bury
 *
 * The top three are shown as "Community favorites"; every row keeps its raw likes and downloads
 * so a number is never shown without what it is made of. "Use" makes a model the one for its
 * type (event ``homepilot:use-model``). Calls are billed to the account linked in Settings →
 * Connectors; without one, the list still shows and says how to link.
 */
import React, { useEffect, useState } from 'react'
import { Check, Download, Heart, Loader2, Sparkles, TrendingUp } from 'lucide-react'
import { resolveBackendUrl } from '../lib/backendUrl'

export type HfModelType = 'chat' | 'multimodal' | 'image' | 'video'
export type HfOrder = 'popular' | 'likes' | 'trending' | 'newest' | 'rising'

type Row = {
  id: string
  name: string
  provider_label?: string
  likes: number
  downloads: number
  trending_score?: number
  live_providers?: string[]
  score?: number
}

export const HF_TYPES: HfModelType[] = ['chat', 'multimodal', 'image', 'video']

const LABEL: Record<HfModelType, string> = { chat: 'chat', multimodal: 'multimodal', image: 'images', video: 'video' }

const ORDERS: Array<{ id: HfOrder; label: string }> = [
  { id: 'popular', label: 'Popular' },
  { id: 'likes', label: 'Most liked' },
  { id: 'trending', label: 'Trending' },
  { id: 'newest', label: 'Newest' },
  { id: 'rising', label: 'Rising' },
]

const ORDER_STORAGE_KEY = 'homepilot_hf_model_order'
const FAVORITES = 3

export function useModelFor(type: HfModelType, model: string) {
  window.dispatchEvent(new CustomEvent('homepilot:use-model', { detail: { type, provider: 'huggingface', model } }))
}

function authHeaders(): Record<string, string> {
  const token = (() => { try { return localStorage.getItem('homepilot_auth_token') || '' } catch { return '' } })()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, '')}K`
  return String(n)
}

function readOrder(): HfOrder {
  try {
    const saved = localStorage.getItem(ORDER_STORAGE_KEY) as HfOrder | null
    return saved && ORDERS.some((o) => o.id === saved) ? saved : 'popular'
  } catch {
    return 'popular'
  }
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
  const [source, setSource] = useState('')
  const [error, setError] = useState('')
  const [using, setUsing] = useState(activeModel || '')
  const [order, setOrder] = useState<HfOrder>(readOrder)
  const [showAll, setShowAll] = useState(false)

  useEffect(() => { setUsing(activeModel || '') }, [activeModel])

  useEffect(() => {
    let alive = true
    setRows(null)
    setError('')
    setShowAll(false)
    const base = resolveBackendUrl(backendUrl).replace(/\/+$/, '')
    fetch(`${base}/v1/connectors/huggingface/models?type=${type}&sort=${order}`, { headers: authHeaders(), credentials: 'include' })
      .then(async (res) => {
        const body = await res.json().catch(() => ({}))
        if (!res.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`)
        if (!alive) return
        setConnected(!!body.connected)
        setSource(String(body.source || ''))
        setRows(body.models || [])
      })
      .catch((e) => { if (alive) { setError(e instanceof Error ? e.message : 'Could not load models.'); setRows([]) } })
    return () => { alive = false }
  }, [backendUrl, type, order])

  function pickOrder(next: HfOrder) {
    setOrder(next)
    try { localStorage.setItem(ORDER_STORAGE_KEY, next) } catch { /* per-device convenience only */ }
  }

  function use(m: Row) {
    useModelFor(type, m.id)
    setUsing(m.id)
  }

  const favorites = rows && (order === 'popular' || order === 'likes') ? rows.slice(0, FAVORITES) : []
  const rest = rows ? rows.slice(favorites.length) : []
  const visible = showAll ? rest : rest.slice(0, 7)

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

      {/* Sort */}
      <div role="radiogroup" aria-label="Sort Hugging Face models" className="flex gap-1.5 overflow-x-auto pb-1 scrollbar-hide">
        {ORDERS.map((o) => (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={order === o.id}
            onClick={() => pickOrder(o.id)}
            className={`shrink-0 min-h-[34px] rounded-full border px-3.5 text-[13px] font-medium transition ${
              order === o.id ? 'border-white bg-white text-black' : 'border-white/10 bg-white/[0.03] text-white/70 hover:bg-white/[0.07]'
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>

      {error ? <p className="text-[13px] text-red-300">{error}</p> : null}
      {rows === null ? (
        <div className="flex items-center gap-2 py-6 text-[13px] text-white/50"><Loader2 size={16} className="animate-spin" /> Ranking Hugging Face models…</div>
      ) : null}

      {/* Community favorites: the top of a popularity order, as cards */}
      {favorites.length > 0 && (
        <section aria-label="Community favorites" className="space-y-2">
          <h4 className="flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-wider text-white/50">
            <Sparkles size={13} aria-hidden /> Community favorites
          </h4>
          <div className="grid gap-2 sm:grid-cols-3">
            {favorites.map((m, i) => {
              const active = using === m.id
              const [, ...rest2] = m.name.split('/')
              return (
                <button
                  key={m.id}
                  type="button"
                  disabled={!connected}
                  onClick={() => use(m)}
                  aria-label={`Use ${m.name} for ${LABEL[type]}`}
                  className={`flex min-h-[92px] flex-col justify-between rounded-2xl border p-3.5 text-left transition disabled:opacity-50 ${
                    active ? 'border-emerald-400/40 bg-emerald-400/[0.08]' : 'border-white/10 bg-white/[0.04] hover:border-white/25'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[11px] font-semibold text-white/45">#{i + 1}</span>
                    {active ? <span className="flex items-center gap-1 text-[11px] font-semibold text-emerald-300"><Check size={12} aria-hidden /> In use</span> : null}
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-[14px] font-semibold text-white">{rest2.join('/') || m.name}</div>
                    <div className="mt-0.5 flex items-center gap-2.5 text-[12px] text-white/50">
                      <span className="truncate">{m.provider_label || m.name.split('/')[0]}</span>
                      <span className="inline-flex items-center gap-1"><Heart size={11} aria-hidden /> {compact(m.likes)}</span>
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        </section>
      )}

      {/* Everything else, in the chosen order */}
      {rest.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.03] divide-y divide-white/[0.06]">
          {visible.map((m) => {
            const active = using === m.id
            const [org, ...rest2] = m.name.split('/')
            return (
              <div key={m.id} className="flex items-center gap-3 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[15px] font-medium text-white">{rest2.join('/') || m.name}</div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-white/45">
                    <span className="truncate">{m.provider_label || org}</span>
                    <span className="inline-flex items-center gap-1" title="Likes on Hugging Face"><Heart size={11} aria-hidden /> {compact(m.likes)}</span>
                    <span className="inline-flex items-center gap-1" title="Downloads, last 30 days"><Download size={11} aria-hidden /> {compact(m.downloads)}</span>
                    {order === 'trending' || order === 'rising' ? (
                      <span className="inline-flex items-center gap-1" title="Trending on Hugging Face"><TrendingUp size={11} aria-hidden /> {Math.round(m.trending_score || 0)}</span>
                    ) : null}
                    {m.live_providers?.length ? <span title={m.live_providers.join(', ')}>{m.live_providers.length} provider{m.live_providers.length === 1 ? '' : 's'}</span> : null}
                  </div>
                </div>
                <button
                  type="button"
                  disabled={!connected}
                  onClick={() => use(m)}
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
          {!showAll && rest.length > visible.length ? (
            <button type="button" onClick={() => setShowAll(true)}
              className="w-full px-4 py-3 text-left text-[13px] font-medium text-white/60 hover:bg-white/[0.04] hover:text-white">
              Show all {rows!.length} models
            </button>
          ) : null}
        </div>
      )}

      {rows && rows.length === 0 && !error ? (
        <p className="text-[13px] text-white/45">No Hugging Face models for {LABEL[type]} in this order right now.</p>
      ) : null}
      {rows && rows.length > 0 ? (
        <p className="text-[11px] leading-relaxed text-white/40">
          Ranked by popularity on Hugging Face{source.startsWith('fitlab') ? ' (FitLab’s latest ranking; the Hub could not be reached)' : ''}.
          Only models a provider serves right now are listed. Popular is not always best for your task.
        </p>
      ) : null}
    </div>
  )
}
