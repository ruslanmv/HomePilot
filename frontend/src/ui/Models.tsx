import React, { useEffect, useMemo, useState } from 'react'
import { Download, RefreshCw, Copy, CheckCircle2, AlertTriangle, XCircle, Settings2 } from 'lucide-react'

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

type Provider = {
  name: string
  label: string
  kind?: 'chat' | 'image' | 'video' | 'multi'
}

type ModelCatalogEntry = {
  id: string
  label?: string
  recommended?: boolean
  // Optional install metadata (future backend support)
  install?: {
    type: 'ollama_pull' | 'http_files' | 'script'
    hint?: string
    files?: Array<{ url: string; dest: string; sha256?: string }>
  }
}

type ModelCatalogResponse = {
  providers?: Record<string, Record<string, ModelCatalogEntry[]>> // providers[providerName][modelType] = list
}

type ModelsListResponse = {
  provider: string
  model_type?: string
  base_url?: string
  models: string[]
  error?: string | null
}

type InstallRequest = {
  provider: string
  model_type: string
  model_id: string
  base_url?: string
  options?: Record<string, any>
}

type InstallResponse = {
  ok?: boolean
  job_id?: string
  message?: string
}

export type ModelsParams = {
  backendUrl: string
  apiKey?: string

  // Defaults from Enterprise Settings
  providerChat?: string
  providerImages?: string
  providerVideo?: string

  baseUrlChat?: string
  baseUrlImages?: string
  baseUrlVideo?: string

  // Experimental features
  experimentalCivitai?: boolean
}

// -----------------------------------------------------------------------------
// Fallback Model Catalogs (when backend /model-catalog is not available)
// -----------------------------------------------------------------------------

const FALLBACK_CATALOGS: Record<string, Record<string, ModelCatalogEntry[]>> = {
  ollama: {
    chat: [
      { id: 'llama3:8b', label: 'Llama 3 8B', recommended: true },
      { id: 'llama3:70b', label: 'Llama 3 70B' },
      { id: 'llama3.1:8b', label: 'Llama 3.1 8B' },
      { id: 'llama3.1:70b', label: 'Llama 3.1 70B' },
      { id: 'mistral:7b', label: 'Mistral 7B' },
      { id: 'mixtral:8x7b', label: 'Mixtral 8x7B' },
      { id: 'qwen2.5:7b', label: 'Qwen 2.5 7B' },
      { id: 'phi3:3.8b', label: 'Phi-3 3.8B' },
      { id: 'gemma2:9b', label: 'Gemma 2 9B' },
    ],
  },
  comfyui: {
    image: [
      { id: 'sd_xl_base_1.0.safetensors', label: 'SDXL Base 1.0 (7GB)', recommended: true },
      { id: 'flux1-schnell.safetensors', label: 'Flux.1 Schnell (23GB)' },
      { id: 'flux1-dev.safetensors', label: 'Flux.1 Dev (23GB)' },
      { id: 'ponyDiffusionV6XL.safetensors', label: 'Pony Diffusion v6 XL (7GB)' },
      { id: 'sd15.safetensors', label: 'Stable Diffusion 1.5 (4GB)' },
      { id: 'realisticVisionV51.safetensors', label: 'Realistic Vision v5.1 (2GB)' },
    ],
    video: [
      { id: 'svd_xt_1_1.safetensors', label: 'Stable Video Diffusion XT 1.1 (10GB)', recommended: true },
      { id: 'svd_xt.safetensors', label: 'Stable Video Diffusion XT (10GB)' },
      { id: 'svd.safetensors', label: 'Stable Video Diffusion (10GB)' },
    ],
  },
  openai_compat: {
    chat: [
      { id: 'local-model', label: 'Local Model (auto-detect)', recommended: true },
    ],
  },
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

function cleanBase(url: string) {
  return (url || '').trim().replace(/\/+$/, '')
}

async function getJson<T>(baseUrl: string, path: string, apiKey?: string): Promise<T> {
  const url = `${cleanBase(baseUrl)}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    method: 'GET',
    headers: {
      ...(apiKey ? { 'x-api-key': apiKey } : {}),
    },
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  return (await res.json()) as T
}

async function postJson<T>(baseUrl: string, path: string, body: any, apiKey?: string): Promise<T> {
  const url = `${cleanBase(baseUrl)}${path.startsWith('/') ? path : `/${path}`}`
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(apiKey ? { 'x-api-key': apiKey } : {}),
    },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status} ${res.statusText}${text ? `: ${text}` : ''}`)
  }
  return (await res.json()) as T
}

