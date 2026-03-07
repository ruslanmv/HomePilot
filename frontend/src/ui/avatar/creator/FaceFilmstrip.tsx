/**
 * FaceFilmstrip — Horizontal strip of face/outfit result thumbnails.
 *
 * MMORPG-style: click a thumbnail to set it as the main stage preview.
 * Hover to reveal a delete (X) button on each thumbnail.
 * Shows below the CharacterStage.
 */

import React from 'react'
import { X } from 'lucide-react'
import type { AvatarResult } from '../types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface FaceFilmstripProps {
  results: AvatarResult[]
  selectedIndex: number
  onSelect: (index: number) => void
  onDelete?: (index: number) => void
  resolveUrl: (url: string) => string
  accent?: 'purple' | 'cyan'
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function FaceFilmstrip({
  results,
  selectedIndex,
  onSelect,
  onDelete,
  resolveUrl,
  accent = 'purple',
}: FaceFilmstripProps) {
  if (results.length <= 1) return null

  const borderActive = accent === 'purple'
    ? 'border-purple-500/60 ring-1 ring-purple-500/20'
    : 'border-cyan-500/60 ring-1 ring-cyan-500/20'

  return (
    <div className="flex gap-2 overflow-x-auto scrollbar-hide justify-center py-2">
      {results.map((r, i) => (
        <div key={i} className="relative group flex-shrink-0">
          <button
            onClick={() => onSelect(i)}
            className={[
              'w-14 h-14 rounded-xl overflow-hidden border-2 transition-all hover:scale-105',
              selectedIndex === i
                ? borderActive
                : 'border-white/10 hover:border-white/25',
            ].join(' ')}
          >
            <img
              src={resolveUrl(r.url)}
              alt={`Result ${i + 1}`}
              className="w-full h-full object-cover"
              loading="lazy"
            />
          </button>
          {/* Delete button — appears on hover */}
          {onDelete && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onDelete(i)
              }}
              className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-red-500/90 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600 shadow-lg z-10"
              title="Remove this face"
            >
              <X size={10} />
            </button>
          )}
        </div>
      ))}
    </div>
  )
}
