import React from 'react'
import { Wrench, Bot } from 'lucide-react'
import type { CapabilityItem } from '../../agentic/types'
import { computeBadges } from './toolBadges'
import { ToolStatusBadge } from './ToolStatusBadge'

type Props = {
  item: CapabilityItem
  onClick: () => void
}

export function ToolCard({ item, onClick }: Props) {
  const { kind, data } = item
  const isA2A = kind === 'a2a_agent'
  const toolUrl = kind === 'tool' ? (data as import('../../agentic/types').CatalogTool).url : undefined
  const badges = computeBadges(data.name, data.description || '', isA2A ? 'A2A' : undefined, toolUrl)

  const Icon = isA2A ? Bot : Wrench
  const gradientFrom = isA2A ? 'from-violet-500/20' : 'from-cyan-500/20'
  const gradientTo = isA2A ? 'to-purple-500/20' : 'to-blue-500/20'
  const iconColor = isA2A ? 'text-violet-400' : 'text-cyan-400'

  return (
    <div
      onClick={onClick}
      className="flex flex-col gap-3 p-5 rounded-2xl bg-white/5 hover:bg-white/10 transition-all duration-200 cursor-pointer border border-white/10 hover:border-white/20 h-full group"
    >
      {/* Header */}
      <div className="flex justify-between items-start gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-10 h-10 shrink-0 rounded-xl bg-gradient-to-br ${gradientFrom} ${gradientTo} border border-white/10 flex items-center justify-center ${iconColor}`}>
            <Icon size={18} strokeWidth={2} />
          </div>
          <div className="min-w-0">
            <h3 className="font-semibold text-sm text-white truncate">{data.name}</h3>
            <ToolStatusBadge enabled={data.enabled} />
          </div>
        </div>
        {/* Type chip */}
        <span className={`shrink-0 text-[10px] px-2 py-0.5 rounded-full font-semibold uppercase tracking-wide ${
          isA2A
            ? 'bg-violet-500/20 text-violet-300'
            : 'bg-blue-500/20 text-blue-300'
        }`}>
          {isA2A ? 'A2A' : 'Tool'}
        </span>
      </div>

      {/* Description */}
      <p className="text-sm text-white/60 leading-relaxed line-clamp-2 flex-1">
        {data.description || 'No description available'}
      </p>

      {/* Badges */}
      <div className="flex flex-wrap gap-1.5">
        {badges.map((b) => (
          <span key={b.label} className={`text-xs px-2 py-0.5 rounded-full font-medium ${b.bg} ${b.color}`}>
            {b.label}
          </span>
        ))}
      </div>
    </div>
  )
}
