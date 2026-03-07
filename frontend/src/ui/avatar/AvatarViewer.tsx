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

import React, { useState, useMemo, useCallback, useEffect } from 'react'
import {
  ChevronLeft,
  Shirt,
  PenLine,
  Download,
  UserPlus,
  Maximize2,
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
  Filter,
  X,
  ArrowRightLeft,
  Image as ImageIcon,
  Expand,
  ChevronDown,
} from 'lucide-react'

import type { GalleryItem, OutfitScenarioTag, ScenarioTagMeta } from './galleryTypes'
import { SCENARIO_TAG_META } from './galleryTypes'
import type { AvatarMode, AvatarResult } from './types'
import { OUTFIT_PRESETS, ACCESSORY_OPTIONS } from '../personaTypes'
import {
  LINGERIE_GARMENTS,
  LINGERIE_STYLES,
  LINGERIE_FABRICS,
  LINGERIE_BRANDS,
  LINGERIE_EXTRAS,
} from './wizard/wizardTypes'
import type { LingerieGarment, LingerieSelectionsMap, LingerieGarmentSelection } from './wizard/wizardTypes'
import { useOutfitGeneration } from './useOutfitGeneration'
import { useGenerateHybridBody } from './useGenerateHybridBody'
import { fetchAvatarCapabilities } from './avatarApi'
import { AvatarSettingsPanel, resolveCheckpoint, loadAvatarSettings } from './AvatarSettingsPanel'
import type { AvatarSettings, HybridFullBodyRequest } from './types'
import { resolveFileUrl } from '../resolveFileUrl'
import { AvatarGeneratingLoader } from './AvatarGeneratingLoader'

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
  onSwapAnchor?: (anchorId: string, portraitId: string) => void
  onOutfitResults?: (results: AvatarResult[], anchorItem: GalleryItem) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveUrl(url: string, backendUrl: string): string {
  return resolveFileUrl(url, backendUrl)
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
  onSwapAnchor,
  onOutfitResults,
}: AvatarViewerProps) {
  const [copiedSeed, setCopiedSeed] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [wardrobeFilter, setWardrobeFilter] = useState<OutfitScenarioTag | 'all'>('all')
  const [wardrobeFilterOpen, setWardrobeFilterOpen] = useState(false)
  const [avatarSettingsState, setAvatarSettingsState] = useState<AvatarSettings>(loadAvatarSettings)

  // Outfit generation state
  const outfit = useOutfitGeneration(backendUrl, apiKey)
  const [selectedPreset, setSelectedPreset] = useState<string | null>('corporate')
  const [customPrompt, setCustomPrompt] = useState('')
  const [outfitCount, setOutfitCount] = useState(1)
  const [outfitCopiedSeed, setOutfitCopiedSeed] = useState<number | null>(null)
  const [outfitTab, setOutfitTab] = useState<'standard' | 'romance' | '18+'>('standard')
  const [showAdvancedOutfit, setShowAdvancedOutfit] = useState(false)
  const [outfitPrimaryColor, setOutfitPrimaryColor] = useState<string | null>(null)
  const [outfitSecondaryColor, setOutfitSecondaryColor] = useState<string | null>(null)
  const [selectedAccessories, setSelectedAccessories] = useState<string[]>([])
  const [showAccessories, setShowAccessories] = useState(false)
  // Lingerie builder — per-garment persistent selections
  const [lingerieType, setLingerieType] = useState<LingerieGarment | null>(null) // currently viewing
  const [lingerieActiveGarments, setLingerieActiveGarments] = useState<LingerieGarment[]>([])
  const [lingerieSelections, setLingerieSelections] = useState<LingerieSelectionsMap>({})
  const [lingerieExtras, setLingerieExtras] = useState<string[]>([])

  // Headshot avatars lack visible torso/clothing — outfit generation produces poor results
  const isHeadshot = item.framingType === 'headshot'

  // Expand headshot → half-body via hybrid pipeline
  const hybridBody = useGenerateHybridBody(backendUrl, apiKey)
  const [hybridAvailable, setHybridAvailable] = useState<boolean | null>(null) // null = loading

  // Stage toggle: flip between anchor face, latest outfit, or equipped wardrobe item
  const [stageTab, setStageTab] = useState<'anchor' | 'outfit'>('anchor')
  const [selectedResultIdx, setSelectedResultIdx] = useState(0)
  // MMORPG "equip" — clicking a wardrobe item shows it on the stage
  const [equippedItem, setEquippedItem] = useState<GalleryItem | null>(null)

  // Auto-switch to Latest Outfit tab when new results arrive
  useEffect(() => {
    if (outfit.results.length > 0) {
      setStageTab('outfit')
      setSelectedResultIdx(0)
      setEquippedItem(null) // new generation overrides equipped
    }
  }, [outfit.results])

  // Check if hybrid body pipeline is available (for headshot → half-body expand)
  useEffect(() => {
    if (!isHeadshot) return
    let cancelled = false
    fetchAvatarCapabilities(backendUrl, apiKey)
      .then((caps) => {
        if (cancelled) return
        const comfyOk = caps.engines?.comfyui?.available ?? false
        const modes = caps.enabled_modes ?? []
        // Hybrid body requires ComfyUI + identity models (studio_reference or hybrid modes)
        const hasIdentity = modes.includes('studio_reference') || modes.includes('hybrid_body')
        const bodyEnabled = avatarSettingsState.bodyWorkflowMethod !== 'disabled'
        setHybridAvailable(comfyOk && hasIdentity && bodyEnabled)
      })
      .catch(() => {
        if (!cancelled) setHybridAvailable(false)
      })
    return () => { cancelled = true }
  }, [isHeadshot, backendUrl, apiKey, avatarSettingsState.bodyWorkflowMethod])

  const handleExpandToHalfBody = useCallback(async () => {
    if (!isHeadshot || hybridBody.loading) return
    try {
      const req: HybridFullBodyRequest = {
        face_image_url: item.url,
        count: 2,
        workflow_method: avatarSettingsState.bodyWorkflowMethod === 'disabled' ? 'default' : avatarSettingsState.bodyWorkflowMethod,
        outfit_style: 'casual',
        posture: 'standing relaxed',
        lighting: 'professional studio lighting',
      }
      await hybridBody.run(req)
    } catch {
      // Error captured in hook state
    }
  }, [isHeadshot, hybridBody, item.url, avatarSettingsState.bodyWorkflowMethod])

  // Equip handler — like clicking armor in an MMO inventory
  const handleEquip = useCallback((wardrobeItem: GalleryItem) => {
    setEquippedItem(wardrobeItem)
    setStageTab('outfit')
  }, [])

  const handleUnequip = useCallback(() => {
    setEquippedItem(null)
    setStageTab('anchor')
  }, [])

  const heroUrl = resolveUrl(item.url, backendUrl)

  const checkpoint = resolveCheckpoint(avatarSettingsState, globalModelImages)
  const readNsfw = useCallback(() => {
    try { return localStorage.getItem('homepilot_nsfw_mode') === 'true' } catch { return false }
  }, [])
  const [nsfwMode, setNsfwMode] = useState(readNsfw)
  useEffect(() => {
    const sync = () => setNsfwMode(readNsfw())
    window.addEventListener('focus', sync)
    window.addEventListener('storage', sync)
    const interval = setInterval(sync, 1000)
    return () => {
      window.removeEventListener('focus', sync)
      window.removeEventListener('storage', sync)
      clearInterval(interval)
    }
  }, [readNsfw])

  // Root character ID — if viewing an outfit, resolve to its parent
  const rootCharacterId = item.parentId || item.id

  // Children of this character — items with parentId pointing here
  const children = useMemo(() => {
    return allItems.filter(
      (g) =>
        g.id !== item.id &&
        (
          g.parentId === rootCharacterId ||
          (!g.parentId && g.referenceUrl && (
            g.referenceUrl === item.url ||
            resolveUrl(g.referenceUrl, backendUrl) === heroUrl
          ))
        ),
    )
  }, [allItems, item, rootCharacterId, heroUrl, backendUrl])

  // Split: portraits (alternative face photos) vs outfits (generated clothing/scenes)
  const portraits = useMemo(() => children.filter((g) => g.role === 'portrait'), [children])
  const outfits = useMemo(() => children.filter((g) => g.role !== 'portrait'), [children])

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

  // Presets filtered by tab + NSFW mode
  const presets = OUTFIT_PRESETS.filter((p) => {
    if (p.category === 'nsfw' && !nsfwMode) return false
    const group = p.group || (p.category === 'sfw' ? 'standard' : 'romance')
    return group === outfitTab
  })

  const isLingerieSelected = selectedPreset === 'lingerie' || selectedPreset === 'boudoir'

  const effectivePrompt = (() => {
    let base = ''
    if (customPrompt.trim()) {
      base = customPrompt.trim()
    } else if (selectedPreset) {
      const preset = presets.find((p) => p.id === selectedPreset)
      base = preset?.prompt || ''
    }
    if (!base) return ''
    // Append advanced options to the prompt
    const extras: string[] = []
    // Lingerie builder — iterates over all active garments for multi-piece outfits
    if (isLingerieSelected) {
      const garments = lingerieActiveGarments.length > 0 ? lingerieActiveGarments : (lingerieType ? [lingerieType] : [])
      for (const gId of garments) {
        const garment = LINGERIE_GARMENTS.find((g) => g.id === gId)
        if (garment) extras.push(garment.prompt)
        const sel = lingerieSelections[gId]
        if (sel?.style) {
          const styles = LINGERIE_STYLES[gId]
          const style = styles?.find((s) => s.id === sel.style)
          if (style) extras.push(style.prompt)
        }
        if (sel?.fabric) {
          const fabric = LINGERIE_FABRICS.find((f) => f.id === sel.fabric)
          if (fabric) extras.push(fabric.prompt)
        }
        if (sel?.brand) {
          const brand = LINGERIE_BRANDS.find((b) => b.id === sel.brand)
          if (brand) extras.push(brand.prompt)
        }
      }
      for (const extId of lingerieExtras) {
        const ext = LINGERIE_EXTRAS.find((e) => e.id === extId)
        if (ext) extras.push(ext.prompt)
      }
    }
    if (outfitPrimaryColor) extras.push(`${outfitPrimaryColor} colored outfit`)
    if (outfitSecondaryColor) extras.push(`${outfitSecondaryColor} accents`)
    if (selectedAccessories.length > 0) {
      const accPrompts = selectedAccessories
        .map((id) => ACCESSORY_OPTIONS.find((a) => a.id === id)?.prompt)
        .filter(Boolean)
      extras.push(...accPrompts as string[])
    }
    return extras.length > 0 ? `${base}, ${extras.join(', ')}` : base
  })()

  const canGenerateOutfit = !outfit.loading && effectivePrompt.length > 0 && !isHeadshot

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
        // Tag each result with the scenario tag + ensure parentId resolves to root
        onOutfitResults?.(result.results, { ...item, scenarioTag, parentId: rootCharacterId })
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

      {/* ═══════════════════════ VIEWPORT-LOCKED BODY ═══════════════════════ */}
      {/* Middle section: flex-grow to fill between header and wardrobe */}
      <div className="flex-1 min-h-0 flex flex-col md:flex-row overflow-hidden">

        {/* ──────── LEFT PANEL: The Stage (constrained ~48% for RPG feel) ──────── */}
        <div className="w-full md:w-[48%] md:flex-shrink-0 min-h-0 flex flex-col px-5 py-3 gap-3 overflow-hidden">
              {/* Toggle tabs: Anchor Face ↔ Latest Outfit */}
              <div className="flex items-center p-1 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                <button
                  onClick={() => setStageTab('anchor')}
                  className={[
                    'flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium transition-all',
                    stageTab === 'anchor'
                      ? 'bg-white/10 text-white shadow-sm'
                      : 'text-white/35 hover:text-white/60',
                  ].join(' ')}
                >
                  <Lock size={12} />
                  Anchor Face
                </button>
                <button
                  onClick={() => setStageTab('outfit')}
                  className={[
                    'flex-1 flex items-center justify-center gap-2 py-2 rounded-lg text-xs font-medium transition-all',
                    stageTab === 'outfit'
                      ? 'bg-gradient-to-r from-cyan-600/80 to-blue-600/80 text-white shadow-sm'
                      : 'text-white/35 hover:text-white/60',
                  ].join(' ')}
                >
                  <Sparkles size={12} />
                  Latest Outfit
                  {outfit.results.length > 0 && (
                    <span className="text-[9px] opacity-60">({outfit.results.length})</span>
                  )}
                </button>
              </div>

              {/* Stage display — fills available height, image uses object-contain */}
              <div className="flex-1 min-h-0 relative">
              {(() => {
                // Resolve what to show on the stage
                const showEquipped = stageTab === 'outfit' && equippedItem
                const equippedUrl = showEquipped ? resolveUrl(equippedItem!.url, backendUrl) : ''
                const equippedTagMeta = showEquipped ? getTagMeta(equippedItem!.scenarioTag) : undefined

                if (stageTab === 'anchor') {
                  return (
                    /* ─── Anchor Face ─── */
                    <div className="relative group h-full">
                      <div className="absolute -inset-[2px] rounded-2xl bg-gradient-to-br from-purple-500/20 via-transparent to-cyan-500/20 opacity-50 group-hover:opacity-100 transition-opacity" />
                      <div
                        className="relative h-full rounded-2xl overflow-hidden border border-white/10 cursor-pointer bg-black/40 flex items-center justify-center"
                        onClick={() => onOpenLightbox?.(heroUrl)}
                      >
                        <img
                          src={heroUrl}
                          alt={item.prompt || 'Avatar portrait'}
                          className="max-w-full max-h-full object-contain"
                        />
                        <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                          <Maximize2 size={28} className="text-white/80" />
                        </div>
                      </div>
                    </div>
                  )
                }

                if (showEquipped) {
                  return (
                    /* ─── Equipped wardrobe item (MMORPG-style) ─── */
                    <div className="relative group h-full animate-fadeSlideIn">
                      <div className="absolute -inset-[2px] rounded-2xl bg-gradient-to-br from-amber-500/25 via-transparent to-orange-500/25 opacity-60 group-hover:opacity-100 transition-opacity" />
                      <div
                        className="relative h-full rounded-2xl overflow-hidden border border-amber-500/20 cursor-pointer bg-black/40 flex items-center justify-center"
                        onClick={() => onOpenLightbox?.(equippedUrl)}
                      >
                        <img
                          src={equippedUrl}
                          alt={equippedItem!.prompt || 'Equipped outfit'}
                          className="max-w-full max-h-full object-contain"
                        />
                        {/* Equipped badge */}
                        {equippedTagMeta && (
                          <div className="absolute top-3 left-3 flex items-center gap-1.5 px-2 py-1 rounded-lg bg-black/50 backdrop-blur-sm border border-amber-500/20 text-[10px] text-amber-200 font-medium">
                            <span>{equippedTagMeta.icon}</span>
                            <span>{equippedTagMeta.label}</span>
                          </div>
                        )}
                        {/* Unequip button — return to base */}
                        <button
                          onClick={(e) => { e.stopPropagation(); handleUnequip() }}
                          className="absolute top-3 right-3 w-8 h-8 rounded-lg bg-black/60 backdrop-blur-sm border border-white/15 flex items-center justify-center text-white/60 hover:text-white hover:bg-red-500/40 hover:border-red-500/30 transition-all"
                          title="Unequip — return to base"
                        >
                          <X size={14} />
                        </button>
                        <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center pointer-events-none">
                          <Maximize2 size={28} className="text-white/80" />
                        </div>
                      </div>
                    </div>
                  )
                }

                if (outfit.loading && outfit.results.length === 0) {
                  return (
                    /* ─── Professional generating loader ─── */
                    <div className="h-full rounded-2xl bg-white/[0.02] border border-white/[0.06] flex items-center justify-center">
                      <AvatarGeneratingLoader
                        label="Generating outfit…"
                        hint="Creating your look"
                      />
                    </div>
                  )
                }

                if (outfit.results.length > 0) {
                  return (
                    /* ─── Latest outfit result (full size) ─── */
                    <div className="relative group h-full animate-fadeSlideIn">
                      <div className="absolute -inset-[2px] rounded-2xl bg-gradient-to-br from-cyan-500/20 via-transparent to-blue-500/20 opacity-50 group-hover:opacity-100 transition-opacity" />
                      <div
                        className="relative h-full rounded-2xl overflow-hidden border border-cyan-500/15 cursor-pointer bg-black/40 flex items-center justify-center"
                        onClick={() => onOpenLightbox?.(resolveUrl(outfit.results[selectedResultIdx].url, backendUrl))}
                      >
                        <img
                          src={resolveUrl(outfit.results[selectedResultIdx].url, backendUrl)}
                          alt={`Outfit result ${selectedResultIdx + 1}`}
                          className="max-w-full max-h-full object-contain"
                        />
                        <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                          <Maximize2 size={28} className="text-white/80" />
                        </div>
                      </div>
                    </div>
                  )
                }

                return (
                  /* ─── Empty outfit state ─── */
                  <div className="h-full rounded-2xl border-2 border-dashed border-white/[0.08] bg-white/[0.01] flex flex-col items-center justify-center gap-2">
                    <Shirt size={32} className="text-white/15" />
                    <span className="text-xs text-white/25">Click a wardrobe item to equip it, or generate a new outfit</span>
                  </div>
                )
              })()}
              </div>

              {/* Result thumbnail filmstrip (when multiple results and no equipped item) */}
              {stageTab === 'outfit' && !equippedItem && outfit.results.length > 1 && (
                <div className="flex gap-1.5 overflow-x-auto scrollbar-hide flex-shrink-0">
                  {outfit.results.map((r, i) => (
                    <button
                      key={i}
                      onClick={() => setSelectedResultIdx(i)}
                      className={[
                        'flex-shrink-0 w-10 h-10 rounded-lg overflow-hidden border-2 transition-all',
                        selectedResultIdx === i
                          ? 'border-cyan-500/60 ring-1 ring-cyan-500/20'
                          : 'border-white/10 hover:border-white/25',
                      ].join(' ')}
                    >
                      <img src={resolveUrl(r.url, backendUrl)} alt={`Result ${i + 1}`} className="w-full h-full object-cover" />
                    </button>
                  ))}
                </div>
              )}

              {/* ── Alternative Portraits strip (swap anchor) ── */}
              {portraits.length > 0 && stageTab === 'anchor' && (
                <div className="flex-shrink-0">
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <ImageIcon size={10} className="text-purple-400/60" />
                    <span className="text-[9px] text-white/30 font-medium uppercase tracking-wider">Alternatives</span>
                    <span className="text-[9px] text-white/15">— click to swap</span>
                  </div>
                  <div className="flex gap-1.5 overflow-x-auto scrollbar-hide">
                    {portraits.map((p) => (
                      <button
                        key={p.id}
                        onClick={() => onSwapAnchor?.(rootCharacterId, p.id)}
                        className="flex-shrink-0 w-12 h-12 rounded-lg overflow-hidden border-2 border-white/10 hover:border-purple-500/50 hover:ring-1 hover:ring-purple-500/20 transition-all group relative"
                        title="Set as main portrait"
                      >
                        <img src={resolveUrl(p.url, backendUrl)} alt="Portrait" className="w-full h-full object-cover" />
                        <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                          <ArrowRightLeft size={12} className="text-purple-300" />
                        </div>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Compact metadata + actions bar */}
              <div className="flex items-center gap-3 flex-shrink-0 flex-wrap">
                {/* Metadata */}
                <div className="flex items-center gap-2 text-[10px] text-white/35 flex-1 min-w-0">
                  {stageTab === 'anchor' ? (
                    <>
                      <span className="flex items-center gap-1">
                        <Clock size={10} />
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
                              <Check size={9} /> copied
                            </span>
                          ) : (
                            <>
                              Seed: {item.seed}
                              <Copy size={8} />
                            </>
                          )}
                        </button>
                      )}
                      {item.personaProjectId && (
                        <span className="flex items-center gap-1 text-purple-300/60">
                          <UserPlus size={10} />
                          Persona
                        </span>
                      )}
                    </>
                  ) : equippedItem ? (
                    <>
                      <span className="flex items-center gap-1 text-amber-400/60">
                        <Shirt size={10} />
                        Equipped
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock size={10} />
                        {formatTimeAgo(equippedItem.createdAt)}
                      </span>
                      {equippedItem.seed !== undefined && (
                        <span className="font-mono">Seed: {equippedItem.seed}</span>
                      )}
                    </>
                  ) : outfit.results.length > 0 ? (
                    <>
                      <span className="flex items-center gap-1">
                        <Clock size={10} />
                        Just now
                      </span>
                      {outfit.results[selectedResultIdx]?.seed !== undefined && (
                        <button
                          onClick={() => handleOutfitCopySeed(outfit.results[selectedResultIdx].seed!)}
                          className="flex items-center gap-1 font-mono hover:text-white/60 transition-colors"
                          title="Copy seed"
                        >
                          {outfitCopiedSeed === outfit.results[selectedResultIdx].seed ? (
                            <span className="flex items-center gap-1 text-green-400">
                              <Check size={9} /> copied
                            </span>
                          ) : (
                            <>Seed: {outfit.results[selectedResultIdx].seed} <Copy size={8} /></>
                          )}
                        </button>
                      )}
                    </>
                  ) : null}
                </div>

                {/* Action buttons (compact) */}
                <div className="flex items-center gap-1.5 flex-shrink-0">
                {stageTab === 'anchor' ? (
                  <>
                    {onSaveAsPersonaAvatar && !item.personaProjectId && (
                      <button onClick={() => onSaveAsPersonaAvatar(item)} className="p-1.5 rounded-lg border border-emerald-500/15 bg-emerald-500/[0.06] text-emerald-300 hover:bg-emerald-500/10 transition-all" title="Export to Persona">
                        <UserPlus size={13} />
                      </button>
                    )}
                    {onSendToEdit && (
                      <button onClick={() => onSendToEdit(heroUrl)} className="p-1.5 rounded-lg border border-purple-500/15 bg-purple-500/[0.06] text-purple-300 hover:bg-purple-500/10 transition-all" title="Edit">
                        <PenLine size={13} />
                      </button>
                    )}
                    <button onClick={() => { const a = document.createElement('a'); a.href = heroUrl; a.download = `avatar_${item.seed ?? item.id}.png`; a.click() }} className="p-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] text-white/50 hover:bg-white/[0.06] hover:text-white/70 transition-all" title="Download">
                      <Download size={13} />
                    </button>
                    {onDeleteItem && (
                      <button onClick={handleDelete} className={`p-1.5 rounded-lg border transition-all ${confirmDelete ? 'border-red-500/30 bg-red-500/15 text-red-300' : 'border-red-500/[0.08] bg-red-500/[0.04] text-red-400/50 hover:bg-red-500/[0.08] hover:text-red-400'}`} title={confirmDelete ? 'Confirm delete' : 'Delete'}>
                        <Trash2 size={13} />
                      </button>
                    )}
                  </>
                ) : equippedItem ? (
                  <>
                    <button onClick={handleUnequip} className="p-1.5 rounded-lg border border-amber-500/15 bg-amber-500/[0.06] text-amber-300 hover:bg-amber-500/10 transition-all" title="Unequip">
                      <X size={13} />
                    </button>
                    {onSendToEdit && (
                      <button onClick={() => onSendToEdit(resolveUrl(equippedItem.url, backendUrl))} className="p-1.5 rounded-lg border border-purple-500/15 bg-purple-500/[0.06] text-purple-300 hover:bg-purple-500/10 transition-all" title="Edit">
                        <PenLine size={13} />
                      </button>
                    )}
                    <button onClick={() => { const url = resolveUrl(equippedItem.url, backendUrl); const a = document.createElement('a'); a.href = url; a.download = `outfit_${equippedItem.seed ?? equippedItem.id}.png`; a.click() }} className="p-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] text-white/50 hover:bg-white/[0.06] hover:text-white/70 transition-all" title="Download">
                      <Download size={13} />
                    </button>
                  </>
                ) : outfit.results.length > 0 ? (
                  <>
                    {onSendToEdit && (
                      <button onClick={() => onSendToEdit(resolveUrl(outfit.results[selectedResultIdx].url, backendUrl))} className="p-1.5 rounded-lg border border-purple-500/15 bg-purple-500/[0.06] text-purple-300 hover:bg-purple-500/10 transition-all" title="Edit">
                        <PenLine size={13} />
                      </button>
                    )}
                    <button onClick={() => { const url = resolveUrl(outfit.results[selectedResultIdx].url, backendUrl); const a = document.createElement('a'); a.href = url; a.download = `outfit_${outfit.results[selectedResultIdx].seed ?? selectedResultIdx}.png`; a.click() }} className="p-1.5 rounded-lg border border-white/[0.08] bg-white/[0.03] text-white/50 hover:bg-white/[0.06] hover:text-white/70 transition-all" title="Download">
                      <Download size={13} />
                    </button>
                  </>
                ) : null}
                </div>
              </div>
            </div>

            {/* ──────── RIGHT PANEL: Outfit Studio (expands to fill) ──────── */}
            <div className="w-full md:flex-1 overflow-y-auto scrollbar-hide px-5 py-3 border-l border-white/[0.06]">
              <div className="max-w-md space-y-4">
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
                    Face locked
                  </div>
                </div>
              </div>

              {/* Anchor Face mini-preview (always visible as context) */}
              <div className="flex items-center gap-3 px-3 py-2.5 rounded-xl bg-white/[0.03] border border-white/[0.06]">
                <div className="w-10 h-10 rounded-lg overflow-hidden border border-white/10 flex-shrink-0">
                  <img src={heroUrl} alt="Anchor face" className="w-full h-full object-cover" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-[10px] text-white/40 font-medium">Identity Anchor</div>
                  <div className="text-[11px] text-white/60 truncate">{item.prompt || 'Your character'}</div>
                </div>
              </div>

              {/* Headshot — expand to half-body or warning */}
              {isHeadshot && (
                <div className="space-y-3">
                  {/* Info + Expand button */}
                  <div className="px-3 py-3 rounded-xl bg-amber-500/[0.06] border border-amber-500/15">
                    <div className="flex items-start gap-2.5">
                      <AlertTriangle size={14} className="text-amber-400 mt-0.5 shrink-0" />
                      <div className="flex-1">
                        <div className="text-[11px] text-amber-200 font-medium">Headshot — outfit generation unavailable</div>
                        <div className="text-[10px] text-amber-400/60 mt-0.5">
                          Close-up headshots have no visible body. Expand to a half-body portrait to unlock outfit generation.
                        </div>
                      </div>
                    </div>
                    {hybridAvailable === null ? (
                      <div className="flex items-center gap-2 mt-2.5 text-[10px] text-white/30">
                        <Loader2 size={12} className="animate-spin" />
                        Checking pipeline availability...
                      </div>
                    ) : hybridAvailable ? (
                      <button
                        onClick={handleExpandToHalfBody}
                        disabled={hybridBody.loading}
                        className={[
                          'mt-2.5 w-full flex items-center justify-center gap-2 py-2.5 rounded-xl text-xs font-semibold transition-all',
                          hybridBody.loading
                            ? 'bg-white/[0.04] text-white/30 cursor-wait'
                            : 'bg-gradient-to-r from-emerald-600 to-teal-600 text-white shadow-lg shadow-emerald-500/15 hover:shadow-emerald-500/25 hover:brightness-110 active:scale-[0.99]',
                        ].join(' ')}
                      >
                        {hybridBody.loading ? (
                          <>
                            <Loader2 size={14} className="animate-spin" />
                            Expanding to half-body...
                          </>
                        ) : (
                          <>
                            <Expand size={14} />
                            Expand to Half-Body Portrait
                          </>
                        )}
                      </button>
                    ) : (
                      <div className="text-[10px] text-white/25 mt-2 italic">
                        Half-body expansion requires ComfyUI + Identity models (InstantID). Check Avatar Settings.
                      </div>
                    )}
                  </div>

                  {/* Hybrid body error */}
                  {hybridBody.error && (
                    <div className="flex items-center gap-2 px-3 py-2.5 rounded-xl bg-red-500/[0.08] border border-red-500/15 text-red-300 text-xs">
                      <AlertTriangle size={14} />
                      <span>{hybridBody.error}</span>
                    </div>
                  )}

                  {/* Expand results grid */}
                  {hybridBody.result?.results && hybridBody.result.results.length > 0 && (
                    <div>
                      <div className="text-[10px] text-white/40 mb-2 font-semibold uppercase tracking-wider">
                        Half-Body Results — select to save
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        {hybridBody.result.results.map((r, i) => {
                          const imgUrl = resolveUrl(r.url, backendUrl)
                          return (
                            <div
                              key={i}
                              className="group relative rounded-xl overflow-hidden border border-white/10 bg-white/[0.02] hover:border-emerald-500/30 transition-all cursor-pointer"
                              onClick={() => onOpenLightbox?.(imgUrl)}
                            >
                              <div className="aspect-[2/3] bg-white/[0.03]">
                                <img
                                  src={imgUrl}
                                  alt={`Half-body ${i + 1}`}
                                  className="w-full h-full object-cover"
                                  loading="lazy"
                                />
                              </div>
                              {/* Hover actions */}
                              <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
                                {onSendToEdit && (
                                  <button
                                    onClick={(e) => { e.stopPropagation(); onSendToEdit(imgUrl) }}
                                    className="p-2 bg-purple-500/30 backdrop-blur-md rounded-lg text-purple-200 hover:bg-purple-500/50 transition-colors"
                                    title="Edit"
                                  >
                                    <PenLine size={14} />
                                  </button>
                                )}
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    const a = document.createElement('a')
                                    a.href = imgUrl
                                    a.download = `halfbody_${r.seed ?? i}.png`
                                    a.click()
                                  }}
                                  className="p-2 bg-white/10 backdrop-blur-md rounded-lg text-white hover:bg-white/20 transition-colors"
                                  title="Download"
                                >
                                  <Download size={14} />
                                </button>
                              </div>
                              {/* Seed label */}
                              <div className="px-2 py-1.5 text-[10px] text-white/30 font-mono">
                                seed {r.seed ?? '---'}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                      {/* Warnings from hybrid pipeline */}
                      {hybridBody.result.warnings && hybridBody.result.warnings.length > 0 && (
                        <div className="flex items-start gap-2 px-3 py-2 mt-2 rounded-lg bg-amber-500/[0.06] border border-amber-500/15 text-amber-400 text-[10px]">
                          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                          <div>{hybridBody.result.warnings.join(' ')}</div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Loading skeleton for expand */}
                  {hybridBody.loading && !hybridBody.result?.results?.length && (
                    <AvatarGeneratingLoader
                      label="Expanding to half-body…"
                      count={2}
                    />
                  )}
                </div>
              )}

              {/* ═══ Outfit Tabs ═══ */}
              <div>
                <div className="text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider">
                  Outfit Style
                </div>

                {/* Tab bar */}
                <div className="flex items-center gap-1 p-1 rounded-xl bg-white/[0.03] border border-white/[0.06] mb-3">
                  {([
                    { id: 'standard' as const, label: 'Standard' },
                    { id: 'romance' as const, label: 'Romance & Roleplay' },
                    ...(nsfwMode ? [{ id: '18+' as const, label: '18+' }] : []),
                  ]).map((tab) => {
                    const active = outfitTab === tab.id
                    return (
                      <button
                        key={tab.id}
                        onClick={() => {
                          setOutfitTab(tab.id)
                          const group = tab.id === 'standard' ? 'standard' : tab.id
                          const first = OUTFIT_PRESETS.find((p) => (p.group || (p.category === 'sfw' ? 'standard' : 'romance')) === group)
                          setSelectedPreset(first?.id ?? null)
                        }}
                        className={[
                          'flex-1 px-2.5 py-2 rounded-lg text-[10px] font-medium transition-all',
                          active
                            ? 'bg-white/10 text-white border border-white/15 shadow-sm'
                            : 'text-white/35 hover:text-white/55 hover:bg-white/[0.04] border border-transparent',
                        ].join(' ')}
                      >
                        {tab.label}
                      </button>
                    )
                  })}
                </div>

                {/* Preset badge grid */}
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

              {/* ── Lingerie Builder — only visible when lingerie/boudoir selected ── */}
              {isLingerieSelected && (() => {
                const currentSel: LingerieGarmentSelection = lingerieType ? (lingerieSelections[lingerieType] ?? {}) : {}
                const updateSel = (patch: Partial<LingerieGarmentSelection>) => {
                  if (!lingerieType) return
                  setLingerieSelections((prev) => ({
                    ...prev,
                    [lingerieType]: { ...(prev[lingerieType] ?? {}), ...patch },
                  }))
                }
                return (
                <div className="space-y-3 p-3 rounded-xl bg-rose-500/[0.03] border border-rose-500/10">
                  {/* Garment Type — multi-select, click toggles active + sets viewing */}
                  <div>
                    <div className="text-[10px] text-rose-300/50 mb-2 font-medium uppercase tracking-wider">Garment Type</div>
                    <div className="text-[9px] text-white/30 mb-1.5">Select one or more pieces. Click to toggle &amp; configure.</div>
                    <div className="flex flex-wrap gap-1.5">
                      {LINGERIE_GARMENTS.map((g) => {
                        const isActive = lingerieActiveGarments.includes(g.id)
                        const isViewing = lingerieType === g.id
                        return (
                          <button
                            key={g.id}
                            onClick={() => {
                              if (isViewing) {
                                // Second click → deactivate
                                setLingerieType(null)
                                setLingerieActiveGarments((prev) => prev.filter((x) => x !== g.id))
                              } else if (isActive) {
                                // Already active → switch to view
                                setLingerieType(g.id)
                              } else {
                                // Activate + view
                                setLingerieType(g.id)
                                setLingerieActiveGarments((prev) => [...prev, g.id])
                              }
                            }}
                            className={[
                              'flex items-center gap-1.5 px-3 py-2 rounded-lg text-[11px] font-medium border transition-all',
                              isViewing
                                ? 'border-rose-500/40 bg-rose-500/15 text-rose-200 shadow-[0_0_8px_rgba(244,63,94,0.1)]'
                                : isActive
                                  ? 'border-rose-500/20 bg-rose-500/5 text-rose-300/60'
                                  : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:text-white/60 hover:border-white/10',
                            ].join(' ')}
                          >
                            <span className="text-sm">{g.icon}</span>
                            <span>{g.label}{isActive && !isViewing ? ' \u2713' : ''}</span>
                          </button>
                        )
                      })}
                    </div>
                    {/* Active garment summary chips */}
                    {lingerieActiveGarments.length > 1 && (
                      <div className="flex flex-wrap gap-1 mt-2">
                        {lingerieActiveGarments.map((gId) => {
                          const g = LINGERIE_GARMENTS.find((x) => x.id === gId)
                          const sel = lingerieSelections[gId]
                          const styleLabel = sel?.style && LINGERIE_STYLES[gId]?.find((s) => s.id === sel.style)?.label
                          return (
                            <span key={gId}
                              className={[
                                'text-[9px] px-2 py-0.5 rounded-full border cursor-pointer transition-all',
                                lingerieType === gId
                                  ? 'border-rose-500/40 bg-rose-500/15 text-rose-200'
                                  : 'border-white/10 bg-white/5 text-white/40 hover:text-white/60',
                              ].join(' ')}
                              onClick={() => setLingerieType(gId)}
                            >
                              {g?.icon} {g?.label}{styleLabel ? `: ${styleLabel}` : ''}
                            </span>
                          )
                        })}
                      </div>
                    )}
                  </div>

                  {/* Style Picker — scoped to currently viewed garment */}
                  {lingerieType && LINGERIE_STYLES[lingerieType] && (
                    <div>
                      <div className="text-[10px] text-rose-300/50 mb-2 font-medium uppercase tracking-wider">
                        {lingerieType === 'bottom' ? 'Panty Style' : lingerieType === 'top' ? 'Bra Style' : lingerieType === 'set' ? 'Set Style' : 'Bodysuit Style'}
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {LINGERIE_STYLES[lingerieType].map((s) => (
                          <button
                            key={s.id}
                            onClick={() => updateSel({ style: currentSel.style === s.id ? null : s.id })}
                            className={[
                              'px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-all',
                              currentSel.style === s.id
                                ? 'border-rose-500/40 bg-rose-500/15 text-rose-200'
                                : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:text-white/60',
                            ].join(' ')}
                          >
                            {s.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Fabric — scoped to currently viewed garment */}
                  {lingerieType && (
                  <div>
                    <div className="text-[10px] text-rose-300/50 mb-2 font-medium uppercase tracking-wider">Fabric</div>
                    <div className="flex flex-wrap gap-1.5">
                      {LINGERIE_FABRICS.map((f) => (
                        <button
                          key={f.id}
                          onClick={() => updateSel({ fabric: currentSel.fabric === f.id ? null : f.id })}
                          className={[
                            'px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-all',
                            currentSel.fabric === f.id
                              ? 'border-rose-500/40 bg-rose-500/15 text-rose-200'
                              : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:text-white/60',
                          ].join(' ')}
                        >
                          {f.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  )}

                  {/* Brand Inspired — scoped to currently viewed garment */}
                  {lingerieType && (
                  <div>
                    <div className="text-[10px] text-rose-300/50 mb-2 font-medium uppercase tracking-wider">Brand Inspired</div>
                    <div className="flex flex-wrap gap-1.5">
                      {LINGERIE_BRANDS.map((b) => (
                        <button
                          key={b.id}
                          onClick={() => updateSel({ brand: currentSel.brand === b.id ? null : b.id })}
                          className={[
                            'px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-all',
                            currentSel.brand === b.id
                              ? 'border-rose-500/40 bg-rose-500/15 text-rose-200'
                              : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:text-white/60',
                          ].join(' ')}
                        >
                          {b.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  )}

                  {/* Lingerie Accessories — shared across all garments */}
                  <div>
                    <div className="text-[10px] text-rose-300/50 mb-2 font-medium uppercase tracking-wider">Lingerie Accessories</div>
                    <div className="flex flex-wrap gap-1.5">
                      {LINGERIE_EXTRAS.map((e) => {
                        const active = lingerieExtras.includes(e.id)
                        return (
                          <button
                            key={e.id}
                            onClick={() => setLingerieExtras((prev) =>
                              active ? prev.filter((x) => x !== e.id) : [...prev, e.id],
                            )}
                            className={[
                              'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-all',
                              active
                                ? 'border-rose-500/40 bg-rose-500/15 text-rose-200'
                                : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:text-white/60',
                            ].join(' ')}
                          >
                            <span>{e.icon}</span>
                            <span>{e.label}</span>
                          </button>
                        )
                      })}
                    </div>
                  </div>
                </div>
                )
              })()}

              {/* ═══ Advanced Options (collapsible) ═══ */}
              <div>
                <button
                  onClick={() => setShowAdvancedOutfit(!showAdvancedOutfit)}
                  className="flex items-center gap-2 w-full text-[10px] text-white/30 hover:text-white/50 font-semibold uppercase tracking-wider transition-colors"
                >
                  <ChevronDown size={12} className={`transition-transform ${showAdvancedOutfit ? 'rotate-0' : '-rotate-90'}`} />
                  Advanced Options
                </button>

                {showAdvancedOutfit && (
                  <div className="mt-3 space-y-4">
                    {/* Primary Color — rendered color circles */}
                    <div>
                      <div className="text-[10px] text-white/30 mb-2 font-medium">Primary Color</div>
                      <div className="flex flex-wrap gap-2">
                        {([
                          { id: 'black', hex: '#1a1a1a' }, { id: 'white', hex: '#f5f5f5' },
                          { id: 'red', hex: '#DC143C' }, { id: 'navy', hex: '#1B2A4A' },
                          { id: 'burgundy', hex: '#6F1E38' }, { id: 'emerald', hex: '#228B22' },
                          { id: 'gold', hex: '#CFB53B' }, { id: 'blush', hex: '#DE5D83' },
                        ]).map((c) => (
                          <button
                            key={c.id}
                            onClick={() => setOutfitPrimaryColor(outfitPrimaryColor === c.id ? null : c.id)}
                            title={c.id}
                            className={[
                              'w-7 h-7 rounded-full border-2 transition-all flex-shrink-0',
                              outfitPrimaryColor === c.id
                                ? 'border-cyan-400 scale-110 shadow-[0_0_8px_rgba(34,211,238,0.4)]'
                                : 'border-white/10 hover:border-white/30 hover:scale-105',
                            ].join(' ')}
                            style={{ backgroundColor: c.hex }}
                          />
                        ))}
                      </div>
                    </div>

                    {/* Secondary Color — rendered color circles */}
                    <div>
                      <div className="text-[10px] text-white/30 mb-2 font-medium">Secondary Color</div>
                      <div className="flex flex-wrap gap-2">
                        {([
                          { id: 'black', hex: '#1a1a1a' }, { id: 'white', hex: '#f5f5f5' },
                          { id: 'silver', hex: '#C0C0C0' }, { id: 'gold', hex: '#CFB53B' },
                          { id: 'cream', hex: '#FFFDD0' }, { id: 'charcoal', hex: '#36454F' },
                        ]).map((c) => (
                          <button
                            key={c.id}
                            onClick={() => setOutfitSecondaryColor(outfitSecondaryColor === c.id ? null : c.id)}
                            title={c.id}
                            className={[
                              'w-7 h-7 rounded-full border-2 transition-all flex-shrink-0',
                              outfitSecondaryColor === c.id
                                ? 'border-cyan-400 scale-110 shadow-[0_0_8px_rgba(34,211,238,0.4)]'
                                : 'border-white/10 hover:border-white/30 hover:scale-105',
                            ].join(' ')}
                            style={{ backgroundColor: c.hex }}
                          />
                        ))}
                      </div>
                    </div>

                    {/* Accessories — collapsible, hidden by default */}
                    <div>
                      <button
                        onClick={() => setShowAccessories(!showAccessories)}
                        className="flex items-center gap-1.5 text-[10px] text-white/30 hover:text-white/50 font-medium uppercase tracking-wider transition-colors"
                      >
                        <ChevronDown size={10} className={`transition-transform ${showAccessories ? 'rotate-0' : '-rotate-90'}`} />
                        Accessories
                        {selectedAccessories.length > 0 && (
                          <span className="px-1.5 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 text-[9px] font-bold">
                            {selectedAccessories.length}
                          </span>
                        )}
                      </button>
                      {showAccessories && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {ACCESSORY_OPTIONS.map((a) => {
                            const active = selectedAccessories.includes(a.id)
                            return (
                              <button
                                key={a.id}
                                onClick={() => setSelectedAccessories((prev) =>
                                  active ? prev.filter((x) => x !== a.id) : [...prev, a.id],
                                )}
                                className={[
                                  'flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[10px] font-medium border transition-all',
                                  active
                                    ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-200'
                                    : 'border-white/[0.06] bg-white/[0.02] text-white/40 hover:text-white/60',
                                ].join(' ')}
                              >
                                <span>{a.icon}</span>
                                <span>{a.label}</span>
                              </button>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* ═══ Custom Outfit Prompt ═══ */}
              <div>
                <div className="text-[10px] text-white/40 mb-2 font-semibold uppercase tracking-wider">
                  Or Custom Outfit
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
              </div>{/* /max-w-md */}
            </div>
          </div>

          {/* ═══════════ WARDROBE (INVENTORY) — pinned to bottom ═══════════ */}
          <div className="flex-shrink-0 border-t border-white/[0.06] px-5 py-2.5 overflow-hidden flex flex-col" style={{ height: '190px' }}>
            {/* Compact wardrobe header */}
            <div className="flex items-center justify-between mb-2 flex-shrink-0">
              <div className="flex items-center gap-2.5 min-w-0 overflow-hidden">
                <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-amber-500/70 to-orange-500/70 flex items-center justify-center flex-shrink-0">
                  <Shirt size={13} className="text-white" />
                </div>
                <h3 className="text-xs font-semibold text-white whitespace-nowrap">
                  Wardrobe
                  {outfits.length > 0 && (
                    <span className="text-white/25 font-normal ml-1">({outfits.length})</span>
                  )}
                </h3>
                <span className="text-[10px] text-white/30 hidden sm:inline whitespace-nowrap truncate">
                  {outfits.length === 0
                    ? 'Generate outfits to fill your inventory'
                    : 'Click to equip'}
                </span>
              </div>

              {/* Filter button + popover */}
              <div className="relative flex-shrink-0 ml-3">
                <button
                  onClick={() => setWardrobeFilterOpen((v) => !v)}
                  className={[
                    'flex items-center gap-2 px-3.5 py-1.5 rounded-full border text-xs font-medium transition-all cursor-pointer',
                    wardrobeFilter !== 'all'
                      ? 'border-cyan-400/50 bg-cyan-500/20 text-cyan-300 shadow-[0_0_8px_rgba(34,211,238,0.15)]'
                      : 'border-white/20 bg-white/[0.08] text-white/70 hover:text-white hover:border-white/30 hover:bg-white/[0.12]',
                  ].join(' ')}
                >
                  <Filter size={13} />
                  <span>
                    {wardrobeFilter === 'all'
                      ? 'All Outfits'
                      : SCENARIO_TAG_META.find((t) => t.id === wardrobeFilter)?.label ?? 'All Outfits'}
                  </span>
                </button>
                {wardrobeFilterOpen && (
                  <>
                    {/* Backdrop to close */}
                    <div className="fixed inset-0 z-40" onClick={() => setWardrobeFilterOpen(false)} />
                    {/* Popover — opens upward */}
                    <div className="absolute right-0 bottom-full mb-2 z-50 w-48 py-1.5 rounded-xl bg-[#1e1e1e] border border-white/[0.12] shadow-2xl shadow-black/50 overflow-hidden">
                      <button
                        onClick={() => { setWardrobeFilter('all'); setWardrobeFilterOpen(false) }}
                        className={[
                          'w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left text-xs font-medium transition-colors',
                          wardrobeFilter === 'all' ? 'bg-white/[0.1] text-white' : 'text-white/50 hover:bg-white/[0.06] hover:text-white/80',
                        ].join(' ')}
                      >
                        <span className="w-5 text-center text-sm">🎒</span>
                        All Outfits
                      </button>
                      {availableTags.map((t) => (
                        <button
                          key={t.id}
                          onClick={() => { setWardrobeFilter(t.id); setWardrobeFilterOpen(false) }}
                          className={[
                            'w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left text-xs font-medium transition-colors',
                            wardrobeFilter === t.id ? 'bg-cyan-500/20 text-cyan-300' : 'text-white/50 hover:bg-white/[0.06] hover:text-white/80',
                          ].join(' ')}
                        >
                          <span className="w-5 text-center text-sm">{t.icon}</span>
                          {t.label}
                          <span className="ml-auto text-[9px] text-white/25">
                            {outfits.filter((o) => o.scenarioTag === t.id).length}
                          </span>
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Wardrobe strip — RPG inventory, horizontal scroll */}
            <div className="flex gap-2 overflow-x-auto scrollbar-hide flex-1 min-h-0 items-start pb-1">
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
                    isEquipped={equippedItem?.id === o.id}
                    onEquip={handleEquip}
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
                  className="flex-shrink-0 w-24 rounded-xl border-2 border-dashed border-white/[0.06] bg-white/[0.01] flex flex-col items-center justify-center gap-1 group hover:border-cyan-500/20 hover:bg-cyan-500/[0.02] transition-all cursor-default"
                  style={{ aspectRatio: '2/3' }}
                >
                  <Plus size={16} className="text-white/10 group-hover:text-cyan-500/30 transition-colors" />
                  <span className="text-[8px] text-white/10 group-hover:text-cyan-500/25 font-medium transition-colors">
                    Empty Slot
                  </span>
                </div>
              ))}
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
  isEquipped,
  onEquip,
  onOpenLightbox,
  onSendToEdit,
  onDelete,
}: {
  item: GalleryItem
  imageUrl: string
  tagMeta?: ScenarioTagMeta
  isEquipped?: boolean
  onEquip?: (item: GalleryItem) => void
  onOpenLightbox?: (url: string) => void
  onSendToEdit?: (url: string) => void
  onDelete?: (id: string) => void
}) {
  return (
    <div className={[
      'group relative rounded-xl overflow-hidden transition-all flex-shrink-0 w-24',
      isEquipped
        ? 'border-2 border-amber-500/50 ring-2 ring-amber-500/20 shadow-[0_0_12px_rgba(245,158,11,0.15)]'
        : 'border border-white/[0.06] bg-white/[0.02] hover:border-white/15',
    ].join(' ')}>
      <div
        className="bg-white/[0.03] cursor-pointer relative"
        style={{ aspectRatio: '2/3' }}
        onClick={() => onEquip?.(item)}
      >
        <img
          src={imageUrl}
          alt={item.prompt || 'Outfit variation'}
          className="w-full h-full object-cover"
          loading="lazy"
        />

        {/* Equipped indicator */}
        {isEquipped && (
          <div className="absolute top-1.5 right-1.5 px-1.5 py-0.5 rounded-md bg-amber-500/80 text-[7px] text-white font-bold uppercase tracking-wider z-10">
            Equipped
          </div>
        )}

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
            {onOpenLightbox && (
              <button
                onClick={(e) => { e.stopPropagation(); onOpenLightbox(imageUrl) }}
                className="p-1.5 bg-white/10 backdrop-blur-sm rounded-lg text-white/80 hover:bg-white/20 transition-colors"
                title="View full size"
              >
                <Maximize2 size={11} />
              </button>
            )}
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
