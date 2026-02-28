/**
 * RegistryDiscoverPanel — browse, install & configure public MCP servers from the Forge catalog.
 *
 * Renders the 81+ servers / 38 categories from mcp-catalog.yml inside
 * HomePilot's MCP Servers tab. Now includes:
 *  - Multi-state server cards (available → installing → needs setup → running)
 *  - Setup wizard integration for all auth types
 *  - Server details drawer
 *  - Uninstall with confirmation
 *  - Status filter (all / available / installed / needs setup)
 *  - Provider switcher: Context Forge catalog / MatrixHub catalog
 *
 * Phase 9+10+11 — fully additive, does not modify any existing component.
 */

import React, { useState } from 'react'
import {
  Search,
  Download,
  Check,
  AlertCircle,
  RefreshCw,
  Globe,
  Lock,
  Key,
  Shield,
  ChevronDown,
  Zap,
  Info,
  X as XIcon,
  CheckCircle,
  Layers,
} from 'lucide-react'
import { useForgeRegistry } from './useForgeRegistry'
import { McpSetupWizard } from './McpSetupWizard'
import { McpServerDetailsDrawer } from './McpServerDetailsDrawer'
import { McpUninstallDialog } from './McpUninstallDialog'
import { MatrixHubCatalogPanel } from './MatrixHubCatalogPanel'
import type { RegistryServer } from '../../agentic/types'
// setupInstructions helpers are used by McpSetupWizard internally

type CatalogSource = 'forge' | 'matrixhub'

type Props = {
  backendUrl: string
  apiKey?: string
  /** Optional MatrixHub URL (e.g. https://hub.agent-matrix.dev or http://localhost:8080) */
  matrixHubUrl?: string
  /** Called after a server is installed/uninstalled so the parent can refresh its catalog */
  onInstalled?: () => void
}

// ── Badge helpers ────────────────────────────────────────────────────────

function authBadge(authType: string) {
  switch (authType) {
    case 'OAuth2.1':
    case 'OAuth':
      return { icon: Lock, color: 'bg-amber-500/20 text-amber-300', label: authType }
    case 'API Key':
    case 'API':
      return { icon: Key, color: 'bg-blue-500/20 text-blue-300', label: 'API Key' }
    case 'OAuth2.1 & API Key':
      return { icon: Key, color: 'bg-violet-500/20 text-violet-300', label: 'OAuth + Key' }
    default:
      return { icon: Shield, color: 'bg-emerald-500/20 text-emerald-300', label: authType || 'Open' }
  }
}

/** Determines the visual state of a server card */
type CardState = 'available' | 'installing' | 'needs_setup' | 'running'

function getCardState(server: RegistryServer, installing: boolean): CardState {
  if (installing) return 'installing'
  if (!server.is_registered) return 'available'
  if (server.requires_oauth_config) return 'needs_setup'
  return 'running'
}

function statusDot(state: CardState) {
  switch (state) {
    case 'running':     return 'bg-emerald-400'
    case 'needs_setup': return 'bg-amber-400'
    case 'installing':  return 'bg-cyan-400 animate-pulse'
    default:            return ''
  }
}

// ── Filter dropdown ──────────────────────────────────────────────────────

function FilterDropdown({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (v: string) => void
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="appearance-none bg-white/5 border border-white/10 rounded-lg pl-3 pr-8 py-1.5 text-xs text-white/70 focus:outline-none focus:border-purple-500/50 cursor-pointer"
      >
        <option value="">{label}</option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
      <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-white/30 pointer-events-none" />
    </div>
  )
}

// ── Status filter pills ─────────────────────────────────────────────────

