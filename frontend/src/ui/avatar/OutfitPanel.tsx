/**
 * OutfitPanel — collapsible section in AvatarStudio for generating outfit variations.
 *
 * Additive component — rendered below the results grid when user selects
 * "Outfit Variations" on a gallery item.
 *
 * Features:
 *   - Reference avatar thumbnail (locked face anchor)
 *   - Outfit preset pills (from OUTFIT_PRESETS)
 *   - Custom outfit prompt input
 *   - Generate button + count selector
 *   - Results grid (reuses AvatarCard pattern)
 */

import React, { useState, useCallback } from 'react'
import {
  Shirt,
  X,
  Wand2,
  Loader2,
  AlertTriangle,
  Download,
  PenLine,
  Maximize2,
  Copy,
  Check,
} from 'lucide-react'
import type { GalleryItem, OutfitScenarioTag, FramingType } from './galleryTypes'
import { SCENARIO_TAG_META, FRAMING_OPTIONS } from './galleryTypes'
import type { AvatarResult } from './types'
import { OUTFIT_PRESETS } from '../personaTypes'
import { useOutfitGeneration } from './useOutfitGeneration'
import { resolveFileUrl } from '../resolveFileUrl'
import { AvatarGeneratingLoader } from './AvatarGeneratingLoader'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface OutfitPanelProps {
  /** The avatar whose face we're keeping — the identity anchor */
  anchor: GalleryItem
  backendUrl: string
  apiKey?: string
  nsfwMode: boolean
  /** Checkpoint override from Avatar Settings (passed to outfit generation) */
  checkpointOverride?: string
  /** Called with generated results so the parent can save to gallery */
  onResults?: (results: AvatarResult[], scenarioTag?: OutfitScenarioTag) => void
  onSendToEdit?: (imageUrl: string) => void
  onOpenLightbox?: (imageUrl: string) => void
  onClose: () => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveUrl(url: string, backendUrl: string): string {
  return resolveFileUrl(url, backendUrl)
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OutfitPanel({
  anchor,
  backendUrl,
  apiKey,
  nsfwMode,
  checkpointOverride,
  onResults,
  onSendToEdit,
  onOpenLightbox,
  onClose,
}: OutfitPanelProps) {
  const outfit = useOutfitGeneration(backendUrl, apiKey)

  const [selectedPreset, setSelectedPreset] = useState<string | null>('corporate')
  const [customPrompt, setCustomPrompt] = useState('')
  const [count, setCount] = useState(4)
  const [copiedSeed, setCopiedSeed] = useState<number | null>(null)

  const anchorUrl = resolveUrl(anchor.url, backendUrl)

  // Filter presets by NSFW mode
  const presets = OUTFIT_PRESETS.filter(
    (p) => p.category === 'sfw' || nsfwMode,
  )

  // The effective outfit prompt
  const effectivePrompt = (() => {
    if (customPrompt.trim()) return customPrompt.trim()
    if (selectedPreset) {
      const preset = presets.find((p) => p.id === selectedPreset)
      return preset?.prompt || ''
    }
    return ''
  })()

  const canGenerate = !outfit.loading && effectivePrompt.length > 0

  const handleGenerate = useCallback(async () => {
    if (!canGenerate) return

    // Determine the scenario tag for this generation
    const scenarioTag: OutfitScenarioTag = selectedPreset
      ? (selectedPreset as OutfitScenarioTag)
      : 'custom'

    // --- Build positive prompt with anchors ---
    const preset = selectedPreset
      ? presets.find((p) => p.id === selectedPreset)
      : null
    let finalOutfitPrompt = effectivePrompt
    if (preset?.positiveAnchors) {
      finalOutfitPrompt = `${effectivePrompt}, ${preset.positiveAnchors}`
    }

    // --- Build combined negative: framing negatives + style negatives ---
    const negParts: string[] = []
    // 1. Framing negatives (based on the anchor's framing type)
    const framingType: FramingType = anchor.framingType || 'half_body'
    const framingOpt = FRAMING_OPTIONS.find((f) => f.id === framingType)
    if (framingOpt?.negativeHints) {
      negParts.push(framingOpt.negativeHints)
    }
    // 2. Style negatives (from the selected preset)
    if (preset?.negativeHints) {
      negParts.push(preset.negativeHints)
    }
    const negativePrompt = negParts.length > 0 ? negParts.join(', ') : undefined

    try {
      const result = await outfit.generate({
        referenceImageUrl: anchor.url,
        outfitPrompt: finalOutfitPrompt,
        characterPrompt: anchor.prompt,
        negativePrompt,
        count,
        checkpointOverride,
      })
      if (result?.results?.length) {
        onResults?.(result.results, scenarioTag)
      }
    } catch {
      // Error is already captured in hook state
    }
  }, [canGenerate, outfit, anchor, effectivePrompt, count, onResults, selectedPreset, presets, checkpointOverride])

  const handleCopySeed = useCallback((seed: number) => {
    navigator.clipboard.writeText(String(seed)).catch(() => {})
    setCopiedSeed(seed)
    setTimeout(() => setCopiedSeed(null), 1500)
  }, [])

  return (
    <div className="mt-6 pt-5 border-t border-cyan-500/20 animate-fadeIn">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-500 flex items-center justify-center">
            <Shirt size={16} className="text-white" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white">Outfit Variations</h3>
            <p className="text-[10px] text-white/40 mt-0.5">
              Same face, different wardrobe
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded-lg text-white/30 hover:text-white/60 hover:bg-white/5 transition-colors"
        >
          <X size={16} />
        </button>
      </div>

      {/* Anchor preview */}
      <div className="flex items-center gap-3 mb-4 px-3 py-2.5 rounded-xl bg-white/[0.03] border border-white/8">
        <div className="w-14 h-14 rounded-lg overflow-hidden border border-white/10 flex-shrink-0">
          <img
            src={anchorUrl}
            alt="Identity anchor"
            className="w-full h-full object-cover"
          />
        </div>
        <div className="text-xs text-white/40">
          <div className="font-medium text-white/60 mb-0.5">Identity Anchor</div>
          <div>This face will be preserved across all outfit variations</div>
        </div>
      </div>

      {/* Outfit presets — grouped by category */}
      <div className="mb-3 space-y-3">
        <div className="text-xs text-white/40 mb-1 font-medium uppercase tracking-wider">
          Outfit Preset
        </div>

        {/* SFW: Standard */}
        {(() => {
          const sfwPresets = presets.filter((p) => p.category === 'sfw' && p.id !== 'custom')
          if (!sfwPresets.length) return null
          return (
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="text-[9px] font-bold text-white/25 uppercase tracking-wider">Standard</span>
                <div className="flex-1 h-px bg-white/[0.06]" />
              </div>
              <div className="flex flex-wrap gap-1.5">
                {sfwPresets.map((p) => {
                  const tagMeta = SCENARIO_TAG_META.find((t) => t.id === p.id)
                  return (
                    <button
                      key={p.id}
                      onClick={() => {
                        setSelectedPreset(selectedPreset === p.id ? null : p.id)
                        if (selectedPreset !== p.id) setCustomPrompt('')
                      }}
                      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                        selectedPreset === p.id
                          ? 'border-cyan-500/40 bg-cyan-500/15 text-cyan-300'
                          : 'border-white/8 bg-white/[0.03] text-white/50 hover:bg-white/5 hover:text-white/70'
                      }`}
                      title={p.prompt}
                    >
                      {tagMeta && <span className="text-sm leading-none">{tagMeta.icon}</span>}
                      {p.label}
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })()}

        {/* NSFW: Romance & Roleplay */}
        {(() => {
          const romancePresets = presets.filter((p) => p.category === 'nsfw' && p.group === 'romance')
          if (!romancePresets.length) return null
          return (
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="text-[9px] font-bold text-rose-400/50 uppercase tracking-wider">Romance & Roleplay</span>
                <div className="flex-1 h-px bg-rose-500/10" />
              </div>
              <div className="flex flex-wrap gap-1.5">
                {romancePresets.map((p) => {
                  const tagMeta = SCENARIO_TAG_META.find((t) => t.id === p.id)
                  return (
                    <button
                      key={p.id}
                      onClick={() => {
                        setSelectedPreset(selectedPreset === p.id ? null : p.id)
                        if (selectedPreset !== p.id) setCustomPrompt('')
                      }}
                      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                        selectedPreset === p.id
                          ? 'border-rose-500/40 bg-rose-500/15 text-rose-300'
                          : 'border-white/8 bg-white/[0.03] text-white/50 hover:bg-white/5 hover:text-rose-300/70'
                      }`}
                      title={p.prompt}
                    >
                      {tagMeta && <span className="text-sm leading-none">{tagMeta.icon}</span>}
                      {p.label}
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })()}

        {/* NSFW: 18+ Explicit */}
        {(() => {
          const explicitPresets = presets.filter((p) => p.category === 'nsfw' && p.group === '18+')
          if (!explicitPresets.length) return null
          return (
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="text-[9px] font-bold text-red-400/50 uppercase tracking-wider">18+ Explicit</span>
                <div className="flex-1 h-px bg-red-500/10" />
              </div>
              <div className="flex flex-wrap gap-1.5">
                {explicitPresets.map((p) => {
                  const tagMeta = SCENARIO_TAG_META.find((t) => t.id === p.id)
                  return (
                    <button
                      key={p.id}
                      onClick={() => {
                        setSelectedPreset(selectedPreset === p.id ? null : p.id)
                        if (selectedPreset !== p.id) setCustomPrompt('')
                      }}
                      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all ${
                        selectedPreset === p.id
                          ? 'border-red-500/40 bg-red-500/15 text-red-300'
                          : 'border-white/8 bg-white/[0.03] text-white/50 hover:bg-white/5 hover:text-red-300/70'
                      }`}
                      title={p.prompt}
                    >
                      {tagMeta && <span className="text-sm leading-none">{tagMeta.icon}</span>}
                      {p.label}
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })()}

        {/* Custom option — deselects preset and focuses prompt input */}
        <button
          onClick={() => {
            setSelectedPreset(null)
            setCustomPrompt('')
          }}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all ${
            !selectedPreset && !customPrompt.trim()
              ? 'border-cyan-500/40 bg-cyan-500/15 text-cyan-300'
              : 'border-white/8 bg-white/[0.03] text-white/50 hover:bg-white/5 hover:text-white/70'
          }`}
        >
          <span className="text-sm leading-none">{'\u270F\uFE0F'}</span>
          Custom
        </button>
      </div>

      {/* Custom prompt */}
      <div className="mb-4">
        <div className="text-xs text-white/40 mb-1.5 font-medium uppercase tracking-wider">
          Custom Outfit Prompt
        </div>
        <input
          value={customPrompt}
          onChange={(e) => {
            setCustomPrompt(e.target.value)
            if (e.target.value.trim()) setSelectedPreset(null)
          }}
          placeholder="e.g. red cocktail dress, rooftop bar, golden hour"
          className="w-full px-3 py-2.5 rounded-xl bg-white/5 border border-white/10 text-white text-sm placeholder:text-white/25 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/20 transition-all"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && canGenerate) {
              e.preventDefault()
              handleGenerate()
            }
          }}
        />
      </div>

      {/* Generate controls */}
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={handleGenerate}
          disabled={!canGenerate}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all ${
            canGenerate
              ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white shadow-lg shadow-cyan-500/20 hover:shadow-cyan-500/30 hover:scale-[1.02] active:scale-[0.98]'
              : 'bg-white/5 text-white/25 cursor-not-allowed'
          }`}
        >
          {outfit.loading ? (
            <>
              <Loader2 size={16} className="animate-spin" />
              Generating...
            </>
          ) : (
            <>
              <Wand2 size={16} />
              Generate {count} Outfits
            </>
          )}
        </button>

        {/* Count selector */}
        <div className="flex items-center gap-1">
          {[1, 4, 8].map((n) => (
            <button
              key={n}
              onClick={() => setCount(n)}
              className={`px-2.5 py-1 rounded-lg text-xs font-medium transition-all border ${
                count === n
                  ? 'border-white/20 bg-white/10 text-white'
                  : 'border-white/5 bg-white/[0.02] text-white/30 hover:text-white/60'
              }`}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {/* Error */}
      {outfit.error && (
        <div className="flex items-center gap-2 px-3 py-2 mb-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-xs">
          <AlertTriangle size={14} />
          <span>{outfit.error}</span>
        </div>
      )}

      {/* Warnings */}
      {outfit.warnings.length > 0 && (
        <div className="flex items-start gap-2 px-3 py-2 mb-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <div>
            {outfit.warnings.map((w, i) => (
              <div key={i}>{w}</div>
            ))}
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {outfit.loading && outfit.results.length === 0 && (
        <AvatarGeneratingLoader
          label="Generating outfits…"
          hint="Creating outfit variations for your character"
          count={count}
        />
      )}

      {/* Results grid */}
      {outfit.results.length > 0 && (
        <div>
          <div className="text-xs text-white/40 mb-2 font-medium uppercase tracking-wider">
            Outfit Results
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
            {outfit.results.map((item, i) => {
              const imgUrl = resolveUrl(item.url, backendUrl)
              return (
                <div
                  key={i}
                  className="group relative rounded-xl overflow-hidden border border-white/8 bg-white/[0.02] hover:border-white/15 transition-all"
                >
                  <div
                    className="aspect-[2/3] bg-white/[0.03] cursor-pointer relative"
                    onClick={() => onOpenLightbox?.(imgUrl)}
                  >
                    <img
                      src={imgUrl}
                      alt={`Outfit variation ${i + 1}`}
                      className="w-full h-full object-cover"
                      loading="lazy"
                    />
                    {/* Hover overlay */}
                    <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity duration-200 flex items-center justify-center gap-2">
                      {onOpenLightbox && (
                        <button
                          onClick={(e) => { e.stopPropagation(); onOpenLightbox(imgUrl) }}
                          className="p-2 bg-white/10 backdrop-blur-md rounded-lg text-white hover:bg-white/20 transition-colors"
                          title="View full size"
                        >
                          <Maximize2 size={16} />
                        </button>
                      )}
                      {onSendToEdit && (
                        <button
                          onClick={(e) => { e.stopPropagation(); onSendToEdit(imgUrl) }}
                          className="p-2 bg-purple-500/30 backdrop-blur-md rounded-lg text-purple-200 hover:bg-purple-500/50 transition-colors"
                          title="Open in Edit"
                        >
                          <PenLine size={16} />
                        </button>
                      )}
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          const a = document.createElement('a')
                          a.href = imgUrl
                          a.download = `outfit_${item.seed ?? i}.png`
                          a.click()
                        }}
                        className="p-2 bg-white/10 backdrop-blur-md rounded-lg text-white hover:bg-white/20 transition-colors"
                        title="Download"
                      >
                        <Download size={16} />
                      </button>
                    </div>
                  </div>

                  {/* Footer */}
                  <div className="px-2.5 py-2">
                    <button
                      onClick={() => item.seed !== undefined && handleCopySeed(item.seed!)}
                      className="text-[11px] text-white/40 font-mono hover:text-white/70 transition-colors cursor-pointer"
                    >
                      {copiedSeed === item.seed ? (
                        <span className="flex items-center gap-1 text-green-400">
                          <Check size={10} /> copied
                        </span>
                      ) : (
                        <span className="flex items-center gap-1">
                          seed {item.seed ?? '---'}
                          <Copy size={9} className="opacity-0 group-hover:opacity-100 transition-opacity" />
                        </span>
                      )}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
