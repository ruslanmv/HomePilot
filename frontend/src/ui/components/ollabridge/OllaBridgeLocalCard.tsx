/**
 * OllaBridge Local card (Model Management → Chat → OllaBridge).
 *
 * Connects the browser to the user's own OllaBridge gateway (default
 * http://localhost:11435), lists its models and routes chat to the one picked:
 * provider=openai_compat, base_url=<gateway>/v1. No Cloud sign-in involved.
 * The connection is remembered (URL + "connected") and re-verified on load,
 * when the tab regains focus, and with backoff while the gateway is down.
 */
import React, { useCallback, useEffect, useId, useRef, useState } from 'react'
import { CheckCircle2, ExternalLink, KeyRound, Link2, Loader2, Monitor, PlugZap, RefreshCw, Unplug } from 'lucide-react'
import {
  CardShell, ErrorLine, FetchButton, FIELD_LABEL, INPUT, InfoLine, ModelSelect, OUTLINE_BUTTON, OverflowMenu,
  WarnLine, type MenuItem, type SelectOption,
} from './cardParts'
import { displayModelId, suggestedByGateway, type GatewayModel } from './models'
import {
  deactivateSource, isSuggested, rememberCatalog, shownModels, sourceKey, useModelShelf,
  type ShelfModel, type ShelfRole,
} from '../../lib/modelShelf'
import ModelShelfPicker from '../ModelShelfPicker'
import { checkKey, useVisionChecks, visionStatus, visionSuggest, type VisionVerdict } from './visionCheck'
import {
  clearLocalConnected, connectLocalGateway, DEFAULT_LOCAL_GATEWAY, fetchLocalModels, forgetLocalApiKey,
  loadLocalSettings, localChatBaseUrl, normalizeGatewayRoot, saveLocalConnection,
  type LocalError, type LocalErrorKind, type LocalFallback, type LocalVia,
} from './ollabridgeLocal'
import { isRoutedTo, type ChatSelection } from './chatRoute'
import { useReconnect, type ConnStatus } from './useReconnect'

/** Failures worth retrying on their own: the gateway may simply be starting or restarting. */
const RETRYABLE = new Set<LocalErrorKind>(['unreachable', 'timeout', 'http'])

const SHELF_TITLE = 'OllaBridge Local'

function toShelf(m: GatewayModel): ShelfModel {
  return { id: m.id, label: m.label, kind: m.kind, group: m.origin, hidden: m.hidden, available: m.available, vision: m.vision }
}

/** Level 1 of the model shelf: what this gateway offers, recorded for Chat settings to use. */
function remember(root: string, models: GatewayModel[], role: ShelfRole): void {
  rememberCatalog(
    { title: SHELF_TITLE, provider: 'openai_compat', baseUrl: localChatBaseUrl(root), role },
    models.map(toShelf),
  )
}

type ConnectMode = 'manual' | 'restore' | 'retry'

export interface OllaBridgeLocalCardProps {
  route: ChatSelection
  onSelect: (baseUrl: string, model: string) => void
  /** HomePilot backend — used only as a same-machine fallback when CORS blocks the browser. */
  backendUrl?: string
  backendApiKey?: string
  /** `vision`: Models → Multimodal — its own model list, and every model is checked first. */
  role?: ShelfRole
}

