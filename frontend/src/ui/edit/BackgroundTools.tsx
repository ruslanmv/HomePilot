/**
 * BackgroundTools - Background manipulation buttons for the Edit page.
 *
 * Provides quick access to background operations:
 * - Remove BG: Make background transparent
 * - Change BG: Replace with AI-generated background
 * - Blur BG: Portrait mode / bokeh effect
 *
 * This component is additive and can be dropped into any page.
 */

import React, { useState } from 'react'
import { Loader2, Scissors, Palette, CircleDot, X } from 'lucide-react'
import { processBackground, BackgroundAction, BACKGROUND_ACTIONS } from '../enhance/backgroundApi'

export interface BackgroundToolsProps {
  /** Backend URL (e.g., http://localhost:8000) */
  backendUrl: string
  /** Optional API key for authentication */
  apiKey?: string
  /** Current image URL to process */
  imageUrl: string | null
  /** Callback when operation completes with new image URL */
  onResult: (resultUrl: string, action: BackgroundAction, hasAlpha: boolean) => void
  /** Callback for errors */
  onError: (error: string) => void
  /** Optional: Disable all buttons */
  disabled?: boolean
  /** Optional: Compact mode for smaller spaces */
  compact?: boolean
}

/**
 * BackgroundTools component for background manipulation.
 *
 * @example
 * ```tsx
 * <BackgroundTools
 *   backendUrl="http://localhost:8000"
 *   imageUrl={currentImage}
 *   onResult={(url, action, hasAlpha) => {
 *     console.log(`Background ${action} completed: ${url}, hasAlpha: ${hasAlpha}`)
 *     setCurrentImage(url)
 *   }}
 *   onError={(err) => setError(err)}
 * />
 * ```
 */
