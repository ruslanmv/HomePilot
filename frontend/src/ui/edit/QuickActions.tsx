/**
 * QuickActions - One-click enhancement buttons for the Edit page.
 *
 * Provides quick access to AI enhancement features:
 * - Enhance (RealESRGAN): Improve photo quality
 * - Restore (SwinIR): Remove artifacts and compression
 * - Fix Faces (GFPGAN): Restore and enhance faces
 *
 * This component is additive and can be dropped into any page.
 */

import React, { useState } from 'react'
import { Loader2, Sparkles, Wand2, User } from 'lucide-react'
import { enhanceImage, EnhanceMode, ENHANCE_MODES } from '../enhance/enhanceApi'

export interface QuickActionsProps {
  /** Backend URL (e.g., http://localhost:8000) */
  backendUrl: string
  /** Optional API key for authentication */
  apiKey?: string
  /** Current image URL to enhance */
  imageUrl: string | null
  /** Callback when enhancement completes with new image URL */
  onResult: (resultUrl: string, mode: EnhanceMode) => void
  /** Callback for errors */
  onError: (error: string) => void
  /** Optional: Disable all buttons */
  disabled?: boolean
  /** Optional: Compact mode for smaller spaces */
  compact?: boolean
}

/**
 * QuickActions component for one-click image enhancement.
 *
 * @example
 * ```tsx
 * <QuickActions
 *   backendUrl="http://localhost:8000"
 *   imageUrl={currentImage}
 *   onResult={(url, mode) => {
 *     console.log(`Enhanced with ${mode}: ${url}`)
 *     setCurrentImage(url)
 *   }}
 *   onError={(err) => setError(err)}
 * />
 * ```
 */
export function QuickActions({
  backendUrl,
  apiKey,
  imageUrl,
  onResult,
  onError,
  disabled = false,
  compact = false,
}: QuickActionsProps) {
  const [loading, setLoading] = useState<EnhanceMode | null>(null)

  const handleEnhance = async (mode: EnhanceMode) => {
    if (!imageUrl || loading || disabled) return

    setLoading(mode)

    try {
      const result = await enhanceImage({
        backendUrl,
        apiKey,
        imageUrl,
        mode,
        scale: mode === 'faces' ? 1 : 2, // Faces doesn't need upscaling
      })

      const enhancedUrl = result?.media?.images?.[0]
      if (enhancedUrl) {
        onResult(enhancedUrl, mode)
      } else {
        onError('Enhancement completed but no image was returned.')
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Enhancement failed')
    } finally {
      setLoading(null)
    }
  }

  const getIcon = (mode: EnhanceMode) => {
    switch (mode) {
      case 'photo':
        return <Sparkles size={compact ? 14 : 16} />
      case 'restore':
        return <Wand2 size={compact ? 14 : 16} />
      case 'faces':
        return <User size={compact ? 14 : 16} />
    }
  }

  const isDisabled = !imageUrl || disabled

  if (compact) {
    return (
      <div className="flex gap-1.5">
        {ENHANCE_MODES.map((modeInfo) => (
          <button
            key={modeInfo.id}
            onClick={() => handleEnhance(modeInfo.id)}
            disabled={isDisabled || loading !== null}
            title={`${modeInfo.label}: ${modeInfo.description}`}
            className={`
              p-2 rounded-lg transition-all
              ${loading === modeInfo.id
                ? 'bg-purple-500/60 text-white animate-pulse'
                : isDisabled || loading !== null
                  ? 'bg-white/5 text-white/30 cursor-not-allowed'
                  : 'bg-white/10 text-white/70 hover:bg-purple-500/30 hover:text-purple-300'
              }
            `}
          >
            {loading === modeInfo.id ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              getIcon(modeInfo.id)
            )}
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="text-xs uppercase tracking-wider text-white/40 font-semibold flex items-center gap-2">
        <Sparkles size={14} />
        Quick Enhance
      </div>

      <div className="grid grid-cols-1 gap-2">
        {ENHANCE_MODES.map((modeInfo) => (
          <button
            key={modeInfo.id}
            onClick={() => handleEnhance(modeInfo.id)}
            disabled={isDisabled || loading !== null}
            className={`
              flex items-center gap-3 p-3 rounded-xl border transition-all text-left
              ${loading === modeInfo.id
                ? 'bg-purple-500/20 border-purple-500/40 text-purple-300'
                : isDisabled || loading !== null
                  ? 'bg-white/5 border-white/5 text-white/30 cursor-not-allowed'
                  : 'bg-white/5 border-white/10 text-white/80 hover:bg-purple-500/10 hover:border-purple-500/30 hover:text-purple-200'
              }
            `}
          >
            <div className={`
              w-9 h-9 rounded-lg flex items-center justify-center
              ${loading === modeInfo.id
                ? 'bg-purple-500/30'
                : 'bg-white/10'
              }
            `}>
              {loading === modeInfo.id ? (
                <Loader2 size={18} className="animate-spin text-purple-400" />
              ) : (
                getIcon(modeInfo.id)
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium">{modeInfo.label}</div>
              <div className="text-[10px] text-white/40 truncate">
                {modeInfo.description}
              </div>
            </div>
          </button>
        ))}
      </div>

      <p className="text-[10px] text-white/30 leading-relaxed">
        One-click AI enhancement. Results are added to your version history.
      </p>
    </div>
  )
}

export default QuickActions
