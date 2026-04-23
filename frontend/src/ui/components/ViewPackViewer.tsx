/**
 * ViewPackViewer — interactive 360° persona preview.
 *
 * Renders the currently-active angle as a large image plus a row of
 * clickable chips (Front / Left / Right / Back) that switch the active
 * angle instantly (all angles are preloaded on mount). Drop-in for any
 * chat surface that receives a message with a ``media.view_pack``.
 *
 * Parity note: Chat (``App.tsx``) has an inline version of this that
 * predates the component being extracted. This file is the shared,
 * additive version used by voice mode and any future surface — App.tsx
 * stays untouched so the chat rendering is not destabilized by the
 * extraction.
 */
import React, { useEffect, useState } from 'react'

export type ViewAngle = 'front' | 'left' | 'right' | 'back'

const VIEW_ANGLE_LABELS: Record<ViewAngle, string> = {
  front: 'Front',
  left: 'Left',
  right: 'Right',
  back: 'Back',
}

export interface ViewPackViewerProps {
  viewPack: Partial<Record<ViewAngle, string>>
  availableViews: ViewAngle[]
  /** Initial angle. Defaults to the first available view, or 'front' if present. */
  initialAngle?: ViewAngle
  /** Optional: notified whenever the user picks a different angle. */
  onAngleChange?: (angle: ViewAngle, url: string) => void
  /** Optional: click on the large image — e.g. to open a lightbox. */
  onImageClick?: (url: string) => void
  /** Styling hooks (both optional). */
  imageClassName?: string
  containerClassName?: string
}

export function ViewPackViewer({
  viewPack,
  availableViews,
  initialAngle,
  onAngleChange,
  onImageClick,
  imageClassName,
  containerClassName,
}: ViewPackViewerProps) {
  const firstAvailable: ViewAngle =
    initialAngle && viewPack[initialAngle]
      ? initialAngle
      : availableViews.find((a) => viewPack[a]) || 'front'

  const [active, setActive] = useState<ViewAngle>(firstAvailable)

  // Preload every angle on mount so clicks feel instant.
  useEffect(() => {
    availableViews.forEach((angle) => {
      const url = viewPack[angle]
      if (url) {
        const img = new Image()
        img.src = url
      }
    })
  }, [viewPack, availableViews])

  // Keep active angle valid even if viewPack/availableViews change under us.
  useEffect(() => {
    if (!viewPack[active]) {
      const fallback = availableViews.find((a) => viewPack[a])
      if (fallback) setActive(fallback)
    }
  }, [viewPack, availableViews, active])

  const activeUrl = viewPack[active] || ''
  if (!activeUrl) return null

  return (
    <div className={containerClassName ?? 'mt-3 hp-fade-in'}>
      <img
        src={activeUrl}
        alt={`Persona ${VIEW_ANGLE_LABELS[active]} view`}
        onClick={() => onImageClick?.(activeUrl)}
        className={
          imageClassName ??
          'w-72 max-h-96 h-auto object-contain rounded-xl border border-white/10 bg-black/20 cursor-zoom-in hover:opacity-90 transition-opacity'
        }
        onError={(e) => {
          ;(e.target as HTMLImageElement).style.display = 'none'
        }}
      />
      <div className="flex gap-1.5 pt-2">
        {availableViews.map((angle) => {
          const url = viewPack[angle]
          if (!url) return null
          const isActive = angle === active
          return (
            <button
              key={angle}
              type="button"
              onClick={() => {
                setActive(angle)
                onAngleChange?.(angle, url)
              }}
              className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                isActive
                  ? 'bg-white/15 border-white/30 text-white/90 font-medium'
                  : 'bg-white/[0.04] border-white/10 text-white/50 hover:bg-white/10 hover:text-white/70'
              }`}
              aria-pressed={isActive}
            >
              {VIEW_ANGLE_LABELS[angle]}
            </button>
          )
        })}
      </div>
    </div>
  )
}