function chipClass(kind: 'ok' | 'warn' | 'bad' | 'muted') {
  switch (kind) {
    case 'ok':
      return 'bg-emerald-500/10 text-emerald-200 border-emerald-500/20'
    case 'warn':
      return 'bg-amber-500/10 text-amber-200 border-amber-500/20'
    case 'bad':
      return 'bg-rose-500/10 text-rose-200 border-rose-500/20'
    default:
      return 'bg-white/5 text-white/60 border-white/10'
  }
}

function IconStatus({ kind }: { kind: 'ok' | 'warn' | 'bad' | 'muted' }) {
  if (kind === 'ok') return <CheckCircle2 size={14} className="text-emerald-300" />
  if (kind === 'warn') return <AlertTriangle size={14} className="text-amber-300" />
  if (kind === 'bad') return <XCircle size={14} className="text-rose-300" />
  return <Settings2 size={14} className="text-white/50" />
}

function safeLabel(id: string, label?: string) {
  return label?.trim() ? label.trim() : id
}

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

export default function ModelsView(props: ModelsParams) {
  const authKey = (props.apiKey || '').trim()
  const backendUrl = cleanBase(props.backendUrl)

  const [providers, setProviders] = useState<Provider[]>([])
  const [providersError, setProvidersError] = useState<string | null>(null)

  const [modelType, setModelType] = useState<'chat' | 'image' | 'video'>('chat')
  const [provider, setProvider] = useState<string>(props.providerChat || 'ollama')

  const defaultBaseUrl = useMemo(() => {
    if (modelType === 'chat') return props.baseUrlChat || ''
    if (modelType === 'image') return props.baseUrlImages || ''
    return props.baseUrlVideo || ''
  }, [modelType, props.baseUrlChat, props.baseUrlImages, props.baseUrlVideo])

  const [baseUrl, setBaseUrl] = useState<string>(defaultBaseUrl)

  // Installed models (dynamic)
  const [installed, setInstalled] = useState<string[]>([])
  const [installedError, setInstalledError] = useState<string | null>(null)
  const [installedLoading, setInstalledLoading] = useState(false)

  // Supported models (curated) — optional endpoint
  const [catalog, setCatalog] = useState<ModelCatalogResponse | null>(null)
  const [catalogError, setCatalogError] = useState<string | null>(null)
  const [catalogLoading, setCatalogLoading] = useState(false)

  // Install jobs — optional endpoint (we degrade if not present)
  const [installBusy, setInstallBusy] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  // Civitai-specific state
  const [civitaiVersionId, setCivitaiVersionId] = useState<string>('')

  // Filter providers based on model type
  const availableProviders = useMemo(() => {
    if (modelType === 'chat') {
      // For chat: all providers EXCEPT comfyui and civitai
      return providers.filter(p => p.name !== 'comfyui' && p.name !== 'civitai')
    } else {
      // For image/video: comfyui + civitai (if experimental enabled)
      const filtered = providers.filter(p => p.name === 'comfyui')

      // Add Civitai if experimental enabled
      if (props.experimentalCivitai) {
        filtered.push({
          name: 'civitai',
          label: '🧪 Civitai (Experimental)',
          kind: modelType as any,
        })
      }

      return filtered
    }
  }, [providers, modelType, props.experimentalCivitai])

  useEffect(() => {
    // When modelType changes, update provider + baseUrl defaults
    if (modelType === 'chat') {
      // Switch to a chat provider (prefer the one from settings, or default to ollama)
      const newProvider = props.providerChat || 'ollama'
      setProvider(newProvider)
      setBaseUrl(props.baseUrlChat || '')
    } else if (modelType === 'image') {
      // Switch to comfyui for images
      setProvider('comfyui')
      setBaseUrl(props.baseUrlImages || '')
    } else {
      // Switch to comfyui for videos
      setProvider('comfyui')
      setBaseUrl(props.baseUrlVideo || '')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modelType])

  // Load providers list from backend
  useEffect(() => {
    let mounted = true
    setProvidersError(null)

    ;(async () => {
      try {
        const res = await getJson<{ ok: boolean; providers: Record<string, any> }>(backendUrl, '/providers', authKey)
        if (!mounted) return
        const providerList: Provider[] = Object.entries(res.providers || {}).map(([name, info]: [string, any]) => ({
          name,
          label: info.label || name,
          kind: 'multi',
        }))
        setProviders(providerList)
      } catch (e: any) {
        if (!mounted) return
        setProviders([])
        setProvidersError(e?.message || String(e))
      }
    })()

    return () => {
      mounted = false
    }
  }, [backendUrl, authKey])

  // Load supported catalog (optional)
  const refreshCatalog = async () => {
    setCatalogLoading(true)
    setCatalogError(null)
    try {
      const data = await getJson<ModelCatalogResponse>(backendUrl, '/model-catalog', authKey)
      setCatalog(data)
    } catch (e: any) {
      // Degrade gracefully if endpoint doesn't exist
      setCatalog(null)
      setCatalogError(e?.message || String(e))
    } finally {
      setCatalogLoading(false)
    }
  }

  // Load installed models (only for local providers)
  const refreshInstalled = async () => {
    // Skip fetching installed models for remote API providers and Civitai
    // Remote providers: they're cloud services, not local installations
    // Civitai: download-only provider, models get installed to ComfyUI after download
    const skipProviders = ['openai', 'claude', 'watsonx', 'civitai']

    if (skipProviders.includes(provider)) {
      setInstalled([])
      setInstalledError(null)
      setInstalledLoading(false)
      return
    }

    setInstalledLoading(true)
    setInstalledError(null)
    try {
      const q = new URLSearchParams()
      q.set('provider', provider)
      if (baseUrl.trim()) q.set('base_url', baseUrl.trim())

      const data = await getJson<ModelsListResponse>(backendUrl, `/models?${q.toString()}`, authKey)
      setInstalled(Array.isArray(data.models) ? data.models : [])
      if (data.error) setInstalledError(String(data.error))
    } catch (e: any) {
      setInstalled([])
      setInstalledError(e?.message || String(e))
    } finally {
      setInstalledLoading(false)
    }
  }

  useEffect(() => {
    refreshInstalled()
    // Load catalog once initially (optional)
    if (catalog === null && catalogError === null && !catalogLoading) {
      refreshCatalog()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, modelType, baseUrl, backendUrl])

  const supportedForSelection: ModelCatalogEntry[] = useMemo(() => {
    // Try backend catalog first
    const p = catalog?.providers?.[provider]
    if (p) {
      const list = p?.[modelType] || []
      if (Array.isArray(list) && list.length > 0) return list
    }

    // Fallback to hardcoded catalogs if backend catalog not available
    const fallback = FALLBACK_CATALOGS[provider]?.[modelType]
    return Array.isArray(fallback) ? fallback : []
  }, [catalog, provider, modelType])

  const installedSet = useMemo(() => new Set(installed), [installed])

  // Merge supported + installed
  const merged = useMemo(() => {
    const supportedMap = new Map<string, ModelCatalogEntry>()
    for (const s of supportedForSelection) supportedMap.set(s.id, s)

    const rows: Array<{
      id: string
      label: string
      recommended?: boolean
      status: 'installed' | 'missing' | 'installed_unsupported'
      install?: ModelCatalogEntry['install']
    }> = []

    // Supported first
    for (const s of supportedForSelection) {
      rows.push({
        id: s.id,
        label: safeLabel(s.id, s.label),
        recommended: s.recommended,
        status: installedSet.has(s.id) ? 'installed' : 'missing',
        install: s.install,
      })
    }

    // Then show installed but not in supported catalog
    for (const m of installed) {
      if (!supportedMap.has(m)) {
        rows.push({
          id: m,
          label: m,
          status: 'installed_unsupported',
        })
      }
    }

    // Sorting: recommended → installed → missing → unsupported
    rows.sort((a, b) => {
      const ar = a.recommended ? 0 : 1
      const br = b.recommended ? 0 : 1
      if (ar !== br) return ar - br
      const order = (s: string) =>
        s === 'installed' ? 0 : s === 'missing' ? 1 : 2
      return order(a.status) - order(b.status)
    })

    return rows
  }, [supportedForSelection, installed, installedSet])

  const tryInstall = async (modelId: string, install?: ModelCatalogEntry['install']) => {
    setInstallBusy(modelId)

    try {
      const body: InstallRequest = {
        provider,
        model_type: modelType,
        model_id: modelId,
        base_url: baseUrl.trim() || undefined,
        options: {},
      }

      // Add civitai_version_id if provider is civitai
      if (provider === 'civitai') {
        if (!civitaiVersionId.trim()) {
          setToast('Please enter a Civitai version ID')
          setInstallBusy(null)
          return
        }
        (body as any).civitai_version_id = civitaiVersionId.trim()
        setToast(`Starting Civitai download for version ${civitaiVersionId}...`)
      } else {
        setToast(`Starting download for ${modelId}...`)
      }

      const res = await postJson<InstallResponse>(backendUrl, '/models/install', body, authKey)

      if (res?.ok) {
        setToast(res.message || `Successfully installed ${modelId}`)
        // Refresh installed list after successful installation
        setTimeout(() => {
          refreshInstalled()
        }, 2000)
      } else {
        setToast(res?.message || 'Installation request sent.')
      }
    } catch (e: any) {
      // Fallback to copy-paste instructions if API fails
      if (provider === 'ollama') {
        const cmd = `ollama pull ${modelId}`
        navigator.clipboard?.writeText(cmd).catch(() => {})
        setToast(`API failed. Command copied: ${cmd}`)
      } else if (provider === 'comfyui') {
        navigator.clipboard?.writeText(`Run: python scripts/download.py --model ${modelId}`).catch(() => {})
        setToast('API failed. Download command copied to clipboard.')
      } else if (provider === 'civitai') {
        setToast(`Installation failed: ${e?.message || String(e)}`)
      } else {
        setToast(`Installation failed: ${e?.message || String(e)}`)
      }
    } finally {
      setInstallBusy(null)
    }
  }

  // Auto-dismiss toast
  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(null), 3500)
    return () => clearTimeout(t)
  }, [toast])

  return (
    <div className="h-full w-full bg-black text-white overflow-hidden flex flex-col">
      {/* Header */}
      <div className="px-8 py-6 border-b border-white/10 flex items-center justify-between bg-gradient-to-b from-white/[0.02] to-transparent">
        <div>
          <div className="text-2xl font-bold text-white tracking-tight">Model Management</div>
          <div className="text-sm text-white/40 mt-1">Configure and deploy AI models across providers</div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => refreshCatalog()}
            disabled={catalogLoading}
            className="px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-semibold flex items-center gap-2.5 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw size={15} className={catalogLoading ? 'animate-spin' : ''} />
            Refresh Catalog
          </button>

          <button
            type="button"
            onClick={() => refreshInstalled()}
            disabled={installedLoading}
            className="px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-semibold flex items-center gap-2.5 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw size={15} className={installedLoading ? 'animate-spin' : ''} />
            Refresh Installed
          </button>
        </div>
      </div>

      {/* Controls */}
      <div className="px-8 py-5 border-b border-white/10 bg-white/[0.01]">
        <div className="grid grid-cols-1 lg:grid-cols-[200px_1fr_1fr] gap-4 max-w-7xl">
          <div>
            <label className="text-[10px] text-white/40 font-bold uppercase tracking-wider block mb-2.5">Model Type</label>
            <div className="flex flex-col gap-1.5">
              {(['chat', 'image', 'video'] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  onClick={() => setModelType(t)}
                  className={`px-4 py-2.5 rounded-lg border text-xs font-bold uppercase tracking-wide transition-all ${
                    modelType === t
                      ? 'bg-white text-black border-white shadow-lg shadow-white/20'
                      : 'bg-transparent border-white/10 text-white/60 hover:bg-white/5 hover:border-white/20 hover:text-white/80'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-[10px] text-white/40 font-bold uppercase tracking-wider block mb-2.5">Provider</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm font-medium outline-none focus:border-white/30 focus:bg-white/10 transition-all"
            >
              {availableProviders.length > 0 ? (
                availableProviders.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.label || p.name}
                  </option>
                ))
              ) : (
                // Fallback options when providers haven't loaded
                modelType === 'chat' ? (
                  <>
                    <option value="ollama">Ollama</option>
                    <option value="openai_compat">OpenAI-compatible (vLLM)</option>
                    <option value="openai">OpenAI</option>
                    <option value="claude">Claude</option>
                    <option value="watsonx">Watsonx</option>
                  </>
                ) : (
                  <option value="comfyui">ComfyUI</option>
                )
              )}
            </select>
            {providersError ? <div className="mt-2 text-xs text-rose-400/80">{providersError}</div> : null}
          </div>

          <div>
            <label className="text-[10px] text-white/40 font-bold uppercase tracking-wider block mb-2.5">Base URL Override</label>
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder={modelType === 'chat' ? 'http://localhost:11434' : 'http://localhost:8188'}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm font-medium outline-none focus:border-white/30 focus:bg-white/10 transition-all placeholder:text-white/30"
            />
            <div className="mt-2 text-[10px] text-white/30 font-medium">
              Optional. Leave empty to use default configuration.
            </div>
          </div>
        </div>
      </div>

      {/* Civitai Input Section (only when provider is civitai) */}
      {provider === 'civitai' && (
        <div className="px-8 py-4 border-b border-white/10 bg-gradient-to-br from-blue-500/5 to-blue-500/0">
          <div className="max-w-7xl">
            <div className="flex items-start gap-4">
              <div className="flex-1">
                <label className="text-[10px] text-blue-400 font-bold uppercase tracking-wider block mb-2.5">
                  🧪 Civitai Version ID
                </label>
                <input
                  value={civitaiVersionId}
                  onChange={(e) => setCivitaiVersionId(e.target.value)}
                  placeholder="e.g., 128713 (from Civitai model URL)"
                  className="w-full bg-white/5 border border-blue-500/20 rounded-xl px-4 py-3 text-sm font-medium outline-none focus:border-blue-500/40 focus:bg-white/10 transition-all placeholder:text-white/30"
                />
                <div className="mt-2 text-[10px] text-blue-300/60 font-medium">
                  Find the version ID in the Civitai model URL (e.g., civitai.com/models/<strong>128713</strong>)
                </div>
              </div>
              <div className="flex-shrink-0 pt-7">
                <button
                  type="button"
                  onClick={() => {
                    if (!civitaiVersionId.trim()) {
                      setToast('Please enter a Civitai version ID first')
                      return
                    }
                    tryInstall(civitaiVersionId, undefined)
                  }}
                  disabled={!civitaiVersionId.trim() || installBusy !== null}
                  className={[
                    "px-6 py-3 rounded-xl text-white text-sm font-bold uppercase tracking-wide transition-all shadow-lg relative overflow-hidden",
                    installBusy !== null
                      ? "bg-blue-700 cursor-wait shadow-blue-700/30"
                      : !civitaiVersionId.trim()
                      ? "bg-blue-600/50 cursor-not-allowed shadow-blue-600/10"
                      : "bg-blue-600 hover:bg-blue-500 shadow-blue-600/20 hover:shadow-blue-600/30 hover:scale-105 active:scale-95"
                  ].join(" ")}
                >
                  {installBusy !== null && (
                    <span className="absolute inset-0 bg-gradient-to-r from-blue-700 via-blue-600 to-blue-700 animate-shimmer" style={{
                      backgroundSize: '200% 100%',
                      animation: 'shimmer 2s infinite linear'
                    }} />
                  )}
                  <span className="relative z-10 flex items-center gap-2.5 justify-center">
                    {installBusy !== null ? (
                      <>
                        <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        <span>Downloading...</span>
                      </>
                    ) : (
                      <>
                        <Download size={16} strokeWidth={2.5} />
                        <span>Download from Civitai</span>
                      </>
                    )}
                  </span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-8 py-6 scrollbar-hide">
        <div className="flex flex-col gap-4 max-w-7xl mx-auto">
          {/* Error messages - hide for Civitai since it's download-only */}
          {installedError && provider !== 'civitai' ? (
            <div className="rounded-xl border border-amber-500/30 bg-gradient-to-br from-amber-500/10 to-amber-500/5 p-5 text-amber-200">
              <div className="font-bold text-sm text-amber-100">Configuration Required</div>
              <div className="text-xs mt-2 text-amber-200/70 font-medium">
                {installedError.includes('LLM_BASE_URL')
                  ? 'Configure LLM_BASE_URL environment variable to use OpenAI-compatible (vLLM) provider. Or switch to a different provider.'
                  : installedError}
              </div>
            </div>
          ) : null}

          {catalogError && !supportedForSelection.length ? (
            <div className="rounded-xl border border-blue-500/20 bg-gradient-to-br from-blue-500/10 to-blue-500/5 p-5 text-blue-200">
              <div className="font-bold text-sm text-blue-100">Backend catalog unavailable</div>
              <div className="mt-2 text-xs text-blue-200/70 font-medium">
                Using fallback model list. Configure <span className="font-mono bg-blue-500/20 px-1.5 py-0.5 rounded text-blue-100">/model-catalog</span> endpoint for enhanced functionality.
              </div>
            </div>
          ) : null}

          {/* Models table */}
          <div className="rounded-2xl border border-white/10 overflow-hidden bg-gradient-to-b from-white/[0.02] to-transparent">
            <div className="bg-white/5 px-6 py-4 flex items-center justify-between border-b border-white/10">
              <div className="text-xs font-bold text-white uppercase tracking-wider">Available Models</div>
              <div className="text-xs text-white/50 font-semibold">
                {(() => {
                  const isRemoteProvider = ['openai', 'claude', 'watsonx'].includes(provider)
                  if (installedLoading) return 'Loading…'
                  if (provider === 'civitai') {
                    return '🧪 Experimental: Enter version ID to download'
                  }
                  if (isRemoteProvider) {
                    return `${supportedForSelection.length} API Models`
                  }
                  return `${installed.length} Installed${supportedForSelection.length ? ` · ${supportedForSelection.length} Available` : ''}`
                })()}
              </div>
            </div>

            <div className="divide-y divide-white/5">
              {merged.length === 0 ? (
                <div className="p-12 text-white/50 text-sm text-center font-medium">
                  {provider === 'civitai' ? (
                    <div className="space-y-2">
                      <div className="text-blue-400 font-bold">🧪 Civitai Download</div>
                      <div>Enter a Civitai version ID above to download models.</div>
                      <div className="text-xs text-white/40">
                        Find models at <a href="https://civitai.com" target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:text-blue-300 underline">civitai.com</a>
                      </div>
                    </div>
                  ) : (
                    'No models found. Try changing provider/base URL and refresh.'
                  )}
                </div>
              ) : (
                merged.map((row) => {
                  const statusKind =
                    row.status === 'installed'
                      ? 'ok'
                      : row.status === 'missing'
                      ? 'warn'
                      : 'muted'

                  const statusLabel =
                    row.status === 'installed'
                      ? 'Installed'
                      : row.status === 'missing'
                      ? 'Available'
                      : 'Custom'

                  // Only allow downloads for local providers (Ollama, ComfyUI)
                  // Remote API providers (OpenAI, Claude, Watsonx, openai_compat) don't support local installation
                  const isLocalProvider = provider === 'ollama' || provider === 'comfyui'
                  const canDownload = row.status === 'missing' && isLocalProvider

                  return (
                    <div key={row.id} className="p-5 flex items-center justify-between gap-4 hover:bg-white/[0.02] transition-all group">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2.5 mb-3">
                          <div className={`px-3 py-1.5 rounded-lg border text-[10px] font-bold uppercase tracking-wider flex items-center gap-1.5 ${chipClass(statusKind)}`}>
                            <IconStatus kind={statusKind} />
                            <span>{statusLabel}</span>
                          </div>
                          {row.recommended ? (
                            <div className="px-3 py-1.5 rounded-lg border border-blue-500/30 bg-blue-500/10 text-[10px] font-bold uppercase tracking-wider text-blue-200">
                              ⭐ Recommended
                            </div>
                          ) : null}
                        </div>

                        <div className="font-bold text-base text-white truncate group-hover:text-white transition-colors">{row.label}</div>
                        <div className="text-[11px] text-white/40 font-mono truncate mt-1">{row.id}</div>
                      </div>

                      <div className="flex items-center gap-3 flex-shrink-0">
                        <button
                          type="button"
                          className="px-4 py-2.5 rounded-xl bg-white/5 hover:bg-white/10 border border-white/10 text-xs font-bold flex items-center gap-2 transition-all hover:scale-105 active:scale-95"
                          onClick={() => {
                            navigator.clipboard?.writeText(row.id).catch(() => {})
                            setToast('Model ID copied to clipboard')
                          }}
                          title="Copy model ID"
                        >
                          <Copy size={14} />
                          <span>Copy</span>
                        </button>

                        {canDownload ? (
                          <button
                            type="button"
                            className={[
                              "px-5 py-2.5 rounded-xl text-xs font-bold uppercase tracking-wide flex items-center gap-2.5 transition-all shadow-lg relative overflow-hidden",
                              installBusy === row.id
                                ? "bg-blue-600 text-white cursor-wait shadow-blue-600/30"
                                : "bg-white text-black hover:bg-gray-100 hover:shadow-white/30 hover:scale-105 active:scale-95 shadow-white/20"
                            ].join(" ")}
                            disabled={installBusy === row.id}
                            onClick={() => void tryInstall(row.id, row.install)}
                            title={installBusy === row.id ? "Downloading model... Please wait" : "Download and install model"}
                          >
                            {installBusy === row.id && (
                              <span className="absolute inset-0 bg-gradient-to-r from-blue-600 via-blue-500 to-blue-600 animate-shimmer" style={{
                                backgroundSize: '200% 100%',
                                animation: 'shimmer 2s infinite linear'
                              }} />
                            )}
                            <span className="relative z-10 flex items-center gap-2.5">
                              {installBusy === row.id ? (
                                <>
                                  <svg className="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                  </svg>
                                  <span>Downloading...</span>
                                </>
                              ) : (
                                <>
                                  <Download size={15} strokeWidth={2.5} />
                                  <span>Install</span>
                                </>
                              )}
                            </span>
                          </button>
                        ) : null}
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Toast notification */}
      {toast ? (
        <div className="fixed bottom-8 right-8 z-50 bg-gradient-to-br from-white/10 to-white/5 backdrop-blur-xl border border-white/20 rounded-2xl px-6 py-4 text-sm text-white shadow-2xl shadow-black/40 animate-in slide-in-from-bottom-4 flex items-center gap-3 min-w-[320px]">
          {toast.includes('Successfully') || toast.includes('installed') ? (
            <div className="flex-shrink-0">
              <CheckCircle2 size={18} className="text-emerald-400" />
            </div>
          ) : toast.includes('failed') || toast.includes('error') || toast.includes('Error') ? (
            <div className="flex-shrink-0">
              <XCircle size={18} className="text-red-400" />
            </div>
          ) : (
            <div className="w-2 h-2 rounded-full bg-blue-400 animate-pulse flex-shrink-0" />
          )}
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-white/90 truncate">{toast}</div>
            {installBusy && (
              <div className="text-[10px] text-white/50 mt-1 font-medium">
                Large models may take several minutes...
              </div>
            )}
          </div>
        </div>
      ) : null}

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }

        @keyframes shimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }

        .animate-shimmer {
          animation: shimmer 2s infinite linear;
        }
      `}</style>
    </div>
  )
}
