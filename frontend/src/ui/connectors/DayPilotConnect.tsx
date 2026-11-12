/**
 * DayPilotConnect — the connect sheet for DayPilot.
 *
 * Pairing, not a pasted token: HomePilot's server asks DayPilot for access,
 * the user approves it inside DayPilot (choosing the workspace and the
 * permissions), and HomePilot's server collects the credential. This sheet only
 * shows the short code and waits; no secret ever reaches the browser.
 */
import React, { useEffect, useRef, useState } from 'react'
import { ExternalLink, Loader2, X } from 'lucide-react'
import { authFetch } from '../lib/authFetch'

type Props = {
  base: string
  defaultEndpoint?: string
  placeholder?: string
  onConnected: () => void
}

const POLL_MS = 3000

export default function DayPilotConnect({ base, defaultEndpoint, placeholder, onConnected }: Props) {
  const [endpoint, setEndpoint] = useState(defaultEndpoint || '')
  const [code, setCode] = useState('')
  const [link, setLink] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const timer = useRef<number | null>(null)

  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current) }, [])

  async function poll() {
    try {
      const res = await authFetch(`${base}/v1/connectors/daypilot/pairing`)
      const body = await res.json().catch(() => ({}))
      if (body.status === 'connected') { onConnected(); return }
      if (body.status === 'pending') { timer.current = window.setTimeout(poll, POLL_MS); return }
      setCode('')
      setError(body.status === 'denied' ? 'The request was declined in DayPilot.'
        : body.status === 'expired' ? 'The code expired. Start again.'
        : body.message || 'Could not finish connecting.')
    } catch {
      timer.current = window.setTimeout(poll, POLL_MS * 2)
    }
  }

  async function start(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const res = await authFetch(`${base}/v1/connectors/daypilot/pairing`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ endpoint: endpoint.trim() }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`)
      setCode(body.user_code)
      setLink(body.verification_url)
      timer.current = window.setTimeout(poll, POLL_MS)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reach DayPilot.')
    } finally {
      setBusy(false)
    }
  }

  if (code) {
    return (
      <div className="text-center" aria-live="polite">
        <h3 id="connect-title" className="text-[19px] font-semibold text-white">Approve in DayPilot</h3>
        <p className="mt-1.5 text-[14px] text-white/60">
          Open DayPilot, check the code, choose a workspace and what to share.
        </p>
        <div className="mx-auto mt-4 w-fit rounded-xl bg-black/30 px-5 py-3 font-mono text-[24px] tracking-[0.2em] text-white">
          {code}
        </div>
        <a href={link} target="_blank" rel="noreferrer"
          className="mt-4 flex min-h-[48px] w-full items-center justify-center gap-2 rounded-full bg-white text-[15px] font-semibold text-black">
          Open DayPilot <ExternalLink size={15} aria-hidden />
        </a>
        <p className="mt-3 flex items-center justify-center gap-2 text-[13px] text-white/50">
          <Loader2 size={13} className="animate-spin" aria-hidden /> Waiting for your approval…
        </p>
      </div>
    )
  }

  return (
    <form onSubmit={start}>
      <h3 id="connect-title" className="text-center text-[19px] font-semibold text-white">Connect DayPilot</h3>
      <p className="mt-1.5 text-center text-[14px] text-white/55">
        You approve the connection inside DayPilot. HomePilot never sees your DayPilot password.
      </p>
      <label className="mt-4 block text-[13px] text-white/60">
        DayPilot address
        <input
          type="url"
          inputMode="url"
          value={endpoint}
          onChange={(e) => setEndpoint(e.target.value)}
          placeholder={placeholder || 'http://localhost:8080'}
          autoComplete="off"
          autoFocus
          className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3.5 py-3 text-[16px] text-white outline-none focus:border-white/30"
        />
      </label>
      {error ? (
        <p role="alert" className="mt-2 flex items-center gap-1.5 text-[13px] text-red-300"><X size={13} aria-hidden /> {error}</p>
      ) : null}
      <button type="submit" disabled={busy || !endpoint.trim()}
        className="mt-4 flex min-h-[48px] w-full items-center justify-center gap-2 rounded-full bg-white text-[15px] font-semibold text-black disabled:opacity-40">
        {busy ? <Loader2 size={16} className="animate-spin" /> : null} Get a code
      </button>
    </form>
  )
}
