import React from 'react'
import {
  Play,
  Pause,
  SkipBack,
  SkipForward,
  Plus,
  Monitor,
  Volume2,
  VolumeX,
  Maximize2,
  Loader2,
} from 'lucide-react'

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

type StudioActionsProps = {
  // Playback controls
  isPlaying?: boolean
  onTogglePlay?: () => void
  canGoBack?: boolean
  canGoForward?: boolean
  onPrevScene?: () => void
  onNextScene?: () => void

  // Generation controls
  isGeneratingScene?: boolean
  onGenerateNextScene?: () => void

  // Scene progress
  currentIndex?: number
  totalScenes?: number
  onSelectScene?: (index: number) => void

  // Media controls
  isMuted?: boolean
  onToggleMute?: () => void
  onFullscreen?: () => void

  // TV Mode
  onEnterTVMode?: () => void
  tvModeDisabled?: boolean

  className?: string
}

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

/**
 * Action bar for Story Mode Studio, styled like Imagine's floating prompt bar.
 * Contains playback controls, scene navigation, and generation actions.
 */
export function StudioActions({
  isPlaying = false,
  onTogglePlay,
  canGoBack = false,
  canGoForward = false,
  onPrevScene,
  onNextScene,
  isGeneratingScene = false,
  onGenerateNextScene,
  currentIndex = 0,
  totalScenes = 0,
  onSelectScene,
  isMuted = false,
  onToggleMute,
  onFullscreen,
  onEnterTVMode,
  tvModeDisabled = false,
  className = '',
}: StudioActionsProps) {
  return (
    <div className={`border-t border-white/10 bg-black/80 backdrop-blur-md ${className}`}>
      <div className="max-w-4xl mx-auto px-4 py-4">
        <div className="flex items-center justify-between gap-4">
          {/* Left: Playback controls */}
          <div className="flex items-center gap-2">
            <button
              onClick={onPrevScene}
              disabled={!canGoBack}
              className="p-3 text-white/50 hover:text-white hover:bg-white/5 rounded-full transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              type="button"
              title="Previous scene"
            >
              <SkipBack size={20} />
            </button>

            <button
              onClick={onTogglePlay}
              className="p-4 bg-purple-500 hover:bg-purple-600 rounded-full transition-colors"
              type="button"
              title={isPlaying ? 'Pause' : 'Play'}
            >
              {isPlaying ? <Pause size={24} /> : <Play size={24} fill="currentColor" />}
            </button>

            <button
              onClick={onNextScene}
              disabled={!canGoForward}
              className="p-3 text-white/50 hover:text-white hover:bg-white/5 rounded-full transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              type="button"
              title="Next scene"
            >
              <SkipForward size={20} />
            </button>
          </div>

          {/* Center: Scene progress bar */}
          <div className="flex-1 mx-4">
            {totalScenes > 0 && onSelectScene && (
              <div className="flex gap-1">
                {Array.from({ length: totalScenes }, (_, i) => (
                  <button
                    key={i}
                    onClick={() => onSelectScene(i)}
                    className={`flex-1 h-1.5 rounded-full transition-colors ${
                      i === currentIndex
                        ? 'bg-purple-500'
                        : i < currentIndex
                        ? 'bg-white/30'
                        : 'bg-white/10'
                    }`}
                    type="button"
                    title={`Scene ${i + 1}`}
                  />
                ))}
              </div>
            )}
          </div>

          {/* Right: Actions */}
          <div className="flex items-center gap-2">
            {/* Mute toggle */}
            {onToggleMute && (
              <button
                onClick={onToggleMute}
                className="p-3 text-white/50 hover:text-white hover:bg-white/5 rounded-full transition-colors"
                type="button"
                title={isMuted ? 'Unmute' : 'Mute'}
              >
                {isMuted ? <VolumeX size={20} /> : <Volume2 size={20} />}
              </button>
            )}

            {/* Fullscreen */}
            {onFullscreen && (
              <button
                onClick={onFullscreen}
                className="p-3 text-white/50 hover:text-white hover:bg-white/5 rounded-full transition-colors"
                type="button"
                title="Fullscreen"
              >
                <Maximize2 size={20} />
              </button>
            )}

            {/* Generate next scene */}
            {onGenerateNextScene && (
              <button
                onClick={onGenerateNextScene}
                disabled={isGeneratingScene}
                className="flex items-center gap-2 px-4 py-2 bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 rounded-full transition-colors disabled:opacity-50"
                type="button"
              >
                {isGeneratingScene ? (
                  <>
                    <Loader2 size={16} className="animate-spin" />
                    <span className="text-sm font-medium">Generating...</span>
                  </>
                ) : (
                  <>
                    <Plus size={16} />
                    <span className="text-sm font-medium">Next Scene</span>
                  </>
                )}
              </button>
            )}

            {/* TV Mode */}
            {onEnterTVMode && (
              <button
                onClick={onEnterTVMode}
                disabled={tvModeDisabled}
                className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-500/20 to-pink-500/20 hover:from-purple-500/30 hover:to-pink-500/30 text-purple-300 border border-purple-500/30 rounded-full transition-all disabled:opacity-50"
                type="button"
                title="Watch story in immersive TV Mode"
              >
                <Monitor size={16} />
                <span className="text-sm font-medium">TV Mode</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default StudioActions
