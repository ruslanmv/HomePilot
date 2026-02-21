/**
 * AvatarLandingPage — Gallery-first landing page for the Avatar tab.
 *
 * Mirrors the Edit tab's TWO-VIEW ARCHITECTURE:
 *   - Gallery grid of all generated avatars (same card style as Edit)
 *   - Clicking a card opens it in the Avatar Designer (AvatarStudio)
 *   - Empty state with friendly onboarding CTA
 *
 * Design principles:
 *   - Matches Edit landing page rhythm (header + grid + floating FAB)
 *   - Cyber-Noir aesthetic (True Black backgrounds)
 *   - No pack warnings on landing — treated as capabilities, not errors
 *   - "New Avatar" button replaces the "Upload Image" CTA from Edit
 */

import React, { useState, useCallback } from 'react'
import {
  Sparkles,
  Trash2,
  Clock,
  Plus,
  User,
  Shuffle,
  Palette,
  Maximize2,
  PenLine,
  Download,
  Shirt,
  UserPlus,
  Image as ImageIcon,
} from 'lucide-react'
import type { GalleryItem } from './galleryTypes'
import type { AvatarMode } from './types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface AvatarLandingPageProps {
  items: GalleryItem[]
  backendUrl: string
  onNewAvatar: () => void
  onOpenItem: (item: GalleryItem) => void
  onDeleteItem: (id: string) => void
  onOpenLightbox?: (url: string) => void
  onSendToEdit?: (url: string) => void
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

const MODE_LABELS: Record<AvatarMode, string> = {
  studio_reference: 'Reference',
  studio_random: 'Random',
  studio_faceswap: 'Face + Style',
  creative: 'Creative',
}

