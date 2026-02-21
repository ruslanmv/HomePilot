/**
 * AvatarViewer — MMORPG-style character sheet for a single avatar.
 *
 * Opened when clicking an avatar card in the landing gallery.
 * Shows the hero portrait, metadata, action toolbar, and a wardrobe
 * grid of all outfit variations generated for this avatar.
 *
 * Design inspiration: character inspection screens in MMORPGs where
 * the character is prominently displayed and outfit slots are arranged
 * below for browsing/customization.
 *
 * Additive — no existing components are modified.
 */

import React, { useState, useMemo, useCallback } from 'react'
import {
  ChevronLeft,
  Shirt,
  PenLine,
  Download,
  UserPlus,
  Maximize2,
  Wand2,
  Trash2,
  Clock,
  Copy,
  Check,
  Plus,
  Sparkles,
  User,
  Shuffle,
  Palette,
} from 'lucide-react'

import type { GalleryItem } from './galleryTypes'
import type { AvatarMode, AvatarResult } from './types'
import { OutfitPanel } from './OutfitPanel'
import { resolveCheckpoint, loadAvatarSettings } from './AvatarSettingsPanel'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface AvatarViewerProps {
  /** The avatar being inspected */
  item: GalleryItem
  /** All gallery items (used to find outfits for this avatar) */
  allItems: GalleryItem[]
  backendUrl: string
  apiKey?: string
  globalModelImages?: string
  onBack: () => void
  onOpenLightbox?: (url: string) => void
  onSendToEdit?: (url: string) => void
  onSaveAsPersonaAvatar?: (item: GalleryItem) => void
  onDeleteItem?: (id: string) => void
  /** Called when outfit generation produces new items */
  onOutfitResults?: (results: AvatarResult[], anchorItem: GalleryItem) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveUrl(url: string, backendUrl: string): string {
  if (url.startsWith('http')) return url
  return `${backendUrl.replace(/\/+$/, '')}${url}`
}

function formatTimeAgo(timestamp: number): string {
  const seconds = Math.floor((Date.now() - timestamp) / 1000)
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

const MODE_LABELS: Record<AvatarMode, string> = {
  studio_reference: 'Reference',
  studio_random: 'Random',
  studio_faceswap: 'Face + Style',
  creative: 'Creative',
}

const MODE_ICONS: Record<AvatarMode, React.ReactNode> = {
  studio_reference: <User size={14} />,
  studio_random: <Shuffle size={14} />,
  studio_faceswap: <Palette size={14} />,
  creative: <Sparkles size={14} />,
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function AvatarViewer({
  item,
  allItems,
  backendUrl,
  apiKey,
  globalModelImages,
  onBack,
  onOpenLightbox,
  onSendToEdit,
  onSaveAsPersonaAvatar,
  onDeleteItem,
  onOutfitResults,
}: AvatarViewerProps) {
  const [showOutfitPanel, setShowOutfitPanel] = useState(false)
  const [copiedSeed, setCopiedSeed] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const heroUrl = resolveUrl(item.url, backendUrl)

  // Find outfits: gallery items whose referenceUrl matches this avatar's URL
  const outfits = useMemo(() => {
    return allItems.filter(
      (g) =>
        g.id !== item.id &&
        g.referenceUrl &&
        (g.referenceUrl === item.url ||
          resolveUrl(g.referenceUrl, backendUrl) === heroUrl),
    )
  }, [allItems, item, heroUrl, backendUrl])

  const handleCopySeed = useCallback(() => {
    if (item.seed !== undefined) {
      navigator.clipboard.writeText(String(item.seed)).catch(() => {})
      setCopiedSeed(true)
      setTimeout(() => setCopiedSeed(false), 1500)
    }
  }, [item.seed])

  const handleDelete = useCallback(() => {
    if (confirmDelete) {
      onDeleteItem?.(item.id)
      onBack()
    } else {
      setConfirmDelete(true)
      setTimeout(() => setConfirmDelete(false), 3000)
    }
  }, [confirmDelete, item.id, onDeleteItem, onBack])

  const avatarSettings = loadAvatarSettings()
  const checkpoint = resolveCheckpoint(avatarSettings, globalModelImages)
  const nsfwMode = (() => {
    try { return localStorage.getItem('homepilot_nsfw_mode') === 'true' } catch { return false }
  })()

  return (
    <div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col">
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div className="px-5 pt-4 pb-3 border-b border-white/5 flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="w-9 h-9 rounded-xl bg-white/10 hover:bg-white/20 flex items-center justify-center backdrop-blur-md transition-colors"
            title="Back to Gallery"
          >
            <ChevronLeft size={18} />
          </button>
          <div>
            <h2 className="text-base font-semibold tracking-tight">Character Sheet</h2>
            <p className="text-[10px] text-white/40 mt-0.5">
              Inspect &amp; customize your avatar
            </p>
          </div>
        </div>

        {/* Mode badge */}
        <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/5 border border-white/10 text-xs text-white/60 font-medium">
          {MODE_ICONS[item.mode]}
          {MODE_LABELS[item.mode] || item.mode}
        </div>
      </div>

      {/* ── Scrollable body ────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto min-h-0 scrollbar-hide">
        <div className="max-w-4xl mx-auto px-5 py-6 space-y-6">

          {/* ── Hero Portrait ──────────────────────────────────────── */}
          <div className="flex flex-col items-center">
            {/* Portrait frame — MMORPG-style glowing border */}
            <div className="relative group">
              <div className="absolute -inset-1 rounded-2xl bg-gradient-to-br from-purple-500/30 via-transparent to-cyan-500/30 blur-sm opacity-60 group-hover:opacity-100 transition-opacity" />
              <div
                className="relative w-72 h-72 sm:w-80 sm:h-80 md:w-96 md:h-96 rounded-2xl overflow-hidden border-2 border-white/15 cursor-pointer bg-white/[0.03]"
                onClick={() => onOpenLightbox?.(heroUrl)}
              >
                <img
                  src={heroUrl}
                  alt={item.prompt || 'Avatar portrait'}
                  className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                />

                {/* Lightbox hint on hover */}
                <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                  <Maximize2 size={28} className="text-white/80" />
                </div>
              </div>
            </div>

            {/* ── Character info ──────────────────────────────────── */}
            <div className="mt-4 text-center space-y-1.5">
              {item.prompt && (
                <p className="text-sm text-white/70 max-w-md leading-relaxed">
                  {item.prompt}
                </p>
              )}
              <div className="flex items-center justify-center gap-3 text-[11px] text-white/40">
                <span className="flex items-center gap-1">
                  <Clock size={11} />
                  {formatTimeAgo(item.createdAt)}
                </span>
                {item.seed !== undefined && (
                  <button
                    onClick={handleCopySeed}
                    className="flex items-center gap-1 font-mono hover:text-white/70 transition-colors cursor-pointer"
                    title="Copy seed"
                  >
                    {copiedSeed ? (
                      <span className="flex items-center gap-1 text-green-400">
                        <Check size={10} /> copied
                      </span>
                    ) : (
                      <>
                        seed {item.seed}
                        <Copy size={9} />
                      </>
                    )}
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* ── Action toolbar ────────────────────────────────────── */}
          <div className="flex flex-wrap items-center justify-center gap-2">
            <button
              onClick={() => setShowOutfitPanel(!showOutfitPanel)}
              className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all border ${
                showOutfitPanel
                  ? 'border-cyan-500/40 bg-cyan-500/15 text-cyan-300'
                  : 'border-cyan-500/20 bg-gradient-to-r from-cyan-600/80 to-blue-600/80 text-white shadow-lg shadow-cyan-500/10 hover:shadow-cyan-500/20 hover:scale-[1.02] active:scale-[0.98]'
              }`}
            >
              <Shirt size={16} />
              {showOutfitPanel ? 'Hide Outfit Studio' : 'Generate Outfits'}
            </button>
            {onSendToEdit && (
              <button
                onClick={() => onSendToEdit(heroUrl)}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border border-purple-500/20 bg-purple-500/10 text-purple-300 hover:bg-purple-500/20 transition-all"
              >
                <PenLine size={16} />
                Edit
              </button>
            )}
            <button
              onClick={() => {
                const a = document.createElement('a')
                a.href = heroUrl
                a.download = `avatar_${item.seed ?? item.id}.png`
                a.click()
              }}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border border-white/10 bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/80 transition-all"
            >
              <Download size={16} />
              Download
            </button>
            {onSaveAsPersonaAvatar && !item.personaProjectId && (
              <button
                onClick={() => onSaveAsPersonaAvatar(item)}
                className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border border-emerald-500/20 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20 transition-all"
              >
                <UserPlus size={16} />
                Save as Persona
              </button>
            )}
            {onDeleteItem && (
              <button
                onClick={handleDelete}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium border transition-all ${
                  confirmDelete
                    ? 'border-red-500/40 bg-red-500/20 text-red-300'
                    : 'border-red-500/10 bg-red-500/5 text-red-400/60 hover:bg-red-500/10 hover:text-red-400'
                }`}
              >
                <Trash2 size={14} />
                {confirmDelete ? 'Confirm Delete' : 'Delete'}
              </button>
            )}
          </div>

          {/* ── Persona badge ─────────────────────────────────────── */}
          {item.personaProjectId && (
            <div className="flex items-center justify-center">
              <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-purple-500/10 border border-purple-500/20 text-purple-300 text-xs font-medium">
                <UserPlus size={12} />
                Linked to Persona
              </div>
            </div>
          )}

          {/* ── Outfit generation panel ──────────────────────────── */}
          {showOutfitPanel && (
            <OutfitPanel
              anchor={item}
              backendUrl={backendUrl}
              apiKey={apiKey}
              nsfwMode={nsfwMode}
              checkpointOverride={checkpoint}
              onResults={(results) => onOutfitResults?.(results, item)}
              onSendToEdit={onSendToEdit}
              onOpenLightbox={onOpenLightbox}
              onClose={() => setShowOutfitPanel(false)}
            />
          )}

          {/* ── Wardrobe section ─────────────────────────────────── */}
          <div className="pt-2">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500/80 to-orange-500/80 flex items-center justify-center">
                  <Shirt size={16} className="text-white" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">Wardrobe</h3>
                  <p className="text-[10px] text-white/40 mt-0.5">
                    {outfits.length === 0
                      ? 'No outfits yet — generate some above'
                      : `${outfits.length} outfit${outfits.length !== 1 ? 's' : ''} in collection`}
                  </p>
                </div>
              </div>
            </div>

            {outfits.length === 0 ? (
              /* Empty wardrobe state */
              <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.02] p-8 text-center">
                <div className="mx-auto w-12 h-12 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center mb-3">
                  <Shirt size={24} className="text-white/20" />
                </div>
                <p className="text-sm text-white/40">
                  Your wardrobe is empty
                </p>
                <p className="text-xs text-white/25 mt-1 mb-4">
                  Generate outfit variations to build your character&apos;s style collection
                </p>
                {!showOutfitPanel && (
                  <button
                    onClick={() => setShowOutfitPanel(true)}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-gradient-to-r from-cyan-600/80 to-blue-600/80 text-white text-sm font-semibold shadow-lg shadow-cyan-500/10 hover:shadow-cyan-500/20 transition-all hover:scale-[1.02] active:scale-[0.98]"
                  >
                    <Wand2 size={14} />
                    Create First Outfit
                  </button>
                )}
              </div>
            ) : (
              /* Wardrobe grid — outfit cards with 2:3 aspect ratio */
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
                {outfits.map((outfit) => {
                  const outfitUrl = resolveUrl(outfit.url, backendUrl)
                  return (
                    <WardrobeCard
                      key={outfit.id}
                      item={outfit}
                      imageUrl={outfitUrl}
                      onOpenLightbox={onOpenLightbox}
                      onSendToEdit={onSendToEdit}
                      onDelete={onDeleteItem}
                    />
                  )
                })}

                {/* "+ New Outfit" card */}
                <button
                  onClick={() => setShowOutfitPanel(true)}
                  className="rounded-xl border-2 border-dashed border-white/10 hover:border-cyan-500/30 bg-white/[0.02] hover:bg-cyan-500/5 aspect-[2/3] flex flex-col items-center justify-center gap-2 transition-all group cursor-pointer"
                >
                  <div className="w-10 h-10 rounded-full bg-white/5 group-hover:bg-cyan-500/10 flex items-center justify-center transition-colors">
                    <Plus size={20} className="text-white/30 group-hover:text-cyan-400 transition-colors" />
                  </div>
                  <span className="text-xs text-white/30 group-hover:text-cyan-400/80 font-medium transition-colors">
                    New Outfit
                  </span>
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
      `}</style>
    </div>
  )
}

// ---------------------------------------------------------------------------
// WardrobeCard — individual outfit item in the wardrobe grid
// ---------------------------------------------------------------------------

function WardrobeCard({
  item,
  imageUrl,
  onOpenLightbox,
  onSendToEdit,
  onDelete,
}: {
  item: GalleryItem
  imageUrl: string
  onOpenLightbox?: (url: string) => void
  onSendToEdit?: (url: string) => void
  onDelete?: (id: string) => void
}) {
  const [hovered, setHovered] = useState(false)

  return (
    <div
      className="group relative rounded-xl overflow-hidden border border-white/8 bg-white/[0.02] hover:border-white/20 transition-all"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div
        className="aspect-[2/3] bg-white/[0.03] cursor-pointer relative"
        onClick={() => onOpenLightbox?.(imageUrl)}
      >
        <img
          src={imageUrl}
          alt={item.prompt || 'Outfit variation'}
          className="w-full h-full object-cover"
          loading="lazy"
        />

        {/* Hover overlay */}
        <div
          className={`absolute inset-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent transition-opacity duration-200 flex flex-col justify-between p-2 ${
            hovered ? 'opacity-100' : 'opacity-0'
          }`}
        >
          {/* Top actions */}
          <div className="flex justify-end gap-1.5">
            {onSendToEdit && (
              <button
                onClick={(e) => { e.stopPropagation(); onSendToEdit(imageUrl) }}
                className="p-1.5 bg-purple-500/30 backdrop-blur-sm rounded-lg text-purple-200 hover:bg-purple-500/50 transition-colors"
                title="Open in Edit"
              >
                <PenLine size={13} />
              </button>
            )}
            <button
              onClick={(e) => {
                e.stopPropagation()
                const a = document.createElement('a')
                a.href = imageUrl
                a.download = `outfit_${item.seed ?? item.id}.png`
                a.click()
              }}
              className="p-1.5 bg-white/10 backdrop-blur-sm rounded-lg text-white/80 hover:bg-white/20 transition-colors"
              title="Download"
            >
              <Download size={13} />
            </button>
          </div>

          {/* Bottom info */}
          <div>
            {item.prompt && (
              <p className="text-[10px] text-white/80 line-clamp-2 mb-1">{item.prompt}</p>
            )}
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-white/50 font-mono">
                {item.seed !== undefined ? `seed ${item.seed}` : ''}
              </span>
              <span className="text-[9px] text-white/40 flex items-center gap-0.5">
                <Clock size={8} />
                {formatTimeAgo(item.createdAt)}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
