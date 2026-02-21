/**
 * AvatarStudio — "Command Center" unified view.
 *
 * Enterprise-grade single-screen layout:
 *   - Top banner: title + gear icon for settings drawer
 *   - Mode pills: Random / From Reference / Face + Style
 *   - Smart prompt bar with inline camera icon → auto-mode switch
 *   - Generate button with count dropdown
 *   - Gallery grid below (persistent)
 *   - Toast-style error messages (no raw JSON)
 *   - Keyboard shortcut: Enter to generate
 */

import React, { useState, useCallback, useRef, useEffect } from 'react'
import {
  Loader2,
  Upload,
  Wand2,
  User,
  Shuffle,
  Palette,
  AlertTriangle,
  Image as ImageIcon,
  X,
  Camera,
  Sparkles,
  ChevronDown,
} from 'lucide-react'

import { useAvatarPacks } from './useAvatarPacks'
import { useGenerateAvatars } from './useGenerateAvatars'
import { useAvatarGallery } from './useAvatarGallery'
import { installAvatarPack } from './avatarApi'
import { AvatarGallery } from './AvatarGallery'
import { AvatarLandingPage } from './AvatarLandingPage'
import { AvatarViewer } from './AvatarViewer'
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
  globalModelImages?: string
  onSendToEdit?: (imageUrl: string) => void
  onOpenLightbox?: (imageUrl: string) => void
  onSaveAsPersonaAvatar?: (item: GalleryItem) => void
  onGenerateOutfits?: (item: GalleryItem) => void
}

// ---------------------------------------------------------------------------
// Mode config
// ---------------------------------------------------------------------------

