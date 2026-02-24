import React from 'react'

type Status = 'active' | 'inactive' | 'unavailable'

const STATUS_CONFIG: Record<Status, { dot: string; label: string; text: string }> = {
  active:      { dot: 'bg-emerald-400', label: 'Active',      text: 'text-emerald-300' },
  inactive:    { dot: 'bg-yellow-400',  label: 'Inactive',    text: 'text-yellow-300' },
  unavailable: { dot: 'bg-white/30',    label: 'Unavailable', text: 'text-white/40' },
}

export function deriveStatus(enabled?: boolean | null): Status {
  if (enabled === true) return 'active'
  if (enabled === false) return 'inactive'
  return 'unavailable'
}

export function ToolStatusBadge({ enabled }: { enabled?: boolean | null }) {
  const status = deriveStatus(enabled)
  const cfg = STATUS_CONFIG[status]

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${cfg.text}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
      {cfg.label}
    </span>
  )
}
