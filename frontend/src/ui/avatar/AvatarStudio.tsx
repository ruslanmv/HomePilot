/**
 * AvatarStudio — "Zero-Prompt Wizard" Command Center.
 *
 * Enterprise-grade avatar creation in 2 clicks (Upload → Pick Vibe → Generate).
 * No text prompt required — visual presets handle everything:
 *
 *   1. Upload a face (inline camera icon, auto-switches to "From Reference")
 *   2. Choose a vibe — tabbed: Standard / Spicy (18+, synced to global settings)
 *   3. [+] Add custom text (optional, progressive disclosure)
 *   4. Generate
 *
 * Spicy tab only appears when `homepilot_nsfw_mode === 'true'` in localStorage.
 * Toast notifications for errors. Gallery below with NSFW blur support.
 */

import React, { useState, useCallback, useRef, useEffect } from 'react'
import {
  Loader2,
  User,
  Shuffle,
  Palette,
  AlertTriangle,
  Image as ImageIcon,
  X,
  Camera,
  Sparkles,
  ChevronDown,
  Plus,
  Flame,
  Star,
  EyeOff,
  CheckCircle2,
  Maximize2,
  Zap,
} from 'lucide-react'

import { useAvatarPacks } from './useAvatarPacks'
import { useGenerateAvatars } from './useGenerateAvatars'
import { useAvatarGallery } from './useAvatarGallery'
import { installAvatarPack } from './avatarApi'
import { AvatarLandingPage } from './AvatarLandingPage'
import { AvatarViewer } from './AvatarViewer'
import { OutfitPanel } from './OutfitPanel'
import { AvatarSettingsPanel, loadAvatarSettings, resolveCheckpoint } from './AvatarSettingsPanel'
import type { AvatarMode, AvatarSettings } from './types'
import type { GalleryItem, AvatarVibePreset, CharacterGender, FramingType } from './galleryTypes'
import { AVATAR_VIBE_PRESETS, GENDER_OPTIONS, CHARACTER_STYLE_PRESETS, buildCharacterPrompt, FRAMING_OPTIONS } from './galleryTypes'
import { resolveFileUrl } from '../resolveFileUrl'
import { CharacterWizard } from './wizard'
import { CharacterCreatorStudio } from './creator'
import { loadVibeTab, saveVibeTab } from './vibeTabPersistence'
import type { VibeTab } from './vibeTabPersistence'
import { AvatarGeneratingLoader } from './AvatarGeneratingLoader'
import {
  DEFAULT_AVATAR_PREFS,
  buildGeneticsPromptFragment,
  SKIN_TONE_OPTIONS,
  HAIR_TYPE_OPTIONS,
  HAIR_COLOR_OPTIONS,
  EYE_COLOR_OPTIONS,
  AGE_RANGE_OPTIONS,
  ETHNICITY_OPTIONS,
} from './avatarPrompt'
import type { AvatarPreferences, SkinTone, HairType, HairColor, AgeRange, EthnicityPreset } from './avatarPrompt'

