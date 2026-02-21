/**
 * AvatarStudio — Main Avatar Studio view component.
 *
 * Matches the existing HomePilot Mode-based architecture:
 *   - Rendered when mode === 'avatar' in App.tsx
 *   - Uses Tailwind CSS + Lucide icons (same as Imagine/Edit/Animate)
 *   - Cyber-Noir aesthetic (True Black backgrounds)
 *
 * Features:
 *   - Mode pills: From Reference / Random Face / Face + Style
 *   - 4-up results grid with hover actions
 *   - Seed display + regenerate
 *   - Reference image upload (drag & drop + click)
 *   - Pack availability badges
 *   - "Open in Edit" to send an avatar into the Edit workspace
 *   - Lightbox support for full-screen preview
 *   - Keyboard shortcut: Enter to generate
 */

import React, { useState, useCallback, useRef, useEffect } from 'react'
import {
  Loader2,
  Upload,
  Wand2,
  RefreshCw,
  Download,
  User,
  Shuffle,
  Palette,
  AlertTriangle,
  Image as ImageIcon,
  X,
  Check,
  Sparkles,
  PenLine,
  Maximize2,
  Copy,
  ChevronLeft,
} from 'lucide-react'

import { useAvatarPacks } from './useAvatarPacks'
import { useGenerateAvatars } from './useGenerateAvatars'
import { useAvatarGallery } from './useAvatarGallery'
import { installAvatarPack } from './avatarApi'
import { AvatarGallery } from './AvatarGallery'
import { AvatarLandingPage } from './AvatarLandingPage'
import { OutfitPanel } from './OutfitPanel'
import { AvatarSettingsPanel, loadAvatarSettings, resolveCheckpoint } from './AvatarSettingsPanel'
import type { AvatarMode, AvatarResult, AvatarSettings } from './types'
import type { GalleryItem } from './galleryTypes'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface AvatarStudioProps {
  backendUrl: string
  apiKey?: string
  /** Global image model from Settings (settingsDraft.modelImages) */
  globalModelImages?: string
  /** Navigate to Edit mode with a given image URL */
  onSendToEdit?: (imageUrl: string) => void
  /** Open full-screen lightbox */
  onOpenLightbox?: (imageUrl: string) => void
  /** Save an avatar as a Persona (opens SaveAsPersonaModal) */
  onSaveAsPersonaAvatar?: (item: GalleryItem) => void
  /** Open outfit variations panel for a gallery item */
  onGenerateOutfits?: (item: GalleryItem) => void
}

// ---------------------------------------------------------------------------
// Mode config
// ---------------------------------------------------------------------------

