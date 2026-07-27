/**
 * OllaBridgeLink — the "OllaBridge Link" settings section, presented as
 * **Remote computers**.
 *
 * HomePilot Web is a *consumer + remote control* here: it signs in to an
 * OllaBridge account and uses the models/personas/GPUs on the user's private
 * computers (HomePilot Local + OllaBridge Local) through the encrypted relay.
 * It is NOT itself a GPU machine, so the copy never implies "this device" is a
 * node. Two distinct relationships are shown separately:
 *
 *   1. OllaBridge account — the browser is authenticated to the account.
 *   2. Your computers      — the compute nodes connected to that account.
 *
 * Self-contained: reuses the token/url helpers from OllaBridgeModels, talks to
 * the Cloud directly (CORS open), stores only the token in localStorage.
 */
import React, { useCallback, useEffect, useState } from 'react'
import { isBffSessionEnabled } from '../account/featureFlags'
import {
  Boxes,
  Check,
  Cloud,
  Copy,
  Cpu,
  Download,
  ExternalLink,
  Info,
  Loader2,
  LogOut,
  Monitor,
  Plus,
  RefreshCw,
  Rocket,
  Server,
  ShieldCheck,
  User,
  Users,
} from 'lucide-react'
import { getCloudToken, getCloudUrl } from './OllaBridgeModels'
import { getEdition, type EditionInfo } from '../lib/edition'
import { resolveBackendUrl } from '../lib/backendUrl'

interface DeviceInfo {
  id: string
  name: string
  platform?: string | null
  online: boolean
  gpu_name?: string | null
  vram_mb?: number | null
  kind?: string | null
  last_seen?: string | null
}

interface ModelCount {
  ollama: number
  personas: number
}

interface LocalStatus {
  edition: string
  available: boolean
  installed: boolean
  running: boolean
  local_url?: string | null
  models?: number
  share_scope?: string
  paired?: boolean | null
  relay_state?: string | null
  device_id?: string | null
  credentials_saved?: boolean | null
  models_shared?: number | null
  relay_url?: string | null
}

const INSTALL_LOCAL_URL = 'https://github.com/ruslanmv/HomePilot#installation'

