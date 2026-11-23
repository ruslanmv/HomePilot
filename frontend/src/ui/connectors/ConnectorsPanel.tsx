/**
 * Settings → Connectors (backend/app/connectors).
 *
 * Accounts on other services that HomePilot uses on your behalf. Linking keeps the secret on
 * the server; this screen only ever sees whether a connector is linked and to which account.
 * A linked Hugging Face account shows up in Models as the "Hugging Face" provider, with its
 * chat, vision, image and video models.
 *
 * Connecting is the usual "Sign in with …" flow (connectors/oauth.py): a sheet says what
 * HomePilot will be able to do, "Continue with Hugging Face" opens Hugging Face's own consent
 * page in a new window, you click Accept, and the window closes itself. This screen hears about
 * it three ways — a message from the window, a BroadcastChannel, and polling the connector list —
 * because a provider's opener policy can cut the first one. Pasting an access token stays
 * available ("Use an access token instead"), and is the only way when the server has no OAuth app.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowRight, Check, ExternalLink, KeyRound, Loader2, Search, ShieldCheck, X } from 'lucide-react'
import { resolveBackendUrl } from '../lib/backendUrl'
import { OPEN_MODELS_EVENT } from '../components/ChatSettingsPopover'

type Connector = {
  id: string
  name: string
  description: string
  auth: 'token'
  oauth?: boolean
  token_url?: string
  token_hint?: string
  grants?: string[]
  billing?: string
  manage_url?: string
  featured?: boolean
  connected: boolean
  expired?: boolean
  account?: string
  avatar?: string
  via?: string
  connected_at?: number | null
}

/** Where a connect sheet is: reading the consent, waiting on the provider's window, done. */
type Step = 'consent' | 'waiting' | 'token' | 'done'

const POLL_MS = 2000
/** The server keeps a pending sign-in for ten minutes (oauth.STATE_TTL_S); make a new one before. */
const PREPARED_TTL_MS = 8 * 60 * 1000
const POPUP_W = 520
const POPUP_H = 720
const WAIT_LIMIT_MS = 10 * 60 * 1000

function authHeaders(): Record<string, string> {
  const token = (() => { try { return localStorage.getItem('homepilot_auth_token') || '' } catch { return '' } })()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** Hugging Face's mark, drawn small and simple. */
function Logo({ id, size = 40 }: { id: string; size?: number }) {
  if (id === 'huggingface') {
    return (
      <div aria-hidden style={{ width: size, height: size, fontSize: size * 0.55 }}
        className="flex shrink-0 items-center justify-center rounded-xl bg-[#FFD21E]">🤗</div>
    )
  }
  return <div aria-hidden style={{ width: size, height: size }} className="shrink-0 rounded-xl bg-white/10" />
}

function Avatar({ c }: { c: Connector }) {
  if (c.avatar) return <img src={c.avatar} alt="" className="h-10 w-10 shrink-0 rounded-xl object-cover" />
  return <Logo id={c.id} />
}

function since(ts?: number | null): string {
  if (!ts) return ''
  try { return new Date(ts * 1000).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) } catch { return '' }
}

