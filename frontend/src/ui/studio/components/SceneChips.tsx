import React, { useState } from 'react'
import { Check, Loader2, AlertCircle, ImageIcon, X } from 'lucide-react'

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

export type SceneChipStatus = 'pending' | 'generating' | 'ready' | 'error'

export type SceneChipData = {
  idx: number
  status: SceneChipStatus
  thumbnailUrl?: string | null
  label?: string
}

type SceneChipsProps = {
  scenes: SceneChipData[]
  activeIndex: number
  onSelect: (idx: number) => void
  onDelete?: (idx: number) => void
  className?: string
}

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

/**
 * Horizontal rail of scene chips, similar to Imagine's variation chips.
 * Shows scene thumbnails with status indicators - clean, minimal design.
 */
export function SceneChips({ scenes, activeIndex, onSelect, onDelete, className = '' }: SceneChipsProps) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null)

  if (scenes.length === 0) return null

  const handleDeleteClick = (e: React.MouseEvent, idx: number) => {
    e.stopPropagation()
    e.preventDefault()

    // Use confirm dialog for clarity
    if (window.confirm(`Delete scene ${idx + 1}? This cannot be undone.`)) {
      console.log('[SceneChips] Deleting scene:', idx)
      onDelete?.(idx)
    }
  }

  return (
    <div className={`w-full overflow-x-auto scrollbar-hide bg-black/40 ${className}`}>
      <div className="flex gap-2 px-4 py-3 min-w-max">
        {scenes.map((scene) => {
          const isActive = scene.idx === activeIndex
          const hasThumb = Boolean(scene.thumbnailUrl)
          const isHovered = hoveredIdx === scene.idx
          const showDelete = onDelete && isHovered && scenes.length > 1

          return (
            <div
              key={scene.idx}
              className="relative"
              onMouseEnter={() => setHoveredIdx(scene.idx)}
              onMouseLeave={() => setHoveredIdx(null)}
            >
              <button
                onClick={() => onSelect(scene.idx)}
                className={`
                  relative rounded-lg overflow-hidden transition-all
                  ${isActive
                    ? 'ring-2 ring-purple-500 ring-offset-2 ring-offset-black'
                    : 'opacity-70 hover:opacity-100'
                  }
                `}
                type="button"
                title={scene.label || `Scene ${scene.idx + 1}`}
              >
                {/* Thumbnail */}
                <div className="w-16 h-10 flex items-center justify-center bg-white/5">
                  {hasThumb ? (
                    <img
                      src={scene.thumbnailUrl!}
                      alt={`Scene ${scene.idx + 1}`}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <ImageIcon size={16} className="text-white/30" />
                  )}
                </div>

                {/* Status Indicator (overlay) */}
                <div className="absolute bottom-1 right-1">
                  <StatusIndicator status={scene.status} />
                </div>
              </button>

              {/* Delete Button */}
              {showDelete && (
                <button
                  onClick={(e) => handleDeleteClick(e, scene.idx)}
                  className="absolute -top-2 -right-2 w-5 h-5 rounded-full flex items-center justify-center transition-all transform hover:scale-110 bg-black/80 text-white/70 hover:text-white hover:bg-red-500"
                  type="button"
                  title="Delete scene"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          )
        })}
      </div>

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
      `}</style>
    </div>
  )
}

// -----------------------------------------------------------------------------
// Sub-components
// -----------------------------------------------------------------------------

function StatusIndicator({ status }: { status: SceneChipStatus }) {
  switch (status) {
    case 'generating':
      return (
        <div className="w-4 h-4 rounded-full bg-black/60 flex items-center justify-center">
          <Loader2 size={10} className="text-purple-400 animate-spin" />
        </div>
      )
    case 'ready':
      // Ready state - no indicator needed (clean look)
      return null
    case 'error':
      return (
        <div className="w-4 h-4 rounded-full bg-red-500/80 flex items-center justify-center">
          <AlertCircle size={10} className="text-white" />
        </div>
      )
    case 'pending':
    default:
      return (
        <div className="w-4 h-4 rounded-full bg-black/60 flex items-center justify-center">
          <div className="w-2 h-2 rounded-full bg-white/40" />
        </div>
      )
  }
}

export default SceneChips
