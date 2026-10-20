/**
 * OllaBridge Cloud card (Model Management → Chat → OllaBridge).
 *
 * The existing Cloud integration in a compact card: sign in with the OllaBridge
 * account (the same POST /v1/auth/login + token handling as before), sync the
 * account's machines and models, pick one, and chat is routed through the Cloud
 * relay to the user's own nodes (openai_compat @ <cloud>/ollama/v1 — the
 * existing "Use for Chat" route). A saved session is shown as Connected only
 * after the Cloud has accepted it again; an expired one drops back to sign-in.
 */
import React, { useCallback, useEffect, useId, useRef, useState } from 'react'
import { CheckCircle2, Cloud, Cpu, ExternalLink, Loader2, LogOut } from 'lucide-react'
import {
  CardShell, ErrorLine, FetchButton, FIELD_LABEL, INPUT, InfoLine, ModelSelect, OverflowMenu, WarnLine,
  type MenuItem, type SelectOption,
} from './cardParts'
import {
  CLOUD_GROUP_LABEL, displayModelId, normalizeCloudModels, type CloudDevice, type CloudModelOption,
} from './models'
import {
  clearCloudSession, cloudChatBaseUrl, cloudLogin, DEFAULT_CLOUD_URL, fetchCloudInventory, getCloudToken,
  getCloudUrl, normalizeCloudUrl, saveCloudSession,
} from './ollabridgeCloud'
import { isRoutedTo, type ChatSelection } from './chatRoute'
import { useReconnect, type ConnStatus } from './useReconnect'
import { deactivateSource, rememberCatalog, sourceKey, type ShelfRole } from '../../lib/modelShelf'
import { checkKey, useVisionChecks, visionStatus, type VisionVerdict } from './visionCheck'

type SyncMode = 'restore' | 'retry' | 'fetch' | 'signin'

export interface OllaBridgeCloudCardProps {
  route: ChatSelection
  onSelect: (baseUrl: string, model: string) => void
  /** `vision`: Models → Multimodal — its own model list, and every model is checked first. */
  role?: ShelfRole
  /** HomePilot backend, which runs the vision check. */
  backendUrl?: string
  backendApiKey?: string
}

