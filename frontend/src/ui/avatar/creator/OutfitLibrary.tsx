/**
 * OutfitLibrary — Left-panel section showing outfits generated during
 * the current wizard session.
 *
 * Displays small rectangular thumbnails (portrait aspect) of each outfit
 * linked to the active identity. Each thumbnail has a delete button on hover.
 * Lets the user see at a glance what outfits they've created in this session.
 */

import React from 'react'
import { Shirt, Trash2, Eye } from 'lucide-react'
import type { GalleryItem } from '../galleryTypes'
import { SCENARIO_TAG_META } from '../galleryTypes'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface OutfitLibraryProps {
  /** Full gallery items. */
  items: GalleryItem[]
  /** Currently active identity — outfits shown are children of this identity. */
  activeIdentityId: string | null
  /** URL of the currently active/displayed outfit (for highlight). */
  activeOutfitUrl?: string | null
  /** Callback when user clicks an outfit to preview it on stage. */
  onSelectOutfit?: (item: GalleryItem) => void
  /** Callback to delete an outfit from the gallery. */
  onDeleteOutfit?: (item: GalleryItem) => void
  resolveUrl: (url: string) => string
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OutfitLibrary({
  items,
  activeIdentityId,
  activeOutfitUrl,
  onSelectOutfit,
  onDeleteOutfit,
  resolveUrl,
}: OutfitLibraryProps) {
  // Outfits are gallery items that have parentId matching the active identity
  // and a scenarioTag (which distinguishes them from portrait alternatives).
  const outfits = activeIdentityId
    ? items.filter(
        (i) => i.parentId === activeIdentityId && i.scenarioTag,
      )
    : []

  if (!activeIdentityId) return null

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Shirt size={10} className="text-cyan-400/60" />
          <span className="text-[9px] text-white/35 font-semibold uppercase tracking-wider">
            Outfits
          </span>
        </div>
        <span className="text-[9px] text-white/20">{outfits.length}</span>
      </div>

      {outfits.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {outfits.map((outfit) => {
            const meta = outfit.scenarioTag
              ? SCENARIO_TAG_META.find((m) => m.id === outfit.scenarioTag)
              : null
            const isActive = activeOutfitUrl && outfit.url === activeOutfitUrl
            return (
              <div
                key={outfit.id}
                className="relative group"
              >
                <button
                  onClick={() => onSelectOutfit?.(outfit)}
                  className={[
                    'w-[42px] h-[56px] rounded-lg overflow-hidden border-2 transition-all',
                    isActive
                      ? 'border-cyan-400 ring-1 ring-cyan-400/30 shadow-[0_0_8px_rgba(34,211,238,0.25)]'
                      : 'border-white/[0.08] hover:border-cyan-500/40',
                  ].join(' ')}
                  title={meta ? `${meta.icon} ${meta.label}` : 'Outfit'}
                >
                  <img
                    src={resolveUrl(outfit.url)}
                    alt={meta?.label || 'Outfit'}
                    className="w-full h-full object-cover"
                    loading="lazy"
                  />
                  {/* Scenario tag overlay */}
                  <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent px-0.5 py-0.5">
                    <span className="text-[7px] text-white/60 leading-none block truncate text-center">
                      {meta?.icon || '✨'}
                    </span>
                  </div>
                </button>
                {/* Delete button on hover */}
                {onDeleteOutfit && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      onDeleteOutfit(outfit)
                    }}
                    className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-red-500/80 hover:bg-red-500 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-sm"
                    title="Delete outfit"
                  >
                    <Trash2 size={8} className="text-white" />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <p className="text-[10px] text-white/15 text-center py-1.5">
          No outfits yet — generate some in Step {'\u2461'}
        </p>
      )}
    </div>
  )
}
