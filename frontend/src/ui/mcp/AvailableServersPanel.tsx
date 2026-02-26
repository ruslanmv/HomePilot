/**
 * AvailableServersPanel — Install/Uninstall MCP servers on-the-fly.
 *
 * Shows all servers from the server catalog (core + optional) grouped by
 * category.  Core servers display a "Core" badge; optional servers have
 * Install / Uninstall action buttons with real-time status feedback.
 *
 * After install, tools are automatically registered in MCP Context Forge
 * and a full sync updates virtual server tool associations.
 */

import React, { useState } from 'react'
import {
  Server,
  Download,
  Trash2,
  CheckCircle,
  Loader2,
  AlertCircle,
  Shield,
  FileText,
  FolderKanban,
  Globe,
  Terminal,
  Mail,
  Calendar,
  BarChart3,
  MessageSquare,
  Github,
  StickyNote,
  Package,
  RefreshCw,
} from 'lucide-react'
import { useAvailableServers, type McpServerEntry } from './useAvailableServers'

type Props = {
  backendUrl: string
  apiKey?: string
  onInstallChange?: () => void
}

/** Map server icon names to Lucide components */
const ICON_MAP: Record<string, React.ElementType> = {
  'user': Server,
  'brain': Server,
  'scale': Server,
  'briefcase': Server,
  'search': Globe,
  'package': Package,
  'file-text': FileText,
  'folder-kanban': FolderKanban,
  'globe': Globe,
  'terminal': Terminal,
  'mail': Mail,
  'calendar': Calendar,
  'bar-chart': BarChart3,
  'message-square': MessageSquare,
  'github': Github,
  'sticky-note': StickyNote,
  'server': Server,
}

const CATEGORY_LABELS: Record<string, string> = {
  core: 'Core Services',
  local: 'Local Integrations',
  communication: 'Communication',
  dev: 'Development & Knowledge',
  other: 'Other',
}

const CATEGORY_ORDER = ['core', 'local', 'communication', 'dev', 'other']

type ActionFeedback = {
  serverId: string
  ok: boolean
  message: string
}

