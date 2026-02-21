/**
 * AvatarGallery — horizontal filmstrip of saved avatars.
 *
 * Additive component — rendered below the results grid in AvatarStudio.
 * Persistent via localStorage (useAvatarGallery hook).
 *
 * Features:
 *   - Horizontal scrollable filmstrip (matches Edit history strip aesthetic)
 *   - Hover actions: View (lightbox), Open in Edit, Outfit Variations, Save as Persona, Delete
 *   - "Clear Gallery" confirmation
 *   - Empty state
 */

import React, { useState, useCallback } from 'react'
import {
  Trash2,
  Maximize2,
  PenLine,
  Download,
  X,
  Shirt,
  UserPlus,
  Image as ImageIcon,
} from 'lucide-react'
import type { GalleryItem } from './galleryTypes'
import { SCENARIO_TAG_META } from './galleryTypes'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface AvatarGalleryProps {
  items: GalleryItem[]
  backendUrl: string
  onDelete: (id: string) => void
  onClearAll: () => void
  onOpenLightbox?: (imageUrl: string) => void
  onSendToEdit?: (imageUrl: string) => void
  onSaveAsPersonaAvatar?: (item: GalleryItem) => void
  onGenerateOutfits?: (item: GalleryItem) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTimeAgo(timestamp: number): string {
  const seconds = Math.floor((Date.now() - timestamp) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

function resolveUrl(url: string, backendUrl: string): string {
  if (url.startsWith('http')) return url
  return `${backendUrl.replace(/\/+$/, '')}${url}`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AvatarGallery({
  items,
  backendUrl,
  onDelete,
  onClearAll,
  onOpenLightbox,
  onSendToEdit,
  onSaveAsPersonaAvatar,
  onGenerateOutfits,
}: AvatarGalleryProps) {
  const [confirmClear, setConfirmClear] = useState(false)

  const handleClear = useCallback(() => {
    if (confirmClear) {
      onClearAll()
      setConfirmClear(false)
    } else {
      setConfirmClear(true)
      setTimeout(() => setConfirmClear(false), 3000)
    }
  }, [confirmClear, onClearAll])

  if (items.length === 0) {
    return (
      <div className="mt-6 pt-5 border-t border-white/5">
        <div className="text-xs uppercase tracking-wider text-white/30 font-semibold mb-3 flex items-center gap-2">
          <ImageIcon size={14} />
          Avatar Gallery
        </div>
        <div className="text-center py-6 text-white/15 text-xs">
          Generated avatars will be saved here automatically
        </div>
      </div>
    )
  }

  return (
    <div className="mt-6 pt-5 border-t border-white/5">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs uppercase tracking-wider text-white/30 font-semibold flex items-center gap-2">
          <ImageIcon size={14} />
          Avatar Gallery
          <span className="text-white/20 normal-case tracking-normal font-normal">
            ({items.length})
          </span>
        </div>
        <button
          onClick={handleClear}
          className={`text-[10px] px-2 py-1 rounded-md transition-all ${
            confirmClear
              ? 'bg-red-500/20 border border-red-500/30 text-red-400'
              : 'text-white/25 hover:text-white/50'
          }`}
        >
          {confirmClear ? 'Confirm clear?' : 'Clear all'}
        </button>
      </div>

      {/* Scrollable filmstrip */}
      <div className="flex gap-2.5 overflow-x-auto pb-2 scrollbar-thin scrollbar-thumb-white/10 scrollbar-track-transparent">
        {items.map((item) => (
          <GalleryThumbnail
            key={item.id}
            item={item}
            backendUrl={backendUrl}
            onDelete={onDelete}
            onOpenLightbox={onOpenLightbox}
            onSendToEdit={onSendToEdit}
            onSaveAsPersonaAvatar={onSaveAsPersonaAvatar}
            onGenerateOutfits={onGenerateOutfits}
          />
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Gallery Thumbnail
// ---------------------------------------------------------------------------

function GalleryThumbnail({
  item,
  backendUrl,
  onDelete,
  onOpenLightbox,
  onSendToEdit,
  onSaveAsPersonaAvatar,
  onGenerateOutfits,
}: {
  item: GalleryItem
  backendUrl: string
  onDelete: (id: string) => void
  onOpenLightbox?: (imageUrl: string) => void
  onSendToEdit?: (imageUrl: string) => void
  onSaveAsPersonaAvatar?: (item: GalleryItem) => void
  onGenerateOutfits?: (item: GalleryItem) => void
}) {
  const imgUrl = resolveUrl(item.url, backendUrl)

  return (
    <div className="group relative flex-shrink-0 w-28 rounded-lg overflow-hidden border border-white/8 bg-white/[0.02] hover:border-white/20 transition-all">
      {/* Image */}
      <div
        className="aspect-square bg-white/[0.03] cursor-pointer relative"
        onClick={() => onOpenLightbox?.(imgUrl)}
      >
        <img
          src={imgUrl}
          alt={`Avatar${item.seed !== undefined ? `, seed ${item.seed}` : ''}`}
          className="w-full h-full object-cover"
          loading="lazy"
        />

        {/* Scenario tag badge */}
        {item.scenarioTag && (() => {
          const tagMeta = SCENARIO_TAG_META.find((t) => t.id === item.scenarioTag)
          return tagMeta ? (
            <div className="absolute top-1 left-1 px-1 py-0.5 rounded bg-black/50 backdrop-blur-sm text-[7px] text-white/60 font-medium flex items-center gap-0.5 border border-white/[0.08]">
              <span>{tagMeta.icon}</span>
            </div>
          ) : null
        })()}

        {/* Persona badge */}
        {item.personaProjectId && !item.scenarioTag && (
          <div className="absolute top-1 left-1 px-1.5 py-0.5 rounded bg-purple-500/30 text-purple-200 text-[8px] font-medium backdrop-blur-sm">
            Persona
          </div>
        )}

        {/* Hover overlay */}
        <div className="absolute inset-0 bg-black/70 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex flex-col items-center justify-center gap-1.5 p-1.5">
          <div className="flex items-center gap-1">
            {onOpenLightbox && (
              <button
                onClick={(e) => { e.stopPropagation(); onOpenLightbox(imgUrl) }}
                className="p-1.5 bg-white/10 rounded-md text-white/80 hover:bg-white/20 transition-colors"
                title="View full size"
              >
                <Maximize2 size={12} />
              </button>
            )}
            {onSendToEdit && (
              <button
                onClick={(e) => { e.stopPropagation(); onSendToEdit(imgUrl) }}
                className="p-1.5 bg-purple-500/20 rounded-md text-purple-200 hover:bg-purple-500/40 transition-colors"
                title="Open in Edit"
              >
                <PenLine size={12} />
              </button>
            )}
            <button
              onClick={(e) => {
                e.stopPropagation()
                const a = document.createElement('a')
                a.href = imgUrl
                a.download = `avatar_${item.seed ?? 'unknown'}.png`
                a.click()
              }}
              className="p-1.5 bg-white/10 rounded-md text-white/80 hover:bg-white/20 transition-colors"
              title="Download"
            >
              <Download size={12} />
            </button>
          </div>
          <div className="flex items-center gap-1">
            {onGenerateOutfits && (
              <button
                onClick={(e) => { e.stopPropagation(); onGenerateOutfits(item) }}
                className="p-1.5 bg-cyan-500/20 rounded-md text-cyan-200 hover:bg-cyan-500/40 transition-colors"
                title="Outfit Variations"
              >
                <Shirt size={12} />
              </button>
            )}
            {onSaveAsPersonaAvatar && !item.personaProjectId && (
              <button
                onClick={(e) => { e.stopPropagation(); onSaveAsPersonaAvatar(item) }}
                className="p-1.5 bg-emerald-500/20 rounded-md text-emerald-200 hover:bg-emerald-500/40 transition-colors"
                title="Save as Persona Avatar"
              >
                <UserPlus size={12} />
              </button>
            )}
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(item.id) }}
              className="p-1.5 bg-red-500/10 rounded-md text-red-300/60 hover:bg-red-500/30 hover:text-red-300 transition-colors"
              title="Delete"
            >
              <Trash2 size={12} />
            </button>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="px-1.5 py-1">
        <div className="text-[9px] text-white/30 font-mono truncate">
          {item.seed !== undefined ? `seed ${item.seed}` : 'no seed'}
        </div>
        <div className="text-[8px] text-white/15 truncate">
          {formatTimeAgo(item.createdAt)}
        </div>
      </div>
    </div>
  )
}
