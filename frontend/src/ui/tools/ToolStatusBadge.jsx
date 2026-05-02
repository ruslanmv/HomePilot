import React from 'react';
const STATUS_CONFIG = {
    active: { dot: 'bg-emerald-400', label: 'Active', text: 'text-emerald-300' },
    inactive: { dot: 'bg-yellow-400', label: 'Inactive', text: 'text-yellow-300' },
    unavailable: { dot: 'bg-white/30', label: 'Unavailable', text: 'text-white/40' },
};
export function deriveStatus(enabled) {
    if (enabled === true)
        return 'active';
    if (enabled === false)
        return 'inactive';
    return 'unavailable';
}
export function ToolStatusBadge({ enabled }) {
    const status = deriveStatus(enabled);
    const cfg = STATUS_CONFIG[status];
    return (<span className={`inline-flex items-center gap-1.5 text-xs font-medium ${cfg.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`}/>
      {cfg.label}
    </span>);
}
