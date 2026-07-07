/**
 * OllaBridgeLink — the "OllaBridge Link" settings section.
 *
 * The one place a user manages linking the web/mobile HomePilot to their
 * OllaBridge Cloud account and to their remote GPU machines (HomePilot Local
 * nodes running the connector). Two linking variants, surfaced clearly:
 *
 *   Variant A — Account link (this device ↔ Cloud): sign in with OllaBridge
 *     (or reuse the token from "Continue with OllaBridge"). This is what lets
 *     the web/mobile app SEE your account's nodes and route inference to them.
 *     Auto-linked when you signed in federated — shown as already connected.
 *
 *   Variant B — Add a GPU machine (a remote HomePilot Local ↔ Cloud): the PC
 *     with the high-end GPU runs the OllaBridge connector and pairs to your
 *     account with a short device code. Once paired, its models sync into the
 *     "OllaBridge" provider under every Model Type. Confirm the code at the
 *     Cloud pairing page.
 *
 * Self-contained: reuses the token/url helpers from OllaBridgeModels, talks to
 * the Cloud directly (CORS open), stores only the token in localStorage.
 */
import React, { useCallback, useEffect, useState } from 'react'
import { Cloud, Cpu, Download, ExternalLink, Loader2, LogOut, MonitorSmartphone, Plus, RefreshCw, Server, ShieldCheck } from 'lucide-react'
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
}

interface LocalStatus {
  edition: string
  available: boolean
  installed: boolean
  running: boolean
  local_url?: string | null
  models?: number
  share_scope?: string
}

const INSTALL_LOCAL_URL = 'https://github.com/ruslanmv/HomePilot#installation'

