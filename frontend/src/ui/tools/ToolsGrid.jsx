import React from 'react';
import { ToolCard } from './ToolCard';
export function ToolsGrid({ items, onSelect }) {
    return (<div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      {items.map((item) => (<ToolCard key={`${item.kind}-${item.data.id}`} item={item} onClick={() => onSelect(item)}/>))}
    </div>);
}
