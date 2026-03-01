/**
 * MeetingOverflowStrip — Paginated gallery strip for overflow participants.
 *
 * When more participants exist than visible seats (default: 6),
 * the extras are shown in a horizontal strip below the table.
 * Users can page through or drag personas from the strip onto table seats.
 *
 * Also supports drag-start for drag-to-seat interactions.
 */

import React, { useMemo } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import type { PersonaSummary, IntentSnapshot } from './types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SeatStatus = 'listening' | 'wants-to-speak' | 'speaking' | 'muted'

export interface MeetingOverflowStripProps {
  /** Personas NOT currently in a visible seat */
  overflowPersonas: PersonaSummary[]
  /** Current page index */
  page: number
  /** Callback to change page */
  onPageChange: (page: number) => void
  /** Items per page */
  pageSize?: number
  backendUrl: string
  /** Intent state for status dots */
  intents: Record<string, IntentSnapshot>
  handRaises: Set<string>
  mutedSet: Set<string>
  runningTurn: boolean
  lastSpeakerId?: string
  /** DnD: start dragging a persona from the strip */
  onDragStart?: (e: React.DragEvent, personaId: string) => void
  /** Double-click to promote to visible seat */
  onPromote?: (personaId: string) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveAvatarUrl(p: PersonaSummary, backendUrl: string): string | null {
  const file = p.persona_appearance?.selected_thumb_filename || p.persona_appearance?.selected_filename
  if (!file) return null
  if (file.startsWith('http')) return file
  return `${backendUrl}/files/${file}`
}

function getSeatStatus(
  personaId: string,
  intents: Record<string, IntentSnapshot>,
  handRaises: Set<string>,
  mutedSet: Set<string>,
  runningTurn: boolean,
  lastSpeakerId?: string,
): SeatStatus {
  if (mutedSet.has(personaId)) return 'muted'
  if (runningTurn && intents[personaId]?.wants_to_speak) return 'speaking'
  if (runningTurn && lastSpeakerId === personaId) return 'speaking'
  if (handRaises.has(personaId) || intents[personaId]?.wants_to_speak) return 'wants-to-speak'
  return 'listening'
}

const STATUS_RING: Record<SeatStatus, string> = {
  speaking: 'border-emerald-400/60 shadow-sm shadow-emerald-400/30',
  'wants-to-speak': 'border-amber-400/50',
  listening: 'border-white/10',
  muted: 'border-red-400/30 opacity-50',
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MeetingOverflowStrip({
  overflowPersonas,
  page,
  onPageChange,
  pageSize = 8,
  backendUrl,
  intents,
  handRaises,
  mutedSet,
  runningTurn,
  lastSpeakerId,
  onDragStart,
  onPromote,
}: MeetingOverflowStripProps) {
  const totalPages = Math.max(1, Math.ceil(overflowPersonas.length / pageSize))
  const safePage = Math.min(page, totalPages - 1)
  const pageItems = overflowPersonas.slice(safePage * pageSize, (safePage + 1) * pageSize)

  if (overflowPersonas.length === 0) return null

  return (
    <div className="flex items-center gap-2 px-4 py-2 border-t border-white/[0.03] bg-white/[0.01] animate-strip-slide">
      {/* Page left */}
      <button
        onClick={() => onPageChange(Math.max(0, safePage - 1))}
        disabled={safePage === 0}
        className={`p-1 rounded transition-colors ${
          safePage === 0 ? 'text-white/10 cursor-default' : 'text-white/30 hover:text-white/50 hover:bg-white/5'
        }`}
        title="Previous page"
      >
        <ChevronLeft size={14} />
      </button>

      {/* Persona tiles */}
      <div className="flex-1 flex items-center gap-2 justify-center">
        {pageItems.map((p) => {
          const avatarUrl = resolveAvatarUrl(p, backendUrl)
          const status = getSeatStatus(p.id, intents, handRaises, mutedSet, runningTurn, lastSpeakerId)
          return (
            <div
              key={p.id}
              className="flex flex-col items-center gap-0.5 cursor-grab active:cursor-grabbing"
              draggable
              onDragStart={(e) => onDragStart?.(e, p.id)}
              onDoubleClick={() => onPromote?.(p.id)}
              title={`${p.name} — double-click to bring to table`}
            >
              <div className={`w-16 h-16 rounded-full overflow-hidden border-2 bg-white/5 transition-all ${STATUS_RING[status]}`}>
                {avatarUrl ? (
                  <img src={avatarUrl} alt={p.name} className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-xs text-white/30 font-bold">
                    {p.name[0]?.toUpperCase()}
                  </div>
                )}
              </div>
              <span className="text-xs text-white/30 truncate max-w-[68px]">{p.name}</span>
            </div>
          )
        })}
      </div>

      {/* Page right */}
      <button
        onClick={() => onPageChange(Math.min(totalPages - 1, safePage + 1))}
        disabled={safePage >= totalPages - 1}
        className={`p-1 rounded transition-colors ${
          safePage >= totalPages - 1 ? 'text-white/10 cursor-default' : 'text-white/30 hover:text-white/50 hover:bg-white/5'
        }`}
        title="Next page"
      >
        <ChevronRight size={14} />
      </button>

      {/* Page indicator */}
      {totalPages > 1 && (
        <span className="text-[8px] text-white/15 ml-1">
          {safePage + 1}/{totalPages}
        </span>
      )}
    </div>
  )
}
