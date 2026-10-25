/**
 * Settings → Connectors (backend/app/connectors).
 *
 * Accounts on other services that HomePilot uses on your behalf. Linking keeps the secret on
 * the server; this screen only ever sees whether a connector is linked and to which account.
 * A linked Hugging Face account shows up in Models as the "Hugging Face" provider, with its
 * chat, vision, image and video models.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Check, ExternalLink, Loader2, Search, X } from 'lucide-react'
import { resolveBackendUrl } from '../lib/backendUrl'

type Connector = {
  id: string
  name: string
  description: string
  auth: 'token'
  token_url?: string
  token_hint?: string
  featured?: boolean
  connected: boolean
  account?: string
}

function authHeaders(): Record<string, string> {
  const token = (() => { try { return localStorage.getItem('homepilot_auth_token') || '' } catch { return '' } })()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Hugging Face's mark, drawn small and simple. */
function Logo({ id }: { id: string }) {
  if (id === 'huggingface') {
    return (
      <div aria-hidden className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#FFD21E] text-[22px]">🤗</div>
    )
  }
  return <div aria-hidden className="h-10 w-10 shrink-0 rounded-xl bg-white/10" />
}

export default function ConnectorsPanel({ backendUrl }: { backendUrl?: string }) {
  const base = resolveBackendUrl(backendUrl).replace(/\/+$/, '')
  const [items, setItems] = useState<Connector[] | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<string | null>(null)   // connector being linked
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')

  const load = useCallback(async () => {
    setError('')
    try {
      const res = await fetch(`${base}/v1/connectors`, { headers: authHeaders(), credentials: 'include' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setItems((await res.json()).connectors || [])
    } catch {
      setError('Could not load connectors. Check the connection to HomePilot.')
      setItems([])
    }
  }, [base])

  useEffect(() => { void load() }, [load])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (items || []).filter((c) => !q || `${c.name} ${c.description}`.toLowerCase().includes(q))
  }, [items, query])

  async function link(c: Connector) {
    setBusy(true)
    setFormError('')
    try {
      const res = await fetch(`${base}/v1/connectors/${c.id}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ token: token.trim() }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`)
      setOpen(null)
      setToken('')
      await load()
    } catch (e) {
      setFormError(e instanceof Error ? e.message : 'Could not connect.')
    } finally {
      setBusy(false)
    }
  }

  async function unlink(c: Connector) {
    setBusy(true)
    try {
      await fetch(`${base}/v1/connectors/${c.id}`, { method: 'DELETE', credentials: 'include', headers: authHeaders() })
      await load()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-white">Connectors</h2>
        <p className="mt-1 text-[14px] leading-relaxed text-white/55">
          Connectors let HomePilot use your accounts on other services. Your keys stay on this server.
        </p>
      </div>

      <label className="flex items-center gap-3 rounded-full border border-white/10 bg-white/[0.05] px-4 py-3 focus-within:border-white/25">
        <Search size={18} className="text-white/40" aria-hidden />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search connectors…"
          aria-label="Search connectors"
          className="min-w-0 flex-1 bg-transparent text-[16px] text-white placeholder:text-white/35 outline-none"
        />
      </label>

      {error ? <p className="text-[13px] text-amber-300/90">{error}</p> : null}
      {items === null ? <Loader2 size={18} className="animate-spin text-white/40" aria-label="Loading" /> : null}

      {shown.length > 0 && (
        <section>
          <h3 className="mb-2 px-1 text-[13px] font-semibold text-white/50">Featured</h3>
          <div className="overflow-hidden rounded-2xl border border-white/[0.06] bg-white/[0.03] divide-y divide-white/[0.06]">
            {shown.map((c) => (
              <div key={c.id}>
                <div className="flex items-center gap-3.5 px-4 py-3.5">
                  <Logo id={c.id} />
                  <div className="min-w-0 flex-1">
                    <div className="text-[16px] font-medium text-white">{c.name}</div>
                    <div className="truncate text-[13px] text-white/50">
                      {c.connected ? <span className="text-emerald-300/90">Connected{c.account ? ` as ${c.account}` : ''}</span> : c.description}
                    </div>
                  </div>
                  {c.connected ? (
                    <button type="button" disabled={busy} onClick={() => { void unlink(c) }}
                      className="min-h-[40px] rounded-full px-3 text-[14px] text-white/50 hover:text-white/80">
                      Disconnect
                    </button>
                  ) : (
                    <button type="button" onClick={() => { setOpen(open === c.id ? null : c.id); setFormError('') }}
                      className="min-h-[40px] rounded-full px-3 text-[15px] font-medium text-white/80 hover:text-white">
                      {open === c.id ? 'Cancel' : 'Connect'}
                    </button>
                  )}
                </div>

                {open === c.id && !c.connected && (
                  <form className="space-y-3 px-4 pb-4" onSubmit={(e) => { e.preventDefault(); void link(c) }}>
                    <p className="text-[13px] leading-relaxed text-white/55">
                      {c.token_hint}{' '}
                      {c.token_url ? (
                        <a href={c.token_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sky-300 hover:underline">
                          Create a token <ExternalLink size={12} aria-hidden />
                        </a>
                      ) : null}
                    </p>
                    <div className="flex gap-2">
                      <input
                        type="password"
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                        placeholder="hf_…"
                        aria-label={`${c.name} access token`}
                        autoComplete="off"
                        className="min-w-0 flex-1 rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 text-[16px] text-white outline-none focus:border-white/30"
                      />
                      <button type="submit" disabled={busy || token.trim().length < 8}
                        className="flex min-h-[44px] items-center gap-1.5 rounded-xl bg-white px-4 text-[14px] font-semibold text-black disabled:opacity-40">
                        {busy ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />} Connect
                      </button>
                    </div>
                    {formError ? (
                      <p className="flex items-center gap-1.5 text-[13px] text-red-300"><X size={13} aria-hidden /> {formError}</p>
                    ) : null}
                  </form>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {items && shown.length === 0 && !error ? (
        <p className="px-1 text-[14px] text-white/45">No connector matches “{query}”.</p>
      ) : null}

      <p className="px-1 text-[13px] leading-relaxed text-white/40">
        After connecting Hugging Face, open <b className="text-white/60">Models</b>, choose the provider
        <b className="text-white/60"> Hugging Face</b>, and pick a model for chat, multimodal, images or video.
        Usage is billed to your Hugging Face account.
      </p>
    </div>
  )
}
