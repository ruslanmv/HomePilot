import React, { useState } from 'react'
import { Search, RefreshCw, Plus, Zap, Filter, Radio, Globe } from 'lucide-react'
import { useInstalledServers } from './useInstalledServers'
import type { InstalledServer } from './useInstalledServers'
import { InstalledServerCard } from './InstalledServerCard'
import { ServerDetailDrawer } from './ServerDetailDrawer'
import { McpServersEmptyState } from './McpServersEmptyState'
import { AddServerDrawer } from './AddServerDrawer'
import { MarketplaceSearch } from './MarketplaceSearch'
import { RegistryDiscoverPanel } from './RegistryDiscoverPanel'

type SubTab = 'installed' | 'discover'

type Props = {
  backendUrl: string
  apiKey?: string
  onGoToTools?: () => void
}

export function McpServersTab({ backendUrl, apiKey, onGoToTools }: Props) {
  const {
    servers,
    counts,
    loading,
    error,
    refresh,
    search,
    setSearch,
    forgeHealthy,
    catalogTools,
  } = useInstalledServers({ backendUrl, apiKey })

  const [subTab, setSubTab] = useState<SubTab>('installed')
  const [selectedServer, setSelectedServer] = useState<InstalledServer | null>(null)
  const [showAddDrawer, setShowAddDrawer] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [syncing, setSyncing] = useState(false)

  const handleRefresh = async () => {
    setRefreshing(true)
    try { await refresh() } finally { setRefreshing(false) }
  }

  const handleSync = async () => {
    setSyncing(true)
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (apiKey) headers['x-api-key'] = apiKey

      const res = await fetch(`${backendUrl}/v1/agentic/sync`, {
        method: 'POST',
        headers,
      })
      if (!res.ok) {
        console.error('Sync failed:', res.status)
      }
      await refresh()
    } catch (e) {
      console.error('Sync error:', e)
    } finally {
      setSyncing(false)
    }
  }

  const hasServers = !loading && !error && servers.length > 0
  const showEmpty = !loading && !error && servers.length === 0 && !search

  return (
    <div className="space-y-6">
      {/* Sub-tab switcher */}
      <div className="flex items-center gap-1 p-1 bg-white/5 rounded-xl w-fit">
        <button
          onClick={() => setSubTab('installed')}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
            subTab === 'installed'
              ? 'bg-white/10 text-white shadow-sm'
              : 'text-white/50 hover:text-white/70'
          }`}
        >
          <Radio size={14} />
          Installed
          {counts.total > 0 && (
            <span className="text-xs px-1.5 py-0.5 rounded-full bg-white/10 text-white/60">
              {counts.total}
            </span>
          )}
        </button>
        <button
          onClick={() => setSubTab('discover')}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
            subTab === 'discover'
              ? 'bg-white/10 text-white shadow-sm'
              : 'text-white/50 hover:text-white/70'
          }`}
        >
          <Globe size={14} />
          Discover
        </button>
      </div>

      {/* ── Installed sub-tab ─────────────────────────────────────────── */}
      {subTab === 'installed' && (
        <>
          <div className="space-y-4">
            {/* Header with stats */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-4">
                <h3 className="text-sm font-semibold text-white">Installed Servers</h3>
                <div className="flex items-center gap-3 text-xs text-white/40">
                  <span>{counts.gateways} gateway{counts.gateways !== 1 ? 's' : ''}</span>
                  <span className="w-px h-3 bg-white/10" />
                  <span>{counts.virtualServers} virtual server{counts.virtualServers !== 1 ? 's' : ''}</span>
                </div>

                {forgeHealthy !== null && (
                  <>
                    <div className="w-px h-4 bg-white/10" />
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                      forgeHealthy
                        ? 'bg-emerald-500/20 text-emerald-300'
                        : 'bg-red-500/20 text-red-300'
                    }`}>
                      Forge {forgeHealthy ? 'Online' : 'Offline'}
                    </span>
                  </>
                )}
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={handleSync}
                  disabled={syncing}
                  className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-amber-300 bg-amber-500/10 hover:bg-amber-500/20 rounded-lg transition-colors disabled:opacity-50"
                  title="Discover and sync all MCP servers from local ports"
                >
                  <Zap size={14} className={syncing ? 'animate-pulse' : ''} />
                  {syncing ? 'Syncing...' : 'Sync All'}
                </button>
                <button
                  onClick={handleRefresh}
                  disabled={refreshing}
                  className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-white/60 hover:text-white bg-white/5 hover:bg-white/10 rounded-lg transition-colors disabled:opacity-50"
                >
                  <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
                  Refresh
                </button>
                <button
                  onClick={() => setShowAddDrawer(true)}
                  className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium text-purple-300 bg-purple-500/10 hover:bg-purple-500/20 rounded-lg transition-colors"
                >
                  <Plus size={14} />
                  Add Server
                </button>
              </div>
            </div>

            {/* Search */}
            {(counts.total > 0 || search) && (
              <div className="relative">
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search servers by name or ID..."
                  className="w-full bg-white/5 border border-white/10 rounded-xl pl-10 pr-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 transition-colors"
                />
              </div>
            )}

            {/* Content */}
            {loading && <McpServersEmptyState loading />}
            {error && <McpServersEmptyState error={error} />}
            {showEmpty && <McpServersEmptyState onAddServer={() => setShowAddDrawer(true)} />}

            {!loading && !error && servers.length === 0 && search && (
              <div className="flex flex-col items-center justify-center h-32 text-white/40">
                <Filter size={28} className="mb-2 opacity-30" />
                <p className="text-sm">No servers match your search.</p>
              </div>
            )}

            {hasServers && (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {servers.map((s) => (
                  <InstalledServerCard key={s.id} server={s} onClick={() => setSelectedServer(s)} />
                ))}
              </div>
            )}
          </div>

          {/* Marketplace Section */}
          <MarketplaceSearch
            backendUrl={backendUrl}
            apiKey={apiKey}
            onInstalled={() => {
              void refresh()
            }}
          />
        </>
      )}

      {/* ── Discover sub-tab ──────────────────────────────────────────── */}
      {subTab === 'discover' && (
        <RegistryDiscoverPanel
          backendUrl={backendUrl}
          apiKey={apiKey}
          onInstalled={() => {
            void refresh()
          }}
        />
      )}

      {/* Drawers (visible in both tabs) */}
      {selectedServer && (
        <ServerDetailDrawer
          server={selectedServer}
          catalogTools={catalogTools}
          backendUrl={backendUrl}
          apiKey={apiKey}
          onClose={() => setSelectedServer(null)}
          onRepaired={() => { void refresh() }}
        />
      )}
      {showAddDrawer && (
        <AddServerDrawer
          backendUrl={backendUrl}
          apiKey={apiKey}
          onClose={() => setShowAddDrawer(false)}
          onRegistered={() => {
            void refresh()
          }}
        />
      )}
    </div>
  )
}