// ── Color swatch maps for the Quick Studio appearance panel ──
const SKIN_SWATCH_COLORS: Record<string, string> = {
  espresso: '#3B1E0A', mocha: '#5C3A1E', umber: '#7A5230',
  sienna: '#A07040', olive: '#B8A060', sand: '#D2B88C',
  ivory: '#F0DCC0', cream: '#FFF0DC',
}
const HAIR_SWATCH_COLORS: Record<string, string> = {
  black: '#1a1a1a', brown: '#5C3317', blonde: '#D4A84B',
  auburn: '#922724', neon_blue: '#00BFFF', fuchsia: '#FF00FF',
}
const EYE_SWATCH_COLORS: Record<string, string> = {
  brown: '#634E34', blue: '#2E86C1', green: '#2E8B57',
  hazel: '#8E7618', amber: '#BF8A30', grey: '#8E9196',
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface AvatarStudioProps {
  backendUrl: string
  apiKey?: string
  globalModelImages?: string
  onSendToEdit?: (imageUrl: string) => void
  onOpenLightbox?: (imageUrl: string) => void
  onSaveAsPersonaAvatar?: (item: GalleryItem, outfitItems: GalleryItem[], batchSiblings?: GalleryItem[]) => void
  onGenerateOutfits?: (item: GalleryItem) => void
}

// ---------------------------------------------------------------------------
// Mode config
// ---------------------------------------------------------------------------

const MODE_OPTIONS: { label: string; value: AvatarMode; icon: React.ReactNode; description: string }[] = [
  { label: 'Design Character', value: 'studio_random',    icon: <Sparkles size={14} />, description: 'Build a character from gender, style, and personality' },
  { label: 'From Reference', value: 'studio_reference', icon: <User size={14} />,    description: 'Upload a photo to generate identity-consistent portraits' },
  { label: 'Face + Style',   value: 'studio_faceswap',  icon: <Palette size={14} />, description: 'Combine your face with a styled body and scene' },
  { label: 'Quick Face',     value: 'studio_quickface', icon: <Zap size={14} />,     description: 'Instant AI face from seed — sub-second on GPU, web fallback' },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function readNsfwMode(): boolean {
  try { return localStorage.getItem('homepilot_nsfw_mode') === 'true' } catch { return false }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AvatarStudio({ backendUrl, apiKey, globalModelImages, onSendToEdit, onOpenLightbox, onSaveAsPersonaAvatar }: AvatarStudioProps) {
  const packs = useAvatarPacks(backendUrl, apiKey)
  const gen = useGenerateAvatars(backendUrl, apiKey)
  const gallery = useAvatarGallery()

  const [viewMode, setViewMode] = useState<'gallery' | 'designer' | 'wizard' | 'viewer' | 'creator'>('gallery')
  const [viewerItem, setViewerItem] = useState<GalleryItem | null>(null)
  const [avatarSettings, setAvatarSettings] = useState<AvatarSettings>(loadAvatarSettings)

  const enabledModes = packs.data?.enabled_modes ?? []
  const [mode, setMode] = useState<AvatarMode>('studio_random')

  // When switching to Quick Face, force headshot framing (StyleGAN2 FFHQ only produces square face crops)
  const setModeWithFramingGuard = useCallback((next: AvatarMode) => {
    setMode(next)
    if (next === 'studio_quickface') setSelectedFraming('headshot')
  }, [])
  const [referenceUrl, setReferenceUrl] = useState('')
  const [referencePreview, setReferencePreview] = useState<string | null>(null)
  const [count, setCount] = useState(1)
  const [showCountMenu, setShowCountMenu] = useState(false)
  const [outfitAnchor, setOutfitAnchor] = useState<GalleryItem | null>(null)
  const [packInstallBusy, setPackInstallBusy] = useState(false)
  const [packInstallError, setPackInstallError] = useState<string | null>(null)

  // Wizard state (vibes — used for reference/faceswap modes)
  // Default to 'headshot' so users always get a portrait (not castles/landscapes)
  const [selectedVibe, setSelectedVibe] = useState<string | null>('headshot')
  const [vibeTab, _setVibeTab] = useState<VibeTab>(loadVibeTab)
  const setVibeTab = useCallback((tab: VibeTab) => { _setVibeTab(tab); saveVibeTab(tab) }, [])
  const [showCustomPrompt, setShowCustomPrompt] = useState(false)
  const [customPrompt, setCustomPrompt] = useState('')
  const nsfwMode = readNsfwMode()

  // Reset spicy tab if NSFW gets disabled
  useEffect(() => {
    if (!nsfwMode && vibeTab === 'spicy') setVibeTab('standard')
  }, [nsfwMode, vibeTab, setVibeTab])

  // Wrap onSaveAsPersonaAvatar to auto-compute outfit items AND batch siblings from the gallery
  const handleSaveAsPersona = useCallback((item: GalleryItem) => {
    if (!onSaveAsPersonaAvatar) return
    const rootId = item.parentId || item.id
    const outfits = gallery.items.filter((g) => g.parentId === rootId && g.id !== item.id)
    // Also collect batch siblings (other results from the same generation)
    const batchSiblings = item.batchId
      ? gallery.items.filter((g) => g.batchId === item.batchId && g.id !== item.id && !g.parentId)
      : []
    onSaveAsPersonaAvatar(item, outfits, batchSiblings)
  }, [gallery.items, onSaveAsPersonaAvatar])

  // Character Builder state (used for studio_random / Design Character mode)
  // Pre-select sensible defaults so clicking Generate immediately works
  const [selectedGender, setSelectedGender] = useState<CharacterGender | null>('female')
  const [selectedStyle, setSelectedStyle] = useState<string | null>('executive')
  const [characterDescription, setCharacterDescription] = useState('')

  // Portrait framing — half_body (default, head-to-waist) vs headshot (close-up)
  const [selectedFraming, setSelectedFraming] = useState<FramingType>('half_body')

  // Quick Face state (used for studio_quickface mode)
  const [quickfaceTruncation, setQuickfaceTruncation] = useState(0.7)
  const [quickfaceSeed, setQuickfaceSeed] = useState<string>('')

  // MMORPG Genetics & Features (additive — enhances character prompt)
  const [showGenetics, setShowGenetics] = useState(false)
  const [geneticsPrefs, setGeneticsPrefs] = useState<AvatarPreferences>(DEFAULT_AVATAR_PREFS)

  // Toast
  const [toast, setToast] = useState<{ message: string; type: 'error' | 'success' | 'info' } | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout>>()

  // Gallery NSFW reveal — auto-show when Spice Mode is enabled globally
  const [showNsfw, setShowNsfw] = useState(nsfwMode)

  // Selection state for the "immersive room" — user picks one result before committing
  const [selectedResultIndex, setSelectedResultIndex] = useState<number | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)

  // Filtered vibes based on active tab (for reference/faceswap modes)
  const vibes = AVATAR_VIBE_PRESETS.filter((v) =>
    vibeTab === 'standard' ? v.category === 'standard' : v.category === 'spicy',
  )

  // Filtered character styles based on active tab (for Design Character mode)
  const charStyles = CHARACTER_STYLE_PRESETS.filter((s) =>
    vibeTab === 'standard' ? s.category === 'standard' : s.category === 'spicy',
  )

  // Auto-fill character description when gender, style, or genetics changes
  useEffect(() => {
    if (mode !== 'studio_random') return
    const style = CHARACTER_STYLE_PRESETS.find((s) => s.id === selectedStyle)
    let baseDesc: string
    if (selectedGender && style) {
      baseDesc = buildCharacterPrompt(selectedGender, style)
    } else if (selectedGender) {
      const word = selectedGender === 'neutral' ? 'An androgynous' : `A ${selectedGender}`
      baseDesc = `Solo portrait of a single ${word} character, front-facing, looking at camera, highly detailed, studio lighting, 8k resolution`
    } else {
      return
    }
    // Append genetics tokens when the genetics panel is open
    if (showGenetics) {
      const geneticsFragment = buildGeneticsPromptFragment(geneticsPrefs)
      setCharacterDescription(`${baseDesc}, ${geneticsFragment}`)
    } else {
      setCharacterDescription(baseDesc)
    }
  }, [mode, selectedGender, selectedStyle, showGenetics, geneticsPrefs])

  // Reset style selection when switching tabs (if selected style doesn't match new tab)
  useEffect(() => {
    if (selectedStyle) {
      const style = CHARACTER_STYLE_PRESETS.find((s) => s.id === selectedStyle)
      if (style && style.category !== vibeTab) setSelectedStyle(null)
    }
  }, [vibeTab, selectedStyle])

  // Resolve the effective prompt based on active mode, with framing suffix
  const framingOption = FRAMING_OPTIONS.find((f) => f.id === selectedFraming) ?? FRAMING_OPTIONS[0]
  // Resolve the active style preset (used for positive anchors + negative hints)
  const activeStylePreset = mode === 'studio_random'
    ? CHARACTER_STYLE_PRESETS.find((s) => s.id === selectedStyle)
    : undefined
  const effectivePrompt = (() => {
    let basePrompt: string
    if (mode === 'studio_random') {
      basePrompt = characterDescription.trim()
    } else {
      const vibePreset = AVATAR_VIBE_PRESETS.find((v) => v.id === selectedVibe)
      const base = vibePreset?.prompt || ''
      const custom = customPrompt.trim()
      if (base && custom) basePrompt = `${base}, ${custom}`
      else if (custom) basePrompt = custom
      else basePrompt = base
    }
    // Append framing keywords as a suffix — the preset prompt is the primary
    // quality driver (executive, cinematic, etc.) and must come first.
    // The output dimensions (512×768 for half-body, 512×512 for headshot)
    // already guide composition; framing tokens are a gentle reinforcement.
    if (basePrompt) {
      // Append style-specific positive anchors (e.g., "business suit visible, formal neckwear")
      const anchors = activeStylePreset?.positiveAnchors
      const withAnchors = anchors ? `${basePrompt}, ${anchors}` : basePrompt
      return `${withAnchors}, ${framingOption.promptPrefix}`
    }
    return framingOption.promptPrefix
  })()

  // Build negative prompt from framing + style hints (max 4 tokens total)
  const negativePrompt = [framingOption.negativeHints, activeStylePreset?.negativeHints].filter(Boolean).join(', ')

  // Determine if current generation is spicy/NSFW content
  const isSpicyContent = (() => {
    if (mode === 'studio_random') {
      return activeStylePreset?.category === 'spicy'
    }
    const selectedVibeData = AVATAR_VIBE_PRESETS.find((v) => v.id === selectedVibe)
    return selectedVibeData?.category === 'spicy'
  })()

  // Tag for gallery storage
  const vibeTagForGallery = mode === 'studio_random' ? selectedStyle : selectedVibe

  // ---- Toast helper ----
  const showToast = useCallback((message: string, type: 'error' | 'success' | 'info' = 'error') => {
    setToast({ message, type })
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 5000)
  }, [])

  // ---- Reference image upload ----
  const handleFileUpload = useCallback(
    async (file: File) => {
      const preview = URL.createObjectURL(file)
      setReferencePreview(preview)
      if (mode === 'studio_random') setMode('studio_reference')

      const formData = new FormData()
      formData.append('file', file)
      const base = (backendUrl || '').replace(/\/+$/, '')
      const headers: Record<string, string> = {}
      if (apiKey) headers['x-api-key'] = apiKey

      try {
        const res = await fetch(`${base}/upload`, { method: 'POST', headers, body: formData })
        if (res.ok) {
          const data = await res.json()
          setReferenceUrl(data.url || data.file_url || '')
        }
      } catch { /* fallback to preview */ }
    },
    [backendUrl, apiKey, mode],
  )

  const handleRemoveReference = useCallback(() => {
    setReferencePreview(null)
    setReferenceUrl('')
    if (mode === 'studio_reference') setMode('studio_random')
  }, [mode])

  // ---- Generate ----
  const onGenerate = useCallback(async () => {
    const checkpoint = resolveCheckpoint(avatarSettings, globalModelImages)
    // studio_random routes to the avatar-service (StyleGAN) via the backend.
    // If StyleGAN is unavailable, the backend returns a 503 which we handle below.
    // For ComfyUI modes, provide a fallback prompt for users who skip the text field.
    const fallbackPrompt = `Solo portrait photograph of a single real female person, front-facing, looking directly at camera, RAW photo, photorealistic, ultra realistic skin texture, pores visible, fine facial detail, DSLR, 85mm lens, f/1.8, professional studio lighting, 8k uhd, ${framingOption.promptPrefix}`
    const resolvedPrompt = effectivePrompt || (mode === 'studio_random' ? fallbackPrompt : '')
    // Use SD 1.5 dimensions from the framing option (backend workflows are SD 1.5 by default)
    // Headshot uses portrait 2:3 by default; only uses 1:1 square when explicitly enabled in settings.
    const framingDims = (selectedFraming === 'headshot' && avatarSettings.headshot1to1)
      ? { width: 512, height: 512 }
      : framingOption.sd15
    try {
      // Quick Face mode uses a minimal payload (seed + truncation only)
      const requestPayload = mode === 'studio_quickface'
        ? {
            mode: 'studio_quickface' as const,
            count,
            seed: quickfaceSeed ? parseInt(quickfaceSeed, 10) : undefined,
            truncation: quickfaceTruncation,
          }
        : {
            mode,
            count,
            prompt: resolvedPrompt || undefined,
            reference_image_url:
              mode === 'studio_reference' || mode === 'studio_faceswap'
                ? referenceUrl || undefined
                : undefined,
            truncation: 0.7,
            checkpoint_override: checkpoint,
            width: framingDims.width,
            height: framingDims.height,
            negative_prompt: negativePrompt || undefined,
          }
      const result = await gen.run(requestPayload)
      if (result?.results?.length) {
        // Always show the selection UI — user must click "Create Avatar" to commit.
        // No auto-commit, even for single results.
        setSelectedResultIndex(null)
        if (result.results.length === 1) {
          showToast('Avatar generated — click to select, then Create Avatar', 'success')
        } else {
          showToast(`${result.results.length} avatars generated — pick your favourite`, 'success')
        }
      }
    } catch {
      showToast('Oops, the servers are a bit busy. Click Generate to try again.', 'error')
    }
  }, [gen, mode, count, effectivePrompt, referenceUrl, gallery, avatarSettings, globalModelImages, showToast, vibeTagForGallery, isSpicyContent, framingOption])

  // ---- Keyboard shortcut ----
  const needsReference = mode === 'studio_reference'
  const canGenerate = !gen.loading && (needsReference ? !!referenceUrl : true)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canGenerate) {
        e.preventDefault()
        onGenerate()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onGenerate, canGenerate])

  // ==========================================================================
  // RENDER - Gallery View (Landing)
  // ==========================================================================
  if (viewMode === 'gallery') {
    return (
      <>
        <AvatarLandingPage
          items={gallery.items}
          backendUrl={backendUrl}
          onNewAvatar={() => setViewMode('designer')}
          onOpenCreator={() => setViewMode('creator')}
          onOpenItem={(item) => { setViewerItem(item); setViewMode('viewer') }}
          onDeleteItem={gallery.removeItem}
          onOpenLightbox={onOpenLightbox}
          onSendToEdit={onSendToEdit}
          onSaveAsPersonaAvatar={handleSaveAsPersona}
          onGenerateOutfits={(item) => { setViewerItem(item); setViewMode('viewer') }}
        />
        {outfitAnchor && (
          <OutfitPanel
            anchor={outfitAnchor} backendUrl={backendUrl} apiKey={apiKey}
            nsfwMode={nsfwMode}
            checkpointOverride={resolveCheckpoint(avatarSettings, globalModelImages)}
            onResults={(results, scenarioTag) => {
              const rootId = outfitAnchor.parentId || outfitAnchor.id
              gallery.addBatch(results, mode, outfitAnchor.prompt, outfitAnchor.url, scenarioTag, { parentId: rootId })
            }}
            onSendToEdit={onSendToEdit} onOpenLightbox={onOpenLightbox}
            onClose={() => setOutfitAnchor(null)}
          />
        )}
      </>
    )
  }

  // ==========================================================================
  // RENDER — Character Wizard (new 7-step professional wizard)
  // ==========================================================================
  if (viewMode === 'wizard') {
    return (
      <CharacterWizard
        backendUrl={backendUrl}
        apiKey={apiKey}
        globalModelImages={globalModelImages}
        nsfwEnabled={readNsfwMode()}
        onClose={() => setViewMode('gallery')}
        onSaveGeneration={(anchor, portraits, genMode, prompt, refUrl, nsfw, wizardMeta) => {
          gallery.addAnchorWithPortraits(anchor, portraits, genMode, prompt, refUrl, { nsfw: nsfw || undefined, wizardMeta })
        }}
      />
    )
  }

  // ==========================================================================
  // RENDER — MMORPG Character Creator Studio
  // ==========================================================================
  if (viewMode === 'creator') {
    return (
      <CharacterCreatorStudio
        backendUrl={backendUrl}
        apiKey={apiKey}
        globalModelImages={globalModelImages}
        enabledModes={enabledModes}
        gallery={gallery}
        onClose={() => setViewMode('gallery')}
        onOpenLightbox={onOpenLightbox}
        onSendToEdit={onSendToEdit}
        onSaveAsPersonaAvatar={onSaveAsPersonaAvatar}
        onOpenViewer={(item) => { setViewerItem(item); setViewMode('viewer') }}
      />
    )
  }

  // ==========================================================================
  // RENDER — Viewer (Character Sheet)
  // ==========================================================================
  if (viewMode === 'viewer' && viewerItem) {
    return (
      <AvatarViewer
        item={viewerItem} allItems={gallery.items} backendUrl={backendUrl}
        apiKey={apiKey} globalModelImages={globalModelImages}
        onBack={() => { setViewerItem(null); setViewMode('gallery') }}
        onOpenLightbox={onOpenLightbox} onSendToEdit={onSendToEdit}
        onSaveAsPersonaAvatar={handleSaveAsPersona}
        onDeleteItem={(id) => {
          gallery.removeItem(id)
          if (id === viewerItem.id) { setViewerItem(null); setViewMode('gallery') }
        }}
        onSwapAnchor={(anchorId, portraitId) => {
          // Grab portrait data before swap (setItems is async)
          const portrait = gallery.items.find((i) => i.id === portraitId)
          gallery.swapAnchor(anchorId, portraitId)
          // Update viewer to show the new anchor (portrait promoted)
          if (portrait) setViewerItem({ ...portrait, role: 'anchor', parentId: undefined })
        }}
        onOutfitResults={(results, anchor) => {
          const rootId = anchor.parentId || anchor.id
          gallery.addBatch(results, anchor.mode, anchor.prompt, anchor.url, anchor.scenarioTag, { parentId: rootId })
        }}
        onUpdateItem={gallery.updateItem}
      />
    )
  }

  // ==========================================================================
  // RENDER - Designer View — "Zero-Prompt Wizard"
  // ==========================================================================
  return (
    <div className="flex-1 flex flex-col min-h-0 bg-black text-white">

      {/* ═══════════ TOP BANNER ═══════════ */}
      <div className="px-6 pt-5 pb-4 border-b border-white/[0.06] flex-shrink-0">
        <div className="flex items-center justify-between max-w-5xl mx-auto">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setViewMode('gallery')}
              className="flex items-center gap-2 text-white/40 hover:text-white/70 transition-colors text-sm"
              title="Back to Gallery"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6"/></svg>
            </button>
            <div className="flex items-center gap-2.5">
              <Sparkles size={18} className="text-purple-400" />
              <h1 className="text-base font-semibold tracking-tight">Avatar Studio</h1>
            </div>
          </div>
          <AvatarSettingsPanel
            globalModelImages={globalModelImages}
            settings={avatarSettings}
            onChange={setAvatarSettings}
            styleganStatus={packs.data?.stylegan_status ?? null}
            openposeAvailable={packs.data?.openpose_available}
          />
        </div>
      </div>

      {/* ═══════════ MAIN CONTENT ═══════════ */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="max-w-3xl mx-auto px-6 py-8">

          {/* Pack install banner */}
          {packs.data && enabledModes.length === 0 && !packs.loading && (
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-4 flex items-center justify-between gap-4 mb-8">
              <div className="flex items-center gap-3 min-w-0">
                <AlertTriangle size={16} className="text-amber-400 flex-shrink-0" />
                <div>
                  <span className="text-sm text-amber-200 font-medium">No avatar packs installed</span>
                  <p className="text-xs text-amber-400/60 mt-0.5">Install the Basic Pack to unlock identity-consistent avatars</p>
                  {packInstallError && <div className="text-[10px] text-red-300 mt-1">{packInstallError}</div>}
                </div>
              </div>
              <button
                className="px-4 py-2 rounded-lg bg-amber-400/20 hover:bg-amber-400/30 text-amber-100 text-sm font-semibold whitespace-nowrap transition-colors disabled:opacity-50"
                disabled={packInstallBusy}
                onClick={async () => {
                  try { setPackInstallError(null); setPackInstallBusy(true); await installAvatarPack(backendUrl, 'avatar-basic', apiKey); await packs.refresh() }
                  catch (e: any) { setPackInstallError(e?.message ?? String(e)) }
                  finally { setPackInstallBusy(false) }
                }}
              >
                {packInstallBusy ? 'Installing...' : 'Install Basic Pack'}
              </button>
            </div>
          )}

          {/* Title */}
          <div className="text-center mb-6">
            <h2 className="text-xl font-bold tracking-tight text-white/90">Create Your Avatar</h2>
          </div>

          {/* Mode pills */}
          <div className="flex items-center justify-center gap-2 mb-8" role="radiogroup" aria-label="Avatar generation mode">
            {MODE_OPTIONS.map((o) => {
              const enabled = enabledModes.includes(o.value)
              const active = mode === o.value
              return (
                <button key={o.value} disabled={!enabled} onClick={() => setModeWithFramingGuard(o.value)} title={o.description}
                  role="radio" aria-checked={active}
                  className={[
                    'flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all',
                    active ? 'bg-white/10 text-white border border-white/20 shadow-[0_0_12px_rgba(255,255,255,0.05)]'
                      : enabled ? 'text-white/40 hover:text-white/60 hover:bg-white/[0.04] border border-transparent'
                        : 'text-white/15 cursor-not-allowed border border-transparent',
                  ].join(' ')}
                >
                  {o.icon}
                  {o.label}
                </button>
              )
            })}
          </div>

          {/* StyleGAN engine info (additive — shown only in studio_random mode) */}
          {mode === 'studio_random' && enabledModes.includes('studio_random') && (
            <div className="text-[10px] text-white/25 text-center -mt-4 mb-4 flex items-center justify-center gap-1.5">
              <Sparkles size={10} className="text-purple-400/50" />
              <span>StyleGAN face generation — fast portraits with seed control</span>
            </div>
          )}

          {mode === 'studio_random' ? (
            /* ═══════════ CHARACTER BUILDER (Design Character mode) ═══════════ */
            <>
              {/* Step 1: Core Identity — Gender */}
              <div className="mb-6">
                <div className="text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider">
                  1. Core Identity
                </div>
                <div className="flex items-center gap-2 p-1.5 rounded-2xl bg-white/[0.03] border border-white/[0.06]">
                  {GENDER_OPTIONS.map((g) => {
                    const active = selectedGender === g.id
                    return (
                      <button
                        key={g.id}
                        onClick={() => setSelectedGender(g.id)}
                        className={[
                          'flex-1 flex items-center justify-center gap-2.5 px-4 py-3 rounded-xl text-sm font-medium transition-all',
                          active
                            ? 'bg-white/10 text-white border border-white/15 shadow-sm'
                            : 'text-white/40 hover:text-white/60 hover:bg-white/[0.04] border border-transparent',
                        ].join(' ')}
                      >
                        <span className="text-lg">{g.icon}</span>
                        <span>{g.label}</span>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Step 2: Appearance (collapsible — color swatches for quick selection) */}
              <div className="mb-6">
                <button
                  onClick={() => setShowGenetics(!showGenetics)}
                  className="flex items-center gap-2 text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider hover:text-white/60 transition-colors"
                >
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className={`transition-transform ${showGenetics ? 'rotate-90' : ''}`}><path d="m9 18 6-6-6-6"/></svg>
                  2. Appearance
                  <span className="text-white/15 normal-case tracking-normal font-normal">(quick customise)</span>
                </button>

                {showGenetics && (
                  <div className="space-y-4 animate-fadeSlideIn">
                    {/* Skin Tone — color swatches */}
                    <div>
                      <div className="text-[10px] text-white/30 mb-2 font-medium">Skin Tone</div>
                      <div className="flex flex-wrap gap-2">
                        {SKIN_TONE_OPTIONS.map((o) => {
                          const active = geneticsPrefs.skinTone === o.key
                          return (
                            <button key={o.key} title={o.label}
                              onClick={() => setGeneticsPrefs((p) => ({ ...p, skinTone: o.key as SkinTone }))}
                              className={[
                                'w-8 h-8 rounded-full border-2 transition-all flex-shrink-0',
                                active
                                  ? 'border-purple-400 scale-110 shadow-[0_0_10px_rgba(168,85,247,0.4)]'
                                  : 'border-white/10 hover:border-white/30 hover:scale-105',
                              ].join(' ')}
                              style={{ backgroundColor: SKIN_SWATCH_COLORS[o.key] || '#888' }}
                            />
                          )
                        })}
                      </div>
                    </div>

                    {/* Hair Color + Type row */}
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <div className="text-[10px] text-white/30 mb-2 font-medium">Hair Color</div>
                        <div className="flex flex-wrap gap-2">
                          {HAIR_COLOR_OPTIONS.map((o) => {
                            const active = geneticsPrefs.hairColor === o.key
                            return (
                              <button key={o.key} title={o.label}
                                onClick={() => setGeneticsPrefs((p) => ({ ...p, hairColor: o.key as HairColor }))}
                                className={[
                                  'w-8 h-8 rounded-full border-2 transition-all flex-shrink-0',
                                  active
                                    ? 'border-purple-400 scale-110 shadow-[0_0_10px_rgba(168,85,247,0.4)]'
                                    : 'border-white/10 hover:border-white/30 hover:scale-105',
                                ].join(' ')}
                                style={{ backgroundColor: HAIR_SWATCH_COLORS[o.key] || '#888' }}
                              />
                            )
                          })}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-white/30 mb-2 font-medium">Hair Type</div>
                        <div className="flex flex-wrap gap-1.5">
                          {HAIR_TYPE_OPTIONS.map((o) => (
                            <button key={o.key} onClick={() => setGeneticsPrefs((p) => ({ ...p, hairType: o.key as HairType }))}
                              className={`flex-1 px-2 py-2 rounded-xl text-[11px] font-medium border transition-colors ${geneticsPrefs.hairType === o.key ? 'bg-purple-500/10 border-purple-500/25 text-purple-200' : 'bg-white/[0.02] border-white/[0.06] text-white/40 hover:bg-white/[0.04]'}`}
                            >{o.label}</button>
                          ))}
                        </div>
                      </div>
                    </div>

                    {/* Eye Color — color swatches */}
                    <div>
                      <div className="text-[10px] text-white/30 mb-2 font-medium">Eye Color</div>
                      <div className="flex flex-wrap gap-2">
                        {EYE_COLOR_OPTIONS.map((o) => {
                          const active = geneticsPrefs.eyeColor === o.key
                          return (
                            <button key={o.key} title={o.label}
                              onClick={() => setGeneticsPrefs((p) => ({ ...p, eyeColor: o.key }))}
                              className={[
                                'w-8 h-8 rounded-full border-2 transition-all flex-shrink-0',
                                active
                                  ? 'border-purple-400 scale-110 shadow-[0_0_10px_rgba(168,85,247,0.4)]'
                                  : 'border-white/10 hover:border-white/30 hover:scale-105',
                              ].join(' ')}
                              style={{ backgroundColor: EYE_SWATCH_COLORS[o.key] || '#888' }}
                            />
                          )
                        })}
                      </div>
                    </div>

                    {/* Age Range — compact row */}
                    <div>
                      <div className="text-[10px] text-white/30 mb-1.5 font-medium">Age Range</div>
                      <div className="flex gap-1.5">
                        {AGE_RANGE_OPTIONS.map((o) => (
                          <button key={o.key} onClick={() => setGeneticsPrefs((p) => ({ ...p, ageRange: o.key as AgeRange }))}
                            className={`flex-1 px-2 py-2 rounded-xl text-[11px] font-medium border transition-colors ${geneticsPrefs.ageRange === o.key ? 'bg-purple-500/10 border-purple-500/25 text-purple-200' : 'bg-white/[0.02] border-white/[0.06] text-white/40 hover:bg-white/[0.04]'}`}
                          >{o.label}</button>
                        ))}
                      </div>
                    </div>

                    {/* Ethnicity — dropdown selector */}
                    <div>
                      <div className="text-[10px] text-white/30 mb-1.5 font-medium">Ethnicity</div>
                      <select
                        value={geneticsPrefs.baseEthnicityPreset === 'custom' ? (geneticsPrefs.customEthnicityHint || '__custom__') : geneticsPrefs.baseEthnicityPreset}
                        onChange={(e) => {
                          const val = e.target.value
                          if (val === 'european_standard' || val === 'global_mixed') {
                            setGeneticsPrefs((p) => ({ ...p, baseEthnicityPreset: val as EthnicityPreset, customEthnicityHint: '' }))
                          } else if (val === '__custom__') {
                            setGeneticsPrefs((p) => ({ ...p, baseEthnicityPreset: 'custom', customEthnicityHint: '' }))
                          } else {
                            // Specific ethnicity picked — store as custom with the value
                            setGeneticsPrefs((p) => ({ ...p, baseEthnicityPreset: 'custom', customEthnicityHint: val }))
                          }
                        }}
                        className="w-full px-3 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-[11px] text-white/70 focus:outline-none focus:border-purple-500/40 appearance-none cursor-pointer"
                        style={{ colorScheme: 'dark', backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='rgba(255,255,255,0.3)' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E")`, backgroundRepeat: 'no-repeat', backgroundPosition: 'right 10px center' }}
                      >
                        <option value="european_standard" className="bg-[#1a1a2e] text-white">European Standard</option>
                        <option value="global_mixed" className="bg-[#1a1a2e] text-white">Global Mixed</option>
                        <option disabled className="bg-[#1a1a2e] text-white/40">───────────</option>
                        {['Mediterranean', 'Nordic', 'South Asian', 'Southeast Asian', 'Middle Eastern', 'East Asian', 'Indigenous American', 'Pacific Islander', 'Sub-Saharan African', 'Caribbean', 'Slavic', 'Celtic', 'Iberian', 'Polynesian', 'Andean', 'Amazigh'].map((s) => (
                          <option key={s} value={s} className="bg-[#1a1a2e] text-white">{s}</option>
                        ))}
                        <option disabled className="bg-[#1a1a2e] text-white/40">───────────</option>
                        <option value="__custom__" className="bg-[#1a1a2e] text-white">Custom...</option>
                      </select>
                      {geneticsPrefs.baseEthnicityPreset === 'custom' && !['Mediterranean', 'Nordic', 'South Asian', 'Southeast Asian', 'Middle Eastern', 'East Asian', 'Indigenous American', 'Pacific Islander', 'Sub-Saharan African', 'Caribbean', 'Slavic', 'Celtic', 'Iberian', 'Polynesian', 'Andean', 'Amazigh'].includes(geneticsPrefs.customEthnicityHint || '') && (
                        <input
                          value={geneticsPrefs.customEthnicityHint || ''}
                          onChange={(e) => setGeneticsPrefs((p) => ({ ...p, customEthnicityHint: e.target.value }))}
                          className="mt-2 w-full px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.08] text-xs text-white/70 placeholder:text-white/20 focus:outline-none focus:border-purple-500/40"
                          placeholder="e.g., Afro-Caribbean, Eurasian..."
                          autoFocus
                        />
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* Step 3: Style & Role Preset */}
              <div className="mb-6">
                <div className="text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider">
                  3. Style &amp; Role Preset
                </div>

                {/* Tabs: Standard / Spicy */}
                <div className="flex items-center gap-1 mb-3 p-1 rounded-xl bg-white/[0.03] border border-white/[0.06] w-fit">
                  <button
                    onClick={() => setVibeTab('standard')}
                    className={[
                      'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                      vibeTab === 'standard'
                        ? 'bg-white/10 text-white shadow-sm'
                        : 'text-white/40 hover:text-white/60',
                    ].join(' ')}
                  >
                    <Star size={12} />
                    Standard
                  </button>
                  {nsfwMode && (
                    <button
                      onClick={() => setVibeTab('spicy')}
                      className={[
                        'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                        vibeTab === 'spicy'
                          ? 'bg-gradient-to-r from-rose-500/20 to-orange-500/20 text-rose-300 border border-rose-500/20 shadow-sm'
                          : 'text-white/40 hover:text-rose-300/60',
                      ].join(' ')}
                    >
                      <Flame size={12} />
                      Romance &amp; Roleplay
                      <span className="text-[8px] px-1 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold">18+</span>
                    </button>
                  )}
                </div>

                {/* Style badge grid */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {charStyles.map((s) => {
                    const active = selectedStyle === s.id
                    return (
                      <button
                        key={s.id}
                        onClick={() => setSelectedStyle(active ? null : s.id)}
                        className={[
                          'flex items-center gap-2.5 px-3.5 py-3 rounded-xl text-left transition-all border',
                          active
                            ? vibeTab === 'spicy'
                              ? 'border-rose-500/30 bg-rose-500/10 text-rose-200 shadow-[0_0_10px_rgba(244,63,94,0.08)]'
                              : 'border-purple-500/30 bg-purple-500/10 text-purple-200 shadow-[0_0_10px_rgba(168,85,247,0.08)]'
                            : 'border-white/[0.06] bg-white/[0.02] text-white/50 hover:bg-white/[0.04] hover:border-white/10 hover:text-white/70',
                        ].join(' ')}
                      >
                        <span className="text-base leading-none">{s.icon}</span>
                        <span className="text-xs font-medium">{s.label}</span>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Step 4: Character Description (Identity Anchor) — hidden by default, toggle in Settings */}
              {avatarSettings.showCharacterDescription && (
                <div className="mb-6">
                  <div className="text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider">
                    5. Character Description
                    <span className="text-white/20 normal-case tracking-normal font-normal ml-1.5">(Your Identity Anchor)</span>
                  </div>
                  <div className={[
                    'rounded-2xl border transition-all',
                    'bg-white/[0.04] focus-within:bg-white/[0.06]',
                    characterDescription
                      ? 'border-purple-500/20 focus-within:border-purple-500/40 focus-within:ring-1 focus-within:ring-purple-500/20'
                      : 'border-white/10 focus-within:border-purple-500/40 focus-within:ring-1 focus-within:ring-purple-500/20',
                  ].join(' ')}>
                    <textarea
                      value={characterDescription}
                      onChange={(e) => setCharacterDescription(e.target.value)}
                      onKeyDown={(e) => {
                        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canGenerate) { e.preventDefault(); onGenerate() }
                      }}
                      placeholder="Select a gender and style above to auto-generate your character description, or type your own..."
                      className="w-full bg-transparent text-white text-sm p-4 resize-none placeholder:text-white/20 focus:outline-none leading-relaxed"
                      rows={3}
                    />
                  </div>
                  <p className="text-[10px] text-white/20 mt-1.5 italic">
                    Auto-filled based on your choices. Edit to lock in exact details!
                  </p>
                </div>
              )}
            </>
          ) : mode === 'studio_quickface' ? (
            /* ═══════════ QUICK FACE PANEL (studio_quickface mode) ═══════════ */
            <>
              {/* Engine info banner */}
              <div className="text-[10px] text-white/25 text-center -mt-4 mb-5 flex items-center justify-center gap-1.5">
                <Zap size={10} className="text-yellow-400/60" />
                <span>Instant photorealistic faces via StyleGAN2 FFHQ — seed-reproducible</span>
              </div>

              {/* Step 1: Diversity (truncation) */}
              <div className="mb-6">
                <div className="text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider">
                  1. Diversity
                </div>
                <div className="flex items-center gap-2 p-1.5 rounded-2xl bg-white/[0.03] border border-white/[0.06]">
                  {([
                    { value: 0.4, label: 'Conservative', icon: '🎯', sub: 'More average, conventionally attractive' },
                    { value: 0.7, label: 'Balanced', icon: '⚖️', sub: 'Default — good variety' },
                    { value: 1.0, label: 'Creative', icon: '🎲', sub: 'More unique, unusual features' },
                  ] as const).map((opt) => {
                    const active = quickfaceTruncation === opt.value
                    return (
                      <button
                        key={opt.value}
                        onClick={() => setQuickfaceTruncation(opt.value)}
                        className={[
                          'flex-1 flex flex-col items-center gap-1 px-3 py-3 rounded-xl text-sm font-medium transition-all',
                          active
                            ? 'bg-white/10 text-white border border-white/15 shadow-sm'
                            : 'text-white/40 hover:text-white/60 hover:bg-white/[0.04] border border-transparent',
                        ].join(' ')}
                      >
                        <span className="text-lg">{opt.icon}</span>
                        <span className="text-[12px]">{opt.label}</span>
                        <span className="text-[9px] text-white/25">{opt.sub}</span>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Step 2: Seed */}
              <div className="mb-6">
                <div className="text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider">
                  2. Seed (Optional)
                </div>
                <div className="flex items-center gap-2">
                  <div className="flex-1 rounded-2xl border border-white/[0.06] bg-white/[0.03] overflow-hidden">
                    <input
                      type="number"
                      value={quickfaceSeed}
                      onChange={(e) => setQuickfaceSeed(e.target.value)}
                      onKeyDown={(e) => {
                        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canGenerate) { e.preventDefault(); onGenerate() }
                      }}
                      placeholder="Leave empty for random"
                      className="w-full bg-transparent text-white text-sm px-4 py-3 placeholder:text-white/20 focus:outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
                    />
                  </div>
                  <button
                    onClick={() => setQuickfaceSeed(String(Math.floor(Math.random() * 2147483647)))}
                    className="h-[44px] w-[44px] rounded-xl border border-white/[0.06] bg-white/[0.03] grid place-items-center text-white/40 hover:text-white/70 hover:bg-white/[0.06] transition-all"
                    title="Random seed"
                  >
                    <Shuffle size={16} />
                  </button>
                </div>
                <p className="text-[10px] text-white/20 mt-1.5">
                  Same seed always produces the same face — great for reproducing a face you like
                </p>
              </div>

              {/* Source indicator */}
              <div className="mb-2 flex items-center gap-2 px-1">
                <div className="h-1.5 w-1.5 rounded-full bg-emerald-400/70" />
                <span className="text-[10px] text-white/25">
                  Source: StyleGAN2 FFHQ 1024 — local GPU or web fallback
                </span>
              </div>
            </>
          ) : (
            /* ═══════════ UPLOAD + VIBES (Reference / Face+Style modes) ═══════════ */
            <>
              {/* Step 1: Upload a face */}
              <div className="mb-6">
                <div className="text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider">
                  1. Upload a face
                </div>
                <div className={[
                  'flex items-center gap-3 px-4 py-3 rounded-2xl border transition-all',
                  'bg-white/[0.04] border-white/10',
                  referencePreview ? 'border-purple-500/30' : 'hover:border-white/15',
                ].join(' ')}>
                  {referencePreview ? (
                    <div className="relative flex-shrink-0">
                      <div className="w-10 h-10 rounded-full overflow-hidden border-2 border-purple-500/40">
                        <img src={resolveFileUrl(referencePreview, backendUrl)} alt="Reference" className="w-full h-full object-cover" />
                      </div>
                      <button
                        onClick={handleRemoveReference}
                        className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-red-500/80 flex items-center justify-center text-white hover:bg-red-500 transition-colors"
                        aria-label="Remove reference"
                      >
                        <X size={8} />
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={() => fileInputRef.current?.click()}
                      className="flex-shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-white/20 hover:text-white/50 hover:bg-white/5 transition-all border border-dashed border-white/10"
                      title="Upload a reference photo"
                    >
                      <Camera size={18} />
                    </button>
                  )}
                  <input ref={fileInputRef} type="file" accept="image/*" className="hidden"
                    onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileUpload(f); e.target.value = '' }}
                  />
                  <div className="flex-1 min-w-0">
                    {referencePreview ? (
                      <span className="text-sm text-white/60">Reference photo attached</span>
                    ) : (
                      <button
                        onClick={() => fileInputRef.current?.click()}
                        className="text-sm text-white/25 hover:text-white/40 transition-colors cursor-pointer text-left"
                      >
                        Click to upload a reference photo
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {/* Step 2: Choose a vibe */}
              <div className="mb-6">
                <div className="text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider">
                  2. Choose a vibe
                </div>

                {/* Tabs: Standard / Spicy */}
                <div className="flex items-center gap-1 mb-3 p-1 rounded-xl bg-white/[0.03] border border-white/[0.06] w-fit">
                  <button
                    onClick={() => setVibeTab('standard')}
                    className={[
                      'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                      vibeTab === 'standard'
                        ? 'bg-white/10 text-white shadow-sm'
                        : 'text-white/40 hover:text-white/60',
                    ].join(' ')}
                  >
                    <Star size={12} />
                    Standard
                  </button>
                  {nsfwMode && (
                    <button
                      onClick={() => setVibeTab('spicy')}
                      className={[
                        'flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all',
                        vibeTab === 'spicy'
                          ? 'bg-gradient-to-r from-rose-500/20 to-orange-500/20 text-rose-300 border border-rose-500/20 shadow-sm'
                          : 'text-white/40 hover:text-rose-300/60',
                      ].join(' ')}
                    >
                      <Flame size={12} />
                      Romance &amp; Roleplay
                      <span className="text-[8px] px-1 py-0.5 rounded bg-rose-500/20 text-rose-300 font-bold">18+</span>
                    </button>
                  )}
                </div>

                {/* Vibe badge grid */}
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {vibes.map((v) => {
                    const active = selectedVibe === v.id
                    return (
                      <button
                        key={v.id}
                        onClick={() => setSelectedVibe(active ? null : v.id)}
                        className={[
                          'flex items-center gap-2.5 px-3.5 py-3 rounded-xl text-left transition-all border',
                          active
                            ? vibeTab === 'spicy'
                              ? 'border-rose-500/30 bg-rose-500/10 text-rose-200 shadow-[0_0_10px_rgba(244,63,94,0.08)]'
                              : 'border-purple-500/30 bg-purple-500/10 text-purple-200 shadow-[0_0_10px_rgba(168,85,247,0.08)]'
                            : 'border-white/[0.06] bg-white/[0.02] text-white/50 hover:bg-white/[0.04] hover:border-white/10 hover:text-white/70',
                        ].join(' ')}
                      >
                        <span className="text-base leading-none">{v.icon}</span>
                        <span className="text-xs font-medium">{v.label}</span>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Optional custom prompt (progressive disclosure) */}
              <div className="mb-6">
                {!showCustomPrompt ? (
                  <button
                    onClick={() => setShowCustomPrompt(true)}
                    className="flex items-center gap-2 text-white/25 hover:text-white/50 text-xs font-medium transition-colors"
                  >
                    <Plus size={14} />
                    Add custom text prompt (Optional)
                  </button>
                ) : (
                  <div className="animate-fadeSlideIn">
                    <div className="flex items-center justify-between mb-2">
                      <div className="text-[10px] text-white/40 font-semibold uppercase tracking-wider">
                        Custom prompt (optional)
                      </div>
                      <button
                        onClick={() => { setShowCustomPrompt(false); setCustomPrompt('') }}
                        className="text-white/25 hover:text-white/50 transition-colors"
                      >
                        <X size={12} />
                      </button>
                    </div>
                    <div className={[
                      'flex items-center gap-2 px-4 py-3 rounded-2xl border transition-all',
                      'bg-white/[0.04] focus-within:bg-white/[0.06]',
                      'border-white/10 focus-within:border-purple-500/40 focus-within:ring-1 focus-within:ring-purple-500/20',
                    ].join(' ')}>
                      <input
                        value={customPrompt}
                        onChange={(e) => setCustomPrompt(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' && canGenerate) { e.preventDefault(); onGenerate() }
                        }}
                        placeholder='Add details: "wearing a red scarf, outdoor setting"...'
                        className="flex-1 bg-transparent text-white text-sm placeholder:text-white/20 focus:outline-none"
                      />
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          {/* ═══ Portrait Framing Toggle ═══ */}
          {mode === 'studio_quickface' ? (
            /* Quick Face: StyleGAN2 FFHQ only produces square face crops — lock to Headshot */
            <div className="mb-6">
              <div className="text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider">
                3. Photo Style
              </div>
              <div className="flex items-center gap-2 p-1.5 rounded-2xl bg-white/[0.03] border border-white/[0.06]">
                <div className="flex-1 flex items-center justify-center gap-2.5 px-4 py-3 rounded-xl bg-white/10 text-white border border-white/15 shadow-sm text-sm font-medium">
                  <span className="text-lg">🙂</span>
                  <div className="flex flex-col items-start">
                    <span className="text-xs">Headshot</span>
                    <span className="text-[9px] text-white/25 font-normal">Close-up — head &amp; shoulders, cinematic portrait</span>
                  </div>
                </div>
              </div>
              <p className="text-[10px] text-white/20 mt-1.5">
                StyleGAN2 FFHQ produces square face crops only — headshot is the native output
              </p>
            </div>
          ) : (
            <div className="mb-6">
              <div className="text-[10px] text-white/40 mb-2.5 font-semibold uppercase tracking-wider">
                {mode === 'studio_random' ? '4' : '3'}. Photo Style
              </div>
              <div className="flex items-center gap-2 p-1.5 rounded-2xl bg-white/[0.03] border border-white/[0.06]">
                {FRAMING_OPTIONS.map((f) => {
                  const active = selectedFraming === f.id
                  return (
                    <button
                      key={f.id}
                      onClick={() => setSelectedFraming(f.id)}
                      className={[
                        'flex-1 flex items-center justify-center gap-2.5 px-4 py-3 rounded-xl text-sm font-medium transition-all',
                        active
                          ? 'bg-white/10 text-white border border-white/15 shadow-sm'
                          : 'text-white/40 hover:text-white/60 hover:bg-white/[0.04] border border-transparent',
                      ].join(' ')}
                      title={f.description}
                    >
                      <span className="text-lg">{f.icon}</span>
                      <div className="flex flex-col items-start">
                        <span className="text-xs">{f.label}</span>
                        <span className="text-[9px] text-white/25 font-normal">{f.description}</span>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* ═══ Generate Button + Count ═══ */}
          <div className="flex items-center justify-center gap-3 mb-8">
            <div className="relative flex items-stretch">
              <button
                onClick={onGenerate}
                disabled={!canGenerate}
                className={[
                  'flex items-center gap-2 pl-5 pr-3 py-2.5 rounded-l-xl text-sm font-semibold transition-all',
                  canGenerate
                    ? 'bg-gradient-to-r from-purple-600 to-pink-600 text-white shadow-lg shadow-purple-500/20 hover:shadow-purple-500/30 hover:brightness-110 active:scale-[0.98]'
                    : 'bg-white/[0.06] text-white/25 cursor-not-allowed',
                ].join(' ')}
              >
                {gen.loading ? (
                  <><Loader2 size={16} className="animate-spin" /> Generating...</>
                ) : (
                  <><Sparkles size={16} /> Generate ({count})</>
                )}
              </button>
              <div className="relative">
                <button
                  onClick={() => setShowCountMenu(!showCountMenu)}
                  className={[
                    'h-full px-2.5 rounded-r-xl border-l transition-all flex items-center',
                    canGenerate
                      ? 'bg-gradient-to-r from-pink-600 to-pink-700 border-white/10 text-white/80 hover:text-white'
                      : 'bg-white/[0.06] border-white/5 text-white/15 cursor-not-allowed',
                  ].join(' ')}
                  disabled={!canGenerate && !gen.loading}
                >
                  <ChevronDown size={14} />
                </button>
                {showCountMenu && (
                  <>
                    <div className="fixed inset-0 z-30" onClick={() => setShowCountMenu(false)} />
                    <div className="absolute right-0 top-full mt-1 bg-[#1a1a1a] border border-white/10 rounded-lg shadow-2xl z-40 overflow-hidden min-w-[80px]">
                      {[1, 4, 8].map((n) => (
                        <button key={n}
                          onClick={() => { setCount(n); setShowCountMenu(false) }}
                          className={[
                            'w-full px-4 py-2 text-left text-sm transition-colors',
                            count === n ? 'bg-purple-500/15 text-purple-300 font-medium' : 'text-white/60 hover:bg-white/5 hover:text-white/80',
                          ].join(' ')}
                        >
                          {n} image{n > 1 ? 's' : ''}
                        </button>
                      ))}
                    </div>
                  </>
                )}
              </div>
            </div>

            {canGenerate && !gen.loading && (
              <span className="text-[10px] text-white/20 hidden sm:inline ml-1">Ctrl+Enter</span>
            )}
          </div>

          {/* Professional generating loader — matches Immagine / Animate style */}
          {gen.loading && (
            <div className="max-w-2xl mx-auto mb-8">
              <AvatarGeneratingLoader
                label={mode === 'studio_random' ? 'Designing your character…' : 'Creating your avatar…'}
                hint="This may take up to a minute"
                onCancel={gen.cancel}
                count={count}
                aspectClass={(selectedFraming === 'headshot' && avatarSettings.headshot1to1) ? 'aspect-square' : 'aspect-[2/3]'}
              />
            </div>
          )}

          {/* ═══════════ IMMERSIVE RESULTS — "Choose Your Character" ═══════════ */}
          {gen.result?.results?.length ? (
            <div className="max-w-2xl mx-auto mb-8 animate-fadeSlideIn">
              <div className="text-xs text-white/30 mb-2 font-medium uppercase tracking-wider text-center">
                {gen.result.results.length === 1 ? 'Your Avatar' : 'Choose Your Avatar'}
              </div>
              <p className="text-[11px] text-white/20 text-center mb-4">
                {gen.result.results.length === 1
                  ? 'Click to select, then Create Avatar to save'
                  : 'Click a photo to preview — select your favourite'}
              </p>

              {/* ── Hero preview — shows the clicked photo at full size ── */}
              {selectedResultIndex !== null && gen.result.results[selectedResultIndex] && (() => {
                const hero = gen.result.results[selectedResultIndex]
                const heroUrl = resolveFileUrl(hero.url, backendUrl)
                return (
                  <div className="mb-5 flex flex-col items-center animate-fadeSlideIn">
                    <div className="relative rounded-2xl overflow-hidden border border-white/10 shadow-2xl bg-black/30 max-w-sm w-full">
                      <img
                        src={heroUrl}
                        alt={`Preview — ${hero.scenarioTag || 'Avatar'}`}
                        className={`w-full ${(selectedFraming === 'headshot' && avatarSettings.headshot1to1) ? 'aspect-square' : 'aspect-[2/3]'} object-cover`}
                      />
                      {/* Info overlay — seed + scenario tag */}
                      <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 via-black/30 to-transparent px-3 py-2.5 flex items-end justify-between">
                        <div className="flex flex-col gap-0.5">
                          {hero.scenarioTag && (
                            <span className="text-[10px] font-semibold uppercase tracking-wider text-purple-300/90">
                              {hero.scenarioTag}
                            </span>
                          )}
                          {hero.seed != null && (
                            <span className="text-[10px] text-white/40 font-mono">
                              Seed: {hero.seed}
                            </span>
                          )}
                        </div>
                        {onOpenLightbox && (
                          <button
                            onClick={(e) => { e.stopPropagation(); onOpenLightbox(heroUrl) }}
                            className="p-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white/60 hover:text-white transition-colors"
                            title="Full screen"
                          >
                            <Maximize2 size={14} />
                          </button>
                        )}
                      </div>
                    </div>
                    <p className="text-[10px] text-white/25 mt-2">
                      {gen.result!.results.length > 1
                        ? `Viewing ${selectedResultIndex + 1} of ${gen.result!.results.length} — click another to compare`
                        : 'Click Create Avatar to save'}
                    </p>
                  </div>
                )
              })()}

              {/* Result grid — select one, dim the rest */}
              <div className={`grid gap-3 ${gen.result.results.length === 1 ? 'grid-cols-1 max-w-xs mx-auto' : 'grid-cols-2 sm:grid-cols-4'}`}>
                {gen.result.results.map((item, i) => {
                  const imgUrl = resolveFileUrl(item.url, backendUrl)
                  const blurred = isSpicyContent && !showNsfw
                  const isSelected = selectedResultIndex === i
                  const hasSelection = selectedResultIndex !== null
                  return (
                    <div key={i}
                      className={[
                        'group relative rounded-xl overflow-hidden border-2 bg-white/[0.02] transition-all duration-300 cursor-pointer',
                        isSelected
                          ? 'border-purple-400 shadow-[0_0_20px_rgba(168,85,247,0.3)] scale-[1.02] z-10'
                          : hasSelection
                            ? 'border-white/[0.04] opacity-50 grayscale-[30%] hover:opacity-70 hover:grayscale-0'
                            : 'border-white/[0.06] hover:border-white/20 hover:shadow-lg',
                      ].join(' ')}
                      onClick={() => {
                        if (blurred) { setShowNsfw(true); return }
                        setSelectedResultIndex(isSelected ? null : i)
                      }}
                    >
                      <div className={`${(selectedFraming === 'headshot' && avatarSettings.headshot1to1) ? 'aspect-square' : 'aspect-[2/3]'} bg-white/[0.03] relative`}>
                        <img src={imgUrl} alt={`Avatar ${i + 1}`}
                          className={`w-full h-full object-cover transition-all duration-300 ${blurred ? 'blur-xl scale-110' : ''}`}
                          loading="lazy"
                        />
                        {blurred && (
                          <div className="absolute inset-0 flex flex-col items-center justify-center bg-black/30">
                            <EyeOff size={20} className="text-white/40 mb-1" />
                            <span className="text-[10px] text-white/40 font-medium">Click to reveal</span>
                          </div>
                        )}
                        {/* Selected checkmark badge */}
                        {isSelected && !blurred && (
                          <div className="absolute top-2 right-2 w-7 h-7 rounded-full bg-purple-500 flex items-center justify-center shadow-lg animate-scaleIn">
                            <CheckCircle2 size={16} className="text-white" />
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>

              {/* ═══════════ CREATE AVATAR — appears on selection ═══════════ */}
              {selectedResultIndex !== null && gen.result.results[selectedResultIndex] && (
                <div className="flex flex-col items-center mt-6 animate-fadeSlideIn">
                  <button
                    onClick={() => {
                      const allResults = gen.result!.results
                      const chosen = allResults[selectedResultIndex!]
                      const portraits = allResults.filter((_, i) => i !== selectedResultIndex!)
                      // Save anchor + linked portraits in one atomic operation
                      gallery.addAnchorWithPortraits(
                        chosen, portraits, mode,
                        effectivePrompt || undefined,
                        referenceUrl || undefined,
                        { vibeTag: vibeTagForGallery || undefined, nsfw: isSpicyContent || undefined, framingType: selectedFraming },
                      )
                      setSelectedResultIndex(null)
                      setViewMode('gallery')
                    }}
                    className="flex items-center gap-3 px-8 py-3.5 rounded-2xl bg-gradient-to-r from-purple-600 to-pink-600 text-white font-semibold text-sm shadow-[0_0_30px_rgba(168,85,247,0.25)] hover:shadow-[0_0_40px_rgba(168,85,247,0.4)] hover:scale-[1.03] active:scale-[0.98] transition-all duration-200"
                  >
                    <User size={18} />
                    Create Avatar
                  </button>
                  <p className="text-[10px] text-white/20 mt-2">
                    Saves avatar to gallery — alternatives saved as portraits
                  </p>
                </div>
              )}
            </div>
          ) : null}

          {/* Empty state — only when nothing has been generated yet */}
          {!gen.result && !gen.loading && (
            <div className="flex flex-col items-center justify-center py-16 text-white/15">
              <ImageIcon size={48} strokeWidth={1} />
              <p className="mt-4 text-sm text-white/30">Your avatars will appear here</p>
              <p className="mt-1 text-[11px] text-white/15">
                {mode === 'studio_random'
                  ? 'Choose a gender and style, then click Generate'
                  : 'Pick a vibe and click Generate to get started'}
              </p>
            </div>
          )}

          {outfitAnchor && (
            <OutfitPanel anchor={outfitAnchor} backendUrl={backendUrl} apiKey={apiKey}
              nsfwMode={nsfwMode}
              checkpointOverride={resolveCheckpoint(avatarSettings, globalModelImages)}
              onResults={(results, scenarioTag) => {
                const rootId = outfitAnchor.parentId || outfitAnchor.id
                gallery.addBatch(results, mode, outfitAnchor.prompt, outfitAnchor.url, scenarioTag, { parentId: rootId })
              }}
              onSendToEdit={onSendToEdit} onOpenLightbox={onOpenLightbox}
              onClose={() => setOutfitAnchor(null)}
            />
          )}
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-toastSlideUp">
          <div className={[
            'flex items-center gap-2.5 px-5 py-3 rounded-xl shadow-2xl backdrop-blur-md border text-sm font-medium',
            toast.type === 'error' ? 'bg-red-500/15 border-red-500/20 text-red-300'
              : toast.type === 'success' ? 'bg-green-500/15 border-green-500/20 text-green-300'
                : 'bg-white/10 border-white/10 text-white/70',
          ].join(' ')}>
            {toast.type === 'error' && <AlertTriangle size={16} />}
            {toast.type === 'success' && <Sparkles size={16} />}
            <span>{toast.message}</span>
            <button onClick={() => setToast(null)} className="ml-2 text-white/30 hover:text-white/60 transition-colors"><X size={14} /></button>
          </div>
        </div>
      )}

      <style>{`
        @keyframes fadeSlideIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        .animate-fadeSlideIn { animation: fadeSlideIn 0.35s ease-out; }
        @keyframes toastSlideUp { from { opacity: 0; transform: translate(-50%, 16px); } to { opacity: 1; transform: translate(-50%, 0); } }
        .animate-toastSlideUp { animation: toastSlideUp 0.25s ease-out; }
        @keyframes scaleIn { from { opacity: 0; transform: scale(0.5); } to { opacity: 1; transform: scale(1); } }
        .animate-scaleIn { animation: scaleIn 0.2s ease-out; }
      `}</style>
    </div>
  )
}
