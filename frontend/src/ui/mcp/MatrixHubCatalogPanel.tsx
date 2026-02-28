/**
 * MatrixHubCatalogPanel — browse and install MCP servers from the MatrixHub catalog.
 *
 * MatrixHub (https://github.com/agent-matrix/matrix-hub) is an optional
 * secondary catalog source for MCP servers, agents, and tools.
 *
 * Phase 11 — fully additive, does not modify any existing component.
 */

import React, { useState } from 'react'
import {
  Search,
  Download,
  RefreshCw,
  Globe,
  Star,
  ExternalLink,
  AlertCircle,
  ChevronDown,
  Copy,
  Check,
  X as XIcon,
} from 'lucide-react'
import { useMatrixHub, type MatrixHubItem } from './useMatrixHub'

type Props = {
  hubUrl: string
  enabled?: boolean
  backendUrl: string
  apiKey?: string
  /** Called after a server is installed so the parent can refresh */
  onInstalled?: () => void
}

// ── Server card ──────────────────────────────────────────────────────────

function MatrixHubServerCard({
  item,
  onInstall,
  onViewDetails,
}: {
  item: MatrixHubItem
  onInstall: () => void
  onViewDetails: () => void
}) {
  return (
    <div className="flex flex-col gap-3 p-5 rounded-2xl transition-all duration-200 border bg-white/5 hover:bg-white/[0.07] border-white/10 hover:border-white/20 h-full">
      {/* Header */}
      <div className="flex justify-between items-start gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br from-violet-500/20 to-indigo-500/20 border border-white/10 flex items-center justify-center text-violet-400">
            <Globe size={18} strokeWidth={2} />
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-sm text-white truncate">{item.name}</h3>
            {item.version && (
              <span className="text-xs text-white/40">v{item.version}</span>
            )}
          </div>
        </div>
        {/* Score badge */}
        {item.score_final > 0 && (
          <span className="flex items-center gap-1 text-xs text-amber-300/80 bg-amber-500/10 px-2 py-0.5 rounded-full shrink-0">
            <Star size={10} />
            {item.score_final.toFixed(1)}
          </span>
        )}
      </div>

      {/* Description */}
      <p className="text-sm text-white/60 leading-relaxed line-clamp-2 flex-1">
        {item.summary || 'No description available.'}
      </p>

      {/* Tags row */}
      <div className="flex flex-wrap items-center gap-1.5">
        {item.capabilities?.slice(0, 3).map((cap) => (
          <span key={cap} className="text-xs px-2 py-0.5 rounded-full font-medium bg-violet-500/20 text-violet-300">
            {cap}
          </span>
        ))}
        {item.frameworks?.slice(0, 2).map((fw) => (
          <span key={fw} className="text-xs px-2 py-0.5 rounded-full bg-white/5 text-white/40">
            {fw}
          </span>
        ))}
      </div>

      {/* Action buttons */}
      <div className="pt-1 flex items-center gap-2">
        <button
          onClick={onViewDetails}
          className="flex-1 flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-violet-500/20 hover:bg-violet-500/30 text-violet-300 rounded-lg transition-colors justify-center"
        >
          <Globe size={14} />
          View Details
        </button>
        {(item.install_url || item.source_url || item.homepage) && (
          <a
            href={item.install_url || item.source_url || item.homepage || '#'}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-white/40 hover:text-white/70 bg-white/5 hover:bg-white/10 rounded-lg transition-colors"
            title="Open source"
          >
            <ExternalLink size={13} />
          </a>
        )}
      </div>
    </div>
  )
}

// ── Details drawer ──────────────────────────────────────────────────────