export default function OllaBridgeLink() {
  const cloudUrl = getCloudUrl()
  const [token, setToken] = useState(getCloudToken())
  const [email, setEmail] = useState('')
  const [me, setMe] = useState<{ email?: string } | null>(null)
  const [devices, setDevices] = useState<DeviceInfo[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [pw, setPw] = useState('')
  const [connecting, setConnecting] = useState(false)
  const [edition, setEdition] = useState<EditionInfo | null>(null)
  const [sidecar, setSidecar] = useState<LocalStatus | null>(null)

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

  const load = useCallback(async (tok: string) => {
    if (!tok) return
    setLoading(true)
    setError('')
    try {
      const auth = { Authorization: `Bearer ${tok}` }
      const [meRes, devRes] = await Promise.all([
        fetch(`${cloudUrl}/v1/auth/me`, { headers: auth }),
        fetch(`${cloudUrl}/v1/devices`, { headers: auth }),
      ])
      if (meRes.status === 401) {
        setError('Your OllaBridge session expired — reconnect below.')
        setToken(''); try { localStorage.removeItem('homepilot_cloud_token') } catch { /* ignore */ }
        return
      }
      setMe(meRes.ok ? await meRes.json() : null)
      // /v1/devices is 404 when device sharing is disabled on the Cloud — treat
      // as "no nodes" rather than an error so account-link still reads as OK.
      setDevices(devRes.ok ? (await devRes.json()) : [])
    } catch {
      setError('Could not reach OllaBridge Cloud.')
    } finally {
      setLoading(false)
    }
  }, [cloudUrl])

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
        localStorage.setItem('homepilot_cloud_token', data.token)
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
    setToken(''); setMe(null); setDevices([])
  }

  const linked = Boolean(token)
  const host = cloudUrl.replace(/^https?:\/\//, '')

  return (
    <div className="space-y-4">
      {/* Section intro */}
      <div className="flex items-start gap-3">
        <span className="h-10 w-10 rounded-xl grid place-items-center bg-gradient-to-br from-cyan-500/20 to-violet-500/20 border border-white/10 shrink-0">
          <Cloud size={18} className="text-cyan-300" />
        </span>
        <div>
          <h3 className="text-sm font-bold text-white">OllaBridge Link</h3>
          <p className="text-xs text-white/50 leading-relaxed">
            Link this HomePilot to your OllaBridge account to use models and GPUs from your
            remote HomePilot machines — from the web or your phone.
          </p>
        </div>
      </div>

      {error && (
        <div className="px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20 text-red-300 text-xs" role="alert">{error}</div>
      )}

      {/* ── Variant A: account link (this device ↔ Cloud) ── */}
      <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
        <div className="flex items-center justify-between gap-3 mb-1">
          <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-white/45">
            <MonitorSmartphone size={13} /> This device
          </div>
          {linked ? (
            <span className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full bg-emerald-500/12 border border-emerald-500/30 text-emerald-300">
              <ShieldCheck size={12} /> Linked
            </span>
          ) : (
            <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-white/50">Not linked</span>
          )}
        </div>

        {linked ? (
          <div className="flex flex-wrap items-center justify-between gap-3 mt-2">
            <p className="text-sm text-white/80 min-w-0">
              Connected as <span className="font-semibold text-white">{me?.email || 'your OllaBridge account'}</span>.
              <span className="block text-xs text-white/40 mt-0.5">Models from your linked machines appear under the “OllaBridge” provider in Models.</span>
            </p>
            <div className="flex items-center gap-2 shrink-0">
              <button type="button" onClick={() => load(token)} className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/70 inline-flex items-center gap-1.5">
                {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Refresh
              </button>
              <button type="button" onClick={disconnect} className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/50 inline-flex items-center gap-1.5">
                <LogOut size={13} /> Disconnect
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={connect} className="grid gap-2.5 sm:grid-cols-[1fr_1fr_auto] mt-2">
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="OllaBridge email" autoComplete="email"
              className="h-11 rounded-xl bg-black/40 border border-white/10 px-3 text-base sm:text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50" />
            <input type="password" required value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Password" autoComplete="current-password"
              className="h-11 rounded-xl bg-black/40 border border-white/10 px-3 text-base sm:text-sm text-white placeholder:text-white/30 outline-none focus:border-cyan-400/50" />
            <button type="submit" disabled={connecting} className="h-11 px-4 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-500 text-white text-sm font-bold disabled:opacity-60">
              {connecting ? 'Linking…' : 'Link account'}
            </button>
            <p className="sm:col-span-3 text-[11px] text-white/35">
              Tip: if you signed in with <span className="text-white/60 font-medium">“Continue with OllaBridge”</span>, this links automatically — no need to type it again.
            </p>
          </form>
        )}
      </div>

      {/* ── This computer (PROVIDER) — local edition only ──
          On the hosted web app there is no GPU to provide, so this whole card
          is hidden; the web app is a pure consumer. */}
      {edition?.is_local && (
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
          <div className="flex items-center justify-between gap-3 mb-1">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-white/45">
              <Server size={13} /> This computer
            </div>
            {sidecar?.running ? (
              <span className="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full bg-emerald-500/12 border border-emerald-500/30 text-emerald-300">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Sidecar running
              </span>
            ) : (
              <span className="text-[11px] px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-white/50">Sidecar stopped</span>
            )}
          </div>
          <p className="text-sm text-white/80">
            This PC can become your <span className="font-semibold text-white">private GPU node</span>. HomePilot Local
            runs the <span className="font-mono text-white/70">ollabridge</span> sidecar; pair it with OllaBridge Cloud to
            reach it from HomePilot Web or mobile.
          </p>
          {sidecar?.running ? (
            <div className="flex flex-wrap items-center gap-2 mt-3">
              <a href={`${(sidecar.local_url || 'http://127.0.0.1:11435')}/ui`} target="_blank" rel="noopener noreferrer"
                className="h-9 px-3 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs text-white/80 inline-flex items-center gap-1.5">
                <ExternalLink size={13} /> Open OllaBridge dashboard
              </a>
              <a href={`${cloudUrl}/link`} target="_blank" rel="noopener noreferrer"
                className="h-9 px-3 rounded-xl bg-gradient-to-r from-cyan-500/90 to-violet-500/90 text-white text-xs font-semibold inline-flex items-center gap-1.5">
                <Plus size={13} /> Pair this computer
              </a>
              <span className="text-[11px] text-white/40 ml-1">Sharing: <span className="text-white/60">my account only</span></span>
            </div>
          ) : (
            <div className="mt-3 text-xs text-white/50 leading-relaxed">
              The OllaBridge Local sidecar isn’t reachable{sidecar?.local_url ? ` at ${sidecar.local_url}` : ''}. Start it with{' '}
              <span className="font-mono text-white/70">ollabridge start</span> (installs on first run) — it serves an
              OpenAI-compatible gateway on <span className="font-mono text-white/70">:11435</span>. HomePilot Local’s desktop
              app starts it for you.
            </div>
          )}
          <p className="mt-2 text-[11px] text-white/30">Installed ≠ paired ≠ shared — nothing is shared until you approve it, and only to your own account by default.</p>
        </div>
      )}

      {/* ── Variant B: your computers on this account (consumer view) ── */}
      {linked && (
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
          <div className="flex items-center justify-between gap-3 mb-2">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wider text-white/45">
              <Cpu size={13} /> Your GPU machines
            </div>
            <a href={`${cloudUrl}/link`} target="_blank" rel="noopener noreferrer"
              className="h-9 px-3 rounded-xl bg-gradient-to-r from-cyan-500/90 to-violet-500/90 text-white text-xs font-semibold inline-flex items-center gap-1.5">
              <Plus size={13} /> Add a machine
            </a>
          </div>

          {devices.length > 0 ? (
            <div className="grid gap-1.5">
              {devices.map((d) => (
                <div key={d.id} className="flex items-center gap-2.5 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2">
                  <span className={`w-2 h-2 rounded-full ${d.online ? 'bg-emerald-400' : 'bg-white/25'}`} />
                  <Cpu size={14} className="text-white/50 shrink-0" />
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-medium text-white/85 truncate">{d.name}</div>
                    <div className="text-[10px] text-white/40 truncate">
                      {d.gpu_name || d.platform || 'node'}{d.vram_mb ? ` · ${Math.round(d.vram_mb / 1024)} GB VRAM` : ''} · {d.online ? 'online' : 'offline'}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : edition?.is_web ? (
            <div className="text-xs text-white/50 leading-relaxed">
              <p className="mb-2">No HomePilot computer linked yet. Install <span className="text-white/80 font-semibold">HomePilot Local</span> on your GPU PC to use its models here.</p>
              <a href={INSTALL_LOCAL_URL} target="_blank" rel="noopener noreferrer"
                className="h-9 px-3 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-500 text-white text-xs font-bold inline-flex items-center gap-1.5">
                <Download size={13} /> Get HomePilot Local
              </a>
              <p className="mt-2 text-white/35">Once it’s installed and paired, its models appear under the “OllaBridge” provider in <span className="text-white/55">Models</span> and run on that GPU.</p>
            </div>
          ) : (
            <div className="text-xs text-white/50 leading-relaxed">
              <p className="mb-1.5">No machines linked yet. To share a PC with a high-end GPU:</p>
              <ol className="list-decimal list-inside space-y-1 text-white/45">
                <li>Open HomePilot on that PC (it runs the OllaBridge sidecar).</li>
                <li>It shows a short pairing code like <span className="font-mono text-white/70">ABCD-1234</span>.</li>
                <li>Enter it at <a href={`${cloudUrl}/link`} target="_blank" rel="noopener noreferrer" className="text-violet-300 hover:text-white underline">{host}/link</a> (or tap “Add a machine”).</li>
              </ol>
              <p className="mt-2 text-white/35">Once paired, its models appear under the “OllaBridge” provider in <span className="text-white/55">Models</span>, and inference runs on that GPU.</p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
