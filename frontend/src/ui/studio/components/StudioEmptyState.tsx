import React from 'react'
import { Film, Plus, Loader2, Sparkles } from 'lucide-react'

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

type StudioEmptyStateProps = {
  title?: string
  description?: string
  isGenerating?: boolean
  generatingLabel?: string
  onGenerateFirstScene?: () => void
  buttonLabel?: string
  className?: string
}

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

/**
 * Empty state component for Story Mode Studio when there are no scenes.
 * Styled like Imagine's empty gallery state.
 */
export function StudioEmptyState({
  title = 'No scenes yet',
  description = 'Generate your first scene to start bringing your story to life.',
  isGenerating = false,
  generatingLabel = 'Generating first scene...',
  onGenerateFirstScene,
  buttonLabel = 'Generate First Scene',
  className = '',
}: StudioEmptyStateProps) {
  return (
    <div className={`flex-1 flex items-center justify-center ${className}`}>
      <div className="text-center p-8 max-w-md">
        {isGenerating ? (
          /* Generating state */
          <div className="flex flex-col items-center">
            <div className="relative mb-6">
              <div className="w-20 h-20 rounded-2xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center">
                <Loader2 size={32} className="text-purple-400 animate-spin" />
              </div>
              <div className="absolute -top-1 -right-1 w-6 h-6 rounded-full bg-purple-500/20 flex items-center justify-center animate-pulse">
                <Sparkles size={12} className="text-purple-400" />
              </div>
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">{generatingLabel}</h3>
            <p className="text-sm text-white/50">
              The AI is crafting your scene. This may take a moment...
            </p>
          </div>
        ) : (
          /* Default empty state */
          <div className="flex flex-col items-center">
            <div className="w-20 h-20 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center mb-6">
              <Film size={32} className="text-white/30" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-2">{title}</h3>
            <p className="text-sm text-white/50 mb-6">{description}</p>

            {onGenerateFirstScene && (
              <button
                onClick={onGenerateFirstScene}
                className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-purple-500 to-pink-500 hover:opacity-90 rounded-full text-white font-semibold transition-all hover:scale-[1.02] active:scale-[0.98]"
                type="button"
              >
                <Plus size={18} />
                {buttonLabel}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

export default StudioEmptyState
