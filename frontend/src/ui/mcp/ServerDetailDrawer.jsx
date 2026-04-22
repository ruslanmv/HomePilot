import React, { useCallback, useEffect, useState } from 'react';
import { X, Radio, Boxes, Copy, Check, RefreshCw, CheckCircle } from 'lucide-react';
export function ServerDetailDrawer({ server, catalogTools, backendUrl, apiKey, onClose, onRepaired }) {
    const isGateway = server.kind === 'gateway';
    const Icon = isGateway ? Radio : Boxes;
    const [copied, setCopied] = React.useState(false);
    const [repairing, setRepairing] = useState(false);
    const [repairResult, setRepairResult] = useState(null);
    const [serverTools, setServerTools] = useState(null);
    const [loadingTools, setLoadingTools] = useState(false);
    // Derive status consistently with InstalledServerCard
    const hasTools = server.toolCount > 0 || (serverTools !== null && serverTools.length > 0);
    const isEnabled = server.enabled === true;
    const status = !isEnabled
        ? 'disconnected'
        : server.kind === 'server' && !hasTools
            ? 'empty'
            : 'connected';
    const copyId = () => {
        navigator.clipboard.writeText(server.id).catch(() => { });
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
    };
    // For virtual servers, fetch full tool objects from the proxy endpoint
    const fetchServerTools = useCallback(async () => {
        if (isGateway)
            return;
        setLoadingTools(true);
        try {
            const headers = {};
            if (apiKey)
                headers['x-api-key'] = apiKey;
            const res = await fetch(`${backendUrl}/v1/agentic/servers/${server.id}/tools`, { headers });
            if (res.ok) {
                const data = await res.json();
                if (Array.isArray(data)) {
                    setServerTools(data.map((t) => ({
                        id: t.id || t.name || '',
                        name: t.name || t.original_name || t.id || '',
                        description: t.description || '',
                        enabled: t.enabled !== false,
                    })));
                    setLoadingTools(false);
                    return;
                }
            }
        }
        catch {
            // fall through to catalog resolution
        }
        // Fallback: resolve tool IDs from catalog
        if (server.toolIds.length > 0) {
            const idSet = new Set(server.toolIds);
            const resolved = catalogTools
                .filter((t) => idSet.has(t.id))
                .map((t) => ({ id: t.id, name: t.name, description: t.description, enabled: t.enabled !== false }));
            setServerTools(resolved);
        }
        else {
            setServerTools([]);
        }
        setLoadingTools(false);
    }, [isGateway, backendUrl, apiKey, server.id, server.toolIds, catalogTools]);
    useEffect(() => {
        fetchServerTools();
    }, [fetchServerTools]);
    // Resolve tools for gateways from catalog by matching IDs
    const gatewayResolvedTools = React.useMemo(() => {
        if (!isGateway || server.toolIds.length === 0)
            return [];
        const idSet = new Set(server.toolIds);
        return catalogTools.filter((t) => idSet.has(t.id));
    }, [isGateway, server.toolIds, catalogTools]);
    const handleRepair = async () => {
        setRepairing(true);
        setRepairResult(null);
        try {
            const headers = { 'Content-Type': 'application/json' };
            if (apiKey)
                headers['x-api-key'] = apiKey;
            const res = await fetch(`${backendUrl}/v1/agentic/sync`, { method: 'POST', headers });
            if (res.ok) {
                const data = await res.json();
                if (data?.sync)
                    setRepairResult(data.sync);
                await fetchServerTools();
                onRepaired?.();
            }
        }
        catch {
            // non-fatal
        }
        finally {
            setRepairing(false);
        }
    };
    const effectiveTools = isGateway ? gatewayResolvedTools : (serverTools || []);
    const toolCount = isGateway ? gatewayResolvedTools.length : (serverTools?.length ?? server.toolCount);
    const statusDot = {
        connected: 'bg-emerald-400',
        empty: 'bg-amber-400',
        disconnected: 'bg-yellow-400',
    }[status];
    const statusLabel = {
        connected: `Active \u00b7 ${toolCount} tool${toolCount !== 1 ? 's' : ''}`,
        empty: 'No tools linked',
        disconnected: 'Disconnected',
    }[status];
    const statusTextColor = {
        connected: 'text-emerald-300',
        empty: 'text-amber-300',
        disconnected: 'text-yellow-300',
    }[status];
    return (<div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm"/>

      {/* Panel */}
      <div className="relative w-full max-w-md bg-[#0b0b12] border-l border-white/10 h-full overflow-y-auto animate-slide-in-right" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="sticky top-0 bg-[#0b0b12]/95 backdrop-blur border-b border-white/10 px-6 py-4 flex items-center justify-between z-10">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-xl bg-gradient-to-br border border-white/10 flex items-center justify-center ${isGateway
            ? 'from-emerald-500/20 to-teal-500/20 text-emerald-400'
            : status === 'connected'
                ? 'from-violet-500/20 to-purple-500/20 text-violet-400'
                : 'from-amber-500/10 to-orange-500/10 text-amber-400/60'}`}>
              <Icon size={18}/>
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">{server.name}</h2>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-xs text-white/40">
                  {isGateway ? 'Gateway' : 'Tool Bundle'}
                </span>
                <span className="text-white/20">·</span>
                <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${statusTextColor}`}>
                  <span className={`w-1.5 h-1.5 rounded-full ${statusDot}`}/>
                  {statusLabel}
                </span>
              </div>
            </div>
          </div>
          <button onClick={onClose} className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-xl transition-colors">
            <X size={18}/>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-6 space-y-5">
          {/* Description */}
          {server.description && (<p className="text-sm text-white/60 leading-relaxed">{server.description}</p>)}

          {/* Endpoint (gateways only) */}
          {isGateway && server.url && (<div>
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">Endpoint</h3>
              <code className="text-xs text-white/60 bg-white/5 border border-white/10 rounded-lg px-3 py-2 block font-mono break-all">
                {server.url}
              </code>
            </div>)}

          {/* Repair result feedback */}
          {repairResult && (<div className={`flex items-start gap-2.5 px-3 py-2.5 rounded-lg border ${repairResult.mcp_servers_reachable > 0
                ? 'border-emerald-500/20 bg-emerald-500/5'
                : 'border-amber-500/20 bg-amber-500/5'}`}>
              <CheckCircle size={14} className={`shrink-0 mt-0.5 ${repairResult.mcp_servers_reachable > 0 ? 'text-emerald-400' : 'text-amber-400'}`}/>
              <div className="text-xs text-white/60 leading-relaxed">
                {repairResult.tools_registered > 0
                ? `Synced ${repairResult.tools_registered} tool${repairResult.tools_registered !== 1 ? 's' : ''}. `
                : 'No new tools found. '}
                {repairResult.mcp_servers_reachable}/{repairResult.mcp_servers_total} servers reachable.
              </div>
            </div>)}

          {/* Tools */}
          <div>
            <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">
              Tools ({loadingTools ? '...' : toolCount})
            </h3>

            {loadingTools && (<div className="flex items-center gap-2 text-sm text-white/40 py-2">
                <RefreshCw size={14} className="animate-spin"/>
                Loading...
              </div>)}

            {!loadingTools && effectiveTools.length > 0 ? (<div className="space-y-1.5 max-h-64 overflow-y-auto">
                {effectiveTools.map((t) => (<div key={t.id} className="flex items-start gap-2.5 px-3 py-2 rounded-lg bg-white/5 border border-white/5">
                    <span className={`w-1.5 h-1.5 rounded-full mt-1.5 shrink-0 ${t.enabled !== false ? 'bg-emerald-400/60' : 'bg-white/20'}`}/>
                    <div className="min-w-0 flex-1">
                      <div className="text-xs text-white/70 font-medium truncate">{t.name}</div>
                      {t.description && (<div className="text-[11px] text-white/40 truncate mt-0.5">{t.description}</div>)}
                    </div>
                  </div>))}
              </div>) : !loadingTools && effectiveTools.length === 0 ? (<p className="text-sm text-white/40">No tools linked yet. Try Sync All below.</p>) : null}
          </div>

          {/* Sync CTA (virtual servers only) */}
          {!isGateway && (<button onClick={handleRepair} disabled={repairing} className="flex items-center gap-2 w-full justify-center px-4 py-2.5 text-xs font-medium text-violet-300 bg-violet-500/10 hover:bg-violet-500/20 rounded-xl transition-colors disabled:opacity-50 border border-violet-500/20">
              <RefreshCw size={14} className={repairing ? 'animate-spin' : ''}/>
              {repairing ? 'Syncing...' : 'Sync All'}
            </button>)}

          {/* Collapsible ID */}
          <div className="pt-2 border-t border-white/5">
            <button onClick={copyId} className="flex items-center gap-2 text-[11px] text-white/30 hover:text-white/50 transition-colors" title="Copy server ID">
              {copied ? <Check size={11} className="text-emerald-400"/> : <Copy size={11}/>}
              <span className="font-mono truncate">{server.id}</span>
            </button>
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
    </div>);
}
