import React, { useCallback, useEffect, useState } from 'react'
import { X, Radio, Boxes, Copy, Check, RefreshCw, AlertTriangle } from 'lucide-react'
import type { InstalledServer } from './useInstalledServers'
import type { CatalogTool } from '../../agentic/types'

type ServerTool = {
  id: string
  name: string
  description?: string
  enabled?: boolean | null
}

type Props = {
  server: InstalledServer
  catalogTools: CatalogTool[]
  backendUrl: string
  apiKey?: string
  onClose: () => void
  onRepaired?: () => void
}

export function ServerDetailDrawer({ server, catalogTools, backendUrl, apiKey, onClose, onRepaired }: Props) {
  const isGateway = server.kind === 'gateway'
  const Icon = isGateway ? Radio : Boxes
  const [copied, setCopied] = React.useState(false)
  const [repairing, setRepairing] = useState(false)
  const [serverTools, setServerTools] = useState<ServerTool[] | null>(null)
  const [loadingTools, setLoadingTools] = useState(false)

  const copyId = () => {
    navigator.clipboard.writeText(server.id).catch(() => {})
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  // For virtual servers, fetch full tool objects from the proxy endpoint
  const fetchServerTools = useCallback(async () => {
    if (isGateway) return
    setLoadingTools(true)
    try {
      const headers: Record<string, string> = {}
      if (apiKey) headers['x-api-key'] = apiKey
      const res = await fetch(`${backendUrl}/v1/agentic/servers/${server.id}/tools`, { headers })
      if (res.ok) {
        const data = await res.json()
        if (Array.isArray(data)) {
          setServerTools(data.map((t: any) => ({
            id: t.id || t.name || '',
            name: t.name || t.original_name || t.id || '',
            description: t.description || '',
            enabled: t.enabled !== false,
          })))
          setLoadingTools(false)
          return
        }
      }
    } catch {
      // fall through to catalog resolution
    }
    // Fallback: resolve tool IDs from catalog
    if (server.toolIds.length > 0) {
      const idSet = new Set(server.toolIds)
      const resolved = catalogTools
        .filter((t) => idSet.has(t.id))
        .map((t) => ({ id: t.id, name: t.name, description: t.description, enabled: t.enabled !== false }))
      setServerTools(resolved)
    } else {
      setServerTools([])
    }
    setLoadingTools(false)
  }, [isGateway, backendUrl, apiKey, server.id, server.toolIds, catalogTools])

  useEffect(() => {
    fetchServerTools()
  }, [fetchServerTools])

  // Resolve tools for gateways from catalog by matching IDs
  const gatewayResolvedTools = React.useMemo(() => {
    if (!isGateway || server.toolIds.length === 0) return []
    const idSet = new Set(server.toolIds)
    return catalogTools.filter((t) => idSet.has(t.id))
  }, [isGateway, server.toolIds, catalogTools])

  const handleRepair = async () => {
    setRepairing(true)
    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (apiKey) headers['x-api-key'] = apiKey
      const res = await fetch(`${backendUrl}/v1/agentic/sync`, { method: 'POST', headers })
      if (res.ok) {
        await fetchServerTools()
        onRepaired?.()
      }
    } catch {
      // non-fatal
    } finally {
      setRepairing(false)
    }
  }

  const effectiveTools: ServerTool[] = isGateway ? gatewayResolvedTools : (serverTools || [])
  const toolCount = isGateway ? gatewayResolvedTools.length : (serverTools?.length ?? server.toolCount)
  const isStale = !isGateway && server.toolIds.length === 0 && (serverTools === null || serverTools.length === 0) && !loadingTools

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Panel */}
      <div
        className="relative w-full max-w-md bg-[#0b0b12] border-l border-white/10 h-full overflow-y-auto animate-slide-in-right"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 bg-[#0b0b12]/95 backdrop-blur border-b border-white/10 px-6 py-4 flex items-center justify-between z-10">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-xl bg-gradient-to-br border border-white/10 flex items-center justify-center ${
              isGateway
                ? 'from-emerald-500/20 to-teal-500/20 text-emerald-400'
                : 'from-violet-500/20 to-purple-500/20 text-violet-400'
            }`}>
              <Icon size={18} />
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">{server.name}</h2>
              <span className="text-xs text-white/40">
                {isGateway ? 'Gateway' : 'Virtual Server (Tool Bundle)'}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-xl transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-6 space-y-6">
          {/* Status */}
          <div>
            <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">Status</h3>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${
                server.enabled === true ? 'bg-emerald-400' :
                server.enabled === false ? 'bg-yellow-400' : 'bg-white/30'
              }`} />
              <span className="text-sm text-white/70">
                {server.enabled === true ? 'Connected and active' :
                 server.enabled === false ? 'Registered but disconnected' :
                 'Status unknown'}
              </span>
            </div>
          </div>

          {/* Description (virtual servers) */}
          {!isGateway && server.description && (
            <div>
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">Description</h3>
              <p className="text-sm text-white/70 leading-relaxed">{server.description}</p>
            </div>
          )}

          {/* Endpoint (gateways only) */}
          {isGateway && server.url && (
            <div>
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">Endpoint</h3>
              <code className="text-xs text-white/60 bg-white/5 border border-white/10 rounded-lg px-3 py-2 block font-mono break-all">
                {server.url}
              </code>
            </div>
          )}

          {/* Transport (gateways only) */}
          {isGateway && (
            <div>
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">Transport</h3>
              <span className="text-sm text-white/70">{server.transport || 'Unknown'}</span>
            </div>
          )}

          {/* ID */}
          <div>
            <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">
              {isGateway ? 'Gateway' : 'Server'} ID
            </h3>
            <div className="flex items-center gap-2">
              <code className="text-xs text-white/60 bg-white/5 border border-white/10 rounded-lg px-3 py-2 flex-1 truncate font-mono">
                {server.id}
              </code>
              <button
                onClick={copyId}
                className="p-2 text-white/40 hover:text-white hover:bg-white/10 rounded-lg transition-colors shrink-0"
                title="Copy ID"
              >
                {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
              </button>
            </div>
          </div>

          {/* Tools */}
          <div>
            <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">
              Tools ({loadingTools ? '...' : toolCount})
            </h3>

            {/* Stale warning for virtual servers with 0 tools */}
            {isStale && (
              <div className="flex items-start gap-2.5 px-3 py-2.5 mb-3 rounded-lg border border-amber-500/20 bg-amber-500/5">
                <AlertTriangle size={14} className="text-amber-400 shrink-0 mt-0.5" />
                <div className="text-xs text-amber-200/80 leading-relaxed">
                  This bundle was created before its tools were registered.
                  Click <strong>Recompute</strong> below to link matching tools.
                </div>
              </div>
            )}

            {loadingTools && (
              <div className="flex items-center gap-2 text-sm text-white/40 py-2">
                <RefreshCw size={14} className="animate-spin" />
                Loading tools...
              </div>
            )}

            {!loadingTools && effectiveTools.length > 0 ? (
              <div className="space-y-1.5 max-h-64 overflow-y-auto">
                {effectiveTools.map((t) => (
                  <div
                    key={t.id}
                    className="flex items-start gap-2.5 px-3 py-2 rounded-lg bg-white/5 border border-white/5"
                  >
                    <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${
                      t.enabled !== false ? 'bg-emerald-400/60' : 'bg-white/20'
                    }`} />
                    <div className="min-w-0 flex-1">
                      <div className="text-xs text-white/70 font-medium truncate">{t.name}</div>
                      {t.description && (
                        <div className="text-[11px] text-white/40 truncate mt-0.5">{t.description}</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : !loadingTools && effectiveTools.length === 0 ? (
              <p className="text-sm text-white/40">No tools associated with this server.</p>
            ) : null}
          </div>

          {/* Repair CTA (virtual servers only) */}
          {!isGateway && (
            <div>
              <button
                onClick={handleRepair}
                disabled={repairing}
                className="flex items-center gap-2 w-full justify-center px-4 py-2.5 text-xs font-medium text-amber-300 bg-amber-500/10 hover:bg-amber-500/20 rounded-xl transition-colors disabled:opacity-50 border border-amber-500/20"
              >
                <RefreshCw size={14} className={repairing ? 'animate-spin' : ''} />
                {repairing ? 'Recomputing...' : 'Recompute Tool Links'}
              </button>
              <p className="text-[11px] text-white/30 mt-2 text-center">
                Re-syncs all MCP servers and updates this bundle's tool associations
              </p>
            </div>
          )}
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
