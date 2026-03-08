/**
 * AvatarOrbitViewer — pseudo-3D 360° character viewer.
 *
 * Simulates orbit rotation using the 4 generated view-angle images.
 * The user drags horizontally to rotate; images crossfade for smooth transitions.
 * Clicking the image still opens the lightbox (non-destructive).
 *
 * Angle order (clockwise):
 *   front → right → back → left → (wrap to front)
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Maximize2, RotateCw } from 'lucide-react'
import type { ViewAngle, ViewPreviewMap } from './viewPack'

// Clockwise orbit order — maps continuous rotation to discrete angles
const ORBIT_ORDER: ViewAngle[] = [
  'front',
  'right',
  'back',
  'left',
]

const ANGLE_LABELS: Record<ViewAngle, string> = {
  front: 'Front',
  right: 'Right',
  back: 'Back',
  left: 'Left',
}

const CROSSFADE_MS = 180

interface AvatarOrbitViewerProps {
  previews: ViewPreviewMap
  activeAngle: ViewAngle | null
  onAngleChange: (angle: ViewAngle) => void
  onOpenLightbox?: (url: string) => void
}

export function AvatarOrbitViewer({
  previews,
  activeAngle,
  onAngleChange,
  onOpenLightbox,
}: AvatarOrbitViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const dragStartX = useRef(0)
  const startIndex = useRef(0)
  const [currentIndex, setCurrentIndex] = useState(() => {
    const idx = ORBIT_ORDER.indexOf(activeAngle ?? 'front')
    return idx >= 0 ? idx : 0
  })
  // Track the *previous* index for crossfade
  const [prevIndex, setPrevIndex] = useState(currentIndex)
  const [fading, setFading] = useState(false)
  const fadeTimer = useRef<ReturnType<typeof setTimeout>>()

  // Available angles that have images
  const availableCount = useMemo(() => {
    return ORBIT_ORDER.filter((angle) => previews[angle]).length
  }, [previews])

  const hasEnoughAngles = availableCount >= 2

  // Find nearest available angle for a given raw index
  const snapToNearest = useCallback((rawIdx: number): number => {
    const len = ORBIT_ORDER.length
    const wrapped = ((rawIdx % len) + len) % len

    // If this angle has an image, use it
    if (previews[ORBIT_ORDER[wrapped]]) return wrapped

    // Search outward for nearest available
    for (let offset = 1; offset <= 2; offset++) {
      const fwd = ((wrapped + offset) % len + len) % len
      if (previews[ORBIT_ORDER[fwd]]) return fwd
      const bwd = ((wrapped - offset) % len + len) % len
      if (previews[ORBIT_ORDER[bwd]]) return bwd
    }
    return 0 // fallback
  }, [previews])

  // Transition to a new index with crossfade
  const transitionTo = useCallback((newIdx: number, fromIdx?: number) => {
    const from = fromIdx ?? currentIndex
    if (newIdx === from && previews[ORBIT_ORDER[newIdx]]) return
    setPrevIndex(from)
    setCurrentIndex(newIdx)
    setFading(true)
    clearTimeout(fadeTimer.current)
    fadeTimer.current = setTimeout(() => setFading(false), CROSSFADE_MS)
  }, [currentIndex, previews])

  // Sync external activeAngle → internal index
  useEffect(() => {
    const target = activeAngle ?? 'front'
    const idx = ORBIT_ORDER.indexOf(target)
    if (idx >= 0 && idx !== currentIndex) {
      transitionTo(idx)
    }
  }, [activeAngle]) // eslint-disable-line react-hooks/exhaustive-deps

  // When previews change (outfit switch), snap to nearest available angle.
  // This prevents showing a blank screen when the previous outfit's angle
  // doesn't exist in the new outfit's view pack.
  const prevPreviewsRef = useRef(previews)
  useEffect(() => {
    const prev = prevPreviewsRef.current
    prevPreviewsRef.current = previews

    // Check if the previews actually changed (not just re-render)
    const changed = ORBIT_ORDER.some((a) => prev[a] !== previews[a])
    if (!changed) return

    const currentAngle = ORBIT_ORDER[currentIndex]
    if (!previews[currentAngle]) {
      // Current angle no longer available — snap to nearest
      const snapped = snapToNearest(currentIndex)
      transitionTo(snapped)
      onAngleChange(ORBIT_ORDER[snapped])
    }
  }, [previews, currentIndex, snapToNearest, transitionTo, onAngleChange])

  // Drag sensitivity: pixels per angle step
  const PX_PER_STEP = 80

  const handlePointerDown = useCallback((e: React.PointerEvent) => {
    if (!hasEnoughAngles) return
    dragging.current = true
    dragStartX.current = e.clientX
    startIndex.current = currentIndex
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
    e.preventDefault()
  }, [hasEnoughAngles, currentIndex])

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragging.current) return
    const dx = e.clientX - dragStartX.current
    const steps = Math.round(dx / PX_PER_STEP)
    if (steps === 0) return

    // Positive dx = drag right = rotate clockwise (increasing index)
    const rawIdx = startIndex.current + steps
    const snapped = snapToNearest(rawIdx)

    if (snapped !== currentIndex) {
      transitionTo(snapped)
      onAngleChange(ORBIT_ORDER[snapped])
    }
  }, [currentIndex, snapToNearest, transitionTo, onAngleChange])

  const handlePointerUp = useCallback(() => {
    dragging.current = false
  }, [])

  const currentAngle = ORBIT_ORDER[currentIndex]
  const currentUrl = previews[currentAngle]
  const prevAngle = ORBIT_ORDER[prevIndex]
  const prevUrl = previews[prevAngle]

  const handleClick = useCallback(() => {
    if (currentUrl && onOpenLightbox) {
      onOpenLightbox(currentUrl)
    }
  }, [currentUrl, onOpenLightbox])

  // Keyboard arrow left/right navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!hasEnoughAngles) return
      let step = 0
      if (e.key === 'ArrowRight') step = 1   // clockwise
      else if (e.key === 'ArrowLeft') step = -1 // counter-clockwise
      else return

      e.preventDefault()
      const rawIdx = currentIndex + step
      const snapped = snapToNearest(rawIdx)

      if (snapped !== currentIndex) {
        transitionTo(snapped)
        onAngleChange(ORBIT_ORDER[snapped])
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [hasEnoughAngles, currentIndex, snapToNearest, transitionTo, onAngleChange])

  // Cleanup
  useEffect(() => {
    return () => clearTimeout(fadeTimer.current)
  }, [])

  // If no image at all, show a placeholder instead of returning null
  if (!currentUrl) {
    // Try to find ANY available angle
    const fallbackIdx = snapToNearest(0)
    const fallbackUrl = previews[ORBIT_ORDER[fallbackIdx]]
    if (!fallbackUrl) {
      return (
        <div className="relative h-full rounded-2xl border border-white/[0.08] bg-black/40 flex items-center justify-center">
          <div className="text-center">
            <RotateCw size={24} className="text-white/15 mx-auto mb-2" />
            <div className="text-xs text-white/25">No 3D views for this outfit</div>
            <div className="text-[10px] text-white/15 mt-1">Generate views in the View Pack panel</div>
          </div>
        </div>
      )
    }
  }

  return (
    <div className="relative group h-full">
      <div className="absolute -inset-[2px] rounded-2xl bg-gradient-to-br from-cyan-500/25 via-transparent to-teal-500/25 opacity-60 group-hover:opacity-100 transition-opacity" />
      <div
        ref={containerRef}
        className="relative h-full rounded-2xl overflow-hidden border border-cyan-500/20 bg-black/40 flex items-center justify-center select-none"
        style={{ touchAction: 'pan-y' }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
      >
        {/* Previous image — fades out during crossfade */}
        {fading && prevUrl && prevUrl !== currentUrl && (
          <img
            src={prevUrl}
            alt={prevAngle}
            className="absolute inset-0 w-full h-full object-contain pointer-events-none"
            style={{
              opacity: 0,
              transition: `opacity ${CROSSFADE_MS}ms ease-out`,
            }}
          />
        )}

        {/* Current image — fades in */}
        {currentUrl && (
          <img
            src={currentUrl}
            alt={currentAngle}
            className="max-w-full max-h-full object-contain pointer-events-none"
            style={{
              opacity: fading ? 0 : 1,
              animation: fading ? `orbitFadeIn ${CROSSFADE_MS}ms ease-out forwards` : undefined,
            }}
          />
        )}

        {/* Orbit indicator badge */}
        <div className="absolute top-3 left-3 flex items-center gap-1.5 px-2 py-1 rounded-lg bg-black/50 backdrop-blur-sm border border-cyan-500/20 text-[10px] text-cyan-200 font-medium">
          <RotateCw size={10} />
          <span>360°</span>
          <span className="text-white/50">·</span>
          <span className="text-white/70">{ANGLE_LABELS[currentAngle] || currentAngle}</span>
          {availableCount > 0 && (
            <>
              <span className="text-white/20">·</span>
              <span className="text-emerald-300/60">{availableCount}/6</span>
            </>
          )}
        </div>

        {/* Drag hint — only if not actively dragging */}
        {hasEnoughAngles && (
          <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-black/50 backdrop-blur-sm border border-white/10 text-[10px] text-white/40 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none">
            <span>← → drag to rotate</span>
          </div>
        )}

        {/* Lightbox overlay on hover */}
        {currentUrl && (
          <div
            className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center cursor-pointer"
            onClick={handleClick}
          >
            <Maximize2 size={28} className="text-white/80" />
          </div>
        )}

        {/* Angle dots — orbit position indicator (clickable) */}
        <div className="absolute bottom-3 right-3 flex items-center gap-1.5">
          {ORBIT_ORDER.map((angle, idx) => {
            const hasImage = Boolean(previews[angle])
            const isActive = idx === currentIndex
            return (
              <button
                key={angle}
                onClick={(e) => {
                  e.stopPropagation()
                  if (!hasImage) return
                  transitionTo(idx)
                  onAngleChange(angle)
                }}
                className={[
                  'w-2 h-2 rounded-full transition-all',
                  isActive
                    ? 'bg-cyan-400 scale-150'
                    : hasImage
                      ? 'bg-white/40 hover:bg-white/60 cursor-pointer'
                      : 'bg-white/10 cursor-default',
                ].join(' ')}
                title={`${ANGLE_LABELS[angle] || angle}${hasImage ? '' : ' (not generated)'}`}
              />
            )
          })}
        </div>
      </div>

      {/* CSS keyframe for fade-in */}
      <style>{`
        @keyframes orbitFadeIn {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
      `}</style>
    </div>
  )
}
