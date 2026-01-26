/**
 * OutpaintTools - Canvas extension tools for the Edit page.
 *
 * Provides controls for extending images beyond their original boundaries:
 * - Direction selection (left, right, up, down, horizontal, vertical, all)
 * - Extension amount slider (64-1024 pixels)
 * - Optional prompt for guiding generated content
 *
 * This component is additive and can be dropped into any page.
 */

import React, { useState } from 'react'
import {
  Loader2,
  Expand,
  ArrowRight,
  ArrowLeft,
  ArrowUp,
  ArrowDown,
  MoveHorizontal,
  MoveVertical,
  Maximize,
} from 'lucide-react'
import { outpaintImage, ExtendDirection, EXTEND_DIRECTIONS } from '../enhance/outpaintApi'

export interface OutpaintToolsProps {
  /** Backend URL (e.g., http://localhost:8000) */
  backendUrl: string
  /** Optional API key for authentication */
  apiKey?: string
  /** Current image URL to extend */
  imageUrl: string | null
  /** Callback when extension completes with new image URL */
  onResult: (resultUrl: string, direction: ExtendDirection, newSize: [number, number]) => void
  /** Callback for errors */
  onError: (error: string) => void
  /** Optional: Disable all buttons */
  disabled?: boolean
}

/**
 * OutpaintTools component for canvas extension.
 *
 * @example
 * ```tsx
 * <OutpaintTools
 *   backendUrl="http://localhost:8000"
 *   imageUrl={currentImage}
 *   onResult={(url, direction, newSize) => {
 *     console.log(`Extended ${direction}: ${url}, new size: ${newSize}`)
 *     setCurrentImage(url)
 *   }}
 *   onError={(err) => setError(err)}
 * />
 * ```
 */
export function OutpaintTools({
  backendUrl,
  apiKey,
  imageUrl,
  onResult,
  onError,
  disabled = false,
}: OutpaintToolsProps) {
  const [loading, setLoading] = useState(false)
  const [selectedDirection, setSelectedDirection] = useState<ExtendDirection>('right')
  const [extendPixels, setExtendPixels] = useState(256)
  const [prompt, setPrompt] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)

  const handleExtend = async () => {
    if (!imageUrl || loading || disabled) return

    setLoading(true)

    try {
      const result = await outpaintImage({
        backendUrl,
        apiKey,
        imageUrl,
        direction: selectedDirection,
        extendPixels,
        prompt: prompt.trim() || undefined,
      })

      const resultUrl = result?.media?.images?.[0]
      if (resultUrl) {
        const newSize = result.new_size ?? [0, 0]
        onResult(resultUrl, selectedDirection, newSize as [number, number])
        setPrompt('') // Clear prompt after success
      } else {
        onError('Outpaint completed but no image was returned.')
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Outpaint failed')
    } finally {
      setLoading(false)
    }
  }

  const getDirectionIcon = (direction: ExtendDirection) => {
    switch (direction) {
      case 'right':
        return <ArrowRight size={14} />
      case 'left':
        return <ArrowLeft size={14} />
      case 'up':
        return <ArrowUp size={14} />
      case 'down':
        return <ArrowDown size={14} />
      case 'horizontal':
        return <MoveHorizontal size={14} />
      case 'vertical':
        return <MoveVertical size={14} />
      case 'all':
        return <Maximize size={14} />
    }
  }

  const isDisabled = !imageUrl || disabled

  return (
    <div className="space-y-3">
      <div className="text-xs uppercase tracking-wider text-white/40 font-semibold flex items-center gap-2">
        <Expand size={14} />
        Extend / Outpaint
      </div>

      {/* Direction Grid */}
      <div className="grid grid-cols-4 gap-1.5">
        {EXTEND_DIRECTIONS.map((dir) => (
          <button
            key={dir.id}
            onClick={() => setSelectedDirection(dir.id)}
            disabled={isDisabled}
            title={dir.description}
            className={`
              p-2 rounded-lg transition-all text-center
              ${selectedDirection === dir.id
                ? 'bg-green-500/30 border-green-500/50 text-green-300 border'
                : isDisabled
                  ? 'bg-white/5 text-white/30 cursor-not-allowed border border-transparent'
                  : 'bg-white/5 text-white/60 hover:bg-green-500/20 hover:text-green-300 border border-transparent hover:border-green-500/30'
              }
            `}
          >
            <div className="flex flex-col items-center gap-1">
              {getDirectionIcon(dir.id)}
              <span className="text-[9px] font-medium">{dir.label}</span>
            </div>
          </button>
        ))}
      </div>

      {/* Extend Amount Slider */}
      <div className="space-y-2">
        <div className="flex justify-between text-xs">
          <span className="uppercase tracking-wider text-white/40 font-semibold">
            Extend Amount
          </span>
          <span className="text-white/60">{extendPixels}px</span>
        </div>
        <input
          type="range"
          min={64}
          max={1024}
          step={64}
          value={extendPixels}
          onChange={(e) => setExtendPixels(Number(e.target.value))}
          disabled={isDisabled}
          className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer disabled:opacity-50 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-green-400 [&::-webkit-slider-thumb]:rounded-full"
        />
        <div className="flex justify-between text-[9px] text-white/30">
          <span>64px</span>
          <span>512px</span>
          <span>1024px</span>
        </div>
      </div>

      {/* Advanced Options Toggle */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        disabled={isDisabled}
        className="w-full text-left text-xs text-white/50 hover:text-white/70 disabled:opacity-50 transition-colors"
      >
        {showAdvanced ? '▼' : '▶'} Advanced Options
      </button>

      {/* Advanced Options */}
      {showAdvanced && (
        <div className="space-y-2 p-3 rounded-xl bg-white/5 border border-white/10 animate-in fade-in slide-in-from-top-2">
          <label className="text-xs text-white/50">
            Prompt (optional)
          </label>
          <input
            type="text"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g., continue the landscape, add mountains..."
            disabled={isDisabled}
            className="w-full rounded-lg bg-black/40 border border-white/10 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-green-500/50 focus:outline-none disabled:opacity-50"
          />
          <p className="text-[9px] text-white/30">
            Guide what should appear in the extended area
          </p>
        </div>
      )}

      {/* Extend Button */}
      <button
        onClick={handleExtend}
        disabled={isDisabled || loading}
        className={`
          w-full flex items-center justify-center gap-2 p-3 rounded-xl font-medium text-sm transition-all
          ${loading
            ? 'bg-green-500/30 text-green-300 border border-green-500/40'
            : isDisabled
              ? 'bg-white/5 text-white/30 cursor-not-allowed border border-transparent'
              : 'bg-green-500/20 text-green-300 hover:bg-green-500/30 border border-green-500/30 hover:border-green-500/50'
          }
        `}
      >
        {loading ? (
          <>
            <Loader2 size={16} className="animate-spin" />
            Extending...
          </>
        ) : (
          <>
            <Expand size={16} />
            Extend {selectedDirection === 'all' ? 'All Sides' : selectedDirection.charAt(0).toUpperCase() + selectedDirection.slice(1)}
          </>
        )}
      </button>

      <p className="text-[10px] text-white/30 leading-relaxed">
        Extend the image canvas and AI will generate seamless content beyond the borders.
        Results are added to your version history.
      </p>
    </div>
  )
}

export default OutpaintTools
