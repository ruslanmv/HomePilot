/**
 * FaceFilmstrip — Horizontal strip of face/outfit result thumbnails.
 *
 * MMORPG-style: click a thumbnail to set it as the main stage preview.
 * Hover to reveal a delete (X) button on each thumbnail.
 * Shows below the CharacterStage.
 *
 * When results carry a `scenarioTag`, a small icon badge appears at the
 * bottom-right corner so users can distinguish outfit styles at a glance.
 */

import React from 'react'
import { X } from 'lucide-react'
import type { AvatarResult } from '../types'
import { SCENARIO_TAG_META } from '../galleryTypes'

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
  /** When true, show scenario-tag icon badges on thumbnails (for outfit filmstrips). */
  showScenarioTags?: boolean
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
  showScenarioTags = false,
}: FaceFilmstripProps) {
  if (results.length <= 1) return null

  const borderActive = accent === 'purple'
    ? 'border-purple-500/60 ring-1 ring-purple-500/20'
    : 'border-cyan-500/60 ring-1 ring-cyan-500/20'

  return (
    <div className="flex gap-2 overflow-x-auto scrollbar-hide justify-center py-2">
      {results.map((r, i) => {
        const tagMeta = showScenarioTags && r.scenarioTag
          ? SCENARIO_TAG_META.find((t) => t.id === r.scenarioTag)
          : undefined
        return (
          <div key={i} className="relative group flex-shrink-0">
            <button
              onClick={() => onSelect(i)}
              className={[
                'w-14 h-14 rounded-xl overflow-hidden border-2 transition-all hover:scale-105',
                selectedIndex === i
                  ? borderActive
                  : 'border-white/10 hover:border-white/25',
              ].join(' ')}
              title={tagMeta ? tagMeta.label : `Result ${i + 1}`}
            >
              <img
                src={resolveUrl(r.url)}
                alt={tagMeta ? `${tagMeta.label} outfit` : `Result ${i + 1}`}
                className="w-full h-full object-cover"
                loading="lazy"
              />
              {/* Scenario tag badge — bottom-right icon */}
              {tagMeta && (
                <span
                  className="absolute bottom-0.5 right-0.5 w-5 h-5 rounded-md bg-black/60 backdrop-blur-sm flex items-center justify-center text-[10px] border border-white/[0.08]"
                  title={tagMeta.label}
                >
                  {tagMeta.icon}
                </span>
              )}
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
        )
      })}
    </div>
  )
}
