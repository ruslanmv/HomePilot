/**
 * McpUninstallDialog — confirmation modal before removing a registered MCP server.
 *
 * Non-destructive UX: clearly tells the user what will and won't be affected.
 *
 * Phase 10 — fully additive, does not modify any existing component.
 */

import React, { useState } from 'react'
import { AlertTriangle, Loader2, X } from 'lucide-react'
import type { RegistryServer } from '../../agentic/types'

type Props = {
  server: RegistryServer
  backendUrl: string
  apiKey?: string
  onClose: () => void
  onUninstalled: () => void
}

export function McpUninstallDialog({ server, backendUrl, apiKey, onClose, onUninstalled }: Props) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleUninstall = async () => {
    setBusy(true)
    setError(null)

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (apiKey) headers['x-api-key'] = apiKey

      const res = await fetch(
        `${backendUrl}/v1/agentic/registry/${encodeURIComponent(server.id)}/unregister`,
        { method: 'POST', headers },
      )

      if (!res.ok) {
        const json = await res.json().catch(() => ({}))
        throw new Error(json.detail || json.message || `HTTP ${res.status}`)
      }

      onUninstalled()
      onClose()
    } catch (e: any) {
      setError(e?.message || 'Uninstall failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" />

      {/* Dialog */}
      <div
        className="relative w-full max-w-sm bg-[#0f0f18] border border-white/10 rounded-2xl shadow-2xl overflow-hidden animate-fade-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-2">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center justify-center">
              <AlertTriangle size={18} className="text-red-400" />
            </div>
            <h3 className="text-sm font-semibold text-white">Uninstall {server.name}?</h3>
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
          <p className="text-sm text-white/60 leading-relaxed">
            This will remove <span className="text-white font-medium">{server.name}</span> and
            its discovered tools from your HomePilot instance.
          </p>
          <div className="rounded-lg bg-white/5 border border-white/5 p-3 space-y-1.5">
            <p className="text-xs text-white/50">
              <span className="text-emerald-400">Safe:</span> Your {server.provider} account and data will not be affected.
            </p>
            <p className="text-xs text-white/50">
              <span className="text-emerald-400">Reversible:</span> You can re-add this server from the Discover tab at any time.
            </p>
          </div>

          {error && (
            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3 px-5 pb-5">
          <button
            onClick={onClose}
            disabled={busy}
            className="flex-1 px-4 py-2.5 text-sm font-medium text-white/60 bg-white/5 hover:bg-white/10 rounded-xl transition-colors border border-white/10"
          >
            Cancel
          </button>
          <button
            onClick={handleUninstall}
            disabled={busy}
            className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 text-sm font-medium text-red-200 bg-red-500/20 hover:bg-red-500/30 rounded-xl transition-colors border border-red-500/30 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 size={14} className="animate-spin" />
            ) : null}
            {busy ? 'Removing...' : 'Uninstall'}
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