export default function ConnectorsPanel({ backendUrl }: { backendUrl?: string }) {
  const base = resolveBackendUrl(backendUrl).replace(/\/+$/, '')
  const [items, setItems] = useState<Connector[] | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [sheet, setSheet] = useState<{ id: string; step: Step } | null>(null)
  const [manage, setManage] = useState<string | null>(null)       // connected row expanded
  const [confirmUnlink, setConfirmUnlink] = useState(false)
  const [token, setToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [signInUrl, setSignInUrl] = useState('')                  // for "Reopen window"
  const [blocked, setBlocked] = useState(false)                  // the browser refused the window
  // The one-use sign-in URL, made as soon as the consent sheet shows, so "Continue" opens it
  // directly inside the click — the same call as "Open the sign-in window". Opening an empty
  // window first and pointing it at Hugging Face once the server answered left that window
  // blank in the Space, which runs HomePilot inside an iframe.
  const [prepared, setPrepared] = useState<{ id: string; url: string; at: number } | null>(null)
  const popup = useRef<Window | null>(null)
  const waitStarted = useRef(0)

  const load = useCallback(async (): Promise<Connector[]> => {
    setError('')
    try {
      const res = await fetch(`${base}/v1/connectors`, { headers: authHeaders(), credentials: 'include' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const list: Connector[] = (await res.json()).connectors || []
      setItems(list)
      return list
    } catch {
      setError('Could not load connectors. Check the connection to HomePilot.')
      setItems((prev) => prev || [])
      return []
    }
  }, [base])

  useEffect(() => { void load() }, [load])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (items || []).filter((c) => !q || `${c.name} ${c.description}`.toLowerCase().includes(q))
  }, [items, query])

  const current = sheet ? (items || []).find((c) => c.id === sheet.id) || null : null

  function openSheet(c: Connector) {
    setFormError('')
    setToken('')
    setSignInUrl('')
    setBlocked(false)
    setSheet({ id: c.id, step: c.oauth ? 'consent' : 'token' })
  }

  function closeSheet() {
    try { popup.current?.close() } catch { /* not ours to close any more */ }
    popup.current = null
    setSheet(null)
  }

  // The sign-in window reports back (message / BroadcastChannel), or polling sees the link.
  const waiting = sheet?.step === 'waiting'
  useEffect(() => {
    if (!waiting || !sheet) return
    const id = sheet.id
    let done = false
    const finish = (ok: boolean, why = '') => {
      if (done) return
      if (ok) {
        done = true
        void load().then(() => setSheet({ id, step: 'done' }))
      } else if (why) {
        done = true
        setFormError(why)
        setSheet({ id, step: 'consent' })
      }
    }
    const onMessage = (e: MessageEvent) => {
      const m = e.data
      if (!m || m.type !== 'homepilot:connector' || m.id !== id) return
      const allowed = [window.location.origin]
      try { allowed.push(new URL(base, window.location.href).origin) } catch { /* relative base */ }
      if (!allowed.includes(e.origin)) return
      finish(!!m.ok, m.ok ? '' : String(m.error || 'The sign-in did not finish.'))
    }
    window.addEventListener('message', onMessage)
    let channel: BroadcastChannel | null = null
    try {
      channel = new BroadcastChannel('homepilot-connectors')
      channel.onmessage = (e) => onMessage(new MessageEvent('message', { data: e.data, origin: window.location.origin }))
    } catch { /* older browsers: polling covers it */ }
    const timer = window.setInterval(async () => {
      if (Date.now() - waitStarted.current > WAIT_LIMIT_MS) {
        finish(false, 'The sign-in took too long. Please try again.')
        return
      }
      const list = await load()
      if (list.find((c) => c.id === id)?.connected) finish(true)
    }, POLL_MS)
    return () => {
      done = true
      window.removeEventListener('message', onMessage)
      try { channel?.close() } catch { /* closed */ }
      window.clearInterval(timer)
    }
  }, [waiting, sheet?.id, base, load]) // eslint-disable-line react-hooks/exhaustive-deps

  async function startSignIn(id: string): Promise<string> {
    const res = await fetch(`${base}/v1/connectors/${id}/oauth/start`, {
      method: 'POST', credentials: 'include', headers: authHeaders(),
    })
    const body = await res.json().catch(() => ({}))
    if (!res.ok || !body.url) throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`)
    return String(body.url)
  }

  // Have the sign-in URL ready while the person reads the consent sheet.
  const consentFor = sheet?.step === 'consent' && current?.oauth ? sheet.id : ''
  useEffect(() => {
    if (!consentFor) return
    if (prepared && prepared.id === consentFor && Date.now() - prepared.at < PREPARED_TTL_MS) return
    let alive = true
    startSignIn(consentFor)
      .then((url) => { if (alive) setPrepared({ id: consentFor, url, at: Date.now() }) })
      .catch(() => { /* "Continue" asks again and shows the error */ })
    return () => { alive = false }
  }, [consentFor]) // eslint-disable-line react-hooks/exhaustive-deps

  /** Open the provider's page in a centred window; null when the browser blocked it. */
  function openSignInWindow(id: string, url: string): Window | null {
    const left = Math.max(0, (window.screenX || 0) + ((window.outerWidth || POPUP_W) - POPUP_W) / 2)
    const top = Math.max(0, (window.screenY || 0) + ((window.outerHeight || POPUP_H) - POPUP_H) / 2)
    try {
      return window.open(url, `homepilot-connect-${id}`, `popup=yes,width=${POPUP_W},height=${POPUP_H},left=${left},top=${top}`)
    } catch {
      return null
    }
  }

  async function continueWithProvider(c: Connector) {
    setFormError('')
    let url = prepared && prepared.id === c.id && Date.now() - prepared.at < PREPARED_TTL_MS ? prepared.url : ''
    setPrepared(null)   // one use: a later "Continue" gets a fresh sign-in
    if (!url) {
      // Not ready yet (slow network): ask now; the click still counts for a few seconds.
      setBusy(true)
      try {
        url = await startSignIn(c.id)
      } catch (e) {
        setFormError(e instanceof Error ? e.message : 'Could not start the sign-in.')
        return
      } finally {
        setBusy(false)
      }
    }
    setSignInUrl(url)
    popup.current = openSignInWindow(c.id, url)
    setBlocked(!popup.current)
    waitStarted.current = Date.now()
    setSheet({ id: c.id, step: 'waiting' })
  }

  function reopen() {
    if (!signInUrl || !current) return
    popup.current = openSignInWindow(current.id, signInUrl)
    setBlocked(!popup.current)
  }

  async function linkWithToken(c: Connector) {
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
      setToken('')
      await load()
      setSheet({ id: c.id, step: 'done' })
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
      setManage(null)
      setConfirmUnlink(false)
    } finally {
      setBusy(false)
    }
  }

  function chooseModels() {
    closeSheet()
    window.dispatchEvent(new CustomEvent(OPEN_MODELS_EVENT))
  }

  // Escape closes the sheet, as any dialog.
  useEffect(() => {
    if (!sheet) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeSheet() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sheet]) // eslint-disable-line react-hooks/exhaustive-deps

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
                  {c.connected ? <Avatar c={c} /> : <Logo id={c.id} />}
                  <div className="min-w-0 flex-1">
                    <div className="text-[16px] font-medium text-white">{c.name}</div>
                    <div className="truncate text-[13px] text-white/50">
                      {c.connected ? (
                        <span className="inline-flex items-center gap-1.5 text-emerald-300/90">
                          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
                          Connected{c.account ? ` as ${c.account}` : ''}
                        </span>
                      ) : c.expired ? (
                        <span className="text-amber-300/90">Sign-in expired — reconnect to keep using it</span>
                      ) : c.description}
                    </div>
                  </div>
                  {c.connected ? (
                    <button type="button" aria-expanded={manage === c.id}
                      onClick={() => { setManage(manage === c.id ? null : c.id); setConfirmUnlink(false) }}
                      className="min-h-[40px] rounded-full border border-white/10 px-4 text-[14px] font-medium text-white/80 hover:bg-white/[0.06]">
                      {manage === c.id ? 'Done' : 'Manage'}
                    </button>
                  ) : (
                    <button type="button" onClick={() => openSheet(c)}
                      className="min-h-[40px] rounded-full bg-white px-4 text-[14px] font-semibold text-black hover:bg-white/90">
                      {c.expired ? 'Reconnect' : 'Connect'}
                    </button>
                  )}
                </div>

                {manage === c.id && c.connected && (
                  <div className="space-y-3 px-4 pb-4">
                    <dl className="grid grid-cols-[auto,1fr] gap-x-4 gap-y-1 rounded-xl bg-black/20 px-3.5 py-3 text-[13px]">
                      <dt className="text-white/45">Account</dt><dd className="truncate text-white/85">{c.account || '—'}</dd>
                      <dt className="text-white/45">Linked with</dt><dd className="text-white/85">{c.via === 'oauth' ? `Sign in with ${c.name}` : 'Access token'}</dd>
                      {c.connected_at ? <><dt className="text-white/45">Since</dt><dd className="text-white/85">{since(c.connected_at)}</dd></> : null}
                    </dl>
                    {confirmUnlink ? (
                      <div className="rounded-xl border border-red-400/20 bg-red-400/[0.06] p-3.5">
                        <p className="text-[13px] leading-relaxed text-red-100/90">
                          Disconnect {c.name}? HomePilot forgets the key on this server, and chats go back to the built-in model.
                        </p>
                        <div className="mt-3 flex gap-2">
                          <button type="button" disabled={busy} onClick={() => { void unlink(c) }}
                            className="flex min-h-[40px] items-center gap-1.5 rounded-full bg-red-500 px-4 text-[14px] font-semibold text-white disabled:opacity-50">
                            {busy ? <Loader2 size={14} className="animate-spin" /> : null} Disconnect
                          </button>
                          <button type="button" onClick={() => setConfirmUnlink(false)}
                            className="min-h-[40px] rounded-full px-4 text-[14px] text-white/70 hover:text-white">Keep</button>
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-wrap items-center gap-2">
                        <button type="button" onClick={chooseModels}
                          className="flex min-h-[40px] items-center gap-1.5 rounded-full bg-white px-4 text-[14px] font-semibold text-black">
                          Choose models <ArrowRight size={14} aria-hidden />
                        </button>
                        {c.manage_url ? (
                          <a href={c.manage_url} target="_blank" rel="noreferrer"
                            className="inline-flex min-h-[40px] items-center gap-1.5 rounded-full px-3 text-[14px] text-white/70 hover:text-white">
                            Review on {c.name} <ExternalLink size={13} aria-hidden />
                          </a>
                        ) : null}
                        <button type="button" onClick={() => setConfirmUnlink(true)}
                          className="ml-auto min-h-[40px] rounded-full px-3 text-[14px] text-red-300/90 hover:text-red-200">
                          Disconnect
                        </button>
                      </div>
                    )}
                  </div>
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

      {sheet && current && (
        <div className="fixed inset-0 z-[80] flex items-end justify-center bg-black/60 p-0 backdrop-blur-sm sm:items-center sm:p-4"
          onMouseDown={(e) => { if (e.target === e.currentTarget && sheet.step !== 'waiting') closeSheet() }}>
          <div role="dialog" aria-modal="true" aria-labelledby="connect-title"
            className="w-full max-w-[420px] rounded-t-3xl border border-white/10 bg-[#121217] p-6 shadow-2xl sm:rounded-3xl">
            <div className="flex justify-end">
              <button type="button" onClick={closeSheet} aria-label="Close"
                className="-mr-2 -mt-2 flex h-9 w-9 items-center justify-center rounded-full text-white/50 hover:bg-white/[0.06] hover:text-white">
                <X size={18} />
              </button>
            </div>

            {/* HomePilot ↔ provider */}
            <div className="mb-5 flex items-center justify-center gap-3">
              <div aria-hidden className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-[26px]">🏠</div>
              <div aria-hidden className="flex gap-1">
                {[0, 1, 2].map((i) => (
                  <span key={i} className={`h-1.5 w-1.5 rounded-full bg-white/30 ${sheet.step === 'waiting' ? 'animate-pulse' : ''}`}
                    style={{ animationDelay: `${i * 150}ms` }} />
                ))}
              </div>
              <Logo id={current.id} size={56} />
            </div>

            {sheet.step === 'done' ? (
              <div className="text-center">
                <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-emerald-400/15 text-emerald-300">
                  <Check size={22} aria-hidden />
                </div>
                <h3 id="connect-title" className="text-[19px] font-semibold text-white">You're connected</h3>
                <p className="mt-1.5 text-[14px] text-white/55">
                  {current.account ? <>Signed in as <b className="text-white/80">{current.account}</b>. </> : null}
                  Pick the models HomePilot should use.
                </p>
                <button type="button" onClick={chooseModels}
                  className="mt-5 flex min-h-[48px] w-full items-center justify-center gap-2 rounded-full bg-white text-[15px] font-semibold text-black">
                  Choose models <ArrowRight size={16} aria-hidden />
                </button>
                <button type="button" onClick={closeSheet}
                  className="mt-2 min-h-[44px] w-full rounded-full text-[14px] text-white/60 hover:text-white">Done</button>
              </div>
            ) : sheet.step === 'waiting' ? (
              <div className="text-center" aria-live="polite">
                <h3 id="connect-title" className="text-[19px] font-semibold text-white">
                  {blocked ? 'Your browser blocked the window' : `Finish in the ${current.name} window`}
                </h3>
                <p className="mt-1.5 text-[14px] leading-relaxed text-white/55">
                  {blocked ? <>Open it below, then click <b className="text-white/80">Authorize</b>.</> : <>Review the request and click <b className="text-white/80">Authorize</b>.</>}
                  {' '}This page updates on its own.
                </p>
                <div className="mt-5 flex items-center justify-center gap-2 text-[13px] text-white/45">
                  <Loader2 size={15} className="animate-spin" aria-hidden /> Waiting for {current.name}…
                </div>
                <div className="mt-5 flex flex-col gap-2">
                  {signInUrl ? (
                    <a href={signInUrl} target="_blank" rel="noopener" onClick={(e) => { e.preventDefault(); reopen() }}
                      className={`flex min-h-[44px] items-center justify-center gap-1.5 rounded-full text-[14px] font-medium ${
                        blocked ? 'bg-[#FFD21E] font-semibold text-black hover:brightness-95' : 'border border-white/10 text-white/80 hover:bg-white/[0.06]'
                      }`}>
                      {blocked ? `Open ${current.name} sign-in` : "Didn't see it? Open the sign-in window"} <ExternalLink size={13} aria-hidden />
                    </a>
                  ) : null}
                  <button type="button" onClick={() => { setFormError(''); setSheet({ id: current.id, step: 'consent' }) }}
                    className="min-h-[44px] rounded-full text-[14px] text-white/55 hover:text-white">Cancel</button>
                </div>
              </div>
            ) : sheet.step === 'consent' ? (
              <div>
                <h3 id="connect-title" className="text-center text-[19px] font-semibold text-white">Connect {current.name}</h3>
                <p className="mt-1.5 text-center text-[14px] text-white/55">Sign in and approve — no keys to copy.</p>
                {current.grants?.length ? (
                  <div className="mt-5 rounded-2xl bg-white/[0.04] p-4">
                    <div className="mb-2 text-[12px] font-semibold uppercase tracking-wider text-white/40">HomePilot will be able to</div>
                    <ul className="space-y-2">
                      {current.grants.map((g) => (
                        <li key={g} className="flex gap-2.5 text-[14px] text-white/80">
                          <Check size={16} className="mt-0.5 shrink-0 text-emerald-300" aria-hidden /> {g}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <p className="mt-3 flex gap-2 px-1 text-[12px] leading-relaxed text-white/45">
                  <ShieldCheck size={14} className="mt-0.5 shrink-0" aria-hidden />
                  <span>{current.billing} HomePilot never sees your password, and you can disconnect at any time.</span>
                </p>
                {formError ? (
                  <p role="alert" className="mt-3 flex items-center gap-1.5 text-[13px] text-red-300"><X size={13} aria-hidden /> {formError}</p>
                ) : null}
                <button type="button" disabled={busy} onClick={() => { void continueWithProvider(current) }}
                  className="mt-5 flex min-h-[48px] w-full items-center justify-center gap-2 rounded-full bg-[#FFD21E] text-[15px] font-semibold text-black hover:brightness-95 disabled:opacity-60">
                  {busy ? <Loader2 size={16} className="animate-spin" /> : <span aria-hidden>🤗</span>} Continue with {current.name}
                </button>
                <button type="button" onClick={() => { setFormError(''); setSheet({ id: current.id, step: 'token' }) }}
                  className="mt-2 flex min-h-[44px] w-full items-center justify-center gap-1.5 rounded-full text-[14px] text-white/55 hover:text-white">
                  <KeyRound size={14} aria-hidden /> Use an access token instead
                </button>
              </div>
            ) : (
              <form onSubmit={(e) => { e.preventDefault(); void linkWithToken(current) }}>
                <h3 id="connect-title" className="text-center text-[19px] font-semibold text-white">Connect with a token</h3>
                <ol className="mt-4 space-y-2 text-[14px] text-white/70">
                  <li className="flex gap-2.5"><span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/10 text-[11px] font-semibold">1</span>
                    <span>
                      {current.token_url ? (
                        <a href={current.token_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-sky-300 hover:underline">
                          Create a token on {current.name} <ExternalLink size={12} aria-hidden />
                        </a>
                      ) : 'Create a token'}
                    </span>
                  </li>
                  <li className="flex gap-2.5"><span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/10 text-[11px] font-semibold">2</span>
                    <span>{current.token_hint}</span></li>
                  <li className="flex gap-2.5"><span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-white/10 text-[11px] font-semibold">3</span>
                    <span>Paste it here.</span></li>
                </ol>
                <input
                  type="password"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="hf_…"
                  aria-label={`${current.name} access token`}
                  autoComplete="off"
                  autoFocus
                  className="mt-4 w-full rounded-xl border border-white/10 bg-black/30 px-3.5 py-3 text-[16px] text-white outline-none focus:border-white/30"
                />
                {formError ? (
                  <p role="alert" className="mt-2 flex items-center gap-1.5 text-[13px] text-red-300"><X size={13} aria-hidden /> {formError}</p>
                ) : null}
                <button type="submit" disabled={busy || token.trim().length < 8}
                  className="mt-4 flex min-h-[48px] w-full items-center justify-center gap-2 rounded-full bg-white text-[15px] font-semibold text-black disabled:opacity-40">
                  {busy ? <Loader2 size={16} className="animate-spin" /> : <Check size={16} />} Connect
                </button>
                {current.oauth ? (
                  <button type="button" onClick={() => { setFormError(''); setSheet({ id: current.id, step: 'consent' }) }}
                    className="mt-2 min-h-[44px] w-full rounded-full text-[14px] text-white/55 hover:text-white">
                    Back to Continue with {current.name}
                  </button>
                ) : null}
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
