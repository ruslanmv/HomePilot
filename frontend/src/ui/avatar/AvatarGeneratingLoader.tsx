/**
 * AvatarGeneratingLoader — Professional animated loader for avatar generation.
 *
 * Matches the Immagine / Animate processing overlay pattern:
 * purple-themed spinner + status text + optional progress + cancel.
 *
 * Uses the same color palette (purple-400/500/600) and backdrop-blur
 * as the rest of the application for visual consistency.
 */

import React from 'react'
import { Loader2, X } from 'lucide-react'

export interface AvatarGeneratingLoaderProps {
  /** What we're generating — e.g. "Creating your avatar…" */
  label?: string
  /** Sub-label hint — e.g. "This may take up to a minute" */
  hint?: string
  /** 0–100 progress (omit for indeterminate) */
  progress?: number
  /** Cancel callback (shows cancel button when provided) */
  onCancel?: () => void
  /** Variant: 'overlay' fills the parent with backdrop blur; 'inline' is a standalone block */
  variant?: 'overlay' | 'inline'
  /** How many items are being generated (shows skeleton grid) */
  count?: number
  /** CSS aspect ratio class for skeleton cards */
  aspectClass?: string
}

export function AvatarGeneratingLoader({
  label = 'Generating…',
  hint,
  progress,
  onCancel,
  variant = 'inline',
  count,
  aspectClass = 'aspect-[2/3]',
}: AvatarGeneratingLoaderProps) {
  const isOverlay = variant === 'overlay'

  return (
    <div
      className={[
        'flex flex-col items-center justify-center gap-4',
        isOverlay
          ? 'absolute inset-0 z-20 bg-black/50 backdrop-blur-sm rounded-2xl'
          : 'w-full py-8',
      ].join(' ')}
    >
      {/* Animated spinner ring */}
      <div className="relative flex items-center justify-center">
        {/* Outer glow ring */}
        <div className="absolute w-20 h-20 rounded-full bg-purple-500/10 animate-ping" style={{ animationDuration: '2s' }} />
        {/* Mid ring — rotating gradient border */}
        <div className="absolute w-16 h-16 rounded-full border-2 border-transparent animate-spin"
          style={{
            borderImage: 'linear-gradient(135deg, #a855f7, #ec4899, transparent, transparent) 1',
            animationDuration: '3s',
          }}
        />
        {/* Core spinner */}
        <div className="relative w-14 h-14 rounded-full bg-black/40 border border-purple-500/20 flex items-center justify-center backdrop-blur-sm">
          <Loader2 size={28} className="text-purple-400 animate-spin" />
        </div>
      </div>

      {/* Status text */}
      <div className="flex flex-col items-center gap-1">
        <span className="text-sm font-medium text-white/90">{label}</span>
        {hint && <span className="text-[11px] text-white/40">{hint}</span>}
      </div>

      {/* Progress bar (when provided) */}
      {typeof progress === 'number' && (
        <div className="w-48 flex flex-col items-center gap-1.5">
          <div className="w-full h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-purple-500 to-pink-500 transition-all duration-500 ease-out"
              style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
            />
          </div>
          <span className="text-[10px] text-white/30 tabular-nums">{Math.round(progress)}%</span>
        </div>
      )}

      {/* Skeleton grid preview */}
      {count && count > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 w-full max-w-md px-4">
          {Array.from({ length: count }).map((_, i) => (
            <div key={i} className="rounded-xl overflow-hidden border border-white/[0.06] bg-white/[0.02]">
              <div className={`${aspectClass} bg-gradient-to-br from-purple-900/10 to-transparent flex items-center justify-center`}>
                <div
                  className="w-6 h-6 rounded-full border-2 border-purple-500/20 border-t-purple-400/60 animate-spin"
                  style={{ animationDuration: `${1.2 + i * 0.3}s` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Cancel button */}
      {onCancel && (
        <button
          onClick={onCancel}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-medium border border-red-500/20 bg-red-500/5 text-red-400/80 hover:bg-red-500/15 hover:text-red-400 hover:border-red-500/30 transition-all"
        >
          <X size={12} /> Cancel
        </button>
      )}
    </div>
  )
}
