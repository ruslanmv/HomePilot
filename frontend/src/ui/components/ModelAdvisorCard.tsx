/**
 * Models → "Suggested for your GPU": the top 5 chat, vision, image and video models
 * for this machine, ranked by FitLab (github.com/ruslanmv/fitlab).
 *
 * - Reads the backend's cached or bundled FitLab data — no network.
 * - "Fetch definitions" asks FitLab for its latest data (a conditional request: nothing is
 *   downloaded when it has not changed); offline, the card keeps the cached or bundled
 *   list and says which one it is showing.
 * - Marks the model in use per kind, and the one FitLab ranks clearly higher.
 * - Install is explicit and confirmed, through the existing POST /models/install.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Copy, Cpu, Download, ExternalLink, Loader2, RefreshCw, Sparkles } from 'lucide-react'
import {
  ADVISOR_KINDS,
  KIND_LABEL,
  type AdvisorKind,
  type AdvisorResponse,
  type CurrentModels,
  type FeedInfo,
  type Suggestion,
  loadAdvisor,
  markSeen,
  newIds,
  readSeen,
  recordCheck,
  setAdvisorEnabled,
  takeFocus,
} from '../modelAdvisor'
const PLAN_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'This machine' },
  ...[4, 6, 8, 12, 16, 24, 32, 48].map((g) => ({ value: String(g), label: `${g} GB GPU` })),
  { value: '0', label: 'CPU only' },
]
const VERDICT: Record<Suggestion['verdict'], { label: string; cls: string }> = {
  fits: { label: 'Fits', cls: 'border-emerald-400/30 bg-emerald-500/15 text-emerald-200' },
  tight: { label: 'Tight fit', cls: 'border-amber-400/30 bg-amber-500/15 text-amber-200' },
  offload: { label: 'Offload', cls: 'border-orange-400/30 bg-orange-500/15 text-orange-200' },
}
const COLLAPSE_KEY = 'homepilot_model_advisor_collapsed'

function sourceLabel(f?: FeedInfo): string {
  if (!f) return ''
  const when = f.generated_at ? ` ${f.generated_at}` : ''
  if (f.source === 'live') return `live${when}`
  if (f.source === 'cache') return `saved copy${when}`
  if (f.source === 'bundled') return `bundled with HomePilot${when}`
  return 'unavailable'
}

function sameModel(a?: string | null, b?: string | null): boolean {
  const n = (x?: string | null) => (x || '').trim().toLowerCase().replace(/:latest$/, '')
  return !!a && !!b && n(a) === n(b)
}

function ago(ts?: number | null): string {
  if (!ts) return 'never'
  const min = Math.max(0, Math.round((Date.now() / 1000 - ts) / 60))
  if (min < 1) return 'just now'
  if (min < 60) return `${min} min ago`
  const h = Math.round(min / 60)
  return h < 48 ? `${h} h ago` : `${Math.round(h / 24)} days ago`
}

function hardwareLine(r: AdvisorResponse): string {
  const hw = r.hardware
  if (!hw) return ''
  if (hw.kind === 'cpu') return `${hw.name} · no GPU${hw.ram_gb ? ` · ${hw.ram_gb} GB RAM` : ''}`
  return `${hw.name} · ${hw.vram_gb} GB${hw.kind === 'apple' ? ' usable memory' : ' VRAM'}`
}

export function ModelAdvisorCard({
  backendUrl,
  apiKey,
  initialKind = 'chat',
  current,
  onToast,
  onInstalled,
}: {
  backendUrl: string
  apiKey?: string
  initialKind?: AdvisorKind
  /** Models in use per kind: marked "In use", and compared for a better fit. */
  current?: CurrentModels
  onToast?: (message: string) => void
  /** Called after an install succeeds, so the page can refresh its installed list. */
  onInstalled?: () => void
}) {
  const [data, setData] = useState<AdvisorResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [fetching, setFetching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  // A notice's "View" asks for a tab; otherwise follow the Models page.
  const [kind, setKind] = useState<AdvisorKind>(() => takeFocus() || initialKind)
  const [plan, setPlan] = useState('')
  const [confirm, setConfirm] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem(COLLAPSE_KEY) === '1' } catch { return false }
  })
  const [fresh, setFresh] = useState<Set<string>>(new Set())
  const seenOnce = useRef(false)

  const firstKind = useRef(true)
  useEffect(() => {
    if (firstKind.current) { firstKind.current = false; return }
    setKind(initialKind)
  }, [initialKind])

  const vramGb = plan === '' ? null : Number(plan)
  const apply = useCallback((r: AdvisorResponse) => {
    setData(r)
    if (r.enabled && !seenOnce.current) {
      // Highlight what changed since the user last looked (e.g. after an update), once.
      seenOnce.current = true
      setFresh(newIds(r, readSeen()))
    }
    if (r.enabled) markSeen(r)
  }, [])

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setError(null)
    try {
      apply(await loadAdvisor(backendUrl, { vramGb, apiKey, signal, current }))
    } catch (e: any) {
      if (e?.name !== 'AbortError') setError('Suggestions are unavailable right now.')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendUrl, vramGb, apiKey, apply, ADVISOR_KINDS.map((k) => current?.[k] || '').join('|')])

  useEffect(() => {
    const ctrl = new AbortController()
    void load(ctrl.signal)
    return () => ctrl.abort()
  }, [load])

  const fetchLatest = async () => {
    setFetching(true)
    setNotice(null)
    try {
      const r = await loadAdvisor(backendUrl, { refresh: true, vramGb, apiKey, current })
      apply(r)
      // A manual fetch counts as today's check for the automatic schedule.
      recordCheck(!!(r.fetch?.ok || r.fetch?.partial))
      const llm = r.feeds?.llm
      const media = r.feeds?.media
      if (r.fetch?.ok && r.fetch.changed === false) {
        setNotice(`Already up to date — FitLab definitions ${llm?.generated_at} (models) and ${media?.generated_at} (image & video).`)
      } else if (r.fetch?.ok) {
        setNotice(`Definitions updated from FitLab — models ${llm?.generated_at}, image & video ${media?.generated_at}.`)
      } else if (r.fetch?.partial) {
        setNotice(llm?.source === 'live'
          ? `Chat & vision definitions updated (${llm?.generated_at}). Image & video: FitLab has not published them yet — showing the ${sourceLabel(media)} list.`
          : `Image & video updated. Chat & vision: showing the ${sourceLabel(llm)} list.`)
      } else {
        setNotice(r.fetch?.network === false
          ? `Fetching is turned off on this server — showing the ${sourceLabel(llm)} list.`
          : `Couldn't reach FitLab — showing the ${sourceLabel(llm)} list.`)
      }
    } catch {
      setNotice("Couldn't fetch suggestions — the current list is unchanged.")
    } finally {
      setFetching(false)
    }
  }

  const install = async (s: Suggestion) => {
    setConfirm(null)
    setBusy(s.id)
    onToast?.(`Installing ${s.name}… this can take a while.`)
    try {
      const res = await fetch(`${backendUrl.replace(/\/+$/, '')}/models/install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(apiKey ? { 'x-api-key': apiKey } : {}) },
        credentials: 'include',
        body: JSON.stringify({ ...s.install, options: {} }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok || body?.ok === false) throw new Error(body?.message || body?.detail || `HTTP ${res.status}`)
      onToast?.(body?.message || `${s.name} installed.`)
      onInstalled?.()
      await load()
    } catch (e: any) {
      onToast?.(`Couldn't install ${s.name}: ${e?.message || e}`)
    } finally {
      setBusy(null)
    }
  }

  const copyCommand = (s: Suggestion) => {
    const cmd = s.install.provider === 'ollama' ? `ollama pull ${s.install.model_id}` : s.install.model_id
    navigator.clipboard?.writeText(cmd).then(() => onToast?.(`Copied: ${cmd}`)).catch(() => {})
  }

  const toggleCollapsed = () => {
    setCollapsed((c) => {
      try { localStorage.setItem(COLLAPSE_KEY, c ? '0' : '1') } catch { /* ignore */ }
      return !c
    })
  }

  const list = useMemo(() => data?.suggestions?.[kind] || [], [data, kind])
  const upgrade = data?.upgrades?.[kind]
  if (data && !data.enabled) return null

  const emptyText = kind === 'image' || kind === 'video'
    ? data?.hardware?.kind === 'cpu' ? 'Image and video generation need a GPU.' : 'No model fits this much GPU memory yet.'
    : 'No model in FitLab fits this machine.'

  return (
    <section
      aria-labelledby="hp-advisor-title"
      className="rounded-2xl border border-violet-400/20 bg-gradient-to-br from-violet-500/[0.07] to-white/[0.02]"
    >
      <header className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
        <button
          type="button"
          onClick={toggleCollapsed}
          aria-expanded={!collapsed}
          aria-controls="hp-advisor-body"
          className="flex min-w-[13rem] flex-1 items-center gap-2 text-left"
        >
          <Sparkles size={16} className="shrink-0 text-violet-300" />
          <span id="hp-advisor-title" className="text-sm font-semibold text-white">Suggested for your GPU</span>
          <span className="rounded-full border border-white/15 bg-white/5 px-2 py-0.5 text-[10px] font-medium text-white/60">FitLab</span>
          <ChevronDown size={16} className={`ml-auto shrink-0 text-white/50 transition-transform ${collapsed ? '-rotate-90' : ''}`} />
        </button>
        <button
          type="button"
          onClick={fetchLatest}
          disabled={fetching}
          className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-xl border border-white/15 bg-white/[0.06] px-3 text-xs font-semibold text-white/85 hover:bg-white/[0.1] disabled:opacity-60 sm:w-auto"
        >
          {fetching ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          {fetching ? 'Fetching…' : 'Fetch definitions'}
        </button>
      </header>

      {!collapsed ? (
        <div id="hp-advisor-body" className="border-t border-white/[0.06] px-4 pb-4 pt-3 sm:px-5">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-white/60">
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <Cpu size={13} className="shrink-0 text-white/40" />
              <span className="truncate" data-testid="advisor-hardware">{data ? hardwareLine(data) : 'Detecting hardware…'}</span>
            </span>
            <label className="inline-flex items-center gap-2">
              <span>Plan for</span>
              <select
                value={plan}
                onChange={(e) => setPlan(e.target.value)}
                className="h-8 rounded-lg border border-white/15 bg-black/40 px-2 text-xs text-white"
              >
                {PLAN_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
          </div>
          {data?.hardware?.note ? <p className="mt-1 text-[11px] text-white/40">{data.hardware.note}</p> : null}

          <div role="tablist" aria-label="Model kind" className="mt-3 flex gap-1.5 overflow-x-auto">
            {ADVISOR_KINDS.map((k) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={kind === k}
                onClick={() => setKind(k)}
                className={[
                  'h-8 shrink-0 rounded-lg border px-3 text-xs font-semibold',
                  kind === k ? 'border-violet-400/50 bg-violet-500/20 text-white' : 'border-white/10 bg-white/[0.03] text-white/65 hover:bg-white/[0.07]',
                ].join(' ')}
              >
                {KIND_LABEL[k]}
              </button>
            ))}
          </div>

          {notice ? <p role="status" className="mt-3 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white/75">{notice}</p> : null}
          {upgrade ? (
            <p className="mt-3 rounded-lg border border-violet-400/25 bg-violet-500/10 px-3 py-2 text-xs text-violet-100" data-testid="advisor-upgrade">
              <strong className="font-semibold">{upgrade.better.name}</strong> ranks above your current {KIND_LABEL[kind].toLowerCase()} model,{' '}
              {upgrade.current.name} (#{upgrade.current.rank} for this computer).
            </p>
          ) : null}

          <div className="mt-3" role="tabpanel" aria-label={`${KIND_LABEL[kind]} suggestions`}>
            {loading && !data ? (
              <p className="py-6 text-center text-xs text-white/50">Ranking models for this machine…</p>
            ) : error ? (
              <p className="py-6 text-center text-xs text-white/50">{error}</p>
            ) : list.length === 0 ? (
              <p className="py-6 text-center text-xs text-white/50">{emptyText}</p>
            ) : (
              <ol className="divide-y divide-white/[0.06]">
                {list.map((s, i) => (
                  <li key={s.id} className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:gap-4">
                    <span className="hidden w-5 shrink-0 text-right text-xs tabular-nums text-white/40 sm:block">{i + 1}</span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-white">{s.name}</span>
                        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${VERDICT[s.verdict].cls}`}>{VERDICT[s.verdict].label}</span>
                        {sameModel(s.install.model_id, current?.[kind]) ? <span className="rounded-full border border-sky-400/30 bg-sky-500/15 px-2 py-0.5 text-[10px] font-semibold text-sky-200">In use</span> : null}
                        {upgrade && upgrade.better.id === s.id ? <span className="rounded-full bg-violet-500/30 px-2 py-0.5 text-[10px] font-semibold text-violet-100">Upgrade</span> : null}
                        {fresh.has(s.id) ? <span className="rounded-full bg-violet-500/30 px-2 py-0.5 text-[10px] font-semibold text-violet-100">New</span> : null}
                        {s.license ? <span className="text-[11px] text-white/40">{s.license}</span> : null}
                      </div>
                      <p className="mt-0.5 text-xs leading-snug text-white/55">{s.reasons.join(' · ')}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {s.hf_id ? (
                        <a
                          href={`https://huggingface.co/${s.hf_id}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={`${s.name} on Hugging Face`}
                          className="grid h-8 w-8 place-items-center rounded-lg text-white/45 hover:bg-white/[0.07] hover:text-white"
                        >
                          <ExternalLink size={14} />
                        </a>
                      ) : null}
                      {s.install.provider === 'ollama' ? (
                        <button
                          type="button"
                          onClick={() => copyCommand(s)}
                          aria-label={`Copy install command for ${s.name}`}
                          className="grid h-8 w-8 place-items-center rounded-lg text-white/45 hover:bg-white/[0.07] hover:text-white"
                        >
                          <Copy size={14} />
                        </button>
                      ) : null}
                      {s.installed ? (
                        <span className="inline-flex h-8 items-center gap-1 rounded-lg px-2 text-xs font-medium text-emerald-300">
                          <Check size={14} /> Installed
                        </span>
                      ) : confirm === s.id ? (
                        <span className="inline-flex items-center gap-1.5">
                          <span className="text-[11px] text-white/55">
                            {s.download_gb ? `Download ~${s.download_gb} GB?` : 'Download now?'}
                          </span>
                          <button type="button" onClick={() => install(s)} className="h-8 rounded-lg bg-violet-500/80 px-2.5 text-xs font-semibold text-white hover:bg-violet-500">Install</button>
                          <button type="button" onClick={() => setConfirm(null)} className="h-8 rounded-lg px-2 text-xs text-white/60 hover:bg-white/[0.07]">Cancel</button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setConfirm(s.id)}
                          disabled={busy !== null}
                          className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-white/15 bg-white/[0.05] px-2.5 text-xs font-semibold text-white/85 hover:bg-white/[0.1] disabled:opacity-50"
                        >
                          {busy === s.id ? <Loader2 size={13} className="animate-spin" /> : <Download size={13} />}
                          {busy === s.id ? 'Installing…' : 'Install'}
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>

          <footer className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-white/[0.06] pt-3 text-[11px] text-white/40">
            <span data-testid="advisor-source">
              Definitions: chat & vision {sourceLabel(data?.feeds?.llm)} · image & video {sourceLabel(data?.feeds?.media)}
              {' · '}checked {ago(data?.feeds?.llm?.checked_at)}
            </span>
            <a href="https://github.com/ruslanmv/fitlab" target="_blank" rel="noopener noreferrer" className="underline-offset-2 hover:text-white/70 hover:underline">
              FitLab · CC BY 4.0
            </a>
            <button
              type="button"
              onClick={() => {
                setAdvisorEnabled(false)
                onToast?.('Model suggestions hidden — turn them back on in Settings → Models.')
              }}
              className="ml-auto hover:text-white/70"
            >
              Hide suggestions
            </button>
          </footer>
        </div>
      ) : null}
    </section>
  )
}

export default ModelAdvisorCard