export function AvailableServersPanel({ backendUrl, apiKey, onInstallChange }: Props) {
  const {
    servers,
    counts,
    loading,
    error,
    refresh,
    install,
    uninstall,
    actionLoading,
  } = useAvailableServers({ backendUrl, apiKey })

  const [feedback, setFeedback] = useState<ActionFeedback | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  const handleInstall = async (server: McpServerEntry) => {
    setFeedback(null)
    const result = await install(server.id)
    if (result.ok) {
      setFeedback({
        serverId: server.id,
        ok: true,
        message: `${server.label} installed — ${result.tools_discovered ?? 0} tools registered in Forge`,
      })
      onInstallChange?.()
    } else {
      setFeedback({
        serverId: server.id,
        ok: false,
        message: result.error || 'Install failed',
      })
    }
  }

  const handleUninstall = async (server: McpServerEntry) => {
    setFeedback(null)
    const result = await uninstall(server.id)
    if (result.ok) {
      setFeedback({
        serverId: server.id,
        ok: true,
        message: `${server.label} uninstalled — tools deactivated in Forge`,
      })
      onInstallChange?.()
    } else {
      setFeedback({
        serverId: server.id,
        ok: false,
        message: result.error || 'Uninstall failed',
      })
    }
  }

  const handleRefresh = async () => {
    setRefreshing(true)
    try { await refresh() } finally { setRefreshing(false) }
  }

  // Group servers by category
  const grouped = CATEGORY_ORDER.map((cat) => ({
    category: cat,
    label: CATEGORY_LABELS[cat] || cat,
    servers: servers.filter((s) => {
      if (cat === 'core') return s.is_core
      return !s.is_core && (s.category === cat || (!CATEGORY_ORDER.includes(s.category) && cat === 'other'))
    }),
  })).filter((g) => g.servers.length > 0)

  if (loading) {
    return (
      <div className="flex items-center justify-center h-40">
        <Loader2 size={24} className="animate-spin text-white/30" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-40 text-white/40">
        <AlertCircle size={28} className="mb-2 text-red-400/60" />
        <p className="text-sm">{error}</p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h3 className="text-sm font-semibold text-white">Server Management</h3>
          <div className="flex items-center gap-3 text-xs text-white/40">
            <span className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
              {counts.running} running
            </span>
            <span className="w-px h-3 bg-white/10" />
            <span>{counts.installed} optional installed</span>
            <span className="w-px h-3 bg-white/10" />
            <span>{counts.optional - counts.installed} available</span>
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

      {/* Feedback banner */}
      {feedback && (
        <div className={`flex items-center gap-3 px-4 py-2.5 rounded-xl border text-xs ${
          feedback.ok
            ? 'bg-emerald-500/5 border-emerald-500/20 text-emerald-300'
            : 'bg-red-500/5 border-red-500/20 text-red-300'
        }`}>
          {feedback.ok
            ? <CheckCircle size={14} className="shrink-0" />
            : <AlertCircle size={14} className="shrink-0" />
          }
          <span className="flex-1">{feedback.message}</span>
          <button
            onClick={() => setFeedback(null)}
            className="text-white/30 hover:text-white/60 transition-colors"
          >
            &times;
          </button>
        </div>
      )}

      {/* Server groups */}
      {grouped.map((group) => (
        <div key={group.category}>
          <h4 className="text-xs font-semibold text-white/40 uppercase tracking-wider mb-3">
            {group.label}
          </h4>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {group.servers.map((server) => (
              <ServerCard
                key={server.id}
                server={server}
                isLoading={actionLoading[server.id] || false}
                onInstall={() => handleInstall(server)}
                onUninstall={() => handleUninstall(server)}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Individual Server Card ────────────────────────────────────────────

type CardProps = {
  server: McpServerEntry
  isLoading: boolean
  onInstall: () => void
  onUninstall: () => void
}

function ServerCard({ server, isLoading, onInstall, onUninstall }: CardProps) {
  const IconComp = ICON_MAP[server.icon] || Server

  const statusColor = server.healthy
    ? 'bg-emerald-400'
    : server.installed
      ? 'bg-yellow-400'
      : 'bg-white/20'

  const statusLabel = server.healthy
    ? 'Running'
    : server.installed
      ? 'Stopped'
      : 'Available'

  return (
    <div className="flex items-center gap-4 p-4 rounded-xl bg-white/5 border border-white/10 hover:border-white/20 transition-colors">
      {/* Icon */}
      <div className={`w-10 h-10 shrink-0 rounded-xl flex items-center justify-center border border-white/10 ${
        server.is_core
          ? 'bg-gradient-to-br from-blue-500/20 to-cyan-500/20 text-blue-400'
          : server.healthy
            ? 'bg-gradient-to-br from-emerald-500/20 to-teal-500/20 text-emerald-400'
            : 'bg-white/5 text-white/40'
      }`}>
        <IconComp size={18} strokeWidth={2} />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-semibold text-white truncate">{server.label}</h4>
          {server.is_core && (
            <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/20 text-blue-300 font-semibold uppercase shrink-0">
              <Shield size={9} />
              Core
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className={`inline-flex items-center gap-1 text-xs ${
            server.healthy ? 'text-emerald-300' : server.installed ? 'text-yellow-300' : 'text-white/30'
          }`}>
            <span className={`w-1.5 h-1.5 rounded-full ${statusColor}`} />
            {statusLabel}
          </span>
          <span className="text-[10px] text-white/20">:{server.port}</span>
        </div>
      </div>

      {/* Action button */}
      <div className="shrink-0">
        {server.is_core ? (
          <span className="text-[10px] text-white/20 px-2 py-1">Always on</span>
        ) : isLoading ? (
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/5 text-white/40 text-xs">
            <Loader2 size={12} className="animate-spin" />
            <span>{server.installed ? 'Removing...' : 'Installing...'}</span>
          </div>
        ) : server.installed ? (
          <button
            onClick={onUninstall}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
              bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/20
              transition-colors"
          >
            <Trash2 size={12} />
            Uninstall
          </button>
        ) : (
          <button
            onClick={onInstall}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
              bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-300 border border-emerald-500/20
              transition-colors"
          >
            <Download size={12} />
            Install
          </button>
        )}
      </div>
    </div>
  )
}

export default AvailableServersPanel
