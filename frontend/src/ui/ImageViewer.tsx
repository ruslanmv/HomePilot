import React, { useState } from 'react'
import { X, Edit, Download, Share2, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react'
import { resolveFileUrl } from './resolveFileUrl'

interface ImageViewerProps {
  imageUrl: string
  onClose: () => void
  onEdit?: (imageUrl: string) => void
}

export function ImageViewer({ imageUrl, onClose, onEdit }: ImageViewerProps) {
  const [zoom, setZoom] = useState(100)

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
          src={resolveFileUrl(imageUrl)}
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

    </div>
  )
}
