import React from 'react'
import type { CapabilityItem } from '../../agentic/types'
import { ToolCard } from './ToolCard'

type Props = {
  items: CapabilityItem[]
  onSelect: (item: CapabilityItem) => void
}

export function ToolsGrid({ items, onSelect }: Props) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {items.map((item) => (
        <ToolCard key={`${item.kind}-${item.data.id}`} item={item} onClick={() => onSelect(item)} />
      ))}
    </div>
  )
}