const MODE_OPTIONS: { label: string; value: AvatarMode; icon: React.ReactNode; description: string }[] = [
  {
    label: 'From Reference',
    value: 'studio_reference',
    icon: <User size={16} />,
    description: 'Upload a photo to generate identity-consistent portraits',
  },
  {
    label: 'Random Face',
    value: 'studio_random',
    icon: <Shuffle size={16} />,
    description: 'Generate a completely new face from scratch',
  },
  {
    label: 'Face + Style',
    value: 'studio_faceswap',
    icon: <Palette size={16} />,
    description: 'Combine your face with a styled body and scene',
  },
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AvatarStudio({ backendUrl, apiKey, globalModelImages, onSendToEdit, onOpenLightbox, onSaveAsPersonaAvatar, onGenerateOutfits }: AvatarStudioProps) {
  const packs = useAvatarPacks(backendUrl, apiKey)
  const gen = useGenerateAvatars(backendUrl, apiKey)
  const gallery = useAvatarGallery()

  // TWO-VIEW ARCHITECTURE: gallery (landing) vs designer (creation workspace)
  const [viewMode, setViewMode] = useState<'gallery' | 'designer'>('gallery')

  // Avatar-specific model settings (persisted in localStorage)
  const [avatarSettings, setAvatarSettings] = useState<AvatarSettings>(loadAvatarSettings)

  const enabledModes = packs.data?.enabled_modes ?? []
  const [mode, setMode] = useState<AvatarMode>('studio_random')
  const [prompt, setPrompt] = useState('studio headshot, soft light, photorealistic')
  const [referenceUrl, setReferenceUrl] = useState('')
  const [referencePreview, setReferencePreview] = useState<string | null>(null)
  const [count, setCount] = useState(4)
  const [outfitAnchor, setOutfitAnchor] = useState<GalleryItem | null>(null)
  const [copiedSeed, setCopiedSeed] = useState<number | null>(null)
  const [isDraggingRef, setIsDraggingRef] = useState(false)
  const [packInstallBusy, setPackInstallBusy] = useState(false)
  const [packInstallError, setPackInstallError] = useState<string | null>(null)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const promptInputRef = useRef<HTMLInputElement>(null)

  // ---- Reference image upload ----
  const handleFileUpload = useCallback(
    async (file: File) => {
      const preview = URL.createObjectURL(file)
      setReferencePreview(preview)

      // Upload to backend
      const formData = new FormData()
      formData.append('file', file)
      const base = (backendUrl || '').replace(/\/+$/, '')
      const headers: Record<string, string> = {}
      if (apiKey) headers['x-api-key'] = apiKey

      try {
        const res = await fetch(`${base}/upload`, {
          method: 'POST',
          headers,
          body: formData,
        })
        if (res.ok) {
          const data = await res.json()
          setReferenceUrl(data.url || data.file_url || '')
        }
      } catch {
        // Fallback: just use the local preview
      }
    },
    [backendUrl, apiKey],
  )

  // ---- Drag and drop for reference image ----
  const handleRefDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDraggingRef(true)
  }, [])

  const handleRefDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDraggingRef(false)
  }, [])

  const handleRefDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      e.stopPropagation()
      setIsDraggingRef(false)
      const file = e.dataTransfer.files?.[0]
      if (file && file.type.startsWith('image/')) {
        handleFileUpload(file)
      }
    },
    [handleFileUpload],
  )

  // ---- Generate ----
  const onGenerate = useCallback(async () => {
    const checkpoint = resolveCheckpoint(avatarSettings, globalModelImages)
    const result = await gen.run({
      mode,
      count,
      prompt: prompt.trim() || undefined,
      reference_image_url:
        mode === 'studio_reference' || mode === 'studio_faceswap'
          ? referenceUrl || undefined
          : undefined,
      truncation: 0.7,
      checkpoint_override: checkpoint,
    })
    // Auto-save results to persistent gallery
    if (result?.results?.length) {
      gallery.addBatch(
        result.results,
        mode,
        prompt.trim() || undefined,
        referenceUrl || undefined,
      )
    }
  }, [gen, mode, count, prompt, referenceUrl, gallery, avatarSettings, globalModelImages])

  // ---- Keyboard shortcut: Enter to generate ----
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd + Enter to generate from anywhere
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canGenerate) {
        e.preventDefault()
        onGenerate()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onGenerate])

  // ---- Copy seed to clipboard ----
  const handleCopySeed = useCallback((seed: number) => {
    navigator.clipboard.writeText(String(seed)).catch(() => {})
    setCopiedSeed(seed)
    setTimeout(() => setCopiedSeed(null), 1500)
  }, [])

  // ---- UI State ----
  // Only "From Reference" strictly requires a photo; Face+Style accepts optional ref
  const needsReference = mode === 'studio_reference'
  const showsReference = mode === 'studio_reference' || mode === 'studio_faceswap'
  const canGenerate = !gen.loading && (needsReference ? !!referenceUrl : true)

  // ==========================================================================
  // RENDER - Gallery View (Landing)
  // ==========================================================================

  if (viewMode === 'gallery') {
    return (
      <AvatarLandingPage
        items={gallery.items}
        backendUrl={backendUrl}
        onNewAvatar={() => setViewMode('designer')}
        onOpenItem={(item) => {
          // Open the lightbox for the selected item
          const imgUrl = item.url.startsWith('http')
            ? item.url
            : `${backendUrl.replace(/\/+$/, '')}${item.url}`
          onOpenLightbox?.(imgUrl)
        }}
        onDeleteItem={gallery.removeItem}
        onOpenLightbox={onOpenLightbox}
        onSendToEdit={onSendToEdit}
        onSaveAsPersonaAvatar={onSaveAsPersonaAvatar}
        onGenerateOutfits={(item) => setOutfitAnchor(item)}
      />
    )
  }

  // ==========================================================================
  // RENDER - Designer View (Avatar Studio workspace)
  // ==========================================================================

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-black text-white">
      {/* Header */}
      <div className="px-5 pt-5 pb-3 border-b border-white/5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Back to Gallery */}
            <button
              onClick={() => setViewMode('gallery')}
              className="w-9 h-9 rounded-xl bg-white/10 hover:bg-white/20 flex items-center justify-center backdrop-blur-md transition-colors"
              title="Back to Gallery"
              aria-label="Back to Avatar Gallery"
            >
              <ChevronLeft size={18} className="text-white" />
            </button>
            <div>
              <h2 className="text-lg font-semibold tracking-tight">Avatar Studio</h2>
              <p className="text-xs text-white/50 mt-0.5">
                Generate reusable portrait avatars for your personas
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {gen.result?.results?.length ? (
              <div className="text-xs text-white/30">
                {gen.result.results.length} result{gen.result.results.length !== 1 ? 's' : ''}
              </div>
            ) : null}
            <AvatarSettingsPanel
              globalModelImages={globalModelImages}
              settings={avatarSettings}
              onChange={setAvatarSettings}
            />
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="max-w-4xl mx-auto px-5 py-5 space-y-5">

          {/* Pack status banner */}
          {packs.error && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs" role="alert">
              <AlertTriangle size={14} />
              <span>Could not load avatar packs: {packs.error}</span>
            </div>
          )}

          {packs.loading && !packs.data && (
            <div className="flex items-center gap-3 px-3 py-3 rounded-lg bg-white/5 border border-white/10">
              <Loader2 size={14} className="animate-spin text-white/50" />
              <span className="text-xs text-white/50">Loading avatar packs...</span>
            </div>
          )}

          {packs.data && enabledModes.length === 0 && !packs.loading && (
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/10 p-3 flex items-center justify-between gap-3" role="alert">
              <div className="flex items-center gap-2 min-w-0">
                <AlertTriangle size={14} className="text-amber-400 flex-shrink-0" />
                <div>
                  <span className="text-xs text-amber-200">
                    No avatar packs installed. Install the Basic Pack to enable identity avatars.
                  </span>
                  {packInstallError && (
                    <div className="text-[10px] text-red-300 mt-1">{packInstallError}</div>
                  )}
                </div>
              </div>
              <button
                className="px-3 py-1.5 rounded-md bg-amber-400/20 hover:bg-amber-400/30 text-amber-100 text-xs font-semibold whitespace-nowrap transition-colors disabled:opacity-50"
                disabled={packInstallBusy}
                onClick={async () => {
                  try {
                    setPackInstallError(null)
                    setPackInstallBusy(true)
                    await installAvatarPack(backendUrl, 'avatar-basic', apiKey)
                    await packs.refresh()
                  } catch (e: any) {
                    setPackInstallError(e?.message ?? String(e))
                  } finally {
                    setPackInstallBusy(false)
                  }
                }}
              >
                {packInstallBusy ? 'Installing...' : 'Install Basic Pack'}
              </button>
            </div>
          )}

          {/* Pack badges */}
          {packs.data && packs.data.packs.length > 0 && (
            <div className="flex flex-wrap gap-2" role="list" aria-label="Installed avatar packs">
              {packs.data.packs.map((p) => (
                <div
                  key={p.id}
                  role="listitem"
                  className={[
                    'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border',
                    p.installed
                      ? 'border-green-500/30 bg-green-500/10 text-green-400'
                      : 'border-white/10 bg-white/5 text-white/40',
                  ].join(' ')}
                >
                  {p.installed ? <Check size={12} /> : <X size={12} />}
                  <span>{p.title}</span>
                  {!p.commercial_ok && p.installed && (
                    <span className="ml-1 px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 text-[10px]">
                      Non-commercial
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Mode pills */}
          <div>
            <div className="text-xs text-white/40 mb-2 font-medium uppercase tracking-wider">
              Generation Mode
            </div>
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Avatar generation mode">
              {MODE_OPTIONS.map((o) => {
                const enabled = enabledModes.includes(o.value)
                const active = mode === o.value
                return (
                  <button
                    key={o.value}
                    disabled={!enabled}
                    onClick={() => setMode(o.value)}
                    title={o.description}
                    role="radio"
                    aria-checked={active}
                    aria-label={`${o.label}: ${o.description}`}
                    className={[
                      'flex items-center gap-2 px-3.5 py-2 rounded-xl text-sm font-medium transition-all',
                      'border',
                      active
                        ? 'border-purple-500/50 bg-purple-500/15 text-purple-300 shadow-[0_0_12px_rgba(168,85,247,0.15)]'
                        : enabled
                          ? 'border-white/10 bg-white/5 text-white/70 hover:bg-white/8 hover:border-white/20'
                          : 'border-white/5 bg-white/[0.02] text-white/20 cursor-not-allowed',
                    ].join(' ')}
                  >
                    {o.icon}
                    {o.label}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Prompt */}
          <div>
            <div className="text-xs text-white/40 mb-2 font-medium uppercase tracking-wider">
              Prompt (optional)
            </div>
            <input
              ref={promptInputRef}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && canGenerate) {
                  e.preventDefault()
                  onGenerate()
                }
              }}
              placeholder="e.g. professional headshot, warm lighting"
              aria-label="Avatar generation prompt"
              className="w-full px-3 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/25 focus:outline-none focus:border-purple-500/50 focus:ring-1 focus:ring-purple-500/20 transition-all"
            />
          </div>

          {/* Reference upload (conditional) */}
          {showsReference && (
            <div>
              <div className="text-xs text-white/40 mb-2 font-medium uppercase tracking-wider">
                Reference Image{!needsReference && <span className="normal-case text-white/25 ml-1.5">(optional)</span>}
              </div>
              <div className="flex items-start gap-4">
                {/* Upload zone with drag & drop */}
                <button
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={handleRefDragOver}
                  onDragLeave={handleRefDragLeave}
                  onDrop={handleRefDrop}
                  aria-label="Upload reference photo"
                  className={[
                    'w-32 h-32 rounded-xl border-2 border-dashed bg-white/[0.02] flex flex-col items-center justify-center gap-2 transition-all cursor-pointer',
                    isDraggingRef
                      ? 'border-purple-500/60 text-purple-400 bg-purple-500/10 scale-105'
                      : 'border-white/15 text-white/40 hover:border-purple-500/40 hover:text-purple-400 hover:bg-purple-500/5',
                  ].join(' ')}
                >
                  <Upload size={20} />
                  <span className="text-[11px]">
                    {isDraggingRef ? 'Drop here' : 'Upload photo'}
                  </span>
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0]
                    if (file) handleFileUpload(file)
                    e.target.value = ''
                  }}
                />

                {/* Preview */}
                {referencePreview && (
                  <div className="relative w-32 h-32 rounded-xl overflow-hidden border border-white/10">
                    <img
                      src={referencePreview}
                      alt="Reference photo preview"
                      className="w-full h-full object-cover"
                    />
                    <button
                      onClick={() => {
                        setReferencePreview(null)
                        setReferenceUrl('')
                      }}
                      aria-label="Remove reference image"
                      className="absolute top-1 right-1 w-6 h-6 rounded-full bg-black/70 flex items-center justify-center text-white/70 hover:text-white transition-colors"
                    >
                      <X size={14} />
                    </button>
                  </div>
                )}

                {/* URL input (fallback) */}
                {!referencePreview && (
                  <div className="flex-1 space-y-2">
                    <div className="text-[11px] text-white/30">Or paste an image URL</div>
                    <input
                      value={referenceUrl}
                      onChange={(e) => setReferenceUrl(e.target.value)}
                      placeholder="https://... or /uploads/..."
                      aria-label="Reference image URL"
                      className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-white text-xs placeholder:text-white/20 focus:outline-none focus:border-purple-500/50 transition-all"
                    />
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Generate button */}
          <div className="flex items-center gap-3">
            <button
              onClick={onGenerate}
              disabled={!canGenerate}
              aria-label={gen.loading ? 'Generating avatars...' : `Generate ${count} avatars`}
              className={[
                'flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all',
                canGenerate
                  ? 'bg-gradient-to-r from-purple-600 to-pink-600 text-white shadow-lg shadow-purple-500/20 hover:shadow-purple-500/30 hover:scale-[1.02] active:scale-[0.98]'
                  : 'bg-white/5 text-white/25 cursor-not-allowed',
              ].join(' ')}
            >
              {gen.loading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Generating...
                </>
              ) : (
                <>
                  <Wand2 size={16} />
                  Generate {count}
                </>
              )}
            </button>

            {/* Count selector */}
            <div className="flex items-center gap-1" role="radiogroup" aria-label="Number of avatars to generate">
              {[1, 4, 8].map((n) => (
                <button
                  key={n}
                  onClick={() => setCount(n)}
                  role="radio"
                  aria-checked={count === n}
                  aria-label={`Generate ${n}`}
                  className={[
                    'px-2.5 py-1 rounded-lg text-xs font-medium transition-all border',
                    count === n
                      ? 'border-white/20 bg-white/10 text-white'
                      : 'border-white/5 bg-white/[0.02] text-white/30 hover:text-white/60',
                  ].join(' ')}
                >
                  {n}
                </button>
              ))}
            </div>

            {gen.result && (
              <button
                onClick={onGenerate}
                disabled={gen.loading}
                aria-label="Regenerate avatars"
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-white/10 bg-white/5 text-white/60 text-xs hover:bg-white/8 transition-all"
              >
                <RefreshCw size={14} />
                Regenerate
              </button>
            )}

            {canGenerate && !gen.loading && (
              <span className="text-[10px] text-white/20 hidden sm:inline">
                Press Enter to generate
              </span>
            )}
          </div>

          {/* Error */}
          {gen.error && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs" role="alert">
              <AlertTriangle size={14} />
              <span>{gen.error}</span>
            </div>
          )}

          {/* Warnings */}
          {gen.result?.warnings?.length ? (
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs" role="alert">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <div>
                {gen.result.warnings.map((w, i) => (
                  <div key={i}>{w}</div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Loading skeleton */}
          {gen.loading && !gen.result && (
            <div>
              <div className="text-xs text-white/40 mb-3 font-medium uppercase tracking-wider">
                Generating...
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                {Array.from({ length: count }).map((_, i) => (
                  <div key={i} className="rounded-xl overflow-hidden border border-white/8 bg-white/[0.02]">
                    <div className="aspect-square bg-white/[0.03] animate-pulse flex items-center justify-center">
                      <Loader2 size={24} className="animate-spin text-white/10" />
                    </div>
                    <div className="px-2.5 py-2">
                      <div className="h-3 bg-white/5 rounded animate-pulse w-16" />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Results grid */}
          {gen.result?.results?.length ? (
            <div>
              <div className="text-xs text-white/40 mb-3 font-medium uppercase tracking-wider flex items-center justify-between">
                <span>Results</span>
                <span className="text-white/20 normal-case tracking-normal">
                  Hover for actions
                </span>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                {gen.result.results.map((item, i) => (
                  <AvatarCard
                    key={i}
                    item={item}
                    backendUrl={backendUrl}
                    onSendToEdit={onSendToEdit}
                    onOpenLightbox={onOpenLightbox}
                    onCopySeed={handleCopySeed}
                    copiedSeed={copiedSeed}
                  />
                ))}
              </div>
            </div>
          ) : null}

          {/* Empty state */}
          {!gen.result && !gen.loading && !gen.error && (
            <div className="flex flex-col items-center justify-center py-16 text-white/20">
              <ImageIcon size={48} strokeWidth={1} />
              <div className="mt-4 text-sm">
                {needsReference && !referenceUrl
                  ? 'Upload a reference photo to preserve identity'
                  : showsReference && !referenceUrl
                    ? 'Upload a photo (optional) or click Generate to create a new avatar'
                    : 'Click Generate to create a new avatar'}
              </div>
              <div className="mt-2 text-[11px] text-white/15">
                Tip: Generated avatars can be sent to Edit Studio for touch-ups
              </div>
            </div>
          )}

          {/* Outfit Variations Panel (appears when user clicks "Outfit Variations" on a gallery item) */}
          {outfitAnchor && (
            <OutfitPanel
              anchor={outfitAnchor}
              backendUrl={backendUrl}
              apiKey={apiKey}
              nsfwMode={(() => { try { return localStorage.getItem('homepilot_nsfw_mode') === 'true' } catch { return false } })()}
              checkpointOverride={resolveCheckpoint(avatarSettings, globalModelImages)}
              onResults={(results) => gallery.addBatch(results, mode, outfitAnchor.prompt, outfitAnchor.url)}
              onSendToEdit={onSendToEdit}
              onOpenLightbox={onOpenLightbox}
              onClose={() => setOutfitAnchor(null)}
            />
          )}

          {/* Persistent Avatar Gallery */}
          <AvatarGallery
            items={gallery.items}
            backendUrl={backendUrl}
            onDelete={gallery.removeItem}
            onClearAll={gallery.clearAll}
            onOpenLightbox={onOpenLightbox}
            onSendToEdit={onSendToEdit}
            onSaveAsPersonaAvatar={onSaveAsPersonaAvatar}
            onGenerateOutfits={(item) => setOutfitAnchor(item)}
          />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// AvatarCard (local component)
// ---------------------------------------------------------------------------

function AvatarCard({
  item,
  backendUrl,
  onSendToEdit,
  onOpenLightbox,
  onCopySeed,
  copiedSeed,
}: {
  item: AvatarResult
  backendUrl: string
  onSendToEdit?: (imageUrl: string) => void
  onOpenLightbox?: (imageUrl: string) => void
  onCopySeed?: (seed: number) => void
  copiedSeed?: number | null
}) {
  const imgUrl = item.url?.startsWith('http')
    ? item.url
    : `${(backendUrl || '').replace(/\/+$/, '')}${item.url}`

  return (
    <div className="group relative rounded-xl overflow-hidden border border-white/8 bg-white/[0.02] hover:border-white/15 transition-all">
      {/* Image */}
      <div
        className="aspect-square bg-white/[0.03] cursor-pointer relative"
        onClick={() => onOpenLightbox?.(imgUrl)}
      >
        <img
          src={imgUrl}
          alt={`Generated avatar${item.seed !== undefined ? `, seed ${item.seed}` : ''}`}
          className="w-full h-full object-cover"
          loading="lazy"
        />

        {/* Hover overlay with actions */}
        <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center justify-center gap-2">
          {onOpenLightbox && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onOpenLightbox(imgUrl)
              }}
              className="p-2 bg-white/10 backdrop-blur-md rounded-lg text-white hover:bg-white/20 transition-colors"
              title="View full size"
              aria-label="View avatar full size"
            >
              <Maximize2 size={16} />
            </button>
          )}
          {onSendToEdit && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onSendToEdit(imgUrl)
              }}
              className="p-2 bg-purple-500/30 backdrop-blur-md rounded-lg text-purple-200 hover:bg-purple-500/50 transition-colors"
              title="Open in Edit Studio"
              aria-label="Send avatar to Edit Studio for touch-ups"
            >
              <PenLine size={16} />
            </button>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between px-2.5 py-2">
        <button
          onClick={() => item.seed !== undefined && onCopySeed?.(item.seed!)}
          className="text-[11px] text-white/40 font-mono hover:text-white/70 transition-colors cursor-pointer"
          title={item.seed !== undefined ? 'Click to copy seed' : undefined}
          aria-label={item.seed !== undefined ? `Copy seed ${item.seed}` : 'No seed'}
        >
          {copiedSeed === item.seed ? (
            <span className="flex items-center gap-1 text-green-400">
              <Check size={10} /> copied
            </span>
          ) : (
            <>
              {item.seed !== undefined ? (
                <span className="flex items-center gap-1">
                  seed {item.seed}
                  <Copy size={9} className="opacity-0 group-hover:opacity-100 transition-opacity" />
                </span>
              ) : (
                'seed ---'
              )}
            </>
          )}
        </button>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            className="p-1 rounded-md hover:bg-white/10 text-white/50 hover:text-white transition-colors"
            title="Download avatar"
            aria-label={`Download avatar${item.seed !== undefined ? ` seed ${item.seed}` : ''}`}
            onClick={() => {
              const a = document.createElement('a')
              a.href = imgUrl
              a.download = `avatar_${item.seed ?? 'unknown'}.png`
              a.click()
            }}
          >
            <Download size={14} />
          </button>
        </div>
      </div>
    </div>
  )
}