export function BackgroundTools({
  backendUrl,
  apiKey,
  imageUrl,
  onResult,
  onError,
  disabled = false,
  compact = false,
}: BackgroundToolsProps) {
  const [loading, setLoading] = useState<BackgroundAction | null>(null)
  const [showPromptInput, setShowPromptInput] = useState(false)
  const [bgPrompt, setBgPrompt] = useState('')
  const [blurStrength, setBlurStrength] = useState(15)

  const handleAction = async (action: BackgroundAction, prompt?: string) => {
    if (!imageUrl || loading || disabled) return

    // For replace action, we need a prompt
    if (action === 'replace' && !prompt) {
      setShowPromptInput(true)
      return
    }

    setLoading(action)
    setShowPromptInput(false)

    try {
      const result = await processBackground({
        backendUrl,
        apiKey,
        imageUrl,
        action,
        prompt,
        blurStrength: action === 'blur' ? blurStrength : undefined,
      })

      const resultUrl = result?.media?.images?.[0]
      if (resultUrl) {
        onResult(resultUrl, action, result.has_alpha ?? false)
      } else {
        onError('Operation completed but no image was returned.')
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Background operation failed')
    } finally {
      setLoading(null)
      setBgPrompt('')
    }
  }

  const getIcon = (action: BackgroundAction) => {
    switch (action) {
      case 'remove':
        return <Scissors size={compact ? 14 : 16} />
      case 'replace':
        return <Palette size={compact ? 14 : 16} />
      case 'blur':
        return <CircleDot size={compact ? 14 : 16} />
    }
  }

  const isDisabled = !imageUrl || disabled

  if (compact) {
    return (
      <div className="flex gap-1.5">
        {BACKGROUND_ACTIONS.map((actionInfo) => (
          <button
            key={actionInfo.id}
            onClick={() => handleAction(actionInfo.id)}
            disabled={isDisabled || loading !== null}
            title={`${actionInfo.label}: ${actionInfo.description}`}
            className={`
              p-2 rounded-lg transition-all
              ${loading === actionInfo.id
                ? 'bg-blue-500/60 text-white animate-pulse'
                : isDisabled || loading !== null
                  ? 'bg-white/5 text-white/30 cursor-not-allowed'
                  : 'bg-white/10 text-white/70 hover:bg-blue-500/30 hover:text-blue-300'
              }
            `}
          >
            {loading === actionInfo.id ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              getIcon(actionInfo.id)
            )}
          </button>
        ))}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="text-xs uppercase tracking-wider text-white/40 font-semibold flex items-center gap-2">
        <Scissors size={14} />
        Background
      </div>

      <div className="grid grid-cols-1 gap-2">
        {BACKGROUND_ACTIONS.map((actionInfo) => (
          <button
            key={actionInfo.id}
            onClick={() => handleAction(actionInfo.id)}
            disabled={isDisabled || loading !== null}
            className={`
              flex items-center gap-3 p-3 rounded-xl border transition-all text-left
              ${loading === actionInfo.id
                ? 'bg-blue-500/20 border-blue-500/40 text-blue-300'
                : isDisabled || loading !== null
                  ? 'bg-white/5 border-white/5 text-white/30 cursor-not-allowed'
                  : 'bg-white/5 border-white/10 text-white/80 hover:bg-blue-500/10 hover:border-blue-500/30 hover:text-blue-200'
              }
            `}
          >
            <div className={`
              w-9 h-9 rounded-lg flex items-center justify-center
              ${loading === actionInfo.id
                ? 'bg-blue-500/30'
                : 'bg-white/10'
              }
            `}>
              {loading === actionInfo.id ? (
                <Loader2 size={18} className="animate-spin text-blue-400" />
              ) : (
                getIcon(actionInfo.id)
              )}
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium">{actionInfo.label}</div>
              <div className="text-[10px] text-white/40 truncate">
                {actionInfo.description}
              </div>
            </div>
          </button>
        ))}
      </div>

      {/* Blur Strength Slider */}
      <div className="space-y-2">
        <div className="flex justify-between text-xs">
          <span className="uppercase tracking-wider text-white/40 font-semibold">Blur Strength</span>
          <span className="text-white/60">{blurStrength}</span>
        </div>
        <input
          type="range"
          min={5}
          max={50}
          value={blurStrength}
          onChange={(e) => setBlurStrength(Number(e.target.value))}
          className="w-full h-1.5 bg-white/10 rounded-full appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:bg-blue-400 [&::-webkit-slider-thumb]:rounded-full"
        />
      </div>

      {/* Prompt Input for Replace Action */}
      {showPromptInput && (
        <div className="space-y-2 p-3 rounded-xl bg-blue-500/10 border border-blue-500/30 animate-in fade-in slide-in-from-top-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-blue-300 font-medium">Describe new background</span>
            <button
              onClick={() => {
                setShowPromptInput(false)
                setBgPrompt('')
              }}
              className="text-white/40 hover:text-white"
            >
              <X size={14} />
            </button>
          </div>
          <input
            type="text"
            value={bgPrompt}
            onChange={(e) => setBgPrompt(e.target.value)}
            placeholder="e.g., sunset beach, city skyline, forest..."
            className="w-full rounded-lg bg-black/40 border border-white/10 px-3 py-2 text-sm text-white placeholder:text-white/30 focus:border-blue-500/50 focus:outline-none"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter' && bgPrompt.trim()) {
                handleAction('replace', bgPrompt.trim())
              }
              if (e.key === 'Escape') {
                setShowPromptInput(false)
                setBgPrompt('')
              }
            }}
          />
          <button
            onClick={() => handleAction('replace', bgPrompt.trim())}
            disabled={!bgPrompt.trim() || loading !== null}
            className="w-full py-2 px-4 rounded-lg bg-blue-500 text-white hover:bg-blue-400 disabled:bg-white/10 disabled:text-white/30 disabled:cursor-not-allowed transition-all text-sm font-medium"
          >
            {loading === 'replace' ? (
              <span className="flex items-center justify-center gap-2">
                <Loader2 size={14} className="animate-spin" />
                Generating...
              </span>
            ) : (
              'Generate Background'
            )}
          </button>
        </div>
      )}

      <p className="text-[10px] text-white/30 leading-relaxed">
        Remove, replace, or blur the background. Results are added to your version history.
      </p>
    </div>
  )
}

export default BackgroundTools
