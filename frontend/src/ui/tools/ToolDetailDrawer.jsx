import React from 'react';
import { X, Wrench, Bot, Copy, Check, Globe, Users } from 'lucide-react';
import { computeBadges, deriveSourceServer } from './toolBadges';
import { ToolStatusBadge } from './ToolStatusBadge';
export function ToolDetailDrawer({ item, onClose }) {
    const { kind, data } = item;
    const isA2A = kind === 'a2a_agent';
    const a2aData = isA2A ? data : null;
    const toolUrl = kind === 'tool' ? data.url : undefined;
    const sourceServer = deriveSourceServer(toolUrl);
    const badges = computeBadges(data.name, data.description || '', isA2A ? 'A2A' : undefined, toolUrl);
    const [copied, setCopied] = React.useState(false);
    const copyId = () => {
        navigator.clipboard.writeText(data.id).catch(() => { });
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
    };
    const Icon = isA2A ? Bot : Wrench;
    const iconColor = isA2A ? 'text-violet-400' : 'text-cyan-400';
    const gradientFrom = isA2A ? 'from-violet-500/20' : 'from-cyan-500/20';
    const gradientTo = isA2A ? 'to-purple-500/20' : 'to-blue-500/20';
    return (<div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm"/>

      {/* Panel */}
      <div className="relative w-full max-w-md bg-[#0b0b12] border-l border-white/10 h-full overflow-y-auto animate-slide-in-right" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="sticky top-0 bg-[#0b0b12]/95 backdrop-blur border-b border-white/10 px-6 py-4 flex items-center justify-between z-10">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${gradientFrom} ${gradientTo} border border-white/10 flex items-center justify-center ${iconColor}`}>
              <Icon size={18}/>
            </div>
            <div>
              <h2 className="text-base font-semibold text-white">{data.name}</h2>
              <div className="flex items-center gap-2 mt-0.5">
                <ToolStatusBadge enabled={data.enabled}/>
                {sourceServer && (<>
                    <span className="text-white/20">·</span>
                    <span className="text-xs text-white/40">{sourceServer}</span>
                  </>)}
              </div>
            </div>
          </div>
          <button onClick={onClose} className="p-2 text-white/50 hover:text-white hover:bg-white/10 rounded-xl transition-colors">
            <X size={18}/>
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-6 space-y-6">
          {/* Type + Badges */}
          <div className="flex flex-wrap gap-2">
            <span className={`text-xs px-2.5 py-1 rounded-full font-semibold uppercase tracking-wide ${isA2A
            ? 'bg-violet-500/20 text-violet-300'
            : 'bg-blue-500/20 text-blue-300'}`}>
              {isA2A ? 'A2A Agent' : 'Tool'}
            </span>
            {badges.map((b) => (<span key={b.label} className={`text-xs px-2.5 py-1 rounded-full font-medium ${b.bg} ${b.color}`}>
                {b.label}
              </span>))}
          </div>

          {/* Description */}
          <div>
            <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">Description</h3>
            <p className="text-sm text-white/70 leading-relaxed">
              {data.description || 'No description available.'}
            </p>
          </div>

          {/* A2A-specific: How to use */}
          {isA2A && (<div className="rounded-xl bg-violet-500/10 border border-violet-500/20 p-4 space-y-2">
              <div className="flex items-center gap-2 text-violet-300">
                <Users size={14}/>
                <h3 className="text-xs font-semibold uppercase tracking-wide">How to Use</h3>
              </div>
              <p className="text-sm text-white/60 leading-relaxed">
                This A2A agent can be selected as a connected agent in your personas or agent projects. When enabled, your agents can delegate tasks to it.
              </p>
            </div>)}

          {/* A2A-specific: Endpoint */}
          {isA2A && a2aData?.endpoint_url && (<div>
              <h3 className="text-xs font-semibold text-white/40 uppercase tracking-wide mb-2">Endpoint</h3>
              <div className="flex items-center gap-2">
                <Globe size={14} className="text-white/30 shrink-0"/>
                <code className="text-xs text-white/60 bg-white/5 border border-white/10 rounded-lg px-3 py-2 flex-1 truncate font-mono">
                  {a2aData.endpoint_url}
                </code>
              </div>
            </div>)}

          {/* Collapsible ID */}
          <div className="pt-2 border-t border-white/5">
            <button onClick={copyId} className="flex items-center gap-2 text-[11px] text-white/30 hover:text-white/50 transition-colors" title={`Copy ${isA2A ? 'agent' : 'tool'} ID`}>
              {copied ? <Check size={11} className="text-emerald-400"/> : <Copy size={11}/>}
              <span className="font-mono truncate">{data.id}</span>
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
