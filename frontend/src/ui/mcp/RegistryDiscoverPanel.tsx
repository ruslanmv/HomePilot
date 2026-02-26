/**
 * RegistryDiscoverPanel — browse & install public MCP servers from the Forge catalog.
 *
 * Renders the 81+ servers / 38 categories from mcp-catalog.yml inside
 * HomePilot's MCP Servers tab (no need to open the Forge admin UI).
 *
 * Phase 9 — fully additive, does not modify any existing component.
 */

import React, { useState } from 'react'
import {
  Search,
  Download,
  Check,
  AlertCircle,
  RefreshCw,
  ExternalLink,
  Globe,
  Lock,
  Key,
  Shield,
  ChevronDown,
} from 'lucide-react'
import { useForgeRegistry } from './useForgeRegistry'
import type { RegistryServer } from '../../agentic/types'

type Props = {
  backendUrl: string
  apiKey?: string
  /** Called after a server is installed so the parent can refresh its catalog */
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
    default:
      return { icon: Shield, color: 'bg-emerald-500/20 text-emerald-300', label: authType || 'Open' }
  }
}

function statusBadge(server: RegistryServer) {
  if (server.is_registered && server.requires_oauth_config) {
    return { label: 'OAuth Required', color: 'bg-amber-500/20 text-amber-300' }
  }
  if (server.is_registered) {
    return { label: 'Installed', color: 'bg-emerald-500/20 text-emerald-300' }
  }
  return null
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

// ── Server card ──────────────────────────────────────────────────────────

function RegistryServerCard({
  server,
  installing,
  onInstall,
}: {
  server: RegistryServer
  installing: boolean
  onInstall: () => void
}) {
  const auth = authBadge(server.auth_type)
  const status = statusBadge(server)
  const AuthIcon = auth.icon

  return (
    <div className="flex flex-col gap-3 p-5 rounded-2xl bg-white/5 hover:bg-white/[0.07] transition-all duration-200 border border-white/10 hover:border-white/20 h-full">
      {/* Header */}
      <div className="flex justify-between items-start gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br from-cyan-500/20 to-blue-500/20 border border-white/10 flex items-center justify-center text-cyan-400">
            <Globe size={18} strokeWidth={2} />
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-sm text-white truncate">{server.name}</h3>
            <span className="text-xs text-white/40">{server.provider}</span>
          </div>
        </div>
        {status && (
          <span className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${status.color}`}>
            {status.label}
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

      {/* Action */}
      <div className="pt-1">
        {server.is_registered ? (
          <button
            disabled
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-emerald-500/10 text-emerald-400 rounded-lg cursor-default w-full justify-center"
          >
            <Check size={14} />
            {server.requires_oauth_config ? 'Needs OAuth Setup' : 'Already Installed'}
          </button>
        ) : (
          <button
            onClick={onInstall}
            disabled={installing}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 rounded-lg transition-colors disabled:opacity-50 w-full justify-center"
          >
            {installing ? (
              <div className="w-3.5 h-3.5 border-2 border-cyan-300/30 border-t-cyan-300 rounded-full animate-spin" />
            ) : (
              <Download size={14} />
            )}
            {installing ? 'Installing...' : 'Add Server'}
          </button>
        )}
      </div>
    </div>
  )
}

// ── Main panel ───────────────────────────────────────────────────────────

export function RegistryDiscoverPanel({ backendUrl, apiKey, onInstalled }: Props) {
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
    search,
    setSearch,
    category,
    setCategory,
    authType,
    setAuthType,
    provider,
    setProvider,
  } = useForgeRegistry({ backendUrl, apiKey })

  const [installing, setInstalling] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const registeredCount = servers.filter((s) => s.is_registered).length

  const handleInstall = async (server: RegistryServer) => {
    setInstalling(server.id)
    setFeedback(null)
    const result = await install(server.id)
    setInstalling(null)
    setFeedback({ ok: result.ok, msg: result.message })
    if (result.ok) {
      onInstalled?.()
      // Auto-clear success feedback
      setTimeout(() => setFeedback(null), 4000)
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    try { await refresh() } finally { setRefreshing(false) }
  }

  // Don't render if Forge is unreachable (total === 0 and no servers and no error)
  if (!loading && !error && total === 0 && servers.length === 0) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-6">
        <div className="flex items-center gap-3 mb-3">
          <Globe size={20} className="text-cyan-400" />
          <h3 className="text-sm font-semibold text-white">Discover MCP Servers</h3>
          <span className="text-xs px-2 py-0.5 rounded-full bg-white/10 text-white/40 font-medium">
            Registry Unavailable
          </span>
        </div>
        <p className="text-sm text-white/50">
          The MCP Server Registry requires Context Forge to be running.
          Start it with <code className="text-white/60 bg-white/10 px-1.5 py-0.5 rounded text-xs">make start-mcp</code> to browse 80+ public MCP servers.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h3 className="text-sm font-semibold text-white">Discover MCP Servers</h3>
          <div className="flex items-center gap-3 text-xs text-white/40">
            <span>{total} available</span>
            <span className="w-px h-3 bg-white/10" />
            <span>{registeredCount} installed</span>
            <span className="w-px h-3 bg-white/10" />
            <span>{categories.length} categories</span>
          </div>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-white/60 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg transition-colors disabled:opacity-50"
        >
          <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

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

      {/* Feedback banner */}
      {feedback && (
        <div className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm ${
          feedback.ok
            ? 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
            : 'bg-red-500/10 text-red-300 border border-red-500/20'
        }`}>
          {feedback.ok ? <Check size={14} /> : <AlertCircle size={14} />}
          {feedback.msg}
        </div>
      )}

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
            />
          ))}
        </div>
      )}

      {/* Empty search */}
      {!loading && !error && servers.length === 0 && (search || category || authType || provider) && (
        <div className="flex flex-col items-center justify-center h-32 text-white/40">
          <Search size={28} className="mb-2 opacity-30" />
          <p className="text-sm">No servers match your filters.</p>
        </div>
      )}
    </div>
  )
}
