/**
 * OllaBridgeModels — the "OllaBridge" provider class in Model Management.
 *
 * A special provider whose models come from the user's LINKED HomePilot /
 * OllaBridge nodes (e.g. a home PC with a high-end GPU running the OllaBridge
 * connector). Signed in with an OllaBridge account, this panel:
 *
 *   1. Lists the user's linked devices (online state, GPU name, VRAM) from
 *      Cloud `GET /v1/devices`.
 *   2. Syncs the models those nodes advertise via Cloud
 *      `GET /ollama/v1/models` (entries sourced from the relay are the
 *      user's own shared devices — model sync, no manual entry).
 *   3. One tap "Use for Chat" routes inference through the Cloud relay to the
 *      user's own GPU node: it configures provider=openai_compat with
 *      base_url={cloud}/ollama/v1 and the picked model; the chat request then
 *      carries the user's Cloud token as provider_api_key so the relay knows
 *      whose node to use.
 *
 * Fully additive and self-contained: talks to the Cloud directly from the
 * browser (CORS is open on the Cloud), stores the token only in
 * localStorage, and hands the provider switch to App via a CustomEvent —
 * zero prop-drilling into the existing Models plumbing.
 */
import React, { useCallback, useEffect, useState } from 'react'
import { isBffSessionEnabled } from '../account/featureFlags'
import { Cloud, Cpu, Loader2, LogOut, RefreshCw, Zap } from 'lucide-react'

const LS_CLOUD_TOKEN = 'homepilot_cloud_token'
const LS_CLOUD_URL = 'homepilot_cloud_url'

export function getCloudUrl(): string {
  try {
    const saved = (localStorage.getItem(LS_CLOUD_URL) || '').trim()
    if (saved) return saved.replace(/\/+$/, '')
  } catch { /* ignore */ }
  const env: Record<string, string | undefined> =
    ((import.meta as unknown as { env?: Record<string, string | undefined> }).env) || {}
  return ((env.VITE_OLLABRIDGE_CLOUD_URL || '').trim() || 'https://ruslanmv-ollabridge.hf.space').replace(/\/+$/, '')
}

export function getCloudToken(): string {
  try { return (localStorage.getItem(LS_CLOUD_TOKEN) || '').trim() } catch { return '' }
}

interface DeviceInfo {
  id: string
  name: string
  platform?: string | null
  online: boolean
  gpu_name?: string | null
  vram_mb?: number | null
}

interface CloudModel {
  id: string
  owned_by?: string
  source?: string
  device_id?: string
  device_name?: string
}

/** Loose model-type guess from the model id — drives badges + per-tab filter. */
function guessType(id: string): string {
  const s = id.toLowerCase()
  if (/(llava|vision|-vl|minicpm-v|moondream)/.test(s)) return 'multimodal'
  if (/(sdxl|flux|stable-diffusion|sd15|sd3|pony|dreamshaper)/.test(s)) return 'image'
  if (/(svd|ltx|wan|video)/.test(s)) return 'video'
  if (/(upscal|esrgan|enhance|restore|gfpgan|codeformer)/.test(s)) return 'enhance'
  if (/lora/.test(s)) return 'LoRA'
  return 'chat'
}

/** Does a model's guessed type belong under the given Model Type tab? */
function matchesTab(filterType: string | undefined, guessed: string): boolean {
  if (!filterType) return true
  switch (filterType) {
    case 'chat': return guessed === 'chat'
    case 'multimodal': return guessed === 'multimodal'
    case 'image':
    case 'edit': return guessed === 'image'
    case 'video': return guessed === 'video'
    case 'enhance': return guessed === 'enhance'
    case 'lora': return guessed === 'LoRA'
    case 'addons': return true
    default: return true
  }
}

const TAB_LABEL: Record<string, string> = {
  chat: 'chat', multimodal: 'multimodal', image: 'image', edit: 'edit',
  video: 'video', enhance: 'enhance', lora: 'LoRA', addons: 'add-on',
}