const MODE_ICONS: Record<AvatarMode, React.ReactNode> = {
  studio_reference: <User size={10} />,
  studio_random: <Shuffle size={10} />,
  studio_faceswap: <Palette size={10} />,
  creative: <Sparkles size={10} />,
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AvatarLandingPage({
  items,
  backendUrl,
  onNewAvatar,
  onOpenItem,
  onDeleteItem,
  onOpenLightbox,
  onSendToEdit,
  onSaveAsPersonaAvatar,
  onGenerateOutfits,
}: AvatarLandingPageProps) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const handleDelete = useCallback(
    (item: GalleryItem, e: React.MouseEvent) => {
      e.stopPropagation()
      if (confirmDeleteId === item.id) {
        onDeleteItem(item.id)
        setConfirmDeleteId(null)
      } else {
        setConfirmDeleteId(item.id)
        setTimeout(() => setConfirmDeleteId(null), 3000)
      }
    },
    [confirmDeleteId, onDeleteItem],
  )

  return (
    <div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col relative">
      {/* Header — matches Edit landing exactly */}
      <div className="absolute top-0 left-0 right-0 z-20 flex justify-between items-center px-6 py-4 bg-gradient-to-b from-black/80 to-transparent pointer-events-none">
        <div className="pointer-events-auto flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center">
            <Sparkles size={16} className="text-white" />
          </div>
          <div>
            <div className="text-sm font-semibold text-white leading-tight">HomePilot</div>
            <div className="text-xs text-white/50 leading-tight">Avatar Studio</div>
          </div>
        </div>

        <div className="pointer-events-auto flex items-center gap-2">
          <button
            className="flex items-center gap-2 bg-gradient-to-r from-purple-600/70 to-pink-600/70 hover:from-purple-500 hover:to-pink-500 border border-purple-500/30 hover:border-purple-400/50 px-4 py-2 rounded-full text-sm font-semibold shadow-lg shadow-purple-500/10 hover:shadow-purple-500/20 transition-all"
            type="button"
            onClick={onNewAvatar}
            aria-label="Create a new avatar"
          >
            <Sparkles size={16} />
            <span>New Avatar</span>
          </button>
        </div>
      </div>

      {/* Grid Gallery */}
      <div className="flex-1 overflow-y-auto px-4 pb-8 pt-20 scrollbar-hide">
        <div className="max-w-[1600px] mx-auto grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 content-start">
          <div className="col-span-full h-1" />

          {/* Empty state — friendly onboarding */}
          {items.length === 0 && (
            <div className="col-span-full">
              <div className="rounded-2xl border bg-white/5 border-white/10 ring-1 ring-white/10 p-10 text-center shadow-2xl transition-all duration-200">
                {/* Icon */}
                <div className="mx-auto size-14 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center">
                  <Sparkles size={24} className="text-white/80" />
                </div>

                {/* Title */}
                <h2 className="mt-5 text-lg font-bold text-white">
                  Create your first avatar
                </h2>

                {/* Description */}
                <p className="mt-2 text-sm text-white/50 max-w-md mx-auto">
                  Generate reusable portrait characters from reference photos,
                  random faces, or face+style combinations.
                </p>

                {/* Actions */}
                <div className="mt-6 flex items-center justify-center gap-3 flex-wrap">
                  <button
                    type="button"
                    onClick={onNewAvatar}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-purple-600/80 to-pink-600/80 hover:from-purple-500 hover:to-pink-500 border border-purple-500/30 hover:border-purple-400/50 text-sm font-semibold text-white shadow-lg shadow-purple-500/10 hover:shadow-purple-500/20 transition-all"
                    aria-label="Create your first avatar from a reference photo"
                  >
                    <User size={16} />
                    <span>From Reference Photo</span>
                  </button>
                  <button
                    type="button"
                    onClick={onNewAvatar}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-white/10 hover:bg-white/15 border border-white/10 hover:border-white/20 text-sm font-semibold text-white transition-all"
                    aria-label="Generate a random face avatar"
                  >
                    <Shuffle size={16} />
                    <span>Random Face</span>
                  </button>
                </div>

                {/* Subtext */}
                <p className="mt-4 text-xs text-white/30">
                  Generated avatars are saved here automatically and can be sent to Edit Studio
                </p>
              </div>
            </div>
          )}

          {/* Gallery items — same card style as Edit */}
          {items.map((item) => {
            const imgUrl = resolveUrl(item.url, backendUrl)
            return (
              <div
                key={item.id}
                onClick={() => onOpenItem(item)}
                className="relative group rounded-2xl overflow-hidden bg-white/5 border border-white/10 hover:border-white/20 transition-colors cursor-pointer aspect-square"
              >
                <img
                  src={imgUrl}
                  alt={item.prompt || 'Avatar'}
                  className="absolute inset-0 w-full h-full object-cover transition-transform duration-700 group-hover:scale-105"
                  loading="lazy"
                />

                {/* Mode badge */}
                <div className="absolute top-2.5 left-2.5 z-10">
                  <div className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-black/50 backdrop-blur-sm border border-white/10 text-[10px] text-white/70 font-medium">
                    {MODE_ICONS[item.mode]}
                    {MODE_LABELS[item.mode] || item.mode}
                  </div>
                </div>

                {/* Persona badge */}
                {item.personaProjectId && (
                  <div className="absolute top-2.5 right-2.5 z-10">
                    <div className="px-1.5 py-0.5 rounded-full bg-purple-500/30 backdrop-blur-sm text-purple-200 text-[10px] font-medium">
                      Persona
                    </div>
                  </div>
                )}

                {/* Hover overlay */}
                <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex flex-col justify-between p-4">
                  {/* Top actions */}
                  <div className="flex justify-end gap-2">
                    {onOpenLightbox && (
                      <button
                        className="bg-white/10 backdrop-blur-md hover:bg-white/20 p-2 rounded-full text-white transition-colors"
                        type="button"
                        title="View full size"
                        onClick={(e) => {
                          e.stopPropagation()
                          onOpenLightbox(imgUrl)
                        }}
                      >
                        <Maximize2 size={16} />
                      </button>
                    )}
                    {onSendToEdit && (
                      <button
                        className="bg-purple-500/20 backdrop-blur-md hover:bg-purple-500/40 p-2 rounded-full text-purple-300 hover:text-purple-200 transition-colors"
                        type="button"
                        title="Open in Edit Studio"
                        onClick={(e) => {
                          e.stopPropagation()
                          onSendToEdit(imgUrl)
                        }}
                      >
                        <PenLine size={16} />
                      </button>
                    )}
                    {onGenerateOutfits && (
                      <button
                        className="bg-cyan-500/20 backdrop-blur-md hover:bg-cyan-500/40 p-2 rounded-full text-cyan-300 hover:text-cyan-200 transition-colors"
                        type="button"
                        title="Outfit Variations"
                        onClick={(e) => {
                          e.stopPropagation()
                          onGenerateOutfits(item)
                        }}
                      >
                        <Shirt size={16} />
                      </button>
                    )}
                    {onSaveAsPersonaAvatar && !item.personaProjectId && (
                      <button
                        className="bg-emerald-500/20 backdrop-blur-md hover:bg-emerald-500/40 p-2 rounded-full text-emerald-300 hover:text-emerald-200 transition-colors"
                        type="button"
                        title="Save as Persona Avatar"
                        onClick={(e) => {
                          e.stopPropagation()
                          onSaveAsPersonaAvatar(item)
                        }}
                      >
                        <UserPlus size={16} />
                      </button>
                    )}
                    <button
                      className={`backdrop-blur-md p-2 rounded-full transition-colors ${
                        confirmDeleteId === item.id
                          ? 'bg-red-500/40 text-red-300'
                          : 'bg-red-500/20 text-red-400 hover:bg-red-500/40 hover:text-red-300'
                      }`}
                      type="button"
                      title={confirmDeleteId === item.id ? 'Confirm delete' : 'Delete'}
                      onClick={(e) => handleDelete(item, e)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>

                  {/* Bottom info */}
                  <div>
                    {item.prompt && (
                      <div className="text-xs text-white/80 line-clamp-2 mb-1">{item.prompt}</div>
                    )}
                    <div className="text-[10px] text-white/50 flex items-center gap-2">
                      <span className="flex items-center gap-1">
                        <Clock size={10} />
                        {formatTimeAgo(item.createdAt)}
                      </span>
                      {item.seed !== undefined && (
                        <span className="font-mono">seed {item.seed}</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Floating New Avatar Button (visible when gallery has items) */}
      {items.length > 0 && (
        <div className="absolute bottom-6 right-6 z-30">
          <button
            onClick={onNewAvatar}
            className="w-14 h-14 rounded-full bg-white text-black hover:bg-gray-200 transition-all shadow-2xl flex items-center justify-center"
            type="button"
            title="Create new avatar"
            aria-label="Create new avatar"
          >
            <Plus size={24} />
          </button>
        </div>
      )}

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
        .line-clamp-2 {
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }
      `}</style>
    </div>
  )
}
