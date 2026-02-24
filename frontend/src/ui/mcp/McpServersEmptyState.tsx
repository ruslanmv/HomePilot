import React from 'react'
import { Server, Plus } from 'lucide-react'

type Props = {
  loading?: boolean
  error?: string | null
  onAddServer?: () => void
}

export function McpServersEmptyState({ loading, error, onAddServer }: Props) {
  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-white/50">
        <div className="w-8 h-8 border-2 border-white/20 border-t-purple-400 rounded-full animate-spin mb-4" />
        <p className="text-sm">Loading MCP servers...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-white/50">
        <Server size={48} className="mb-4 opacity-30" />
        <p className="text-lg font-semibold mb-2 text-white/70">Unable to load servers</p>
        <p className="text-sm text-white/40 mb-1">Could not reach the agentic catalog.</p>
        <p className="text-xs text-red-400/70 font-mono">{error}</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center justify-center h-64 text-white/50">
      <Server size={48} className="mb-4 opacity-30" />
      <p className="text-lg font-semibold mb-2 text-white/70">No MCP servers connected</p>
      <p className="text-sm text-white/40 mb-4">
        Add an MCP gateway or sync with Context Forge to get started.
      </p>
      {onAddServer && (
        <button
          onClick={onAddServer}
          className="flex items-center gap-2 bg-white/10 hover:bg-white/20 px-4 py-2 rounded-full text-sm font-medium transition-colors"
        >
          <Plus size={16} />
          Add Server
        </button>
      )}
    </div>
  )
}