function MatrixHubDetailsDrawer({
  item,
  onClose,
}: {
  item: MatrixHubItem
  onClose: () => void
}) {
  const [copiedUrl, setCopiedUrl] = useState(false)

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text).catch(() => {})
    setCopiedUrl(true)
    setTimeout(() => setCopiedUrl(false), 2000)
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative w-full max-w-md bg-[#0b0b12] border-l border-white/10 h-full overflow-y-auto animate-slide-in-right"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 bg-[#0b0b12]/95 backdrop-blur border-b border-white/10 px-6 py-4 flex items-center justify-between z-10">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br from-violet-500/20 to-indigo-500/20 border border-white/10 flex items-center justify-center text-violet-400">
              <Globe size={18} strokeWidth={2} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">{item.name}</h2>
              <div className="flex items-center gap-2 mt-0.5">
                {item.version && <span className="text-xs text-white/40">v{item.version}</span>}
                {item.score_final > 0 && (
                  <>
                    <span className="text-white/20">·</span>
                    <span className="flex items-center gap-1 text-xs text-amber-300/70">
                      <Star size={10} />
                      {item.score_final.toFixed(1)}
                    </span>
                  </>
                )}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-xl transition-colors"
          >
            <XIcon size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-6 space-y-5">
          <p className="text-sm text-white/60 leading-relaxed">{item.summary}</p>

          {/* Capabilities */}
          {item.capabilities?.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">Capabilities</h3>
              <div className="flex flex-wrap gap-1.5">
                {item.capabilities.map((c) => (
                  <span key={c} className="text-xs px-2.5 py-1 rounded-full bg-violet-500/20 text-violet-300 border border-violet-500/10">
                    {c}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Frameworks */}
          {item.frameworks?.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">Frameworks</h3>
              <div className="flex flex-wrap gap-1.5">
                {item.frameworks.map((f) => (
                  <span key={f} className="text-xs px-2.5 py-1 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/10">
                    {f}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Providers */}
          {item.providers?.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">Providers</h3>
              <div className="flex flex-wrap gap-1.5">
                {item.providers.map((p) => (
                  <span key={p} className="text-xs px-2.5 py-1 rounded-full bg-white/5 text-white/50 border border-white/5">
                    {p}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Snippet / install command */}
          {item.snippet && (
            <div>
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">Install Snippet</h3>
              <div className="relative">
                <pre className="text-xs text-white/60 bg-black/40 border border-white/10 rounded-xl p-4 font-mono overflow-x-auto whitespace-pre-wrap">
                  {item.snippet}
                </pre>
                <button
                  onClick={() => copyToClipboard(item.snippet || '')}
                  className="absolute top-2 right-2 p-1.5 text-white/30 hover:text-white/60 bg-white/5 hover:bg-white/10 rounded-lg transition-colors"
                  title="Copy snippet"
                >
                  {copiedUrl ? <Check size={12} className="text-emerald-400" /> : <Copy size={12} />}
                </button>
              </div>
            </div>
          )}

          {/* Links */}
          <div className="space-y-2">
            {item.homepage && (
              <a
                href={item.homepage}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 w-full px-4 py-3 text-sm font-medium text-cyan-300 bg-cyan-500/10 hover:bg-cyan-500/20 rounded-xl transition-colors border border-cyan-500/20"
              >
                <Globe size={16} />
                Homepage
              </a>
            )}
            {item.source_url && (
              <a
                href={item.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 w-full px-4 py-3 text-sm font-medium text-white/60 bg-white/5 hover:bg-white/10 rounded-xl transition-colors border border-white/10"
              >
                <ExternalLink size={16} />
                Source Code
              </a>
            )}
            {item.manifest_url && (
              <a
                href={item.manifest_url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-2 w-full px-4 py-3 text-sm font-medium text-white/60 bg-white/5 hover:bg-white/10 rounded-xl transition-colors border border-white/10"
              >
                <ExternalLink size={16} />
                Manifest
              </a>
            )}
          </div>
        </div>
      </div>

      <style>{`
        @keyframes slide-in-right {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
        .animate-slide-in-right {
          animation: slide-in-right 0.2s ease-out;
        }
      `}</style>
    </div>
  )
}

// ── Capability filter ────────────────────────────────────────────────────

function CapabilityFilter({
  capabilities,
  selected,
  onSelect,
}: {
  capabilities: string[]
  selected: string
  onSelect: (v: string) => void
}) {
  if (capabilities.length === 0) return null
  return (
    <div className="relative">
      <select
        value={selected}
        onChange={(e) => onSelect(e.target.value)}
        className="appearance-none bg-white/5 border border-white/10 rounded-lg pl-3 pr-8 py-1.5 text-xs text-white/70 focus:outline-none focus:border-violet-500/50 cursor-pointer"
      >
        <option value="">All Capabilities</option>
        {capabilities.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
      <ChevronDown size={12} className="absolute right-2 top-1/2 -translate-y-1/2 text-white/30 pointer-events-none" />
    </div>
  )
}

// ── Main panel ───────────────────────────────────────────────────────────

export function MatrixHubCatalogPanel({ hubUrl, enabled = true }: Props) {
  const {
    items,
    total,
    loading,
    error,
    healthy,
    search,
    setSearch,
    capabilities,
    refresh,
  } = useMatrixHub({ hubUrl, enabled })

  const [refreshing, setRefreshing] = useState(false)
  const [capFilter, setCapFilter] = useState('')
  const [detailItem, setDetailItem] = useState<MatrixHubItem | null>(null)

  const filteredItems = capFilter
    ? items.filter((i) => i.capabilities?.includes(capFilter))
    : items

  const handleRefresh = async () => {
    setRefreshing(true)
    try { await refresh() } finally { setRefreshing(false) }
  }

  // Not reachable
  if (!enabled || healthy === false) {
    return (
      <div className="rounded-2xl border border-white/10 bg-white/5 p-6">
        <div className="flex items-center gap-3 mb-3">
          <Globe size={20} className="text-violet-400" />
          <h3 className="text-sm font-semibold text-white">MatrixHub Catalog</h3>
          <span className="text-xs px-2 py-0.5 rounded-full bg-white/10 text-white/40 font-medium">
            {healthy === false ? 'Unreachable' : 'Disabled'}
          </span>
        </div>
        <p className="text-sm text-white/50">
          {healthy === false
            ? `Cannot connect to MatrixHub at ${hubUrl}. Make sure it is running.`
            : 'MatrixHub integration is disabled.'}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-3 text-xs text-white/40">
            <span>{total} servers</span>
            {capabilities.length > 0 && (
              <>
                <span className="w-px h-3 bg-white/10" />
                <span>{capabilities.length} capabilities</span>
              </>
            )}
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
            placeholder="Search MatrixHub..."
            className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-violet-500/50 transition-colors"
          />
        </div>
        <CapabilityFilter capabilities={capabilities} selected={capFilter} onSelect={setCapFilter} />
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12 text-white/40">
          <div className="w-5 h-5 border-2 border-white/20 border-t-violet-400 rounded-full animate-spin mr-3" />
          Loading MatrixHub catalog...
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 text-red-400 text-sm py-4">
          <AlertCircle size={14} />
          {error}
        </div>
      )}

      {/* Grid */}
      {!loading && filteredItems.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filteredItems.map((item) => (
            <MatrixHubServerCard
              key={item.id}
              item={item}
              onInstall={() => {}}
              onViewDetails={() => setDetailItem(item)}
            />
          ))}
        </div>
      )}

      {/* Empty */}
      {!loading && !error && filteredItems.length === 0 && (search || capFilter) && (
        <div className="flex flex-col items-center justify-center h-32 text-white/40">
          <Search size={28} className="mb-2 opacity-30" />
          <p className="text-sm">No servers match your search.</p>
        </div>
      )}

      {/* Details drawer */}
      {detailItem && (
        <MatrixHubDetailsDrawer
          item={detailItem}
          onClose={() => setDetailItem(null)}
        />
      )}
    </div>
  )
}