export default function OllaBridgeCloudCard({ route, onSelect, role = 'chat', backendUrl, backendApiKey }: OllaBridgeCloudCardProps) {
  const vision = role === 'vision'
  const { checks, running, run } = useVisionChecks()
  const [visionNote, setVisionNote] = useState<{ model: string; verdict: VisionVerdict } | null>(null)
  const [cloudUrl, setCloudUrl] = useState(getCloudUrl)
  const [token, setToken] = useState(getCloudToken)
  const [status, setStatus] = useState<ConnStatus>(() => (getCloudToken() ? 'connecting' : 'disconnected'))
  const [devices, setDevices] = useState<CloudDevice[]>([])
  const [models, setModels] = useState<CloudModelOption[] | null>(null)
  const [fetching, setFetching] = useState(false)
  const [error, setError] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [signingIn, setSigningIn] = useState(false)

  const uid = useId()
  const titleId = `${uid}-title`
  const urlId = `${uid}-url`
  const modelId = `${uid}-model`
  const emailId = `${uid}-email`
  const passwordId = `${uid}-password`

  const seqRef = useRef(0)
  const tokenRef = useRef(token)
  tokenRef.current = token
  const urlRef = useRef(cloudUrl)
  urlRef.current = cloudUrl

  /** Verify the session against the Cloud and load devices + models. */
  const sync = useCallback(async (tok: string, url: string, mode: SyncMode) => {
    const seq = ++seqRef.current
    if (mode === 'fetch') setFetching(true)
    const inv = await fetchCloudInventory(url, tok)
    if (seq !== seqRef.current) return
    setFetching(false)
    if (inv.status === 'expired') {
      clearCloudSession()
      deactivateSource(sourceKey('openai_compat', cloudChatBaseUrl(url), role))
      setToken('')
      setDevices([])
      setModels(null)
      setStatus('disconnected')
      setError('Your OllaBridge Cloud session expired — sign in again.')
      return
    }
    if (inv.status === 'unreachable') {
      setError('Could not reach OllaBridge Cloud.')
      setStatus('lost')
      return
    }
    const verified = inv.modelsStatus < 400 || inv.devicesStatus < 400
    if (!verified) {
      const code = inv.modelsStatus
      setError(`OllaBridge Cloud answered HTTP ${code}.`)
      // 5xx: the Cloud is having trouble — keep retrying. 4xx: it refuses this session.
      setStatus(code >= 500 ? 'lost' : 'disconnected')
      return
    }
    setDevices(inv.devices)
    const options = normalizeCloudModels(inv.models, inv.devices)
    setModels(options)
    // Level 1 of the model shelf: what this account offers, for each chat's Chat settings.
    rememberCatalog(
      { title: 'OllaBridge Cloud', provider: 'openai_compat', baseUrl: cloudChatBaseUrl(url), role },
      options.map((o) => ({
        id: o.id,
        label: o.label,
        kind: o.group === 'persona' ? 'assistant' : 'model',
        group: CLOUD_GROUP_LABEL[o.group],
        available: o.available,
      })),
    )
    setStatus('connected')
    setError(inv.modelsStatus >= 400 ? `Couldn't load your models (HTTP ${inv.modelsStatus}) — try Fetch Models again.` : '')
  }, [])

  // A saved session is re-verified before it is shown as connected.
  useEffect(() => {
    const tok = tokenRef.current
    if (tok) void sync(tok, urlRef.current, 'restore')
    return () => { seqRef.current++ }
  }, [sync])

  useReconnect(status, useCallback(async () => {
    if (tokenRef.current) await sync(tokenRef.current, urlRef.current, 'retry')
  }, [sync]))

  async function signIn(e: React.FormEvent) {
    e.preventDefault()
    const url = normalizeCloudUrl(cloudUrl) || DEFAULT_CLOUD_URL
    setSigningIn(true)
    setError('')
    const res = await cloudLogin(url, email, password)
    setSigningIn(false)
    if (!res.ok) {
      setError(res.error)
      return
    }
    saveCloudSession(url, res.token)
    setCloudUrl(url)
    setToken(res.token)
    setPassword('')
    setStatus('connecting')
    await sync(res.token, url, 'signin')
  }

  function signOut() {
    seqRef.current++
    clearCloudSession()
    deactivateSource(sourceKey('openai_compat', cloudChatBaseUrl(urlRef.current), role))
    setToken('')
    setDevices([])
    setModels(null)
    setError('')
    setFetching(false)
    setStatus('disconnected')
  }

  // ── derived ──
  const connected = status === 'connected'
  const host = cloudUrl.replace(/^https?:\/\//, '')
  const chatBase = cloudChatBaseUrl(cloudUrl)
  const isActive = isRoutedTo(route, chatBase)
  const selected = isActive ? route.model : ''
  const selectedOption = models?.find((m) => m.id === selected)
  const missing = connected && isActive && !!selected && models !== null && !selectedOption
  const offline = connected && !!selectedOption && !selectedOption.available
  const onlineCount = devices.filter((d) => d.online).length

  // Multimodal: each model carries its vision-check verdict. The Cloud reports no capability
  // flags, so the check is the only evidence — it runs when a model is chosen.
  const verdictOf = (id: string) => checks[checkKey(chatBase, id)]
  const checkingId = (id: string) => !!running[checkKey(chatBase, id)]
  const labelOf = (m: CloudModelOption) => (vision ? `${m.label} — ${visionStatus({}, verdictOf(m.id), checkingId(m.id))}` : m.label)

  const options: SelectOption[] = []
  if (missing) options.push({ value: selected, label: `${displayModelId(selected)} — unavailable`, disabled: true })
  for (const m of models || []) {
    options.push({ value: m.id, label: labelOf(m), group: CLOUD_GROUP_LABEL[m.group], disabled: !m.available })
  }
  const selectable = (models || []).some((m) => m.available)

  /** Multimodal: check the model with a test image before images are sent to it. */
  const choose = async (id: string, force = false) => {
    if (!vision || force) {
      setVisionNote(null)
      onSelect(chatBase, id)
      return
    }
    const known = verdictOf(id)
    const verdict = known?.sees ? known : await run({ backendUrl, backendApiKey, baseUrl: chatBase, model: id, apiKey: tokenRef.current || undefined })
    if (verdict.sees) {
      setVisionNote(null)
      onSelect(chatBase, id)
    } else {
      setVisionNote({ model: id, verdict })
    }
  }

  const placeholder = !connected
    ? 'Connect first to load models'
    : models === null
      ? 'Loading models…'
      : !selectable
        ? 'No models available'
        : 'Select a model'

  const menuItems: MenuItem[] = [
    ...(token
      ? [{ id: 'devices', label: devices.length ? 'Manage machines' : 'Pair a machine', icon: <Cpu size={13} aria-hidden />, href: `${cloudUrl}/link` }]
      : []),
    { id: 'open', label: 'Open OllaBridge Cloud', icon: <ExternalLink size={13} aria-hidden />, href: cloudUrl },
    ...(token
      ? [{ id: 'signout', label: 'Sign out', icon: <LogOut size={13} aria-hidden />, onSelect: signOut, danger: true }]
      : []),
  ]

  return (
    <CardShell
      tone="cloud"
      labelledBy={titleId}
      icon={<Cloud size={20} />}
      title="OllaBridge Cloud"
      status={status}
      subtitle="Connect to your OllaBridge Cloud account and synced machines."
      menu={<OverflowMenu label="OllaBridge Cloud connection" items={menuItems} />}
    >
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex-[1_1_18rem] min-w-0">
          <label htmlFor={urlId} className={FIELD_LABEL}>Base URL</label>
          <input
            id={urlId}
            type="text"
            inputMode="url"
            spellCheck={false}
            autoComplete="off"
            value={cloudUrl}
            readOnly={status !== 'disconnected'}
            title={status !== 'disconnected' ? 'Sign out to change the Cloud URL' : undefined}
            onChange={(e) => setCloudUrl(e.target.value)}
            onBlur={() => setCloudUrl((u) => normalizeCloudUrl(u) || DEFAULT_CLOUD_URL)}
            placeholder={DEFAULT_CLOUD_URL}
            className={`${INPUT} read-only:text-white/70 read-only:cursor-default`}
          />
        </div>
        <div className="flex-[1_1_16rem] min-w-0">
          <label htmlFor={modelId} className={FIELD_LABEL}>Model</label>
          <ModelSelect
            id={modelId}
            value={selected}
            options={options}
            disabled={!connected || !selectable}
            placeholder={placeholder}
            onChange={(v) => { if (v) void choose(v) }}
          />
        </div>
        <div className="flex-[1_1_100%] sm:flex-none">
          <FetchButton
            disabled={!connected}
            busy={fetching}
            onClick={() => { if (token) void sync(token, cloudUrl, 'fetch') }}
          />
        </div>
      </div>

      {status === 'lost' ? (
        <WarnLine
          action={
            <button type="button" onClick={() => { if (token) void sync(token, cloudUrl, 'retry') }} className="text-amber-100 underline underline-offset-2 hover:text-white">
              Retry now
            </button>
          }
        >
          {error || 'Lost contact with OllaBridge Cloud.'} Retrying automatically…
        </WarnLine>
      ) : error ? (
        <ErrorLine>{error}</ErrorLine>
      ) : null}

      {status === 'connecting' && token && <InfoLine>Checking your saved OllaBridge Cloud session…</InfoLine>}

      {status === 'disconnected' && (
        <form onSubmit={signIn} className="mt-3 grid gap-2.5 sm:grid-cols-[1fr_1fr_auto]" aria-label="Sign in to OllaBridge Cloud">
          <label htmlFor={emailId} className="sr-only">OllaBridge email</label>
          <input
            id={emailId}
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="OllaBridge email"
            autoComplete="email"
            className={INPUT}
          />
          <label htmlFor={passwordId} className="sr-only">Password</label>
          <input
            id={passwordId}
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Password"
            autoComplete="current-password"
            className={INPUT}
          />
          <button
            type="submit"
            disabled={signingIn}
            aria-busy={signingIn || undefined}
            className="h-11 px-4 rounded-xl bg-gradient-to-r from-cyan-500 to-violet-500 text-white text-sm font-bold inline-flex items-center justify-center gap-2 disabled:opacity-60 disabled:cursor-wait focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/60"
          >
            {signingIn && <Loader2 size={15} className="animate-spin" aria-hidden />}
            {signingIn ? 'Connecting…' : 'Connect Cloud'}
          </button>
          <p className="sm:col-span-3 text-[11px] text-white/35">
            Sign in with your OllaBridge account to sync models from your linked HomePilot machines.
            Your token stays in this browser only.
          </p>
        </form>
      )}

      {missing && (
        <WarnLine>
          “{displayModelId(selected)}” is no longer offered by OllaBridge Cloud. Choose another model — chat stays on it until you do.
        </WarnLine>
      )}
      {offline && (
        <WarnLine>
          “{displayModelId(selected)}” is on a machine that is offline right now. Turn it on, or choose another model.
        </WarnLine>
      )}

      {vision && visionNote && (
        <WarnLine
          action={
            <button
              type="button"
              onClick={() => void choose(visionNote.model, true)}
              className="text-amber-100 underline underline-offset-2 hover:text-white"
            >
              Use anyway
            </button>
          }
        >
          “{displayModelId(visionNote.model)}” did not pass the image check — {visionNote.verdict.reason || 'it did not describe the test image.'}
        </WarnLine>
      )}

      {vision && connected && Object.keys(running).some((k) => k.startsWith(`${chatBase.toLowerCase().replace(/\/+$/, '')}|`)) && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-white/55" role="status">
          <Loader2 size={13} className="animate-spin" aria-hidden /> Checking with a test image…
        </p>
      )}

      {connected && selectedOption?.available && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-emerald-300/90">
          <CheckCircle2 size={13} aria-hidden />
          {vision
            ? <>Images are read by {selectedOption.label} through OllaBridge Cloud.</>
            : <>Chat uses {selectedOption.label} through OllaBridge Cloud.</>}
        </p>
      )}

      {connected && (
        devices.length === 0 ? (
          <InfoLine>
            No machines paired yet. Pair a PC at{' '}
            <a href={`${cloudUrl}/link`} target="_blank" rel="noopener noreferrer" className="text-violet-300 hover:text-white underline underline-offset-2">
              {host}/link
            </a>{' '}— its models appear here automatically.
          </InfoLine>
        ) : (
          <p className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-white/45">
            <span className="inline-flex items-center gap-1.5">
              <Cpu size={12} aria-hidden /> {devices.length} machine{devices.length === 1 ? '' : 's'} · {onlineCount} online
            </span>
            {devices.slice(0, 4).map((d) => (
              <span key={d.id} className="inline-flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 rounded-full ${d.online ? 'bg-emerald-400' : 'bg-white/25'}`} aria-hidden />
                {d.name}{d.gpu_name ? ` · ${d.gpu_name}` : ''}
                <span className="sr-only">{d.online ? '(online)' : '(offline)'}</span>
              </span>
            ))}
          </p>
        )
      )}
    </CardShell>
  )
}