function StatusFilterPills({
  value,
  onChange,
  counts,
}: {
  value: string
  onChange: (v: '' | 'available' | 'installed' | 'needs_setup') => void
  counts: { total: number; installed: number; needsSetup: number }
}) {
  const pills: { key: '' | 'available' | 'installed' | 'needs_setup'; label: string; count?: number }[] = [
    { key: '', label: 'All', count: counts.total },
    { key: 'available', label: 'Available', count: counts.total - counts.installed },
    { key: 'installed', label: 'Installed', count: counts.installed },
    ...(counts.needsSetup > 0
      ? [{ key: 'needs_setup' as const, label: 'Needs Setup', count: counts.needsSetup }]
      : []),
  ]

  return (
    <div className="flex items-center gap-1">
      {pills.map((pill) => (
        <button
          key={pill.key}
          onClick={() => onChange(pill.key)}
          className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-lg transition-colors ${
            value === pill.key
              ? pill.key === 'needs_setup'
                ? 'bg-amber-500/20 text-amber-300'
                : 'bg-white/10 text-white'
              : 'text-white/40 hover:text-white/60 hover:bg-white/5'
          }`}
        >
          {pill.label}
          {pill.count !== undefined && (
            <span className={`text-[10px] px-1 py-px rounded-full ${
              value === pill.key ? 'bg-white/10' : 'bg-white/5'
            }`}>
              {pill.count}
            </span>
          )}
        </button>
      ))}
    </div>
  )
}

// ── Server card ──────────────────────────────────────────────────────────

function RegistryServerCard({
  server,
  installing,
  onInstall,
  onSetup,
  onDetails,
  onUninstall,
}: {
  server: RegistryServer
  installing: boolean
  onInstall: () => void
  onSetup: () => void
  onDetails: () => void
  onUninstall: () => void
}) {
  const auth = authBadge(server.auth_type)
  const AuthIcon = auth.icon
  const cardState = getCardState(server, installing)
  const dot = statusDot(cardState)

  return (
    <div className={`flex flex-col gap-3 p-5 rounded-2xl transition-all duration-200 border h-full ${
      cardState === 'running'
        ? 'bg-emerald-500/[0.03] border-emerald-500/20 hover:border-emerald-500/30'
        : cardState === 'needs_setup'
          ? 'bg-amber-500/[0.03] border-amber-500/15 hover:border-amber-500/25'
          : 'bg-white/5 hover:bg-white/[0.07] border-white/10 hover:border-white/20'
    }`}>
      {/* Header */}
      <div className="flex justify-between items-start gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br border border-white/10 flex items-center justify-center ${
            cardState === 'running'
              ? 'from-emerald-500/20 to-teal-500/20 text-emerald-400'
              : cardState === 'needs_setup'
                ? 'from-amber-500/20 to-orange-500/20 text-amber-400'
                : 'from-cyan-500/20 to-blue-500/20 text-cyan-400'
          }`}>
            <Globe size={18} strokeWidth={2} />
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-sm text-white truncate">{server.name}</h3>
            <span className="text-xs text-white/40">{server.provider}</span>
          </div>
        </div>
        {/* Status dot */}
        {dot && (
          <span className="flex items-center gap-1.5 shrink-0">
            <span className={`w-2 h-2 rounded-full ${dot}`} />
            <span className={`text-[11px] font-medium ${
              cardState === 'running' ? 'text-emerald-400' : cardState === 'needs_setup' ? 'text-amber-400' : 'text-cyan-400'
            }`}>
              {cardState === 'running' ? 'Active' : cardState === 'needs_setup' ? 'Setup' : 'Adding...'}
            </span>
          </span>
        )}
      </div>

      {/* Description */}
      <p className="text-sm text-white/60 leading-relaxed line-clamp-2 flex-1">
        {server.description}
      </p>

      {/* Tags row */}
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-purple-500/20 text-purple-300">
          {server.category}
        </span>
        <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium ${auth.color}`}>
          <AuthIcon size={10} />
          {auth.label}
        </span>
        {server.tags.slice(0, 2).map((tag) => (
          <span key={tag} className="text-xs px-2 py-0.5 rounded-full bg-white/5 text-white/40">
            {tag}
          </span>
        ))}
      </div>

      {/* Action buttons — different per state */}
      <div className="pt-1">
        {cardState === 'available' && (
          <button
            onClick={onInstall}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 rounded-lg transition-colors w-full justify-center"
          >
            <Download size={14} />
            Add Server
          </button>
        )}

        {cardState === 'installing' && (
          <button
            disabled
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-cyan-500/10 text-cyan-300/60 rounded-lg w-full justify-center"
          >
            <div className="w-3.5 h-3.5 border-2 border-cyan-300/30 border-t-cyan-300 rounded-full animate-spin" />
            Adding...
          </button>
        )}

        {cardState === 'needs_setup' && (
          <div className="flex items-center gap-2">
            <button
              onClick={onSetup}
              className="flex-1 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 rounded-lg transition-colors justify-center"
            >
              <Zap size={13} />
              Setup
            </button>
            <button
              onClick={onDetails}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-white/40 hover:text-white/70 bg-white/5 hover:bg-white/10 rounded-lg transition-colors"
              title="Details"
            >
              <Info size={13} />
            </button>
            <button
              onClick={onUninstall}
              className="flex items-center gap-1 px-2 py-1.5 text-xs font-medium text-red-400/50 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
              title="Uninstall"
            >
              <XIcon size={13} />
            </button>
          </div>
        )}

        {cardState === 'running' && (
          <div className="flex items-center gap-2">
            <button
              disabled
              className="flex-1 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-emerald-500/10 text-emerald-400 rounded-lg cursor-default justify-center"
            >
              <CheckCircle size={13} />
              Running
            </button>
            <button
              onClick={onDetails}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-white/40 hover:text-white/70 bg-white/5 hover:bg-white/10 rounded-lg transition-colors"
              title="Details"
            >
              <Info size={13} />
            </button>
            <button
              onClick={onUninstall}
              className="flex items-center gap-1 px-2 py-1.5 text-xs font-medium text-red-400/50 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors"
              title="Uninstall"
            >
              <XIcon size={13} />
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Catalog source switcher ──────────────────────────────────────────────

function CatalogSourceSwitcher({
  value,
  onChange,
  matrixHubAvailable,
}: {
  value: CatalogSource
  onChange: (v: CatalogSource) => void
  matrixHubAvailable: boolean
}) {
  return (
    <div className="flex items-center gap-1 bg-white/5 border border-white/10 rounded-xl p-0.5">
      <button
        onClick={() => onChange('forge')}
        className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
          value === 'forge'
            ? 'bg-cyan-500/20 text-cyan-300'
            : 'text-white/40 hover:text-white/60 hover:bg-white/5'
        }`}
      >
        <Layers size={12} />
        Context Forge
      </button>
      <button
        onClick={() => matrixHubAvailable && onChange('matrixhub')}
        disabled={!matrixHubAvailable}
        className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
          value === 'matrixhub'
            ? 'bg-violet-500/20 text-violet-300'
            : matrixHubAvailable
              ? 'text-white/40 hover:text-white/60 hover:bg-white/5'
              : 'text-white/20 cursor-not-allowed'
        }`}
        title={matrixHubAvailable ? 'Browse MatrixHub catalog' : 'Set MATRIX_HUB_URL to enable'}
      >
        <Globe size={12} />
        MatrixHub
      </button>
    </div>
  )
}

// ── Main panel ───────────────────────────────────────────────────────────

export function RegistryDiscoverPanel({ backendUrl, apiKey, matrixHubUrl, onInstalled }: Props) {
  const {
    servers,
    total,
    categories,
    authTypes,
    providers,
    loading,
    error,
    refresh,
    install,
    needsSetupCount,
    search,
    setSearch,
    category,
    setCategory,
    authType,
    setAuthType,
    provider,
    setProvider,
    statusFilter,
    setStatusFilter,
  } = useForgeRegistry({ backendUrl, apiKey })

  const [installing, setInstalling] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [catalogSource, setCatalogSource] = useState<CatalogSource>('forge')

  // Drawer/dialog state
  const [setupServer, setSetupServer] = useState<RegistryServer | null>(null)
  const [detailsServer, setDetailsServer] = useState<RegistryServer | null>(null)
  const [uninstallServer, setUninstallServer] = useState<RegistryServer | null>(null)

  const registeredCount = servers.filter((s) => s.is_registered).length
  const matrixHubAvailable = Boolean(matrixHubUrl)

  const handleInstall = async (server: RegistryServer) => {
    // All auth types: just register the server in the gateway.
    // The user manually clicks "Setup" afterwards if credentials are needed.
    setInstalling(server.id)
    setFeedback(null)
    const result = await install(server.id)
    setInstalling(null)
    setFeedback({ ok: result.ok, msg: result.message })
    if (result.ok) {
      onInstalled?.()
      setTimeout(() => setFeedback(null), 4000)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    try { await refresh() } finally { setRefreshing(false) }
  }

  const handleSetupComplete = () => {
    setSetupServer(null)
    void refresh()
    onInstalled?.()
    setFeedback({ ok: true, msg: 'Server configured successfully!' })
    setTimeout(() => setFeedback(null), 4000)
  }

  const handleUninstalled = () => {
    setUninstallServer(null)
    void refresh()
    onInstalled?.()
    setFeedback({ ok: true, msg: 'Server uninstalled.' })
    setTimeout(() => setFeedback(null), 4000)
  }

  // Don't render if Forge is unreachable (only for Forge tab)
  if (catalogSource === 'forge' && !loading && !error && total === 0 && servers.length === 0) {
    return (
      <div className="space-y-4">
        {/* Source switcher always visible */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <h3 className="text-sm font-semibold text-white">Discover MCP Servers</h3>
            <CatalogSourceSwitcher value={catalogSource} onChange={setCatalogSource} matrixHubAvailable={matrixHubAvailable} />
          </div>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-6">
          <div className="flex items-center gap-3 mb-3">
            <Globe size={20} className="text-cyan-400" />
            <h3 className="text-sm font-semibold text-white">Context Forge Catalog</h3>
            <span className="text-xs px-2 py-0.5 rounded-full bg-white/10 text-white/40 font-medium">
              Registry Unavailable
            </span>
          </div>
          <p className="text-sm text-white/50">
            The MCP Server Registry requires Context Forge to be running.
            Start it with <code className="text-white/60 bg-white/10 px-1.5 py-0.5 rounded text-xs">make start-mcp</code> to browse 80+ public MCP servers.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h3 className="text-sm font-semibold text-white">Discover MCP Servers</h3>
          <CatalogSourceSwitcher value={catalogSource} onChange={setCatalogSource} matrixHubAvailable={matrixHubAvailable} />
        </div>
        {catalogSource === 'forge' && (
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-white/60 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg transition-colors disabled:opacity-50"
          >
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
            Refresh
          </button>
        )}
      </div>

      {/* Feedback banner — shared across both sources */}
      {feedback && (
        <div className={`flex items-center justify-between px-4 py-2 rounded-lg text-sm ${
          feedback.ok
            ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
            : 'bg-red-500/10 text-red-300 border border-red-500/20'
        }`}>
          <div className="flex items-center gap-2">
            {feedback.ok ? <Check size={14} /> : <AlertCircle size={14} />}
            {feedback.msg}
          </div>
          <button
            onClick={() => setFeedback(null)}
            className="p-1 text-current opacity-50 hover:opacity-100 transition-opacity"
          >
            <XIcon size={12} />
          </button>
        </div>
      )}

      {/* ── MatrixHub catalog (when selected) ──────────────────────────── */}
      {catalogSource === 'matrixhub' && matrixHubUrl && (
        <MatrixHubCatalogPanel
          hubUrl={matrixHubUrl}
          enabled
          backendUrl={backendUrl}
          apiKey={apiKey}
          onInstalled={onInstalled}
        />
      )}

      {/* ── Forge catalog (default) ────────────────────────────────────── */}
      {catalogSource === 'forge' && (
        <>
          {/* Stats bar */}
          <div className="flex items-center gap-3 text-xs text-white/40">
            <span>{total} available</span>
            <span className="w-px h-3 bg-white/10" />
            <span className="text-emerald-400/70">{registeredCount} installed</span>
            {needsSetupCount > 0 && (
              <>
                <span className="w-px h-3 bg-white/10" />
                <span className="text-amber-400/70">{needsSetupCount} needs setup</span>
              </>
            )}
            <span className="w-px h-3 bg-white/10" />
            <span>{categories.length} categories</span>
          </div>

          {/* Status filter pills */}
          <StatusFilterPills
            value={statusFilter}
            onChange={setStatusFilter}
            counts={{ total, installed: registeredCount, needsSetup: needsSetupCount }}
          />

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[200px]">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search registry..."
                className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-cyan-500/50 transition-colors"
              />
            </div>
            <FilterDropdown label="Category" value={category} options={categories} onChange={setCategory} />
            <FilterDropdown label="Auth Type" value={authType} options={authTypes} onChange={setAuthType} />
            <FilterDropdown label="Provider" value={provider} options={providers} onChange={setProvider} />
          </div>

          {/* Loading */}
          {loading && (
            <div className="flex items-center justify-center py-12 text-white/40">
              <div className="w-5 h-5 border-2 border-white/20 border-t-cyan-400 rounded-full animate-spin mr-3" />
              Loading registry...
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="flex items-center gap-2 text-red-400 text-sm py-4">
              <AlertCircle size={14} />
              {error}
            </div>
          )}

          {/* Server grid */}
          {!loading && servers.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {servers.map((server) => (
                <RegistryServerCard
                  key={server.id}
                  server={server}
                  installing={installing === server.id}
                  onInstall={() => handleInstall(server)}
                  onSetup={() => setSetupServer(server)}
                  onDetails={() => setDetailsServer(server)}
                  onUninstall={() => setUninstallServer(server)}
                />
              ))}
            </div>
          )}

          {/* Empty search */}
          {!loading && !error && servers.length === 0 && (search || category || authType || provider || statusFilter) && (
            <div className="flex flex-col items-center justify-center h-32 text-white/40">
              <Search size={28} className="mb-2 opacity-30" />
              <p className="text-sm">No servers match your filters.</p>
            </div>
          )}
        </>
      )}

      {/* ── Drawers & Dialogs ──────────────────────────────────────────── */}

      {setupServer && (
        <McpSetupWizard
          server={setupServer}
          backendUrl={backendUrl}
          apiKey={apiKey}
          onClose={() => setSetupServer(null)}
          onComplete={handleSetupComplete}
        />
      )}

      {detailsServer && (
        <McpServerDetailsDrawer
          server={detailsServer}
          backendUrl={backendUrl}
          apiKey={apiKey}
          onClose={() => setDetailsServer(null)}
          onSetup={() => {
            setDetailsServer(null)
            setSetupServer(detailsServer)
          }}
          onUninstall={() => {
            setDetailsServer(null)
            setUninstallServer(detailsServer)
          }}
        />
      )}

      {uninstallServer && (
        <McpUninstallDialog
          server={uninstallServer}
          backendUrl={backendUrl}
          apiKey={apiKey}
          onClose={() => setUninstallServer(null)}
          onUninstalled={handleUninstalled}
        />
      )}
    </div>
  )
}
