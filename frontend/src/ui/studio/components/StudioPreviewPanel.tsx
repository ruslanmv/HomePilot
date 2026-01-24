import React from 'react'
import { Loader2, ImageIcon, RefreshCw } from 'lucide-react'

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

type StudioPreviewPanelProps = {
  imageUrl?: string | null
  isGenerating?: boolean
  narration?: string
  prompt?: string
  onRegenerateImage?: () => void
  className?: string
}

// -----------------------------------------------------------------------------
// Component
// -----------------------------------------------------------------------------

/**
 * Preview panel for the current scene, styled like Imagine's lightbox.
 * Shows the scene image with narration overlay and generation status.
 */
export function StudioPreviewPanel({
  imageUrl,
  isGenerating = false,
  narration,
  prompt,
  onRegenerateImage,
  className = '',
}: StudioPreviewPanelProps) {
  const hasImage = Boolean(imageUrl)

  return (
    <div className={`relative flex-1 overflow-hidden ${className}`}>
      {/* Background gradient */}
      <div className="absolute inset-0 bg-gradient-to-b from-black via-[#0a0a0f] to-[#121218]" />

      {/* Main content area */}
      <div className="absolute inset-0 flex items-center justify-center p-4">
        {hasImage ? (
          <div className="relative w-full h-full flex items-center justify-center">
            {/* Image container with subtle shadow */}
            <div className="relative max-w-full max-h-full">
              <img
                src={imageUrl!}
                alt="Scene preview"
                className="max-h-[calc(100vh-320px)] max-w-full object-contain rounded-lg shadow-2xl transition-opacity duration-700"
              />

              {/* Regenerate overlay on hover */}
              {onRegenerateImage && (
                <div className="absolute inset-0 flex items-center justify-center opacity-0 hover:opacity-100 transition-opacity duration-300 bg-black/40 rounded-lg">
                  <button
                    onClick={onRegenerateImage}
                    disabled={isGenerating}
                    className="flex items-center gap-2 px-4 py-2 bg-white/10 backdrop-blur-md border border-white/20 rounded-full text-white text-sm font-medium hover:bg-white/20 transition-colors disabled:opacity-50"
                    type="button"
                  >
                    <RefreshCw size={14} className={isGenerating ? 'animate-spin' : ''} />
                    Regenerate Image
                  </button>
                </div>
              )}
            </div>

            {/* Generating overlay */}
            {isGenerating && (
              <div className="absolute inset-0 flex items-center justify-center bg-black/60 rounded-lg">
                <div className="flex flex-col items-center gap-3">
                  <Loader2 size={32} className="text-purple-400 animate-spin" />
                  <span className="text-white/70 text-sm">Generating image...</span>
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Empty state when no image */
          <div className="flex flex-col items-center justify-center text-center p-8">
            {isGenerating ? (
              <>
                <Loader2 size={48} className="text-purple-400 animate-spin mb-4" />
                <p className="text-white/70 text-sm">Generating image...</p>
                {prompt && (
                  <p className="text-white/40 text-xs mt-2 max-w-md line-clamp-2">{prompt}</p>
                )}
              </>
            ) : (
              <>
                <div className="w-16 h-16 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center mb-4">
                  <ImageIcon size={24} className="text-white/30" />
                </div>
                <p className="text-white/50 text-sm">No image for this scene</p>
                {onRegenerateImage && (
                  <button
                    onClick={onRegenerateImage}
                    className="mt-4 flex items-center gap-2 px-4 py-2 bg-purple-500 hover:bg-purple-600 rounded-full text-white text-sm font-medium transition-colors"
                    type="button"
                  >
                    Generate Image
                  </button>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Narration subtitle overlay */}
      {narration && (
        <div className="absolute bottom-6 left-0 right-0 flex justify-center px-8 pointer-events-none">
          <div className="bg-black/80 backdrop-blur-sm px-6 py-4 rounded-xl max-w-3xl shadow-lg border border-white/5">
            <p className="text-base md:text-lg text-white leading-relaxed text-center">
              {narration}
            </p>
          </div>
        </div>
      )}

      <style>{`
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

export default StudioPreviewPanel
