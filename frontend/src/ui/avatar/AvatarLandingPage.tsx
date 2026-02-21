/**
 * AvatarLandingPage — Gallery-first landing page for the Avatar tab.
 *
 * Clean, enterprise-grade design matching the "Command Center" aesthetic:
 *   - Minimal header with title + "New Avatar" CTA
 *   - Responsive grid gallery of all generated avatars
 *   - Empty state with friendly onboarding
 *   - Floating FAB for quick access to avatar creation
 */

import React, { useState, useCallback, useMemo } from 'react'
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
  Eye,
  EyeOff,
} from 'lucide-react'
import type { GalleryItem } from './galleryTypes'
import { SCENARIO_TAG_META } from './galleryTypes'
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
  // Auto-show NSFW content when Spice Mode is enabled globally
  const [showNsfw, setShowNsfw] = useState(() => {
    try { return localStorage.getItem('homepilot_nsfw_mode') === 'true' } catch { return false }
  })

  // Only show root characters (no parentId) — outfits live inside the Character Sheet
  const rootCharacters = useMemo(() => items.filter((i) => !i.parentId), [items])

  // Count outfits per root character
  const outfitCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const item of items) {
      if (item.parentId) {
        counts[item.parentId] = (counts[item.parentId] || 0) + 1
      }
    }
    return counts
  }, [items])

  const hasNsfwItems = rootCharacters.some((i) => i.nsfw)

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

      {/* ═══════════════ HEADER ═══════════════ */}
      <div className="absolute top-0 left-0 right-0 z-20 flex justify-between items-center px-6 py-4 bg-gradient-to-b from-black/90 via-black/60 to-transparent pointer-events-none">
        <div className="pointer-events-auto flex items-center gap-3">
          <div className="flex items-center gap-2.5">
            <Sparkles size={18} className="text-purple-400" />
            <div>
              <div className="text-sm font-semibold text-white leading-tight">Avatar Studio</div>
              <div className="text-[10px] text-white/35 leading-tight">
                {rootCharacters.length > 0 ? `${rootCharacters.length} character${rootCharacters.length !== 1 ? 's' : ''}` : 'Gallery'}
              </div>
            </div>
          </div>
        </div>

        <div className="pointer-events-auto flex items-center gap-2">
          {hasNsfwItems && (
            <button
              onClick={() => setShowNsfw(!showNsfw)}
              className={[
                'flex items-center gap-1.5 px-2.5 py-2 rounded-xl text-[10px] font-medium transition-all border',
                showNsfw
                  ? 'border-rose-500/20 bg-rose-500/10 text-rose-300'
                  : 'border-white/[0.08] bg-white/[0.05] text-white/30 hover:text-white/50',
              ].join(' ')}
              title={showNsfw ? 'Hide NSFW content' : 'Show NSFW content'}
            >
              {showNsfw ? <Eye size={12} /> : <EyeOff size={12} />}
              {showNsfw ? 'NSFW Visible' : 'Show NSFW'}
            </button>
          )}
          <button
            className="flex items-center gap-2 bg-gradient-to-r from-purple-600 to-pink-600 hover:brightness-110 border border-purple-500/20 px-4 py-2 rounded-xl text-sm font-semibold shadow-lg shadow-purple-500/10 hover:shadow-purple-500/20 transition-all"
            type="button"
            onClick={onNewAvatar}
            aria-label="Create a new avatar"
          >
            <Sparkles size={14} />
            <span>New Avatar</span>
          </button>
        </div>
      </div>

      {/* ═══════════════ GALLERY GRID ═══════════════ */}
      <div className="flex-1 overflow-y-auto px-4 pb-8 pt-20 scrollbar-hide">
        <div className="max-w-[1400px] mx-auto grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 content-start">
          <div className="col-span-full h-1" />

          {/* Empty state */}
          {rootCharacters.length === 0 && (
            <div className="col-span-full">
              <div className="rounded-2xl border bg-white/[0.03] border-white/[0.08] p-12 text-center max-w-lg mx-auto">
                <div className="mx-auto size-14 rounded-2xl bg-white/[0.04] border border-white/[0.08] flex items-center justify-center">
                  <Sparkles size={24} className="text-white/40" />
                </div>

                <h2 className="mt-5 text-lg font-bold text-white/90">
                  Create your first avatar
                </h2>

                <p className="mt-2 text-sm text-white/40 max-w-sm mx-auto leading-relaxed">
                  Generate portrait characters from reference photos,
                  random faces, or face+style combinations.
                </p>

                <div className="mt-6 flex items-center justify-center gap-3 flex-wrap">
                  <button
                    type="button"
                    onClick={onNewAvatar}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-purple-600 to-pink-600 hover:brightness-110 border border-purple-500/20 text-sm font-semibold text-white shadow-lg shadow-purple-500/10 hover:shadow-purple-500/20 transition-all"
                  >
                    <User size={16} />
                    <span>From Reference Photo</span>
                  </button>
                  <button
                    type="button"
                    onClick={onNewAvatar}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.08] hover:border-white/15 text-sm font-semibold text-white transition-all"
                  >
                    <Shuffle size={16} />
                    <span>Random Face</span>
                  </button>
                </div>

                <p className="mt-5 text-xs text-white/20">
                  Generated avatars are saved here automatically
                </p>
              </div>
            </div>
          )}

          {/* Gallery cards — one card per character (outfits live in Character Sheet) */}
          {rootCharacters.map((item) => {
            const imgUrl = resolveUrl(item.url, backendUrl)
            const oCount = outfitCounts[item.id] || 0
            return (
              <div
                key={item.id}
                onClick={() => onOpenItem(item)}
                className="relative group rounded-2xl overflow-hidden bg-white/[0.03] border border-white/[0.06] hover:border-white/15 transition-all cursor-pointer aspect-square"
              >
                <img
                  src={imgUrl}
                  alt={item.prompt || 'Avatar'}
                  className={`absolute inset-0 w-full h-full object-cover transition-transform duration-700 group-hover:scale-105${item.nsfw && !showNsfw ? ' blur-xl scale-110' : ''}`}
                  loading="lazy"
                />

                {/* NSFW overlay */}
                {item.nsfw && !showNsfw && (
                  <div className="absolute inset-0 z-[5] flex items-center justify-center bg-black/30">
                    <div className="text-[10px] text-white/40 font-medium px-2 py-1 rounded-md bg-black/40 backdrop-blur-sm">
                      <EyeOff size={12} className="inline mr-1 -mt-0.5" />
                      NSFW
                    </div>
                  </div>
                )}

                {/* Mode badge */}
                <div className="absolute top-2.5 left-2.5 z-10">
                  <div className="flex items-center gap-1 px-2 py-0.5 rounded-md bg-black/50 backdrop-blur-sm border border-white/[0.08] text-[9px] text-white/60 font-medium">
                    {MODE_ICONS[item.mode]}
                    {MODE_LABELS[item.mode] || item.mode}
                  </div>
                </div>

                {/* Outfit count badge (top right) */}
                {oCount > 0 && (
                  <div className="absolute top-2.5 right-2.5 z-10">
                    <div className="flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-cyan-500/30 backdrop-blur-sm border border-cyan-500/20 text-[9px] text-cyan-200 font-medium">
                      <Shirt size={9} />
                      {oCount}
                    </div>
                  </div>
                )}

                {/* Persona badge (when no outfits) */}
                {item.personaProjectId && oCount === 0 && (
                  <div className="absolute top-2.5 right-2.5 z-10">
                    <div className="px-1.5 py-0.5 rounded-md bg-purple-500/30 backdrop-blur-sm text-purple-200 text-[9px] font-medium">
                      Persona
                    </div>
                  </div>
                )}

                {/* Hover overlay */}
                <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex flex-col justify-between p-3">
                  {/* Top actions */}
                  <div className="flex justify-end gap-1.5">
                    {onOpenLightbox && (
                      <button
                        className="bg-white/10 backdrop-blur-md hover:bg-white/20 p-2 rounded-lg text-white transition-colors"
                        type="button"
                        title="View full size"
                        onClick={(e) => { e.stopPropagation(); onOpenLightbox(imgUrl) }}
                      >
                        <Maximize2 size={14} />
                      </button>
                    )}
                    {onSendToEdit && (
                      <button
                        className="bg-purple-500/20 backdrop-blur-md hover:bg-purple-500/40 p-2 rounded-lg text-purple-300 transition-colors"
                        type="button"
                        title="Open in Edit Studio"
                        onClick={(e) => { e.stopPropagation(); onSendToEdit(imgUrl) }}
                      >
                        <PenLine size={14} />
                      </button>
                    )}
                    {onGenerateOutfits && (
                      <button
                        className="bg-cyan-500/20 backdrop-blur-md hover:bg-cyan-500/40 p-2 rounded-lg text-cyan-300 transition-colors"
                        type="button"
                        title="Open Character Sheet"
                        onClick={(e) => { e.stopPropagation(); onGenerateOutfits(item) }}
                      >
                        <Shirt size={14} />
                      </button>
                    )}
                    {onSaveAsPersonaAvatar && !item.personaProjectId && (
                      <button
                        className="bg-emerald-500/20 backdrop-blur-md hover:bg-emerald-500/40 p-2 rounded-lg text-emerald-300 transition-colors"
                        type="button"
                        title="Save as Persona Avatar"
                        onClick={(e) => { e.stopPropagation(); onSaveAsPersonaAvatar(item) }}
                      >
                        <UserPlus size={14} />
                      </button>
                    )}
                    <button
                      className={`backdrop-blur-md p-2 rounded-lg transition-colors ${
                        confirmDeleteId === item.id
                          ? 'bg-red-500/40 text-red-300'
                          : 'bg-red-500/20 text-red-400 hover:bg-red-500/40 hover:text-red-300'
                      }`}
                      type="button"
                      title={confirmDeleteId === item.id ? 'Confirm delete' : 'Delete'}
                      onClick={(e) => handleDelete(item, e)}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>

                  {/* Bottom info */}
                  <div>
                    {item.prompt && (
                      <div className="text-xs text-white/80 line-clamp-2 mb-1">{item.prompt}</div>
                    )}
                    <div className="text-[10px] text-white/45 flex items-center gap-2">
                      <span className="flex items-center gap-1">
                        <Clock size={9} />
                        {formatTimeAgo(item.createdAt)}
                      </span>
                      {oCount > 0 && (
                        <span className="flex items-center gap-1">
                          <Shirt size={9} />
                          {oCount} outfit{oCount !== 1 ? 's' : ''}
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Floating New Avatar FAB */}
      {rootCharacters.length > 0 && (
        <div className="absolute bottom-6 right-6 z-30">
          <button
            onClick={onNewAvatar}
            className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-600 to-pink-600 text-white hover:brightness-110 transition-all shadow-2xl shadow-purple-500/20 flex items-center justify-center"
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