export default function OllaBridgeModels({ filterType }: { filterType?: string } = {}) {
  const cloudUrl = getCloudUrl()
  const [token, setToken] = useState(getCloudToken())
  const [devices, setDevices] = useState<DeviceInfo[]>([])
  const [models, setModels] = useState<CloudModel[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [activeModel, setActiveModel] = useState(
    () => { try { return localStorage.getItem('homepilot_model_chat') || '' } catch { return '' } },
  )

  const refresh = useCallback(async (tok: string) => {
    if (!tok) return
    setLoading(true)
    setError('')
    try {
      const auth = { Authorization: `Bearer ${tok}` }
      const [devRes, modRes] = await Promise.all([
        fetch(`${cloudUrl}/v1/devices`, { headers: auth }),
        fetch(`${cloudUrl}/ollama/v1/models`, { headers: auth }),
      ])
      if (devRes.status === 401 || modRes.status === 401) {
        setError('OllaBridge session expired — reconnect to refresh your nodes.')
        setToken('')
        try { localStorage.removeItem(LS_CLOUD_TOKEN) } catch { /* ignore */ }
        return
      }
      const devs = devRes.ok ? await devRes.json() : []
      setDevices(Array.isArray(devs) ? devs : [])
      const mods = modRes.ok ? await modRes.json() : { data: [] }
      const list: CloudModel[] = Array.isArray(mods?.data) ? mods.data : []
      // Own-node models first (relay/shared_device), then the rest.
      list.sort((a, b) => Number(b.source === 'shared_device') - Number(a.source === 'shared_device'))
      setModels(list)
    } catch {
      setError('Could not reach OllaBridge Cloud.')
    } finally {
      setLoading(false)
    }
  }, [cloudUrl])

  useEffect(() => { if (token) void refresh(token) }, [token, refresh])

  async function handleConnect(e: React.FormEvent) {
    e.preventDefault()
    setConnecting(true)
    setError('')
    try {
      const r = await fetch(`${cloudUrl}/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), password }),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok || !data.token) {
        setError(data.detail || 'Invalid OllaBridge email or password')
        return
      }
      try {
        // Batch 7 (BFF): the token lives in this component's memory for the
        // session; when BFF is on we no longer persist it in browser storage.
        if (!isBffSessionEnabled()) localStorage.setItem(LS_CLOUD_TOKEN, data.token)
        localStorage.setItem(LS_CLOUD_URL, cloudUrl)
      } catch { /* ignore */ }
      setToken(data.token)
      setPassword('')
    } catch {
      setError('Could not reach OllaBridge Cloud.')
    } finally {
      setConnecting(false)
    }
  }

  function handleDisconnect() {
    try { localStorage.removeItem(LS_CLOUD_TOKEN) } catch { /* ignore */ }
    setToken('')
    setDevices([])
    setModels([])
  }

  function useForChat(modelId: string) {
    setActiveModel(modelId)
    // App.tsx listens for this and flips chat provider to the OllaBridge relay
    // (openai_compat @ {cloud}/ollama/v1) + persists the choice.
    window.dispatchEvent(new CustomEvent('homepilot:use-gpu-node', {
      detail: { baseUrl: `${cloudUrl}/ollama/v1`, model: modelId },
    }))
  }

  const onlineCount = devices.filter((d) => d.online).length

  return (
    <section className="rounded-2xl border border-white/10 bg-gradient-to-br from-[#101018] to-[#0b0b12] p-4 sm:p-5 mb-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="h-9 w-9 rounded-xl grid place-items-center bg-gradient-to-br from-cyan-500/20 to-violet-500/20 border border-white/10 shrink-0">
            <Cloud size={17} className="text-cyan-300" />
          </span>
          <div className="min-w-0">
            <h3 className="text-sm font-bold text-white leading-tight">OllaBridge — your remote HomePilot nodes</h3>
            <p className="text-xs text-white/45 truncate">
              Models synced from linked machines; inference runs on your own GPU through the relay.
            </p>
          </div>
        </div>
        {token && (
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => refresh(token)}
              className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/70 hover:text-white inline-flex items-center gap-1.5 transition-colors"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Sync
            </button>
            <button
              type="button"
              onClick={handleDisconnect}
              className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/50 hover:text-white inline-flex items-center gap-1.5 transition-colors"
              title="Disconnect OllaBridge"
            >
              <LogOut size={13} />
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-3 px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-xs" role="alert">
          {error}
        </div>
      )}

      {!token ? (
        /* Connect card */
        <form onSubmit={handleConnect} className="grid gap-2.5 sm:grid-cols-[1fr_1fr_auto]">
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="OllaBridge email"
            autoComplete="email"
            className="h-11 rounded-xl bg-black/40 border border-white/10 px-3 text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50"
          />
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoComplete="current-password"
            className="h-11 rounded-xl bg-black/40 border border-white/10 px-3 text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50"
          />
          <button
            type="submit"
            disabled={connecting}
            className="h-11 px-4 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-500 text-white text-sm font-bold disabled:opacity-60"
          >
            {connecting ? 'Connecting…' : 'Connect OllaBridge'}
          </button>
          <p className="sm:col-span-3 text-[11px] text-white/35">
            Sign in with your OllaBridge account to sync models from your linked HomePilot machines.
            Your token stays in this browser only.
          </p>
        </form>
      ) : (
        <>
          {/* Devices strip */}
          <div className="flex gap-2 overflow-x-auto pb-1 mb-3">
            {devices.length === 0 && !loading && (
              <p className="text-xs text-white/40 py-1">
                No linked machines yet. Pair a PC at{' '}
                <a href={`${cloudUrl}/link`} target="_blank" rel="noopener noreferrer" className="text-violet-300 hover:text-white underline">
                  {cloudUrl.replace(/^https?:\/\//, '')}/link
                </a>{' '}— its models will appear here automatically.
              </p>
            )}
            {devices.map((d) => (
              <div
                key={d.id}
                className="shrink-0 flex items-center gap-2 rounded-xl border border-white/10 bg-black/30 px-3 py-2"
              >
                <span className={`w-2 h-2 rounded-full ${d.online ? 'bg-emerald-400' : 'bg-white/25'}`} />
                <Cpu size={14} className="text-white/50" />
                <div className="leading-tight">
                  <div className="text-xs font-semibold text-white">{d.name}</div>
                  <div className="text-[10px] text-white/40">
                    {d.gpu_name || d.platform || 'node'}
                    {d.vram_mb ? ` · ${Math.round(d.vram_mb / 1024)} GB VRAM` : ''}
                    {d.online ? ' · online' : ' · offline'}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Synced models — filtered to the active Model Type tab. */}
          {(() => {
            const shown = models.filter((m) => matchesTab(filterType, guessType(m.id)))
            if (shown.length === 0) {
              if (loading || devices.length === 0) return null
              const lbl = filterType ? (TAB_LABEL[filterType] || filterType) : ''
              return (
                <p className="text-xs text-white/40 py-1">
                  No {lbl} models advertised by your nodes yet. Pull {lbl} models on your linked
                  HomePilot and they’ll sync here automatically.
                </p>
              )
            }
            return (
            <div className="grid gap-1.5">
              {shown.slice(0, 40).map((m) => {
                const own = m.source === 'shared_device'
                const type = guessType(m.id)
                const isActive = activeModel === m.id
                return (
                  <div
                    key={`${m.id}-${m.device_id || m.source || ''}`}
                    className="flex items-center gap-2.5 rounded-xl border border-white/[0.07] bg-white/[0.02] hover:bg-white/[0.045] px-3 py-2 transition-colors"
                  >
                    <span className="flex-1 min-w-0">
                      <span className="block text-[13px] text-white/85 truncate font-medium">{m.id}</span>
                      <span className="block text-[10px] text-white/35 truncate">
                        {own ? `your node${m.device_name ? ` · ${m.device_name}` : ''}` : (m.owned_by || m.source || 'cloud')} · {type}
                      </span>
                    </span>
                    {own && (
                      <span className="shrink-0 text-[9px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-md bg-emerald-500/15 text-emerald-300 border border-emerald-500/25">
                        GPU node
                      </span>
                    )}
                    {(type === 'chat' || type === 'multimodal') ? (
                      <button
                        type="button"
                        onClick={() => useForChat(m.id)}
                        className={[
                          'shrink-0 h-8 px-3 rounded-lg text-xs font-semibold inline-flex items-center gap-1.5 transition-colors',
                          isActive
                            ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
                            : 'bg-white/5 hover:bg-white/10 border border-white/10 text-white/70 hover:text-white',
                        ].join(' ')}
                      >
                        <Zap size={12} /> {isActive ? 'Active' : 'Use for Chat'}
                      </button>
                    ) : (
                      <span className="shrink-0 text-[10px] text-white/40 px-2 py-1 rounded-md bg-white/5 border border-white/10">Synced</span>
                    )}
                  </div>
                )
              })}
            </div>
            )
          })()}
        </>
      )}
    </section>
  )
}
