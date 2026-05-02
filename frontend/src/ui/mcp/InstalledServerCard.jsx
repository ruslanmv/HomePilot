import React from 'react';
import { Radio, Boxes } from 'lucide-react';
export function InstalledServerCard({ server, onClick }) {
    const isGateway = server.kind === 'gateway';
    const Icon = isGateway ? Radio : Boxes;
    // Status logic:
    // - connected: has tools and is enabled (normal active server)
    // - offline: has tools but is disabled (was installed, now unreachable)
    // - not-installed: 0 tools (shouldn't normally appear — filtered out upstream)
    const hasTools = server.toolCount > 0;
    const isEnabled = server.enabled !== false;
    const status = hasTools && isEnabled
        ? 'connected'
        : hasTools && !isEnabled
            ? 'offline'
            : 'not-installed';
    const statusColor = {
        connected: 'text-emerald-300',
        offline: 'text-amber-300',
        'not-installed': 'text-white/30',
    }[status] ?? 'text-white/40';
    const dotColor = {
        connected: 'bg-emerald-400',
        offline: 'bg-amber-400',
        'not-installed': 'bg-white/20',
    }[status] ?? 'bg-white/30';
    const statusLabel = {
        connected: `${server.toolCount} tool${server.toolCount !== 1 ? 's' : ''}`,
        offline: 'Offline',
        'not-installed': 'Not installed',
    }[status] ?? 'Unknown';
    return (<div onClick={onClick} className="flex flex-col gap-3 p-5 rounded-2xl bg-white/5 hover:bg-white/10 transition-all duration-200 cursor-pointer border border-white/10 hover:border-white/20 h-full group">
      {/* Header */}
      <div className="flex justify-between items-start gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br border border-white/10 flex items-center justify-center ${isGateway
            ? 'from-emerald-500/20 to-teal-500/20 text-emerald-400'
            : status === 'connected'
                ? 'from-violet-500/20 to-purple-500/20 text-violet-400'
                : 'from-amber-500/10 to-orange-500/10 text-amber-400/60'}`}>
            <Icon size={18} strokeWidth={2}/>
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-sm text-white truncate">{server.name}</h3>
            <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${statusColor}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`}/>
              {statusLabel}
            </span>
          </div>
        </div>
      </div>

      {/* Description */}
      <p className="text-sm text-white/60 leading-relaxed line-clamp-2 flex-1">
        {server.description}
      </p>

      {/* Footer badges */}
      <div className="flex items-center gap-2">
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${isGateway ? 'bg-emerald-500/20 text-emerald-300' : 'bg-violet-500/20 text-violet-300'}`}>
          {isGateway ? 'Gateway' : 'Virtual Server'}
        </span>
        {server.transport && (<span className="text-xs px-2 py-0.5 rounded-full font-medium bg-white/5 text-white/40">
            {server.transport}
          </span>)}
        {server.toolCount > 0 && (<span className="text-xs text-white/40">
            {server.toolCount} tool{server.toolCount !== 1 ? 's' : ''}
          </span>)}
        {status === 'offline' && (<span className="text-xs text-amber-400/70">
            Server unreachable
          </span>)}
      </div>
    </div>);
}