export default function OllaBridgeLink({ onOpenModels }: { onOpenModels?: () => void } = {}) {
  const cloudUrl = getCloudUrl()
  const [token, setToken] = useState(getCloudToken())
  const [email, setEmail] = useState('')
  const [me, setMe] = useState<{ email?: string } | null>(null)
  const [devices, setDevices] = useState<DeviceInfo[]>([])
  const [modelCounts, setModelCounts] = useState<Record<string, ModelCount>>({})
  // A failed lookup is NOT the same as "no machines" — track it separately so
  // an API error never renders as an empty state.
  const [deviceError, setDeviceError] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadedOnce, setLoadedOnce] = useState(false)
  const [error, setError] = useState('')
  const [pw, setPw] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [edition, setEdition] = useState<EditionInfo | null>(null)
  const [sidecar, setSidecar] = useState<LocalStatus | null>(null)
  const [copiedId, setCopiedId] = useState('')
  const [expandedId, setExpandedId] = useState('')
  const [showConnect, setShowConnect] = useState(false)

  // Edition + (local only) sidecar status. This decides consumer vs provider UX.
  useEffect(() => {
    let alive = true
    getEdition().then((ed) => {
      if (!alive) return
      setEdition(ed)
      if (ed.is_local) {
        fetch(`${resolveBackendUrl()}/v1/ollabridge/local/status`, { credentials: 'include' })
          .then((r) => (r.ok ? r.json() : null))
          .then((s) => { if (alive) setSidecar(s) })
          .catch(() => { /* ignore */ })
      }
    })
    return () => { alive = false }
  }, [])

  /** Count each device's shared Ollama models vs HomePilot personas from the
   *  cloud model list (best-effort — the card still renders without it). */
  const loadModelCounts = useCallback(async (tok: string) => {
    try {
      const res = await fetch(`${cloudUrl}/ollama/v1/models`, { headers: { Authorization: `Bearer ${tok}` } })
      if (!res.ok) return
      const data = await res.json()
      const rows: any[] = Array.isArray(data?.data) ? data.data : []
      const counts: Record<string, ModelCount> = {}
      for (const m of rows) {
        const src = m?.x_source || m?.source
        if (src !== 'shared_device') continue
        const id: string = String(m?.id || '')
        let dev: string = String(m?.x_device_id || '')
        if (!dev) {
          const owned = String(m?.owned_by || '')
          const mm = owned.match(/^relay:(.+)$/)
          if (mm) dev = mm[1]
        }
        if (!dev || !id) continue
        const c = (counts[dev] ||= { ollama: 0, personas: 0 })
        if (id.startsWith('persona:') || id.startsWith('personality:')) c.personas += 1
        else c.ollama += 1
      }
      setModelCounts(counts)
    } catch { /* ignore — counts are optional */ }
  }, [cloudUrl])

  const load = useCallback(async (tok: string) => {
    if (!tok) return
    setLoading(true)
    setError('')
    setDeviceError('')
    try {
      const auth = { Authorization: `Bearer ${tok}` }
      // Prefer the always-on, owner-scoped compute-node inventory (returns only
      // GPU machines, never client apps). Fall back to /v1/devices only for an
      // older Cloud that lacks the endpoint.
      const [meRes, cnRes] = await Promise.all([
        fetch(`${cloudUrl}/v1/auth/me`, { headers: auth }),
        fetch(`${cloudUrl}/v1/account/compute-nodes`, { headers: auth }),
      ])
      if (meRes.status === 401 || cnRes.status === 401) {
        setError('Your OllaBridge session expired — reconnect below.')
        setToken(''); try { localStorage.removeItem('homepilot_cloud_token') } catch { /* ignore */ }
        return
      }
      setMe(meRes.ok ? await meRes.json() : null)
      if (cnRes.ok) {
        const data = await cnRes.json()
        setDevices(Array.isArray(data?.nodes) ? data.nodes : [])
      } else if (cnRes.status === 404) {
        // Older Cloud without the compute-node inventory — fall back to the
        // legacy device list (compute + client mixed).
        const devRes = await fetch(`${cloudUrl}/v1/devices`, { headers: auth })
        if (devRes.ok) {
          setDevices(await devRes.json())
        } else if (devRes.status === 404) {
          setDevices([])
        } else {
          setDeviceError(`Could not load your computers (${devRes.status}).`)
        }
      } else {
        setDeviceError(`Could not load your computers (${cnRes.status}).`)
      }
      void loadModelCounts(tok)
    } catch {
      setError('Could not reach OllaBridge Cloud.')
    } finally {
      setLoading(false)
      setLoadedOnce(true)
    }
  }, [cloudUrl, loadModelCounts])

  useEffect(() => { if (token) void load(token) }, [token, load])

  async function connect(e: React.FormEvent) {
    e.preventDefault()
    setConnecting(true); setError('')
    try {
      const r = await fetch(`${cloudUrl}/v1/auth/login`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), password: pw }),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok || !data.token) { setError(data.detail || 'Invalid OllaBridge email or password'); return }
      try {
        if (!isBffSessionEnabled()) localStorage.setItem('homepilot_cloud_token', data.token)
        localStorage.setItem('homepilot_cloud_url', cloudUrl)
      } catch { /* ignore */ }
      setToken(data.token); setPw('')
    } catch {
      setError('Could not reach OllaBridge Cloud.')
    } finally {
      setConnecting(false)
    }
  }

  function disconnect() {
    try { localStorage.removeItem('homepilot_cloud_token') } catch { /* ignore */ }
    setToken(''); setMe(null); setDevices([]); setModelCounts({}); setLoadedOnce(false)
  }

  const copyDeviceId = useCallback(async (id: string) => {
    try {
      await navigator.clipboard.writeText(id)
      setCopiedId(id); setTimeout(() => setCopiedId(''), 1500)
    } catch { /* ignore */ }
  }, [])

  const linked = Boolean(token)

  // Derived relay/pairing state for the local-edition "This computer" card.
  const relayState = (sidecar?.relay_state || '').toLowerCase()
  const isPaired = sidecar?.paired === true || !!sidecar?.credentials_saved || !!sidecar?.device_id
  const isRelayConnected = relayState === 'connected'
  const isReconnecting = relayState === 'reconnecting' || relayState === 'pairing'
  const modelsShared = sidecar?.models_shared ?? sidecar?.models ?? 0
  const sidecarUiUrl = `${sidecar?.local_url || 'http://127.0.0.1:11435'}/ui`

  const sectionLabel = 'text-[11px] font-bold uppercase tracking-[0.12em] text-white/40'
  const cardCls = 'rounded-2xl border border-white/10 bg-white/[0.025] p-5'
  const btnOutline =
    'h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 hover:border-white/20 text-xs font-medium text-white/80 inline-flex items-center justify-center gap-1.5 transition-colors'

  return (
    <div className="space-y-5">
      {/* ── Header ── */}
      <div className="flex items-start gap-3">
        <span className="h-12 w-12 rounded-2xl grid place-items-center bg-gradient-to-br from-cyan-500/25 to-violet-500/25 border border-white/10 shrink-0">
          <Cloud size={22} className="text-cyan-300" />
        </span>
        <div className="min-w-0">
          <h3 className="text-lg font-bold text-white leading-tight">Remote computers</h3>
          <p className="text-xs text-white/50 leading-relaxed mt-0.5">
            Use models, personas and GPUs running on your private HomePilot computers — from HomePilot Web or your phone.
          </p>
        </div>
      </div>

      {error && (
        <div className="px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-xs" role="alert">{error}</div>
      )}

      {/* ── OllaBridge account ── */}
      <div className="space-y-2">
        <div className={sectionLabel}>OllaBridge account</div>
        <div className={cardCls}>
          {linked ? (
            <div className="flex flex-col sm:flex-row sm:items-center gap-4">
              <span className="h-14 w-14 rounded-full grid place-items-center bg-white/[0.04] border border-white/10 shrink-0">
                <User size={22} className="text-cyan-300/80" />
              </span>
              <div className="min-w-0 flex-1">
                <span className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full bg-emerald-500/12 border border-emerald-500/30 text-emerald-300 mb-1.5">
                  <ShieldCheck size={12} /> Connected
                </span>
                <div className="text-sm text-white/90">
                  Signed in as <span className="font-semibold text-white">{me?.email || 'your OllaBridge account'}</span>.
                </div>
                <div className="text-xs text-white/45 mt-0.5">
                  HomePilot Web can access computers connected to this account.
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <a href={`${cloudUrl}/dashboard`} target="_blank" rel="noopener noreferrer" className={btnOutline}>
                  <User size={13} /> Manage Account
                </a>
                <button type="button" onClick={disconnect}
                  className="h-9 px-3 rounded-xl bg-red-500/[0.06] hover:bg-red-500/10 border border-red-500/25 text-xs font-medium text-red-300 inline-flex items-center justify-center gap-1.5 transition-colors">
                  <LogOut size={13} /> Disconnect
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={connect} className="space-y-3">
              <div className="text-sm text-white/80">Sign in to your OllaBridge account to reach your private computers.</div>
              <div className="grid gap-2.5 sm:grid-cols-[1fr_1fr_auto]">
                <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="OllaBridge email" autoComplete="email"
                  className="h-11 rounded-xl bg-black/40 border border-white/10 px-3 text-base sm:text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50" />
                <input type="password" required value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Password" autoComplete="current-password"
                  className="h-11 rounded-xl bg-black/40 border border-white/10 px-3 text-base sm:text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50" />
                <button type="submit" disabled={connecting} className="h-11 px-4 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-500 text-white text-sm font-bold disabled:opacity-60">
                  {connecting ? 'Connecting…' : 'Connect'}
                </button>
              </div>
              <p className="text-[11px] text-white/35">
                Tip: if you signed in with <span className="text-white/60 font-medium">“Continue with OllaBridge”</span>, this connects automatically.
              </p>
            </form>
          )}
        </div>
      </div>

      {/* ── Your computers ── */}
      {linked && (
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
            <div className={sectionLabel}>Your computers</div>
            <button type="button" onClick={() => setShowConnect((v) => !v)}
              className="h-9 px-3.5 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-500 text-white text-xs font-semibold inline-flex items-center gap-1.5 shadow-sm">
              <Plus size={14} /> Connect another computer
            </button>
          </div>

          {showConnect && (
            <div className={cardCls + ' space-y-2'}>
              <div className="text-sm font-semibold text-white">Connect a computer</div>
              <ol className="list-decimal list-inside text-xs text-white/55 space-y-1">
                <li>Open <span className="text-white/80 font-medium">HomePilot Local</span> on the computer you want to use.</li>
                <li>Open <span className="text-white/80 font-medium">Remote Access</span> (OllaBridge → Cloud).</li>
                <li>Click <span className="text-white/80 font-medium">Connect to OllaBridge</span>.</li>
                <li>Approve the computer in the browser page that opens.</li>
              </ol>
              <p className="text-[11px] text-white/35">This page updates automatically after approval — no code to type.</p>
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <a href={INSTALL_LOCAL_URL} target="_blank" rel="noopener noreferrer"
                  className="h-9 px-3 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-500 text-white text-xs font-bold inline-flex items-center gap-1.5">
                  <Download size={13} /> Download HomePilot Local
                </a>
                <a href={`${cloudUrl}/dashboard`} target="_blank" rel="noopener noreferrer" className={btnOutline}>
                  <ExternalLink size={13} /> Open OllaBridge dashboard
                </a>
              </div>
            </div>
          )}

          {/* States: error → loading → empty → devices */}
          {deviceError ? (
            <div className={cardCls}>
              <div className="text-sm font-semibold text-white mb-1">We couldn’t load your computers</div>
              <p className="text-xs text-white/50 leading-relaxed">
                Your OllaBridge account is connected, but the computer list couldn’t be retrieved. This does not mean your computers are disconnected. {deviceError}
              </p>
              <div className="flex flex-wrap items-center gap-2 mt-3">
                <button type="button" onClick={() => load(token)} className={btnOutline}>
                  <RefreshCw size={13} /> Try again
                </button>
                <a href={`${cloudUrl}/dashboard`} target="_blank" rel="noopener noreferrer" className={btnOutline}>
                  <ExternalLink size={13} /> Open OllaBridge dashboard
                </a>
              </div>
            </div>
          ) : loading && !loadedOnce ? (
            <div className={cardCls + ' flex items-center gap-2 text-sm text-white/50'}>
              <Loader2 size={15} className="animate-spin" /> Loading your computers…
            </div>
          ) : devices.length > 0 ? (
            <div className="space-y-3">
              {devices.map((d) => (
                <ComputerCard
                  key={d.id}
                  device={d}
                  counts={modelCounts[d.id]}
                  copied={copiedId === d.id}
                  expanded={expandedId === d.id}
                  onCopy={() => copyDeviceId(d.id)}
                  onToggleExpand={() => setExpandedId((v) => (v === d.id ? '' : d.id))}
                  onUseModels={onOpenModels}
                  manageAccessUrl={`${cloudUrl}/dashboard`}
                  cardCls={cardCls}
                  btnOutline={btnOutline}
                />
              ))}
            </div>
          ) : (
            /* Genuine empty state — only after a successful load returned none. */
            <div className={cardCls}>
              <div className="text-sm font-semibold text-white mb-1">No computers connected</div>
              <p className="text-xs text-white/50 leading-relaxed">
                Install <span className="text-white/80 font-semibold">HomePilot Local</span> on a computer with your models, then enable Remote Access.
              </p>
              <div className="flex flex-wrap items-center gap-2 mt-3">
                <a href={INSTALL_LOCAL_URL} target="_blank" rel="noopener noreferrer"
                  className="h-9 px-3 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-500 text-white text-xs font-bold inline-flex items-center gap-1.5">
                  <Download size={13} /> Get HomePilot Local
                </a>
                <a href={`${cloudUrl}/dashboard`} target="_blank" rel="noopener noreferrer" className={btnOutline}>
                  <ExternalLink size={13} /> How to connect
                </a>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── This computer (PROVIDER) — local edition only ── */}
      {edition?.is_local && (
        <div className="space-y-2">
          <div className={sectionLabel}>This computer</div>
          <div className={cardCls}>
            <div className="flex items-center justify-between gap-3 mb-1">
              <div className="flex items-center gap-2 text-xs font-semibold text-white/70">
                <Server size={14} /> Provide this computer’s GPU
              </div>
              {!sidecar?.running ? (
                <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-white/50">Sidecar stopped</span>
              ) : isRelayConnected ? (
                <span className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full bg-emerald-500/12 border border-emerald-500/30 text-emerald-300">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Connected
                </span>
              ) : isReconnecting ? (
                <span className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full bg-amber-500/12 border border-amber-500/30 text-amber-300">
                  <span className="w-1.5 h-1.5 rounded-full bg-amber-400" /> Reconnecting
                </span>
              ) : isPaired ? (
                <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-white/50">Disconnected</span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full bg-emerald-500/12 border border-emerald-500/30 text-emerald-300">
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Sidecar running
                </span>
              )}
            </div>

            {!sidecar?.running ? (
              <div className="mt-1 text-xs text-white/50 leading-relaxed">
                The OllaBridge Local sidecar isn’t reachable{sidecar?.local_url ? ` at ${sidecar.local_url}` : ''}. Start it with{' '}
                <span className="font-mono text-white/70">ollabridge start</span> — HomePilot Local’s desktop app starts it for you.
              </div>
            ) : isRelayConnected ? (
              <>
                <p className="text-sm text-white/80"><span className="font-semibold text-white">Ready.</span> This PC is online through OllaBridge Cloud.</p>
                <div className="mt-2 grid gap-0.5 text-[11px] text-white/45">
                  {sidecar?.device_id && <div>Device: <span className="font-mono text-white/70">{sidecar.device_id}</span></div>}
                  <div>{modelsShared} model{modelsShared === 1 ? '' : 's'} shared · Access: <span className="text-white/60">Private — only your account</span></div>
                </div>
                <div className="mt-3">
                  <a href={sidecarUiUrl} target="_blank" rel="noopener noreferrer" className={btnOutline}>
                    <ExternalLink size={13} /> Open OllaBridge dashboard
                  </a>
                </div>
              </>
            ) : isPaired ? (
              <>
                <p className="text-sm text-white/80">
                  {isReconnecting ? (
                    <>This computer is <span className="font-semibold text-white">reconnecting</span> — no action needed.</>
                  ) : (
                    <>This computer is paired but its cloud tunnel is <span className="font-semibold text-white">disconnected</span>.</>
                  )}
                </p>
                <div className="mt-3">
                  <a href={sidecarUiUrl} target="_blank" rel="noopener noreferrer" className={btnOutline}>
                    <ExternalLink size={13} /> Open OllaBridge dashboard
                  </a>
                </div>
              </>
            ) : (
              <>
                <p className="text-sm text-white/80">Connect this computer to OllaBridge Cloud to reach it from HomePilot Web or mobile.</p>
                <div className="mt-3">
                  <a href={sidecarUiUrl} target="_blank" rel="noopener noreferrer"
                    className="h-9 px-3 rounded-xl bg-gradient-to-r from-cyan-500/90 to-violet-500/90 text-white text-xs font-semibold inline-flex items-center gap-1.5">
                    <Plus size={13} /> Connect this computer
                  </a>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* ── Info footer ── */}
      {linked && (
        <div className="flex items-start gap-2.5 rounded-2xl border border-white/[0.07] bg-white/[0.015] px-4 py-3">
          <Info size={15} className="text-cyan-300/70 shrink-0 mt-0.5" />
          <p className="text-xs text-white/45 leading-relaxed">
            No re-pairing is needed after restart. Connected computers automatically reappear here.
          </p>
        </div>
      )}
    </div>
  )
}

// ── One connected computer, matching the "My PC" card in the design ──────────
function ComputerCard({
  device: d,
  counts,
  copied,
  expanded,
  onCopy,
  onToggleExpand,
  onUseModels,
  manageAccessUrl,
  cardCls,
  btnOutline,
}: {
  device: DeviceInfo
  counts?: ModelCount
  copied: boolean
  expanded: boolean
  onCopy: () => void
  onToggleExpand: () => void
  onUseModels?: () => void
  manageAccessUrl: string
  cardCls: string
  btnOutline: string
}) {
  const online = !!d.online
  const platform = d.platform || 'node'
  const ollamaN = counts?.ollama ?? 0
  const personaN = counts?.personas ?? 0
  const lastSeen = d.last_seen ? new Date(d.last_seen).toLocaleString() : '—'

  return (
    <div className={cardCls}>
      <div className="flex flex-col lg:flex-row lg:items-start gap-4">
        {/* Icon with online dot */}
        <div className="relative shrink-0">
          <span className="h-16 w-16 rounded-2xl grid place-items-center bg-gradient-to-br from-slate-700/60 to-slate-900/60 border border-white/10">
            <Monitor size={26} className="text-white/70" />
          </span>
          <span className={`absolute -bottom-1 -left-1 w-3.5 h-3.5 rounded-full border-2 border-[#16171b] ${online ? 'bg-emerald-400' : 'bg-white/30'}`} />
        </div>

        {/* Details */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2.5">
            <h4 className="text-base font-bold text-white truncate">{d.name}</h4>
            {online ? (
              <span className="inline-flex items-center gap-1.5 text-[11px] px-2 py-0.5 rounded-full bg-emerald-500/12 border border-emerald-500/30 text-emerald-300">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Online
              </span>
            ) : (
              <span className="text-[11px] px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-white/45">Offline</span>
            )}
          </div>

          <div className="flex items-center gap-2 mt-1 text-xs text-white/45">
            <span className="inline-flex items-center gap-1">
              <Cpu size={12} /> {platform}
            </span>
            <span className="text-white/20">•</span>
            <span className="font-mono text-white/55 truncate">{d.id}</span>
            <button type="button" onClick={onCopy} aria-label="Copy device ID"
              className="w-6 h-6 grid place-items-center rounded-md text-white/40 hover:text-white/80 hover:bg-white/5 shrink-0">
              {copied ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
            </button>
          </div>

          {/* Chips */}
          <div className="flex flex-wrap items-center gap-2 mt-3">
            <span className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-lg bg-white/[0.04] border border-white/10 text-white/70">
              <Boxes size={12} className="text-cyan-300/80" /> {ollamaN} Ollama model{ollamaN === 1 ? '' : 's'}
            </span>
            <span className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-lg bg-white/[0.04] border border-white/10 text-white/70">
              <Users size={12} className="text-violet-300/80" /> {personaN} HomePilot persona{personaN === 1 ? '' : 's'}
            </span>
            <span className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-lg bg-white/[0.04] border border-white/10 text-white/70">
              <ShieldCheck size={12} className="text-emerald-300/80" /> Private access
            </span>
          </div>

          <p className="text-xs text-white/50 mt-3 leading-relaxed">
            Requests run on this computer through the encrypted OllaBridge relay.
          </p>
          <p className="text-[11px] text-white/35 mt-0.5">
            Available in <span className="text-cyan-300/80">Models</span> under the OllaBridge provider.
          </p>

          {expanded && (
            <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 rounded-xl bg-black/20 border border-white/[0.06] p-3 text-[11px]">
              <Detail label="Name" value={d.name} />
              <Detail label="Status" value={online ? 'Online' : 'Offline'} />
              <Detail label="Platform" value={platform} />
              <Detail label="Last seen" value={lastSeen} />
              <Detail label="Ollama models" value={String(ollamaN)} />
              <Detail label="HomePilot personas" value={String(personaN)} />
              {d.gpu_name ? <Detail label="GPU" value={d.gpu_name} /> : null}
              {d.vram_mb ? <Detail label="VRAM" value={`${Math.round(d.vram_mb / 1024)} GB`} /> : null}
              <Detail label="Access" value="Private — only your account" />
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex flex-row lg:flex-col gap-2 shrink-0 lg:w-40">
          <button type="button" onClick={onUseModels} disabled={!onUseModels}
            className="h-9 px-3 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-500 text-white text-xs font-semibold inline-flex items-center justify-center gap-1.5 disabled:opacity-60 flex-1 lg:flex-none">
            <Rocket size={13} /> Use Models
          </button>
          <button type="button" onClick={onToggleExpand} className={btnOutline + ' flex-1 lg:flex-none'}>
            <Monitor size={13} /> View Computer
          </button>
          <a href={manageAccessUrl} target="_blank" rel="noopener noreferrer" className={btnOutline + ' flex-1 lg:flex-none'}>
            <Users size={13} /> Manage Access
          </a>
        </div>
      </div>
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-white/35">{label}</div>
      <div className="text-white/75 truncate">{value}</div>
    </div>
  )
}
