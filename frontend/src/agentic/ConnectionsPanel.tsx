/**
 * ConnectionsPanel: wizard "Connections" section.
 *
 * Renders a tool bundle dropdown (virtual-server-first), A2A agent
 * multi-select, and a preview of "X tools + Y connected agents".
 *
 * Additive: this component is imported optionally by ProjectsView.tsx.
 */

import React, { useMemo } from 'react'
import type { AgenticCatalog } from './types'

type Props = {
  catalog: AgenticCatalog | null
  loading: boolean
  error: string | null
  toolSource: string
  setToolSource: (v: string) => void
  selectedA2AAgentIds: string[]
  setSelectedA2AAgentIds: (ids: string[]) => void
  onRefresh: () => void
}

export function ConnectionsPanel(props: Props) {
  const {
    catalog,
    loading,
    error,
    toolSource,
    setToolSource,
    selectedA2AAgentIds,
    setSelectedA2AAgentIds,
    onRefresh,
  } = props

  const servers = catalog?.servers || []
  const tools = catalog?.tools || []
  const agents = catalog?.a2a_agents || []

  const enabledTools = useMemo(() => tools.filter((t) => t.enabled !== false), [tools])

  const serverToolCount = useMemo(() => {
    if (!toolSource.startsWith('server:')) return 0
    const sid = toolSource.replace('server:', '')
    const s = servers.find((x) => x.id === sid)
    return s?.tool_ids?.length || 0
  }, [toolSource, servers])

  const toolCount = useMemo(() => {
    if (toolSource === 'none') return 0
    if (toolSource === 'all') return enabledTools.length
    if (toolSource.startsWith('server:')) return serverToolCount
    return 0
  }, [toolSource, enabledTools.length, serverToolCount])

  const toggleAgent = (id: string) => {
    setSelectedA2AAgentIds(
      selectedA2AAgentIds.includes(id)
        ? selectedA2AAgentIds.filter((x) => x !== id)
        : [...selectedA2AAgentIds, id],
    )
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-medium text-white/80">Connections</div>
          <div className="text-xs text-white/50">Choose a tool bundle + optional A2A agents.</div>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="text-xs px-3 py-2 rounded-lg border border-white/10 bg-white/5 hover:bg-white/10 text-white/70"
        >
          Refresh
        </button>
      </div>

      {loading ? <div className="text-xs text-white/50">Loading catalog...</div> : null}
      {error ? <div className="text-xs text-red-300">Catalog error: {error}</div> : null}
      {catalog && catalog.forge && !catalog.forge.healthy ? (
        <div className="text-xs text-yellow-200">
          Forge not healthy: {catalog.forge.error || 'unknown error'}
        </div>
      ) : null}

      {/* Tool bundle */}
      <div className="rounded-xl border border-white/10 bg-white/5 p-4 space-y-2">
        <div className="text-xs font-semibold text-white/70">Tool bundle</div>
        <select
          value={toolSource}
          onChange={(e) => setToolSource(e.target.value)}
          className="w-full rounded-lg bg-black/30 border border-white/10 p-2 text-white/80"
        >
          <option value="all">All enabled tools</option>
          {servers.map((s) => (
            <option key={s.id} value={`server:${s.id}`}>
              Virtual server: {s.name}
            </option>
          ))}
          <option value="none">No tools</option>
        </select>

        <div className="text-xs text-white/50">
          This agent can use{' '}
          <span className="text-white/80 font-semibold">{toolCount}</span> tools +{' '}
          <span className="text-white/80 font-semibold">{selectedA2AAgentIds.length}</span>{' '}
          connected agents.
        </div>

        {/* Enterprise warning for "All enabled tools" */}
        {toolSource === 'all' && enabledTools.length > 0 && (
          <div className="text-[11px] px-3 py-2 rounded-lg border border-yellow-500/20 bg-yellow-500/5 text-yellow-200/80">
            <strong>Wide scope:</strong> &quot;All enabled tools&quot; grants access to every tool in Forge.
            For tighter control, select a Virtual Server bundle instead.
          </div>
        )}

        {catalog?.last_updated ? (
          <div className="text-[10px] text-white/30">
            Last updated: {new Date(catalog.last_updated).toLocaleTimeString()}
          </div>
        ) : null}
      </div>

      {/* A2A agents */}
      <div className="rounded-xl border border-white/10 bg-white/5 p-4 space-y-2">
        <div className="text-xs font-semibold text-white/70">A2A agents (optional)</div>
        {agents.length === 0 ? (
          <div className="text-xs text-white/50">No A2A agents discovered.</div>
        ) : (
          <div className="space-y-2 max-h-44 overflow-y-auto pr-1">
            {agents.map((a) => {
              const checked = selectedA2AAgentIds.includes(a.id)
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => toggleAgent(a.id)}
                  className={`w-full p-3 rounded-xl border text-left transition-all ${
                    checked
                      ? 'border-purple-500/60 bg-purple-500/10'
                      : 'border-white/10 bg-white/5 hover:border-white/20 hover:bg-white/10'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-semibold text-white">{a.name}</div>
                      {a.description ? (
                        <div className="text-xs text-white/50 mt-1">{a.description}</div>
                      ) : null}
                    </div>
                    <div
                      className={`h-5 w-5 rounded-md border flex items-center justify-center ${
                        checked
                          ? 'border-purple-400 bg-purple-500/20'
                          : 'border-white/20 bg-white/5'
                      }`}
                    >
                      {checked ? (
                        <span className="text-purple-300 text-xs">&#10003;</span>
                      ) : null}
                    </div>
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
