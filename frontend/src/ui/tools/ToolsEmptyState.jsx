import React from 'react';
import { Wrench } from 'lucide-react';
export function ToolsEmptyState({ loading, error, onGoToMcpServers }) {
    if (loading) {
        return (<div className="flex flex-col items-center justify-center h-64 text-white/50">
        <div className="w-8 h-8 border-2 border-white/20 border-t-purple-400 rounded-full animate-spin mb-4"/>
        <p className="text-sm">Loading capabilities catalog...</p>
      </div>);
    }
    if (error) {
        return (<div className="flex flex-col items-center justify-center h-64 text-white/50">
        <Wrench size={48} className="mb-4 opacity-30"/>
        <p className="text-lg font-semibold mb-2 text-white/70">Unable to load capabilities</p>
        <p className="text-sm text-white/40 mb-1">Could not reach the agentic catalog.</p>
        <p className="text-xs text-red-400/70 font-mono">{error}</p>
      </div>);
    }
    return (<div className="flex flex-col items-center justify-center h-64 text-white/50">
      <Wrench size={48} className="mb-4 opacity-30"/>
      <p className="text-lg font-semibold mb-2 text-white/70">No capabilities registered</p>
      <p className="text-sm text-white/40 mb-4">
        Register MCP servers or sync tools and A2A agents from Context Forge to see them here.
      </p>
      {onGoToMcpServers && (<button onClick={onGoToMcpServers} className="flex items-center gap-2 bg-white/10 hover:bg-white/20 px-4 py-2 rounded-full text-sm font-medium transition-colors">
          Go to MCP Servers
        </button>)}
    </div>);
}