const MODE_OPTIONS: { label: string; value: AvatarMode; icon: React.ReactNode; description: string }[] = [
  {
    label: 'Random',
    value: 'studio_random',
    icon: <Shuffle size={14} />,
    description: 'Generate a completely new face from scratch',
  },
  {
    label: 'From Reference',
    value: 'studio_reference',
    icon: <User size={14} />,
    description: 'Upload a photo to generate identity-consistent portraits',
  },
  {
    label: 'Face + Style',
    value: 'studio_faceswap',
    icon: <Palette size={14} />,
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

  // THREE-VIEW ARCHITECTURE: gallery (landing) → viewer (character sheet) → designer (creation)
  const [viewMode, setViewMode] = useState<'gallery' | 'designer' | 'viewer'>('gallery')
  const [viewerItem, setViewerItem] = useState<GalleryItem | null>(null)

  // Avatar-specific model settings (persisted in localStorage)
  const [avatarSettings, setAvatarSettings] = useState<AvatarSettings>(loadAvatarSettings)

  const enabledModes = packs.data?.enabled_modes ?? []
  const [mode, setMode] = useState<AvatarMode>('studio_random')
  const [prompt, setPrompt] = useState('')
  const [referenceUrl, setReferenceUrl] = useState('')
  const [referencePreview, setReferencePreview] = useState<string | null>(null)
  const [count, setCount] = useState(1)
  const [showCountMenu, setShowCountMenu] = useState(false)
  const [outfitAnchor, setOutfitAnchor] = useState<GalleryItem | null>(null)
  const [packInstallBusy, setPackInstallBusy] = useState(false)
  const [packInstallError, setPackInstallError] = useState<string | null>(null)

  // Toast notification state
  const [toast, setToast] = useState<{ message: string; type: 'error' | 'success' | 'info' } | null>(null)
  const toastTimer = useRef<ReturnType<typeof setTimeout>>()

  const fileInputRef = useRef<HTMLInputElement>(null)
  const promptInputRef = useRef<HTMLInputElement>(null)

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

      // Auto-switch mode to "From Reference" when photo is uploaded
      if (mode === 'studio_random') {
        setMode('studio_reference')
      }

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
    [backendUrl, apiKey, mode],
  )

  // ---- Remove reference ----
  const handleRemoveReference = useCallback(() => {
    setReferencePreview(null)
    setReferenceUrl('')
    // Auto-switch back to Random if we were on Reference
    if (mode === 'studio_reference') {
      setMode('studio_random')
    }
  }, [mode])

  // ---- Generate ----
  const onGenerate = useCallback(async () => {
    const checkpoint = resolveCheckpoint(avatarSettings, globalModelImages)
    try {
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
      if (result?.results?.length) {
        gallery.addBatch(
          result.results,
          mode,
          prompt.trim() || undefined,
          referenceUrl || undefined,
        )
        showToast(`${result.results.length} avatar${result.results.length > 1 ? 's' : ''} created`, 'success')
      }
    } catch {
      showToast('Oops, the servers are a bit busy. Click Generate to try again.', 'error')
    }
  }, [gen, mode, count, prompt, referenceUrl, gallery, avatarSettings, globalModelImages, showToast])

  // ---- Keyboard shortcut: Enter/Cmd+Enter to generate ----
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canGenerate) {
        e.preventDefault()
        onGenerate()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onGenerate])

  // ---- UI State ----
  const needsReference = mode === 'studio_reference'
  const canGenerate = !gen.loading && (needsReference ? !!referenceUrl : true)

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
          onOpenItem={(item) => {
            setViewerItem(item)
            setViewMode('viewer')
          }}
          onDeleteItem={gallery.removeItem}
          onOpenLightbox={onOpenLightbox}
          onSendToEdit={onSendToEdit}
          onSaveAsPersonaAvatar={onSaveAsPersonaAvatar}
          onGenerateOutfits={(item) => {
            setViewerItem(item)
            setViewMode('viewer')
          }}
        />
        {outfitAnchor && (
          <OutfitPanel
            anchor={outfitAnchor}
            backendUrl={backendUrl}
            apiKey={apiKey}
            nsfwMode={(() => { try { return localStorage.getItem('homepilot_nsfw_mode') === 'true' } catch { return false } })()}
            checkpointOverride={resolveCheckpoint(avatarSettings, globalModelImages)}
            onResults={(results, scenarioTag) => gallery.addBatch(results, mode, outfitAnchor.prompt, outfitAnchor.url, scenarioTag)}
            onSendToEdit={onSendToEdit}
            onOpenLightbox={onOpenLightbox}
            onClose={() => setOutfitAnchor(null)}
          />
        )}
      </>
    )
  }

  // ==========================================================================
  // RENDER — Viewer (MMORPG-style Character Sheet)
  // ==========================================================================

  if (viewMode === 'viewer' && viewerItem) {
    return (
      <AvatarViewer
        item={viewerItem}
        allItems={gallery.items}
        backendUrl={backendUrl}
        apiKey={apiKey}
        globalModelImages={globalModelImages}
        onBack={() => {
          setViewerItem(null)
          setViewMode('gallery')
        }}
        onOpenLightbox={onOpenLightbox}
        onSendToEdit={onSendToEdit}
        onSaveAsPersonaAvatar={onSaveAsPersonaAvatar}
        onDeleteItem={(id) => {
          gallery.removeItem(id)
          if (id === viewerItem.id) {
            setViewerItem(null)
            setViewMode('gallery')
          }
        }}
        onOutfitResults={(results, anchor) => {
          gallery.addBatch(results, anchor.mode, anchor.prompt, anchor.url, anchor.scenarioTag)
        }}
      />
    )
  }

  // ==========================================================================
  // RENDER - Designer View — "Command Center" Layout
  // ==========================================================================

  return (
    <div className="flex-1 flex flex-col min-h-0 bg-black text-white">

      {/* ═══════════════════════ TOP BANNER ═══════════════════════ */}
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
          />
        </div>
      </div>

      {/* ═══════════════════════ MAIN CONTENT ═══════════════════════ */}
      <div className="flex-1 overflow-y-auto min-h-0">
        <div className="max-w-5xl mx-auto px-6 py-8">

          {/* ── Pack Install Banner (only when needed) ──────────── */}
          {packs.data && enabledModes.length === 0 && !packs.loading && (
            <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.06] p-4 flex items-center justify-between gap-4 mb-8">
              <div className="flex items-center gap-3 min-w-0">
                <AlertTriangle size={16} className="text-amber-400 flex-shrink-0" />
                <div>
                  <span className="text-sm text-amber-200 font-medium">
                    No avatar packs installed
                  </span>
                  <p className="text-xs text-amber-400/60 mt-0.5">
                    Install the Basic Pack to unlock identity-consistent avatars
                  </p>
                  {packInstallError && (
                    <div className="text-[10px] text-red-300 mt-1">{packInstallError}</div>
                  )}
                </div>
              </div>
              <button
                className="px-4 py-2 rounded-lg bg-amber-400/20 hover:bg-amber-400/30 text-amber-100 text-sm font-semibold whitespace-nowrap transition-colors disabled:opacity-50"
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

          {/* ── Title Section ──────────────────────────────────── */}
          <div className="text-center mb-6">
            <h2 className="text-xl font-bold tracking-tight text-white/90">
              Create Your Avatar
            </h2>
          </div>

          {/* ── Mode Pills ─────────────────────────────────────── */}
          <div className="flex items-center justify-center gap-2 mb-6" role="radiogroup" aria-label="Avatar generation mode">
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
                  className={[
                    'flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium transition-all',
                    active
                      ? 'bg-white/10 text-white border border-white/20 shadow-[0_0_12px_rgba(255,255,255,0.05)]'
                      : enabled
                        ? 'text-white/40 hover:text-white/60 hover:bg-white/[0.04] border border-transparent'
                        : 'text-white/15 cursor-not-allowed border border-transparent',
                  ].join(' ')}
                >
                  {o.icon}
                  {o.label}
                </button>
              )
            })}
          </div>

          {/* ── Smart Prompt Bar ─────────────────────────────────── */}
          <div className="max-w-2xl mx-auto mb-5">
            <div className={[
              'flex items-center gap-2 px-4 py-3 rounded-2xl border transition-all',
              'bg-white/[0.04] focus-within:bg-white/[0.06]',
              'border-white/10 focus-within:border-purple-500/40 focus-within:ring-1 focus-within:ring-purple-500/20',
            ].join(' ')}>

              {/* Camera icon / reference thumbnail */}
              {referencePreview ? (
                <div className="relative flex-shrink-0">
                  <div className="w-9 h-9 rounded-full overflow-hidden border-2 border-purple-500/40">
                    <img
                      src={referencePreview}
                      alt="Reference"
                      className="w-full h-full object-cover"
                    />
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
                  className="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center text-white/20 hover:text-white/50 hover:bg-white/5 transition-all"
                  title="Upload a reference photo"
                  aria-label="Upload reference photo"
                >
                  <Camera size={18} />
                </button>
              )}

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

              {/* Prompt input */}
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
                placeholder='Describe your avatar (e.g., "cyberpunk, studio lighting")...'
                aria-label="Avatar generation prompt"
                className="flex-1 bg-transparent text-white text-sm placeholder:text-white/25 focus:outline-none"
              />
            </div>
          </div>

          {/* ── Generate Button + Count ─────────────────────────── */}
          <div className="flex items-center justify-center gap-3 mb-8">
            <div className="relative flex items-stretch">
              {/* Main generate button */}
              <button
                onClick={onGenerate}
                disabled={!canGenerate}
                aria-label={gen.loading ? 'Generating avatars...' : `Generate ${count} avatar${count > 1 ? 's' : ''}`}
                className={[
                  'flex items-center gap-2 pl-5 pr-3 py-2.5 rounded-l-xl text-sm font-semibold transition-all',
                  canGenerate
                    ? 'bg-gradient-to-r from-purple-600 to-pink-600 text-white shadow-lg shadow-purple-500/20 hover:shadow-purple-500/30 hover:brightness-110 active:scale-[0.98]'
                    : 'bg-white/[0.06] text-white/25 cursor-not-allowed',
                ].join(' ')}
              >
                {gen.loading ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    Generating...
                  </>
                ) : (
                  <>
                    <Sparkles size={16} />
                    Generate ({count})
                  </>
                )}
              </button>

              {/* Count dropdown toggle */}
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
                  aria-label="Select generation count"
                >
                  <ChevronDown size={14} />
                </button>

                {/* Count dropdown */}
                {showCountMenu && (
                  <>
                    <div className="fixed inset-0 z-30" onClick={() => setShowCountMenu(false)} />
                    <div className="absolute right-0 top-full mt-1 bg-[#1a1a1a] border border-white/10 rounded-lg shadow-2xl z-40 overflow-hidden min-w-[80px]">
                      {[1, 4, 8].map((n) => (
                        <button
                          key={n}
                          onClick={() => { setCount(n); setShowCountMenu(false) }}
                          className={[
                            'w-full px-4 py-2 text-left text-sm transition-colors',
                            count === n
                              ? 'bg-purple-500/15 text-purple-300 font-medium'
                              : 'text-white/60 hover:bg-white/5 hover:text-white/80',
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

            {gen.loading && (
              <button
                onClick={gen.cancel}
                className="flex items-center gap-1.5 px-3.5 py-2.5 rounded-xl text-sm font-medium border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-all"
                aria-label="Cancel generation"
              >
                <X size={14} />
                Cancel
              </button>
            )}

            {canGenerate && !gen.loading && (
              <span className="text-[10px] text-white/20 hidden sm:inline ml-1">
                Enter to generate
              </span>
            )}
          </div>

          {/* ── Loading skeleton ──────────────────────────────── */}
          {gen.loading && (
            <div className="max-w-2xl mx-auto mb-8">
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {Array.from({ length: count }).map((_, i) => (
                  <div key={i} className="rounded-xl overflow-hidden border border-white/[0.06] bg-white/[0.02]">
                    <div className="aspect-square bg-white/[0.03] animate-pulse flex items-center justify-center">
                      <Loader2 size={20} className="animate-spin text-white/10" />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Latest Results (flash in) ────────────────────── */}
          {gen.result?.results?.length ? (
            <div className="max-w-2xl mx-auto mb-8 animate-fadeSlideIn">
              <div className="text-xs text-white/30 mb-3 font-medium uppercase tracking-wider text-center">
                Latest Results
              </div>
              <div className={`grid gap-3 ${gen.result.results.length === 1 ? 'grid-cols-1 max-w-xs mx-auto' : 'grid-cols-2 sm:grid-cols-4'}`}>
                {gen.result.results.map((item, i) => {
                  const imgUrl = item.url?.startsWith('http')
                    ? item.url
                    : `${(backendUrl || '').replace(/\/+$/, '')}${item.url}`
                  return (
                    <div
                      key={i}
                      className="group relative rounded-xl overflow-hidden border border-white/[0.06] bg-white/[0.02] hover:border-white/15 transition-all cursor-pointer"
                      onClick={() => onOpenLightbox?.(imgUrl)}
                    >
                      <div className="aspect-square bg-white/[0.03] relative">
                        <img
                          src={imgUrl}
                          alt={`Generated avatar ${i + 1}`}
                          className="w-full h-full object-cover"
                          loading="lazy"
                        />
                        <div className="absolute inset-0 bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center gap-2">
                          {onSendToEdit && (
                            <button
                              onClick={(e) => { e.stopPropagation(); onSendToEdit(imgUrl) }}
                              className="p-2 bg-purple-500/30 backdrop-blur-md rounded-lg text-purple-200 hover:bg-purple-500/50 transition-colors"
                              title="Open in Edit Studio"
                            >
                              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>
                            </button>
                          )}
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              const a = document.createElement('a')
                              a.href = imgUrl
                              a.download = `avatar_${item.seed ?? i}.png`
                              a.click()
                            }}
                            className="p-2 bg-white/10 backdrop-blur-md rounded-lg text-white/80 hover:bg-white/20 transition-colors"
                            title="Download"
                          >
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                          </button>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ) : null}

          {/* ── Empty State ───────────────────────────────────── */}
          {!gen.result && !gen.loading && gallery.items.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-white/15">
              <ImageIcon size={48} strokeWidth={1} />
              <p className="mt-4 text-sm text-white/30">
                Your avatars will appear here
              </p>
              <p className="mt-1 text-[11px] text-white/15">
                Upload a photo or click Generate to get started
              </p>
            </div>
          )}

          {/* ── Divider ───────────────────────────────────────── */}
          {gallery.items.length > 0 && (
            <div className="border-t border-white/[0.06] pt-6">
              <AvatarGallery
                items={gallery.items}
                backendUrl={backendUrl}
                onDelete={gallery.removeItem}
                onClearAll={gallery.clearAll}
                onOpenLightbox={onOpenLightbox}
                onSendToEdit={onSendToEdit}
                onSaveAsPersonaAvatar={onSaveAsPersonaAvatar}
                onGenerateOutfits={(item) => {
                  setViewerItem(item)
                  setViewMode('viewer')
                }}
              />
            </div>
          )}

          {/* ── Outfit Panel (if opened from gallery) ──────── */}
          {outfitAnchor && (
            <OutfitPanel
              anchor={outfitAnchor}
              backendUrl={backendUrl}
              apiKey={apiKey}
              nsfwMode={(() => { try { return localStorage.getItem('homepilot_nsfw_mode') === 'true' } catch { return false } })()}
              checkpointOverride={resolveCheckpoint(avatarSettings, globalModelImages)}
              onResults={(results, scenarioTag) => gallery.addBatch(results, mode, outfitAnchor.prompt, outfitAnchor.url, scenarioTag)}
              onSendToEdit={onSendToEdit}
              onOpenLightbox={onOpenLightbox}
              onClose={() => setOutfitAnchor(null)}
            />
          )}
        </div>
      </div>

      {/* ═══════════════════════ TOAST NOTIFICATIONS ═══════════════════════ */}
      {toast && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 animate-toastSlideUp">
          <div className={[
            'flex items-center gap-2.5 px-5 py-3 rounded-xl shadow-2xl backdrop-blur-md border text-sm font-medium',
            toast.type === 'error'
              ? 'bg-red-500/15 border-red-500/20 text-red-300'
              : toast.type === 'success'
                ? 'bg-green-500/15 border-green-500/20 text-green-300'
                : 'bg-white/10 border-white/10 text-white/70',
          ].join(' ')}>
            {toast.type === 'error' && <AlertTriangle size={16} />}
            {toast.type === 'success' && <Sparkles size={16} />}
            <span>{toast.message}</span>
            <button
              onClick={() => setToast(null)}
              className="ml-2 text-white/30 hover:text-white/60 transition-colors"
            >
              <X size={14} />
            </button>
          </div>
        </div>
      )}

      <style>{`
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateY(12px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .animate-fadeSlideIn {
          animation: fadeSlideIn 0.35s ease-out;
        }
        @keyframes toastSlideUp {
          from { opacity: 0; transform: translate(-50%, 16px); }
          to { opacity: 1; transform: translate(-50%, 0); }
        }
        .animate-toastSlideUp {
          animation: toastSlideUp 0.25s ease-out;
        }
      `}</style>
    </div>
  )
}
