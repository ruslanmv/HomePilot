import React, { useState } from 'react'
import { X, Edit, Download, Share2, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'

interface ImageViewerProps {
  imageUrl: string
  onClose: () => void
  onEdit?: (imageUrl: string) => void
  onGenerateVideo?: (imageUrl: string, prompt: string) => void
}

export function ImageViewer({ imageUrl, onClose, onEdit, onGenerateVideo }: ImageViewerProps) {
  const [zoom, setZoom] = useState(100)
  const [videoPrompt, setVideoPrompt] = useState('')
  const [isGeneratingVideo, setIsGeneratingVideo] = useState(false)

  const handleDownload = async () => {
    try {
      const response = await fetch(imageUrl)
      const blob = await response.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `homepilot-${Date.now()}.png`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)
    } catch (error) {
      console.error('Download failed:', error)
    }
  }

  const handleShare = async () => {
    try {
      if (navigator.share) {
        const response = await fetch(imageUrl)
        const blob = await response.blob()
        const file = new File([blob], 'image.png', { type: 'image/png' })
        await navigator.share({
          files: [file],
          title: 'Generated Image',
          text: 'Check out this AI-generated image!',
        })
      } else {
        // Fallback: copy URL to clipboard
        await navigator.clipboard.writeText(imageUrl)
        alert('Image URL copied to clipboard!')
      }
    } catch (error) {
      console.error('Share failed:', error)
    }
  }

  const handleZoomIn = () => {
    setZoom((prev) => Math.min(prev + 25, 200))
  }

  const handleZoomOut = () => {
    setZoom((prev) => Math.max(prev - 25, 50))
  }

  const handleZoomReset = () => {
    setZoom(100)
  }

  const handleGenerateVideo = async () => {
    if (!onGenerateVideo) return
    if (!videoPrompt.trim()) {
      alert('Please enter a description for the video animation')
      return
    }
    setIsGeneratingVideo(true)
    try {
      await onGenerateVideo(imageUrl, videoPrompt)
    } finally {
      setIsGeneratingVideo(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/95 backdrop-blur-sm flex flex-col"
      onClick={onClose}
    >
      {/* Top Controls Bar */}
      <div className="absolute top-0 left-0 right-0 flex items-center justify-between p-4 bg-gradient-to-b from-black/80 to-transparent z-10">
        <div className="flex items-center gap-2">
          {onEdit && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onEdit(imageUrl)
              }}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
              title="Edit image"
            >
              <Edit size={18} />
              <span className="text-sm font-medium">Edit image</span>
            </button>
          )}

          <button
            onClick={(e) => {
              e.stopPropagation()
              handleDownload()
            }}
            className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
            title="Download"
          >
            <Download size={18} />
          </button>

          <button
            onClick={(e) => {
              e.stopPropagation()
              handleShare()
            }}
            className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
            title="Share"
          >
            <Share2 size={18} />
          </button>

          <div className="w-px h-6 bg-white/20" />

          <button
            onClick={(e) => {
              e.stopPropagation()
              handleZoomOut()
            }}
            className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
            title="Zoom out"
            disabled={zoom <= 50}
          >
            <ZoomOut size={18} />
          </button>

          <span className="text-sm font-medium px-2 min-w-[4rem] text-center">{zoom}%</span>

          <button
            onClick={(e) => {
              e.stopPropagation()
              handleZoomIn()
            }}
            className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
            title="Zoom in"
            disabled={zoom >= 200}
          >
            <ZoomIn size={18} />
          </button>

          <button
            onClick={(e) => {
              e.stopPropagation()
              handleZoomReset()
            }}
            className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
            title="Reset zoom"
          >
            <Maximize2 size={18} />
          </button>
        </div>

        <button
          onClick={onClose}
          className="p-2 bg-white/10 hover:bg-white/20 rounded-lg transition-colors"
          aria-label="Close"
        >
          <X size={24} />
        </button>
      </div>

      {/* Image Display Area */}
      <div className="flex-1 flex items-center justify-center p-20 overflow-auto">
        <img
          src={imageUrl}
          onClick={(e) => e.stopPropagation()}
          className="rounded-lg shadow-2xl border border-white/10 transition-transform"
          style={{
            transform: `scale(${zoom / 100})`,
            maxWidth: '90vw',
            maxHeight: '70vh',
            objectFit: 'contain',
          }}
          alt="preview"
        />
      </div>

      {/* Video Generation Interface — only shown when onGenerateVideo is provided */}
      {onGenerateVideo && (
        <div
          className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/90 via-black/80 to-transparent p-6 pb-8"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="max-w-4xl mx-auto">
            <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              Generate Video from Image
            </h3>
            <p className="text-sm text-gray-400 mb-4">
              Animate this image with AI. Describe the motion or action you want to see.
            </p>

            <div className="flex gap-3">
              <input
                type="text"
                value={videoPrompt}
                onChange={(e) => setVideoPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    handleGenerateVideo()
                  }
                }}
                placeholder="Type to customize video... (e.g., 'make the horse gallop across the desert at sunset')"
                className="flex-1 px-4 py-3 bg-white/5 border border-white/10 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent placeholder-gray-500"
                disabled={isGeneratingVideo}
              />
              <button
                onClick={handleGenerateVideo}
                disabled={isGeneratingVideo || !videoPrompt.trim()}
                className="px-6 py-3 bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg font-medium transition-all duration-200 flex items-center gap-2 min-w-[140px] justify-center"
              >
                {isGeneratingVideo ? (
                  <>
                    <svg
                      className="animate-spin h-5 w-5"
                      xmlns="http://www.w3.org/2000/svg"
                      fill="none"
                      viewBox="0 0 24 24"
                    >
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                      />
                    </svg>
                    <span>Generating...</span>
                  </>
                ) : (
                  <>
                    <svg
                      className="w-5 h-5"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M7 11l5-5m0 0l5 5m-5-5v12"
                      />
                    </svg>
                    <span>Make video</span>
                  </>
                )}
              </button>
            </div>

            <div className="mt-3 flex items-center gap-4 text-xs text-gray-500">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 bg-green-500 rounded-full" />
                HD Quality
              </span>
              <span>•</span>
              <span>5-30 seconds</span>
              <span>•</span>
              <span>Press Enter to generate</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