export default function OllaBridgeLocalCard({ route, onSelect, backendUrl, backendApiKey, role = 'chat' }: OllaBridgeLocalCardProps) {
  const vision = role === 'vision'
  const { checks, running, run } = useVisionChecks()
  const [visionNote, setVisionNote] = useState<{ model: string; verdict: VisionVerdict } | null>(null)
  const [initial] = useState(loadLocalSettings)
  const [draftUrl, setDraftUrl] = useState(initial.url)
  const [apiKey, setApiKey] = useState(initial.apiKey)
  const [showKey, setShowKey] = useState(Boolean(initial.apiKey))
  const [status, setStatus] = useState<ConnStatus>(initial.connected ? 'connecting' : 'disconnected')
  // The gateway we are connected to — or, while restoring / lost, the one we remember.
  const [root, setRoot] = useState<string | null>(initial.connected ? initial.url : null)
  const [via, setVia] = useState<LocalVia>('browser')
  const [models, setModels] = useState<GatewayModel[] | null>(null)
  const [switching, setSwitching] = useState(false)
  const [fetching, setFetching] = useState(false)
  const [error, setError] = useState<LocalError | null>(null)
  const [choosing, setChoosing] = useState(false)
  const shelf = useModelShelf()

  const uid = useId()
  const titleId = `${uid}-title`
  const urlId = `${uid}-url`
  const modelId = `${uid}-model`
  const keyId = `${uid}-key`

  // Latest values for async callbacks (connect is triggered by timers and focus).
  const seqRef = useRef(0)
  const statusRef = useRef(status)
  statusRef.current = status
  const rootRef = useRef(root)
  rootRef.current = root
  const apiKeyRef = useRef(apiKey)
  apiKeyRef.current = apiKey
  const fallbackRef = useRef<LocalFallback>({ backendUrl, backendApiKey })
  fallbackRef.current = { backendUrl, backendApiKey }

  const connect = useCallback(async (rootInput: string, mode: ConnectMode) => {
    const target = normalizeGatewayRoot(rootInput)
    const seq = ++seqRef.current
    const wasConnected = statusRef.current === 'connected' && !!rootRef.current
    const isSwitch = wasConnected && target !== rootRef.current
    if (mode === 'manual') {
      setError(null)
      if (isSwitch) setSwitching(true)
      else setStatus('connecting')
    }
    const key = apiKeyRef.current
    const res = await connectLocalGateway(target, key, fallbackRef.current)
    if (seq !== seqRef.current) return // superseded (disconnect, newer connect)
    setSwitching(false)
    if (res.ok) {
      setRoot(target)
      if (mode === 'manual') setDraftUrl(target)
      setVia(res.via)
      setModels(res.models)
      remember(target, res.models, role)
      setError(null)
      setStatus('connected')
      saveLocalConnection(target, key)
      return
    }
    setError(res.error)
    if (res.error.kind === 'auth') setShowKey(true)
    // A failed switch keeps the working connection; the error says what went wrong.
    if (isSwitch) return
    // A remembered connection that dropped keeps retrying (useReconnect).
    if ((mode !== 'manual' || wasConnected) && RETRYABLE.has(res.error.kind)) {
      setStatus('lost')
      return
    }
    setStatus('disconnected')
    setRoot(null)
    setModels(null)
  }, [])

  // Re-verify a remembered connection on load.
  useEffect(() => {
    if (initial.connected) void connect(initial.url, 'restore')
    return () => { seqRef.current++ }
  }, [connect, initial])

  useReconnect(status, useCallback(async () => {
    if (rootRef.current) await connect(rootRef.current, 'retry')
  }, [connect]))

  const disconnect = () => {
    seqRef.current++
    clearLocalConnected()
    if (rootRef.current) deactivateSource(sourceKey('openai_compat', localChatBaseUrl(rootRef.current), role))
    setStatus('disconnected')
    setRoot(null)
    setModels(null)
    setError(null)
    setSwitching(false)
    setFetching(false)
  }

  const fetchModels = async () => {
    if (!root || status !== 'connected') return
    const seq = ++seqRef.current
    setFetching(true)
    setError(null)
    const res = await fetchLocalModels(root, apiKey, via, fallbackRef.current)
    if (seq !== seqRef.current) return
    setFetching(false)
    if (res.ok) {
      setModels(res.models)
      remember(root, res.models, role)
      saveLocalConnection(root, apiKey)
      return
    }
    setError(res.error)
    if (res.error.kind === 'auth') setShowKey(true)
    if (RETRYABLE.has(res.error.kind)) setStatus('lost')
  }

  // ── derived ──
  const connected = status === 'connected'
  const draftRoot = normalizeGatewayRoot(draftUrl)
  const gatewayRoot = root || draftRoot || DEFAULT_LOCAL_GATEWAY
  const chatBase = localChatBaseUrl(gatewayRoot)
  const isActive = isRoutedTo(route, chatBase)
  const selected = isActive ? route.model : ''
  const selectedModel = models?.find((m) => m.id === selected)
  const unavailable = connected && isActive && !!selected && models !== null && !selectedModel
  const showConnect = !connected || draftRoot !== root
  const connectBusy = status === 'connecting' || switching
  // The models offered: the user's choice for this gateway (Choose models), else the gateway's
  // own suggestion — for Multimodal, further narrowed by the vision check. The full catalog
  // stays one click away.
  const verdictOf = (id: string) => checks[checkKey(chatBase, id)]
  const checkingId = (id: string) => !!running[checkKey(chatBase, id)]
  const suggest = vision ? visionSuggest(verdictOf) : isSuggested
  const shelfSource = shelf[sourceKey('openai_compat', chatBase, role)]
  const offeredIds = new Set(
    shelfSource
      ? shownModels(shelfSource, suggest).map((m) => m.id)
      : (models || []).filter(vision ? (m) => suggestedByGateway(m) && suggest(toShelf(m)) : suggestedByGateway).map((m) => m.id),
  )
  const offered = (models || []).filter((m) => offeredIds.has(m.id))
  const multiOrigin = new Set(offered.map((m) => m.origin)).size > 1
  const labelOf = (m: GatewayModel) => (vision ? `${m.label} — ${visionStatus(m, verdictOf(m.id), checkingId(m.id))}` : m.label)

  const options: SelectOption[] = []
  if (unavailable) options.push({ value: selected, label: `${displayModelId(selected)} — unavailable`, disabled: true })
  // The current choice stays visible even when it is not on the list any more.
  if (selectedModel && !offeredIds.has(selectedModel.id)) options.push({ value: selectedModel.id, label: labelOf(selectedModel) })
  for (const m of offered) options.push({ value: m.id, label: labelOf(m), group: multiOrigin ? m.origin : undefined })

  /**
   * Multimodal: a model is checked before images go to it. A pass routes it; a failure says why
   * and offers "Use anyway" for a model the person knows better than the check does.
   */
  const choose = async (id: string, force = false) => {
    if (!vision || force) {
      setVisionNote(null)
      onSelect(chatBase, id)
      return
    }
    const known = verdictOf(id)
    const verdict = known?.sees ? known : await run({ backendUrl, backendApiKey, baseUrl: chatBase, model: id, apiKey: apiKeyRef.current || undefined })
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
      : models.length === 0
        ? 'No models available'
        : offered.length === 0
          ? 'No models chosen — Choose models'
          : 'Select a model'

  const menuItems: MenuItem[] = connected
    ? [
        { id: 'reconnect', label: 'Reconnect', icon: <RefreshCw size={13} aria-hidden />, onSelect: () => void connect(gatewayRoot, 'manual') },
        { id: 'key', label: showKey ? 'Hide API key' : 'API key…', icon: <KeyRound size={13} aria-hidden />, onSelect: () => setShowKey((s) => !s) },
        { id: 'dashboard', label: 'Open dashboard', icon: <ExternalLink size={13} aria-hidden />, href: `${gatewayRoot}/ui` },
        { id: 'disconnect', label: 'Disconnect', icon: <Unplug size={13} aria-hidden />, onSelect: disconnect, danger: true },
      ]
    : [
        { id: 'connect', label: status === 'lost' ? 'Reconnect now' : 'Connect', icon: <PlugZap size={13} aria-hidden />, onSelect: () => void connect(draftUrl, 'manual') },
        { id: 'key', label: showKey ? 'Hide API key' : 'API key…', icon: <KeyRound size={13} aria-hidden />, onSelect: () => setShowKey((s) => !s) },
        { id: 'dashboard', label: 'Open dashboard', icon: <ExternalLink size={13} aria-hidden />, href: `${gatewayRoot}/ui` },
        ...(status === 'lost' || root
          ? [{ id: 'disconnect', label: 'Disconnect', icon: <Unplug size={13} aria-hidden />, onSelect: disconnect, danger: true }]
          : []),
      ]

  return (
    <CardShell
      tone="local"
      labelledBy={titleId}
      icon={<Monitor size={20} />}
      title="OllaBridge Local"
      status={status}
      subtitle="Connect to your local OllaBridge gateway running on your machine."
      menu={<OverflowMenu label="OllaBridge Local connection" items={menuItems} />}
    >
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => { e.preventDefault(); if (showConnect && !connectBusy) void connect(draftUrl, 'manual') }}
      >
        <div className="flex-[1_1_18rem] min-w-0">
          <label htmlFor={urlId} className={FIELD_LABEL}>Gateway URL</label>
          <div className="flex gap-2">
            <input
              id={urlId}
              type="text"
              inputMode="url"
              spellCheck={false}
              autoComplete="off"
              value={draftUrl}
              onChange={(e) => setDraftUrl(e.target.value)}
              placeholder={DEFAULT_LOCAL_GATEWAY}
              className={`${INPUT} flex-1 min-w-0`}
            />
            {showConnect && (
              <button type="submit" disabled={connectBusy} aria-busy={connectBusy || undefined} className={`${OUTLINE_BUTTON} shrink-0`}>
                {connectBusy ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Link2 size={15} aria-hidden />}
                {connectBusy ? 'Connecting…' : 'Connect Local'}
              </button>
            )}
          </div>
        </div>
        <div className="flex-[1_1_16rem] min-w-0">
          <label htmlFor={modelId} className={FIELD_LABEL}>Model</label>
          <ModelSelect
            id={modelId}
            value={selected}
            options={options}
            disabled={!connected || (models?.length ?? 0) === 0}
            placeholder={placeholder}
            onChange={(v) => { if (v) void choose(v) }}
          />
          {connected && models !== null && models.length > 0 && (
            <p className="mt-1.5 text-[11px] text-white/45">
              Showing {offered.length} of {models.length}
              {' · '}
              <button
                type="button"
                onClick={() => setChoosing((v) => !v)}
                aria-expanded={choosing}
                className="text-cyan-300 underline-offset-2 hover:text-white hover:underline"
              >
                Choose models
              </button>
            </p>
          )}
        </div>
        <div className="flex-[1_1_100%] sm:flex-none">
          <FetchButton disabled={!connected} busy={fetching} onClick={() => void fetchModels()} />
        </div>
      </form>

      {choosing && connected && shelfSource && (
        <ModelShelfPicker
          source={shelfSource}
          onClose={() => setChoosing(false)}
          suggest={suggest}
          {...(vision ? {
            title: 'Models offered for images',
            hint: 'Each model is checked with a test image when you add it.',
            statusOf: (m: ShelfModel) => visionStatus(m, verdictOf(m.id), checkingId(m.id)),
            // A newly ticked model is checked straight away, so nothing unverified is offered.
            onAdded: (m: ShelfModel) => {
              if (!verdictOf(m.id)) void run({ backendUrl, backendApiKey, baseUrl: chatBase, model: m.id, apiKey: apiKeyRef.current || undefined })
            },
          } : {})}
        />
      )}

      {showKey && (
        <div className="mt-3 max-w-md">
          <label htmlFor={keyId} className={FIELD_LABEL}>API key (optional)</label>
          <div className="flex gap-2">
            <input
              id={keyId}
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Only if the gateway requires one"
              className={`${INPUT} flex-1 min-w-0`}
            />
            {apiKey && (
              <button
                type="button"
                onClick={() => { setApiKey(''); forgetLocalApiKey() }}
                className="h-11 px-3 rounded-xl border border-white/10 bg-white/[0.03] text-xs text-white/60 hover:text-white hover:bg-white/[0.06]"
              >
                Clear
              </button>
            )}
          </div>
          <p className="mt-1.5 text-[11px] text-white/35">
            Needed only when the gateway’s auth mode is “required”. Sent only to this gateway, never to OllaBridge Cloud.
          </p>
        </div>
      )}

      {status === 'lost' ? (
        <WarnLine
          action={
            <button type="button" onClick={() => void connect(gatewayRoot, 'retry')} className="text-amber-100 underline underline-offset-2 hover:text-white">
              Retry now
            </button>
          }
        >
          {error?.message || `Lost contact with the gateway at ${gatewayRoot}.`} Retrying automatically…
        </WarnLine>
      ) : error ? (
        <ErrorLine>{error.message}</ErrorLine>
      ) : null}

      {connected && via === 'server' && (
        <InfoLine>
          Listed through HomePilot’s server because the gateway’s CORS settings block this page — chat requests go
          through the server too. Add this page’s origin to <span className="font-mono text-white/60">CORS_ORIGINS</span> in
          OllaBridge’s .env to connect directly and see where each model comes from.
        </InfoLine>
      )}

      {connected && models !== null && models.length === 0 && (
        <InfoLine>
          The gateway is running but has no models — add a backend in its{' '}
          <a href={`${gatewayRoot}/ui`} target="_blank" rel="noopener noreferrer" className="text-cyan-300 hover:text-white underline underline-offset-2">dashboard</a>,
          then press Fetch Models.
        </InfoLine>
      )}

      {unavailable && (
        <WarnLine>
          “{displayModelId(selected)}” is no longer offered by this gateway. Choose another model — chat stays on it until you do.
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

      {connected && selectedModel && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-emerald-300/90">
          <CheckCircle2 size={13} aria-hidden />
          {vision
            ? <>Images are read by {selectedModel.label} through this gateway.</>
            : <>Chat uses {selectedModel.label} through this gateway.</>}
        </p>
      )}

      {status === 'disconnected' && !error && (
        <InfoLine>
          Connect to your local OllaBridge gateway to discover available models.
          {isActive && selected ? ` Chat is still set to ${displayModelId(selected)} on this gateway.` : ''}
        </InfoLine>
      )}
    </CardShell>
  )
}
