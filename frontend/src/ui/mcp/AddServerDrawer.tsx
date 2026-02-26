import React, { useState } from 'react'
import { X, Plus, RefreshCw } from 'lucide-react'

type Props = {
  backendUrl: string
  apiKey?: string
  onClose: () => void
  onRegistered: () => void
}

const TRANSPORTS = ['SSE', 'STREAMABLEHTTP', 'HTTP', 'STDIO'] as const

export function AddServerDrawer({ backendUrl, apiKey, onClose, onRegistered }: Props) {
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [transport, setTransport] = useState<string>('SSE')
  const [description, setDescription] = useState('')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const canSubmit = name.trim() && url.trim() && !busy

  const handleSubmit = async () => {
    if (!canSubmit) return
    setBusy(true)
    setError(null)

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' }
      if (apiKey) headers['x-api-key'] = apiKey

      const res = await fetch(`${backendUrl}/v1/agentic/register/gateway`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          name: name.trim(),
          url: url.trim(),
          transport,
          description: description.trim(),
          auto_refresh: autoRefresh,
        }),
      })

      const data = await res.json()
      if (!res.ok || !data.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`)
      }

      setSuccess(true)
      setTimeout(() => {
        onRegistered()
        onClose()
      }, 1000)
    } catch (e: any) {
      setError(e?.message || 'Registration failed')
    } finally {
      setBusy(false)
    }
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
          <h2 className="text-base font-semibold text-white">Add MCP Server</h2>
          <button
            onClick={onClose}
            className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-xl transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <div className="px-6 py-6 space-y-5">
          {/* Name */}
          <div>
            <label className="text-xs font-semibold text-white/50 uppercase tracking-wide mb-1.5 block">
              Server Name *
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. my-mcp-server"
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 transition-colors"
            />
          </div>

          {/* URL */}
          <div>
            <label className="text-xs font-semibold text-white/50 uppercase tracking-wide mb-1.5 block">
              Endpoint URL *
            </label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="e.g. http://localhost:9101/rpc"
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 transition-colors"
            />
          </div>

          {/* Transport */}
          <div>
            <label className="text-xs font-semibold text-white/50 uppercase tracking-wide mb-1.5 block">
              Transport
            </label>
            <div className="flex gap-2">
              {TRANSPORTS.map((t) => (
                <button
                  key={t}
                  onClick={() => setTransport(t)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                    transport === t
                      ? 'bg-purple-500/20 border-purple-500/50 text-purple-300'
                      : 'bg-white/5 border-white/10 text-white/40 hover:text-white/60'
                  }`}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="text-xs font-semibold text-white/50 uppercase tracking-wide mb-1.5 block">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional description..."
              rows={3}
              className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 focus:outline-none focus:border-purple-500/50 transition-colors resize-none"
            />
          </div>

          {/* Auto-refresh toggle */}
          <label className="flex items-center gap-3 cursor-pointer">
            <div
              onClick={() => setAutoRefresh(!autoRefresh)}
              className={`w-10 h-5 rounded-full transition-colors relative ${
                autoRefresh ? 'bg-purple-500' : 'bg-white/10'
              }`}
            >
              <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                autoRefresh ? 'left-5' : 'left-0.5'
              }`} />
            </div>
            <span className="text-sm text-white/70">Auto-discover tools after registration</span>
          </label>

          {/* Error / Success */}
          {error && (
            <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/20 rounded-xl px-4 py-3">
              {error}
            </div>
          )}
          {success && (
            <div className="text-sm text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 rounded-xl px-4 py-3">
              Server registered successfully!
            </div>
          )}

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="w-full flex items-center justify-center gap-2 bg-purple-500 hover:bg-purple-600 disabled:bg-white/10 disabled:text-white/30 px-4 py-3 rounded-xl text-sm font-semibold transition-all"
          >
            {busy ? (
              <RefreshCw size={16} className="animate-spin" />
            ) : (
              <Plus size={16} />
            )}
            {busy ? 'Registering...' : 'Register Gateway'}
          </button>
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
