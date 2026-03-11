/**
 * ExternalUninstallDialog — confirmation modal for uninstalling external MCP servers.
 *
 * Shows persona dependency warnings before confirming.  Non-destructive:
 * the server files remain on disk and can be reinstalled at any time.
 * Tools are disabled (not deleted) and automatically re-enabled on reinstall.
 *
 * Fully additive — does not modify any existing component.
 */

import React, { useEffect, useState } from 'react'
import { AlertTriangle, Loader2, X, Users, Wrench, Info } from 'lucide-react'
import type { McpServerEntry, UninstallPreview } from './useAvailableServers'

type Props = {
  server: McpServerEntry
  backendUrl: string
  apiKey?: string
  onClose: () => void
  onConfirmUninstall: () => void
  /** Optional pre-fetched preview; if omitted the dialog fetches it. */
  preview?: UninstallPreview | null
}

export function ExternalUninstallDialog({
  server,
  backendUrl,
  apiKey,
  onClose,
  onConfirmUninstall,
  preview: externalPreview,
}: Props) {
  const [preview, setPreview] = useState<UninstallPreview | null>(externalPreview ?? null)
  const [loadingPreview, setLoadingPreview] = useState(!externalPreview)

  // Fetch preview on mount if not provided
  useEffect(() => {
    if (externalPreview) return
    const fetchPreview = async () => {
      setLoadingPreview(true)
      try {
        const headers: Record<string, string> = {}
        if (apiKey) headers['x-api-key'] = apiKey
        const res = await fetch(
          `${backendUrl}/v1/agentic/servers/external/${encodeURIComponent(server.id)}/uninstall-preview`,
          { headers },
        )
        if (res.ok) {
          setPreview(await res.json())
        }
      } catch {
        // Preview failed — still allow uninstall
      } finally {
        setLoadingPreview(false)
      }
    }
    void fetchPreview()
  }, [server.id, backendUrl, apiKey, externalPreview])

  const affectedCount = preview?.affected_personas?.length ?? 0
  const toolCount = preview?.tools_to_deactivate?.length ?? server.tools_discovered ?? 0

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />

      {/* Dialog */}
      <div
        className="relative w-full max-w-md bg-[#0f0f18] border border-white/10 rounded-2xl shadow-2xl overflow-hidden animate-fade-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-2">
          <div className="flex items-center gap-3">
            <div className={`w-9 h-9 rounded-xl flex items-center justify-center border ${
              affectedCount > 0
                ? 'bg-amber-500/10 border-amber-500/20'
                : 'bg-red-500/10 border-red-500/20'
            }`}>
              <AlertTriangle size={18} className={affectedCount > 0 ? 'text-amber-400' : 'text-red-400'} />
            </div>
            <h3 className="text-sm font-semibold text-white">Uninstall {server.label}?</h3>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-white/40 hover:text-white/70 hover:bg-white/10 rounded-lg transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-3">
          {loadingPreview ? (
            <div className="flex items-center gap-2 text-sm text-white/40">
              <Loader2 size={14} className="animate-spin" />
              Checking dependencies...
            </div>
          ) : (
            <>
              {/* Persona dependency warning */}
              {affectedCount > 0 && (
                <div className="rounded-xl bg-amber-500/5 border border-amber-500/20 p-4 space-y-2">
                  <div className="flex items-center gap-2 text-amber-300 text-xs font-semibold uppercase tracking-wide">
                    <Users size={14} />
                    {affectedCount} Persona{affectedCount > 1 ? 's' : ''} Affected
                  </div>
                  <div className="space-y-1.5">
                    {preview!.affected_personas.map((p) => (
                      <div key={p.project_id} className="flex items-start gap-2 text-xs">
                        <span className="text-amber-200/80 font-medium shrink-0">{p.project_name}</span>
                        <span className="text-white/30">—</span>
                        <span className="text-white/40">
                          {p.tools_affected.length} tool{p.tools_affected.length > 1 ? 's' : ''} will be disabled
                        </span>
                      </div>
                    ))}
                  </div>
                  <p className="text-[11px] text-amber-200/50 leading-relaxed mt-1">
                    These personas will lose access to {server.label} tools until the server is reinstalled.
                  </p>
                </div>
              )}

              {/* Tools to deactivate */}
              {toolCount > 0 && (
                <div className="flex items-center gap-2 text-xs text-white/50">
                  <Wrench size={12} className="shrink-0 text-white/30" />
                  <span>{toolCount} tool{toolCount > 1 ? 's' : ''} will be deactivated in Context Forge</span>
                </div>
              )}

              {/* Description */}
              <p className="text-sm text-white/60 leading-relaxed">
                This will stop <span className="text-white font-medium">{server.label}</span> and
                deactivate its tools from your HomePilot instance.
              </p>

              {/* Safety info */}
              <div className="rounded-lg bg-white/5 border border-white/5 p-3 space-y-1.5">
                <p className="text-xs text-white/50">
                  <span className="text-emerald-400">Non-destructive:</span> Server files remain on disk. No data is deleted.
                </p>
                <p className="text-xs text-white/50">
                  <span className="text-emerald-400">Reversible:</span> Reinstall anytime — disabled tools will be re-enabled automatically.
                </p>
                {affectedCount > 0 && (
                  <p className="text-xs text-white/50">
                    <span className="text-amber-400">Personas:</span> Affected personas will have this tool disabled. Re-importing or reinstalling restores them.
                  </p>
                )}
              </div>
            </>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3 px-5 pb-5">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2.5 text-sm font-medium text-white/60 bg-white/5 hover:bg-white/10 rounded-xl transition-colors border border-white/10"
          >
            Cancel
          </button>
          <button
            onClick={onConfirmUninstall}
            disabled={loadingPreview}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium rounded-xl transition-colors border disabled:opacity-50 ${
              affectedCount > 0
                ? 'text-amber-200 bg-amber-500/20 hover:bg-amber-500/30 border-amber-500/30'
                : 'text-red-200 bg-red-500/20 hover:bg-red-500/30 border-red-500/30'
            }`}
          >
            {affectedCount > 0 ? 'Uninstall Anyway' : 'Uninstall'}
          </button>
        </div>
      </div>

      <style>{`
        @keyframes fade-scale-in {
          from { opacity: 0; transform: scale(0.95); }
          to { opacity: 1; transform: scale(1); }
        }
        .animate-fade-scale-in {
          animation: fade-scale-in 0.15s ease-out;
        }
      `}</style>
    </div>
  )
}
