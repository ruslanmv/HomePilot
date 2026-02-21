/**
 * AvatarViewer — RPG-style "Character Sheet" split-panel layout.
 *
 * LEFT PANEL  — Identity Anchor: hero portrait, metadata, file actions
 * RIGHT PANEL — Outfit Studio: scenario badges, custom prompt, generation
 * BOTTOM      — Wardrobe Inventory: tagged outfit grid with empty slot visuals
 *
 * Design:
 *   - Split-panel on md+ screens, stacked on mobile
 *   - Scenario badges feel like "equipping gear" in an RPG
 *   - Face lock indicator reassures user identity is preserved
 *   - Empty wardrobe slots trigger "fill the inventory" psychology
 *   - Each outfit is tagged with its scenario for future filtering
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
  Lock,
  Loader2,
  AlertTriangle,
  X,
  Filter,
} from 'lucide-react'

import type { GalleryItem, OutfitScenarioTag, ScenarioTagMeta } from './galleryTypes'
import { SCENARIO_TAG_META } from './galleryTypes'
import type { AvatarMode, AvatarResult } from './types'
import { OUTFIT_PRESETS } from '../personaTypes'
import { useOutfitGeneration } from './useOutfitGeneration'
import { AvatarSettingsPanel, resolveCheckpoint, loadAvatarSettings } from './AvatarSettingsPanel'
import type { AvatarSettings } from './types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface AvatarViewerProps {
  item: GalleryItem
  allItems: GalleryItem[]
  backendUrl: string
  apiKey?: string
  globalModelImages?: string
  onBack: () => void
  onOpenLightbox?: (url: string) => void
  onSendToEdit?: (url: string) => void
  onSaveAsPersonaAvatar?: (item: GalleryItem) => void
  onDeleteItem?: (id: string) => void
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
  studio_reference: <User size={12} />,
  studio_random: <Shuffle size={12} />,
  studio_faceswap: <Palette size={12} />,
  creative: <Sparkles size={12} />,
}

/** How many empty "inventory slots" to show when wardrobe has few items */
const MIN_WARDROBE_SLOTS = 6

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
  const [copiedSeed, setCopiedSeed] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [wardrobeFilter, setWardrobeFilter] = useState<OutfitScenarioTag | 'all'>('all')
  const [avatarSettingsState, setAvatarSettingsState] = useState<AvatarSettings>(loadAvatarSettings)

  // Outfit generation state
  const outfit = useOutfitGeneration(backendUrl, apiKey)
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null)
  const [customPrompt, setCustomPrompt] = useState('')
  const [outfitCount, setOutfitCount] = useState(1)
  const [outfitCopiedSeed, setOutfitCopiedSeed] = useState<number | null>(null)

  const heroUrl = resolveUrl(item.url, backendUrl)

  const checkpoint = resolveCheckpoint(avatarSettingsState, globalModelImages)
  const nsfwMode = (() => {
    try { return localStorage.getItem('homepilot_nsfw_mode') === 'true' } catch { return false }
  })()

  // Find outfits: gallery items whose referenceUrl matches this avatar
  const outfits = useMemo(() => {
    return allItems.filter(
      (g) =>
        g.id !== item.id &&
        g.referenceUrl &&
        (g.referenceUrl === item.url ||
          resolveUrl(g.referenceUrl, backendUrl) === heroUrl),
    )
  }, [allItems, item, heroUrl, backendUrl])

  // Filtered outfits for wardrobe display
  const filteredOutfits = useMemo(() => {
    if (wardrobeFilter === 'all') return outfits
    return outfits.filter((o) => o.scenarioTag === wardrobeFilter)
  }, [outfits, wardrobeFilter])

  // Available scenario tags from actual wardrobe items (for filter)
  const availableTags = useMemo(() => {
    const tagSet = new Set<OutfitScenarioTag>()
    outfits.forEach((o) => { if (o.scenarioTag) tagSet.add(o.scenarioTag) })
    return SCENARIO_TAG_META.filter((t) => tagSet.has(t.id))
  }, [outfits])

  // Presets filtered by NSFW mode
  const presets = OUTFIT_PRESETS.filter(
    (p) => p.category === 'sfw' || nsfwMode,
  )

  const effectivePrompt = (() => {
    if (customPrompt.trim()) return customPrompt.trim()
    if (selectedPreset) {
      const preset = presets.find((p) => p.id === selectedPreset)
      return preset?.prompt || ''
    }
    return ''
  })()

  const canGenerateOutfit = !outfit.loading && effectivePrompt.length > 0

  // ---- Actions ----
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

  const handleGenerateOutfit = useCallback(async () => {
    if (!canGenerateOutfit) return
    // Determine the scenario tag for this generation
    const scenarioTag: OutfitScenarioTag = selectedPreset
      ? (selectedPreset as OutfitScenarioTag)
      : 'custom'

    try {
      const result = await outfit.generate({
        referenceImageUrl: item.url,
        outfitPrompt: effectivePrompt,
        characterPrompt: item.prompt,
        count: outfitCount,
        checkpointOverride: checkpoint,
      })
      if (result?.results?.length) {
        // Tag each result with the scenario tag via the callback
        onOutfitResults?.(result.results, { ...item, scenarioTag })
      }
    } catch {
      // Error captured in hook state
    }
  }, [canGenerateOutfit, outfit, item, effectivePrompt, outfitCount, checkpoint, selectedPreset, onOutfitResults])

  const handleOutfitCopySeed = useCallback((seed: number) => {
    navigator.clipboard.writeText(String(seed)).catch(() => {})
    setOutfitCopiedSeed(seed)
    setTimeout(() => setOutfitCopiedSeed(null), 1500)
  }, [])

  // Find scenario tag metadata for display
  const getTagMeta = (tag?: OutfitScenarioTag): ScenarioTagMeta | undefined => {
    return SCENARIO_TAG_META.find((t) => t.id === tag)
  }

  return (
    <div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col">

      {/* ═══════════════════════ HEADER ═══════════════════════ */}
      <div className="px-5 pt-4 pb-3 border-b border-white/[0.06] flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="w-9 h-9 rounded-xl bg-white/[0.06] hover:bg-white/10 flex items-center justify-center transition-colors"
            title="Back to Gallery"
          >
            <ChevronLeft size={18} className="text-white/60" />
          </button>
          <div>
            <h2 className="text-base font-semibold tracking-tight">Character Sheet</h2>
            <p className="text-[10px] text-white/35 mt-0.5">
              Inspect &amp; customize your avatar
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Mode badge */}
          <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/[0.04] border border-white/[0.08] text-[11px] text-white/50 font-medium">
            {MODE_ICONS[item.mode]}
            {MODE_LABELS[item.mode] || item.mode}
          </div>
          {/* Settings gear */}
          <AvatarSettingsPanel
            globalModelImages={globalModelImages}
            settings={avatarSettingsState}
            onChange={setAvatarSettingsState}
          />
        </div>
      </div>

      {/* ═══════════════════════ SCROLLABLE BODY ═══════════════════════ */}
      <div className="flex-1 overflow-y-auto min-h-0 scrollbar-hide">
        <div className="max-w-6xl mx-auto px-5 py-6">

          {/* ═══ SPLIT PANEL: Left (Identity) + Right (Outfit Studio) ═══ */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">

            {/* ──────── LEFT PANEL: Identity Anchor ──────── */}
            <div className="space-y-4">
              {/* Portrait frame */}
              <div className="relative group">
                <div className="absolute -inset-[2px] rounded-2xl bg-gradient-to-br from-purple-500/20 via-transparent to-cyan-500/20 opacity-50 group-hover:opacity-100 transition-opacity" />
                <div
                  className="relative aspect-square rounded-2xl overflow-hidden border border-white/10 cursor-pointer bg-white/[0.02]"
                  onClick={() => onOpenLightbox?.(heroUrl)}
                >
                  <img
                    src={heroUrl}
                    alt={item.prompt || 'Avatar portrait'}
                    className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-[1.03]"
                  />
                  <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                    <Maximize2 size={28} className="text-white/80" />
                  </div>
                </div>
              </div>

              {/* Character info */}
              <div className="space-y-2">
                {item.prompt && (
                  <p className="text-sm text-white/60 leading-relaxed">
                    &ldquo;{item.prompt}&rdquo;
                  </p>
                )}
                <div className="flex items-center gap-3 text-[11px] text-white/35">
                  <span className="flex items-center gap-1">
                    <Clock size={11} />
                    {formatTimeAgo(item.createdAt)}
                  </span>
                  {item.seed !== undefined && (
                    <button
                      onClick={handleCopySeed}
                      className="flex items-center gap-1 font-mono hover:text-white/60 transition-colors"
                      title="Copy seed"
                    >
                      {copiedSeed ? (
                        <span className="flex items-center gap-1 text-green-400">
                          <Check size={10} /> copied
                        </span>
                      ) : (
                        <>
                          Seed: {item.seed}
                          <Copy size={9} />
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>

              {/* Persona badge */}
              {item.personaProjectId && (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-purple-500/[0.08] border border-purple-500/15 text-purple-300 text-xs font-medium w-fit">
                  <UserPlus size={12} />
                  Linked to Persona
                </div>
              )}

              {/* File action buttons */}
              <div className="flex flex-wrap gap-2 pt-1">
                {onSaveAsPersonaAvatar && !item.personaProjectId && (
                  <button
                    onClick={() => onSaveAsPersonaAvatar(item)}
                    className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-medium border border-emerald-500/15 bg-emerald-500/[0.06] text-emerald-300 hover:bg-emerald-500/10 transition-all"
                  >
                    <UserPlus size={14} />
                    Save Persona
                  </button>
                )}
                {onSendToEdit && (
                  <button
                    onClick={() => onSendToEdit(heroUrl)}
                    className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-medium border border-purple-500/15 bg-purple-500/[0.06] text-purple-300 hover:bg-purple-500/10 transition-all"
                  >
                    <PenLine size={14} />
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
                  className="flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-medium border border-white/[0.08] bg-white/[0.03] text-white/50 hover:bg-white/[0.06] hover:text-white/70 transition-all"
                >
                  <Download size={14} />
                  Download
                </button>
                {onDeleteItem && (
                  <button
                    onClick={handleDelete}
                    className={[
                      'flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs font-medium border transition-all',
                      confirmDelete
                        ? 'border-red-500/30 bg-red-500/15 text-red-300'
                        : 'border-red-500/[0.08] bg-red-500/[0.04] text-red-400/50 hover:bg-red-500/[0.08] hover:text-red-400',
                    ].join(' ')}
                  >
                    <Trash2 size={13} />
                    {confirmDelete ? 'Confirm' : 'Delete'}
                  </button>
                )}
              </div>
            </div>

            {/* ──────── RIGHT PANEL: Outfit Studio ──────── */}
            <div className="space-y-5">
              {/* Panel header */}
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2.5">
                    <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/80 to-blue-500/80 flex items-center justify-center">
                      <Shirt size={15} className="text-white" />
                    </div>
                    <h3 className="text-sm font-semibold text-white">Outfit Studio</h3>
                  </div>
                  <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/[0.04] border border-white/[0.08] text-[10px] text-white/40 font-medium">
                    <Lock size={10} />
                    Face locked to anchor
                  </div>
                </div>
                <p className="text-[11px] text-white/30 mt-2 ml-[42px]">
                  Generate outfit variations — your face stays consistent
                </p>
              </div>

              {/* 1. Choose a Scenario — Badge Grid */}
              <div>
                <div className="text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider">
                  1. Choose a Scenario
                </div>
                <div className="grid grid-cols-2 gap-2">
                  {presets.map((p) => {
                    const tagMeta = SCENARIO_TAG_META.find((t) => t.id === p.id)
                    const active = selectedPreset === p.id
                    return (
                      <button
                        key={p.id}
                        onClick={() => {
                          setSelectedPreset(active ? null : p.id)
                          if (!active) setCustomPrompt('')
                        }}
                        className={[
                          'flex items-center gap-2.5 px-3.5 py-3 rounded-xl text-left transition-all border',
                          active
                            ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200 shadow-[0_0_10px_rgba(34,211,238,0.06)]'
                            : 'border-white/[0.06] bg-white/[0.02] text-white/50 hover:bg-white/[0.04] hover:border-white/10 hover:text-white/70',
                        ].join(' ')}
                      >
                        <span className="text-base leading-none">{tagMeta?.icon || '\u2728'}</span>
                        <span className="text-xs font-medium">{p.label}</span>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* 2. Or Custom Outfit Prompt */}
              <div>
                <div className="text-[10px] text-white/40 mb-2 font-semibold uppercase tracking-wider">
                  2. Or Custom Outfit Prompt
                </div>
                <div className={[
                  'flex items-center gap-2 px-3.5 py-2.5 rounded-xl border transition-all',
                  'bg-white/[0.03] focus-within:bg-white/[0.05]',
                  'border-white/[0.08] focus-within:border-cyan-500/30 focus-within:ring-1 focus-within:ring-cyan-500/15',
                ].join(' ')}>
                  <PenLine size={14} className="text-white/20 flex-shrink-0" />
                  <input
                    value={customPrompt}
                    onChange={(e) => {
                      setCustomPrompt(e.target.value)
                      if (e.target.value.trim()) setSelectedPreset(null)
                    }}
                    placeholder="Describe custom clothing..."
                    className="flex-1 bg-transparent text-white text-sm placeholder:text-white/20 focus:outline-none"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && canGenerateOutfit) {
                        e.preventDefault()
                        handleGenerateOutfit()
                      }
                    }}
                  />
                </div>
              </div>

              {/* Count + Generate */}
              <div className="space-y-3">
                <div className="flex items-center gap-4">
                  <div className="text-[10px] text-white/30 font-medium">Qty:</div>
                  <div className="flex items-center gap-1.5" role="radiogroup" aria-label="Outfit count">
                    {[1, 4, 8].map((n) => (
                      <button
                        key={n}
                        onClick={() => setOutfitCount(n)}
                        role="radio"
                        aria-checked={outfitCount === n}
                        className={[
                          'w-8 h-8 rounded-lg text-xs font-medium transition-all border flex items-center justify-center',
                          outfitCount === n
                            ? 'border-white/15 bg-white/10 text-white'
                            : 'border-white/[0.05] bg-white/[0.02] text-white/30 hover:text-white/50',
                        ].join(' ')}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>

                <button
                  onClick={handleGenerateOutfit}
                  disabled={!canGenerateOutfit}
                  className={[
                    'w-full flex items-center justify-center gap-2 py-3 rounded-xl text-sm font-semibold transition-all',
                    canGenerateOutfit
                      ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white shadow-lg shadow-cyan-500/15 hover:shadow-cyan-500/25 hover:brightness-110 active:scale-[0.99]'
                      : 'bg-white/[0.04] text-white/20 cursor-not-allowed',
                  ].join(' ')}
                >
                  {outfit.loading ? (
                    <>
                      <Loader2 size={16} className="animate-spin" />
                      Generating...
                    </>
                  ) : (
                    <>
                      <Sparkles size={16} />
                      Generate Outfit ({outfitCount})
                    </>
                  )}
                </button>
              </div>

              {/* Error */}
              {outfit.error && (
                <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-red-500/[0.08] border border-red-500/15 text-red-300 text-xs">
                  <AlertTriangle size={14} />
                  <span>Oops, something went wrong. Please try again.</span>
                </div>
              )}

              {/* Outfit loading skeleton */}
              {outfit.loading && outfit.results.length === 0 && (
                <div className="grid grid-cols-2 gap-2">
                  {Array.from({ length: outfitCount }).map((_, i) => (
                    <div key={i} className="rounded-xl overflow-hidden border border-white/[0.06] bg-white/[0.02]">
                      <div className="aspect-[2/3] bg-white/[0.03] animate-pulse flex items-center justify-center">
                        <Loader2 size={18} className="animate-spin text-white/10" />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Latest outfit results */}
              {outfit.results.length > 0 && (
                <div className="animate-fadeSlideIn">
                  <div className="text-[10px] text-white/30 mb-2 font-semibold uppercase tracking-wider">
                    Latest Results
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    {outfit.results.map((r, i) => {
                      const imgUrl = resolveUrl(r.url, backendUrl)
                      return (
                        <div
                          key={i}
                          className="group relative rounded-xl overflow-hidden border border-white/[0.06] hover:border-white/15 transition-all cursor-pointer"
                          onClick={() => onOpenLightbox?.(imgUrl)}
                        >
                          <div className="aspect-[2/3] bg-white/[0.03] relative">
                            <img src={imgUrl} alt={`Outfit ${i + 1}`} className="w-full h-full object-cover" loading="lazy" />
                            <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-1.5">
                              {onSendToEdit && (
                                <button
                                  onClick={(e) => { e.stopPropagation(); onSendToEdit(imgUrl) }}
                                  className="p-1.5 bg-purple-500/30 backdrop-blur-sm rounded-lg text-purple-200 hover:bg-purple-500/50 transition-colors"
                                  title="Edit"
                                >
                                  <PenLine size={13} />
                                </button>
                              )}
                              <button
                                onClick={(e) => {
                                  e.stopPropagation()
                                  const a = document.createElement('a')
                                  a.href = imgUrl
                                  a.download = `outfit_${r.seed ?? i}.png`
                                  a.click()
                                }}
                                className="p-1.5 bg-white/10 backdrop-blur-sm rounded-lg text-white/80 hover:bg-white/20 transition-colors"
                                title="Download"
                              >
                                <Download size={13} />
                              </button>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* ═══════════ WARDROBE (INVENTORY) ═══════════ */}
          <div className="border-t border-white/[0.06] pt-6">
            {/* Wardrobe header */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-500/70 to-orange-500/70 flex items-center justify-center">
                  <Shirt size={15} className="text-white" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">
                    Wardrobe
                    {outfits.length > 0 && (
                      <span className="text-white/25 font-normal ml-1.5">({outfits.length})</span>
                    )}
                  </h3>
                  <p className="text-[10px] text-white/30 mt-0.5">
                    {outfits.length === 0
                      ? 'Generate outfits to fill your inventory'
                      : 'Your collection of outfit variations'}
                  </p>
                </div>
              </div>

              {/* Filter dropdown (only when tags exist) */}
              {availableTags.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <Filter size={12} className="text-white/25" />
                  <select
                    value={wardrobeFilter}
                    onChange={(e) => setWardrobeFilter(e.target.value as OutfitScenarioTag | 'all')}
                    className="bg-white/[0.04] border border-white/[0.08] rounded-lg px-2.5 py-1.5 text-[11px] text-white/50 focus:outline-none focus:border-white/15 appearance-none cursor-pointer"
                  >
                    <option value="all">All Outfits</option>
                    {availableTags.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.icon} {t.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            {/* Wardrobe grid — RPG inventory style */}
            <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 lg:grid-cols-6 gap-3">
              {/* Filled outfit slots */}
              {filteredOutfits.map((o) => {
                const outfitUrl = resolveUrl(o.url, backendUrl)
                const tagMeta = getTagMeta(o.scenarioTag)
                return (
                  <WardrobeSlot
                    key={o.id}
                    item={o}
                    imageUrl={outfitUrl}
                    tagMeta={tagMeta}
                    onOpenLightbox={onOpenLightbox}
                    onSendToEdit={onSendToEdit}
                    onDelete={onDeleteItem}
                  />
                )
              })}

              {/* Empty inventory slots */}
              {Array.from({ length: Math.max(0, MIN_WARDROBE_SLOTS - filteredOutfits.length) }).map((_, i) => (
                <div
                  key={`empty-${i}`}
                  className="aspect-[2/3] rounded-xl border-2 border-dashed border-white/[0.06] bg-white/[0.01] flex flex-col items-center justify-center gap-1.5 group hover:border-cyan-500/20 hover:bg-cyan-500/[0.02] transition-all cursor-default"
                >
                  <Plus size={18} className="text-white/10 group-hover:text-cyan-500/30 transition-colors" />
                  <span className="text-[9px] text-white/10 group-hover:text-cyan-500/25 font-medium transition-colors">
                    Empty Slot
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .animate-fadeSlideIn {
          animation: fadeSlideIn 0.3s ease-out;
        }
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

// ---------------------------------------------------------------------------
// WardrobeSlot — individual outfit in the RPG inventory grid
// ---------------------------------------------------------------------------

function WardrobeSlot({
  item,
  imageUrl,
  tagMeta,
  onOpenLightbox,
  onSendToEdit,
  onDelete,
}: {
  item: GalleryItem
  imageUrl: string
  tagMeta?: ScenarioTagMeta
  onOpenLightbox?: (url: string) => void
  onSendToEdit?: (url: string) => void
  onDelete?: (id: string) => void
}) {
  return (
    <div className="group relative rounded-xl overflow-hidden border border-white/[0.06] bg-white/[0.02] hover:border-white/15 transition-all">
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

        {/* Scenario tag badge */}
        {tagMeta && (
          <div className="absolute top-1.5 left-1.5 px-1.5 py-0.5 rounded-md bg-black/50 backdrop-blur-sm text-[8px] text-white/70 font-medium flex items-center gap-1 border border-white/[0.08]">
            <span>{tagMeta.icon}</span>
            <span>{tagMeta.label}</span>
          </div>
        )}

        {/* Hover overlay */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex flex-col justify-between p-2">
          <div className="flex justify-end gap-1">
            {onSendToEdit && (
              <button
                onClick={(e) => { e.stopPropagation(); onSendToEdit(imageUrl) }}
                className="p-1.5 bg-purple-500/30 backdrop-blur-sm rounded-lg text-purple-200 hover:bg-purple-500/50 transition-colors"
                title="Edit"
              >
                <PenLine size={11} />
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
              <Download size={11} />
            </button>
            {onDelete && (
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(item.id) }}
                className="p-1.5 bg-red-500/10 backdrop-blur-sm rounded-lg text-red-300/50 hover:bg-red-500/30 hover:text-red-300 transition-colors"
                title="Delete"
              >
                <Trash2 size={11} />
              </button>
            )}
          </div>
          <div>
            {item.prompt && (
              <p className="text-[9px] text-white/70 line-clamp-2 mb-0.5">{item.prompt}</p>
            )}
            <div className="text-[8px] text-white/40 flex items-center gap-1">
              <Clock size={7} />
              {formatTimeAgo(item.createdAt)}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
