/**
 * CharacterStage — The center "hero" preview panel.
 *
 * Shows: placeholder silhouette → loading skeleton → generated face/outfit.
 * Matches MMORPG character creator "stage" pattern where the character
 * is always the center of the interface.
 */

import React from 'react'
import {
  Maximize2,
  Loader2,
  User,
  Lock,
  Trash2,
  X,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type StageContent =
  | { kind: 'empty' }
  | { kind: 'generating' }
  | { kind: 'face'; url: string; seed?: number }
  | { kind: 'outfit'; url: string; seed?: number; scenarioLabel?: string }

export interface CharacterStageProps {
  content: StageContent
  faceLocked?: boolean
  lockedFaceUrl?: string
  onOpenLightbox?: (url: string) => void
  /** Delete the currently displayed result */
  onDelete?: () => void
  className?: string
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CharacterStage({
  content,
  faceLocked,
  lockedFaceUrl,
  onOpenLightbox,
  onDelete,
  className = '',
}: CharacterStageProps) {
  return (
    <div className={`relative flex flex-col items-center justify-center h-full min-h-0 ${className}`}>
      {/* Studio stage background — radial light + floor reflection */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden rounded-2xl">
        {/* Radial spotlight from top */}
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[120%] h-[70%] bg-gradient-radial from-purple-900/8 via-transparent to-transparent" />
        {/* Subtle floor reflection at bottom */}
        <div className="absolute bottom-0 left-0 right-0 h-[30%] bg-gradient-to-t from-white/[0.02] to-transparent" />
        {/* Floor line */}
        <div className="absolute bottom-[15%] left-[10%] right-[10%] h-px bg-gradient-to-r from-transparent via-white/[0.05] to-transparent" />
      </div>

      {/* Face-locked badge */}
      {faceLocked && lockedFaceUrl && (
        <div className="absolute top-3 left-3 z-20 flex items-center gap-2 px-2.5 py-1.5 rounded-lg bg-black/60 backdrop-blur-sm border border-purple-500/25">
          <div className="w-6 h-6 rounded-full overflow-hidden border border-purple-500/40 flex-shrink-0">
            <img src={lockedFaceUrl} alt="Locked face" className="w-full h-full object-cover" />
          </div>
          <Lock size={10} className="text-purple-400" />
          <span className="text-[10px] text-purple-300 font-medium">Face locked</span>
        </div>
      )}

      {/* Stage content */}
      {content.kind === 'empty' && (
        <div className="flex flex-col items-center justify-center gap-3 text-white/15">
          <div className="w-32 h-32 rounded-full border-2 border-dashed border-white/[0.08] flex items-center justify-center">
            <User size={48} strokeWidth={1} className="text-white/10" />
          </div>
          <span className="text-xs text-white/25">Your character will appear here</span>
          <span className="text-[10px] text-white/15">Generate faces to begin</span>
        </div>
      )}

      {content.kind === 'generating' && (
        <div className="flex flex-col items-center justify-center gap-3">
          <div className="w-32 h-32 rounded-full bg-white/[0.03] border border-white/[0.06] animate-pulse flex items-center justify-center">
            <Loader2 size={32} className="animate-spin text-white/15" />
          </div>
          <span className="text-xs text-white/30">Generating...</span>
        </div>
      )}

      {(content.kind === 'face' || content.kind === 'outfit') && (
        <div className="relative group h-full w-full flex items-center justify-center">
          {/* Gradient glow border */}
          <div className={`absolute -inset-[2px] rounded-2xl bg-gradient-to-br opacity-50 group-hover:opacity-100 transition-opacity ${
            content.kind === 'face'
              ? 'from-purple-500/20 via-transparent to-pink-500/20'
              : 'from-cyan-500/20 via-transparent to-blue-500/20'
          }`} />
          <div
            className={`relative h-full w-full rounded-2xl overflow-hidden border cursor-pointer bg-black/40 flex items-center justify-center ${
              content.kind === 'face' ? 'border-purple-500/15' : 'border-cyan-500/15'
            }`}
            onClick={() => onOpenLightbox?.(content.url)}
          >
            <img
              src={content.url}
              alt={content.kind === 'face' ? 'Character face' : 'Character outfit'}
              className="max-w-full max-h-full object-contain"
            />
            {/* Hover overlay */}
            <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
              <Maximize2 size={28} className="text-white/80" />
            </div>
          </div>

          {/* Delete button — bottom-right */}
          {onDelete && (
            <button
              onClick={(e) => { e.stopPropagation(); onDelete() }}
              className="absolute bottom-3 right-3 w-8 h-8 rounded-lg bg-black/60 backdrop-blur-sm border border-white/10 flex items-center justify-center text-white/40 hover:text-red-400 hover:border-red-500/30 hover:bg-red-500/10 transition-all z-10"
              title="Remove this result"
            >
              <Trash2 size={14} />
            </button>
          )}

          {/* Scenario label for outfits */}
          {content.kind === 'outfit' && content.scenarioLabel && (
            <div className="absolute top-3 right-3 px-2.5 py-1 rounded-lg bg-black/50 backdrop-blur-sm border border-cyan-500/20 text-[10px] text-cyan-200 font-medium z-10">
              {content.scenarioLabel}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
