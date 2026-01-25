/**
 * EditResultGrid - Grid display of generated edit results.
 *
 * Shows 2-4 result images with actions to use, download, or retry.
 */

import React from 'react'
import { Check, RefreshCw, Download } from 'lucide-react'
import type { EditResultGridProps } from './types'

export function EditResultGrid({
  images,
  onUse,
  onTryAgain,
  onOpen,
  disabled,
}: EditResultGridProps) {
  // Don't render if no images
  if (!images?.length) {
    return null
  }

  const handleDownload = async (url: string, e: React.MouseEvent) => {
    e.stopPropagation()

    try {
      const response = await fetch(url)
      const blob = await response.blob()
      const blobUrl = URL.createObjectURL(blob)

      const link = document.createElement('a')
      link.href = blobUrl
      link.download = `edit-result-${Date.now()}.png`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)

      URL.revokeObjectURL(blobUrl)
    } catch (error) {
      // Fallback: open in new tab
      window.open(url, '_blank')
    }
  }

  return (
    <div className="mt-4">
      {/* Header with try again button */}
      <div className="flex items-center justify-between mb-2">
        <div className="text-[11px] uppercase tracking-wider text-white/40 font-semibold">
          Results
        </div>

        <button
          type="button"
          onClick={onTryAgain}
          disabled={disabled}
          className={[
            'inline-flex items-center gap-2 px-3 py-1.5 rounded-xl',
            'bg-white/10 hover:bg-white/15 border border-white/10',
            'transition-colors text-xs font-semibold',
            disabled ? 'opacity-50 cursor-not-allowed' : '',
          ].join(' ')}
        >
          <RefreshCw size={14} />
          Try again
        </button>
      </div>

      {/* Results grid */}
      <div className="grid grid-cols-2 gap-3">
        {images.slice(0, 4).map((url, index) => (
          <div
            key={`${url}-${index}`}
            className="group relative rounded-2xl overflow-hidden border border-white/10 bg-white/5"
          >
            {/* Clickable image */}
            <button
              type="button"
              onClick={() => onOpen(url)}
              className="block w-full focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500/50"
              aria-label={`View result ${index + 1} fullscreen`}
            >
              <img
                src={url}
                className="w-full aspect-square object-cover"
                alt={`Edit result ${index + 1}`}
                loading="lazy"
              />
            </button>

            {/* Action overlay */}
            <div className="absolute inset-x-0 bottom-0 p-3 bg-gradient-to-t from-black/80 via-black/30 to-transparent">
              <div className="flex gap-2">
                {/* Use this button */}
                <button
                  type="button"
                  onClick={() => !disabled && onUse(url)}
                  disabled={disabled}
                  className={[
                    'flex-1 inline-flex items-center justify-center gap-2',
                    'px-3 py-2 rounded-xl bg-blue-600 hover:bg-blue-700',
                    'transition-colors text-sm font-semibold',
                    disabled ? 'opacity-50 cursor-not-allowed' : '',
                  ].join(' ')}
                >
                  <Check size={16} />
                  Use this
                </button>

                {/* Download button */}
                <button
                  type="button"
                  onClick={(e) => handleDownload(url, e)}
                  className={[
                    'inline-flex items-center justify-center gap-2',
                    'px-3 py-2 rounded-xl bg-white/10 hover:bg-white/15',
                    'border border-white/10 transition-colors text-sm font-semibold',
                  ].join(' ')}
                  aria-label="Download image"
                >
                  <Download size={16} />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Hint */}
      <p className="mt-3 text-xs text-white/40 text-center">
        Click an image to view full size, or click "Use this" to continue editing
      </p>
    </div>
  )
}

export default EditResultGrid
