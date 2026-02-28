/**
 * MeetingLeftRail — Collapsible persona sidebar for the meeting room.
 *
 * Two sections:
 *   1. "In Meeting" — current participants with live status dots
 *   2. "Available"  — personas that can be added (with search)
 *
 * Collapsed mode: slim icon bar (44px).
 * Expanded mode:  full sidebar (224px) with search + lists.
 *
 * Supports HTML5 drag-start so personas can be dragged onto table seats.
 */

import React, { useState, useMemo } from 'react'
import {
  Users,
  Search,
  ChevronLeft,
  ChevronRight,
  Plus,
  Mic,
  MicOff,
  X,
  Hand,
} from 'lucide-react'
import type { PersonaSummary, IntentSnapshot, HandRaiseMeta } from './types'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type SeatStatus = 'listening' | 'wants-to-speak' | 'speaking' | 'muted'

export interface MeetingLeftRailProps {
  expanded: boolean
  onToggle: () => void
  /** All personas (both in meeting and available) */
  personas: PersonaSummary[]
  /** IDs of personas currently in the meeting */
  participantIds: string[]
  /** Current intent snapshots keyed by persona ID */
  intents: Record<string, IntentSnapshot>
  handRaises: Set<string>
  handRaiseMeta: Record<string, HandRaiseMeta>
  currentRound: number
  mutedSet: Set<string>
  /** True when backend is generating persona turns */
  runningTurn: boolean
  /** Last assistant message sender ID (for "speaking" detection) */
  lastSpeakerId?: string
  backendUrl: string
  onAddParticipant: (id: string) => void
  onCallOn?: (id: string) => void
  onToggleMute?: (id: string) => void
  onRemoveParticipant: (id: string) => void
  /** HTML5 DnD: called when drag starts on a persona chip */
  onDragStartPersona?: (e: React.DragEvent, personaId: string) => void
  /** Open persona profile panel */
  onOpenProfile?: (personaId: string) => void
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
  if (runningTurn) {
    const intent = intents[personaId]
    if (intent?.wants_to_speak) return 'speaking'
  }
  if (lastSpeakerId === personaId) return 'speaking'
  if (handRaises.has(personaId) || intents[personaId]?.wants_to_speak) return 'wants-to-speak'
  return 'listening'
}

const STATUS_DOT: Record<SeatStatus, string> = {
  speaking: 'bg-emerald-400 shadow-sm shadow-emerald-400/50',
  'wants-to-speak': 'bg-amber-400 shadow-sm shadow-amber-400/40',
  listening: 'bg-white/20',
  muted: 'bg-red-400/60',
}

const STATUS_LABEL: Record<SeatStatus, string> = {
  speaking: 'Speaking',
  'wants-to-speak': 'Wants to speak',
  listening: 'Listening',
  muted: 'Muted',
}

const STATUS_TEXT_COLOR: Record<SeatStatus, string> = {
  speaking: 'text-emerald-300/70',
  'wants-to-speak': 'text-amber-300/60',
  listening: 'text-white/25',
  muted: 'text-red-300/50',
}

const INTENT_PILL: Record<string, { bg: string; text: string; label: string }> = {
  idea: { bg: 'bg-purple-500/15', text: 'text-purple-300/70', label: 'Idea' },
  risk: { bg: 'bg-red-500/15', text: 'text-red-300/70', label: 'Risk' },
  clarify: { bg: 'bg-blue-500/15', text: 'text-blue-300/70', label: 'Clarify' },
  summary: { bg: 'bg-teal-500/15', text: 'text-teal-300/70', label: 'Summary' },
  action: { bg: 'bg-orange-500/15', text: 'text-orange-300/70', label: 'Action' },
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MeetingLeftRail({
  expanded,
  onToggle,
  personas,
  participantIds,
  intents,
  handRaises,
  handRaiseMeta,
  currentRound,
  mutedSet,
  runningTurn,
  lastSpeakerId,
  backendUrl,
  onAddParticipant,
  onCallOn,
  onToggleMute,
  onRemoveParticipant,
  onDragStartPersona,
  onOpenProfile,
}: MeetingLeftRailProps) {
  const [search, setSearch] = useState('')

  const personaMap = useMemo(() => new Map(personas.map((p) => [p.id, p])), [personas])

  const inMeeting = useMemo(
    () => participantIds.map((id) => personaMap.get(id)).filter(Boolean) as PersonaSummary[],
    [participantIds, personaMap],
  )

  const available = useMemo(() => {
    const idSet = new Set(participantIds)
    let list = personas.filter((p) => p.project_type === 'persona' && !idSet.has(p.id))
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(
        (p) =>
          p.name.toLowerCase().includes(q) ||
          (p.description || '').toLowerCase().includes(q),
      )
    }
    return list
  }, [personas, participantIds, search])

  // ── Collapsed icon bar ──
  if (!expanded) {
    return (
      <div className="flex-shrink-0 w-11 border-r border-white/[0.04] bg-white/[0.01] flex flex-col items-center py-3 gap-2">
        <button
          onClick={onToggle}
          className="p-2 rounded-lg hover:bg-white/5 text-white/30 hover:text-white/60 transition-colors"
          title="Show people panel"
        >
          <Users size={16} />
        </button>
        {/* Mini status dots for in-meeting participants */}
        <div className="flex flex-col items-center gap-1.5 mt-2">
          {inMeeting.slice(0, 8).map((p) => {
            const status = getSeatStatus(p.id, intents, handRaises, mutedSet, runningTurn, lastSpeakerId)
            const avatarUrl = resolveAvatarUrl(p, backendUrl)
            return (
              <div
                key={p.id}
                className="relative cursor-pointer"
                title={`${p.name} — ${STATUS_LABEL[status]}`}
                onClick={() => onOpenProfile?.(p.id)}
              >
                <div className="w-10 h-10 rounded-full overflow-hidden border border-white/10 bg-white/5">
                  {avatarUrl ? (
                    <img src={avatarUrl} alt={p.name} className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-[9px] text-white/30 font-bold">
                      {p.name[0]?.toUpperCase()}
                    </div>
                  )}
                </div>
                <span className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-black ${STATUS_DOT[status]}`} />
              </div>
            )
          })}
          {inMeeting.length > 8 && (
            <span className="text-[8px] text-white/20">+{inMeeting.length - 8}</span>
          )}
        </div>
      </div>
    )
  }

  // ── Expanded sidebar ──
  return (
    <div className="flex-shrink-0 w-56 border-r border-white/[0.04] bg-white/[0.01] flex flex-col animate-rail-slide-left overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2.5 border-b border-white/[0.04]">
        <span className="text-sm font-semibold text-white/50 flex items-center gap-1.5">
          <Users size={15} />
          People
        </span>
        <button
          onClick={onToggle}
          className="p-1 rounded hover:bg-white/5 text-white/30 hover:text-white/50 transition-colors"
          title="Collapse panel"
        >
          <ChevronLeft size={14} />
        </button>
      </div>

      {/* Speaking Queue (auto hand-raisers) */}
      {(() => {
        const queueEntries = (Object.entries(handRaiseMeta) as [string, HandRaiseMeta][])
          .filter(([pid]) => participantIds.includes(pid))
          .sort(([, a], [, b]) => b.confidence_at_raise - a.confidence_at_raise)
        if (queueEntries.length === 0) return null
        return (
          <div className="px-3 pt-3 pb-1">
            <div className="text-[10px] font-semibold text-amber-300/40 uppercase tracking-wider mb-2 flex items-center gap-1">
              <Hand size={10} />
              Queue ({queueEntries.length})
            </div>
            <div className="space-y-1">
              {queueEntries.map(([pid, meta], idx) => {
                const p = personaMap.get(pid)
                if (!p) return null
                const avatarUrl = resolveAvatarUrl(p, backendUrl)
                const ttl = Math.max(0, meta.expires_round - currentRound)
                const pill = INTENT_PILL[meta.intent_type]
                return (
                  <div key={pid} className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-amber-500/[0.04] border border-amber-500/[0.08]">
                    <span className="text-[9px] text-amber-300/40 w-3 text-right font-mono">{idx + 1}</span>
                    <div className="w-9 h-9 rounded-full overflow-hidden border border-amber-400/20 bg-white/5 flex-shrink-0">
                      {avatarUrl ? (
                        <img src={avatarUrl} alt={p.name} className="w-full h-full object-cover" />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center text-[8px] text-white/30 font-bold">{p.name[0]?.toUpperCase()}</div>
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[11px] text-white/60 font-medium truncate">{p.name}</div>
                      <div className="flex items-center gap-1">
                        {pill && (
                          <span className={`text-[8px] px-1 py-px rounded ${pill.bg} ${pill.text}`}>{pill.label}</span>
                        )}
                        <span className="text-[9px] text-white/20">{Math.round(meta.confidence_at_raise * 100)}%</span>
                      </div>
                    </div>
                    <span className={`text-[8px] font-mono ${ttl <= 1 ? 'text-red-400/60' : 'text-amber-300/40'}`} title={`Expires in ${ttl} round(s)`}>
                      {ttl}r
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })()}

      {/* In Meeting section */}
      <div className="px-3 pt-3 pb-1">
        <div className="text-xs font-semibold text-white/30 uppercase tracking-wider mb-2">
          In Meeting ({inMeeting.length})
        </div>
        <div className="space-y-1 max-h-[240px] overflow-y-auto scrollbar-hide">
          {inMeeting.map((p) => {
            const status = getSeatStatus(p.id, intents, handRaises, mutedSet, runningTurn, lastSpeakerId)
            const avatarUrl = resolveAvatarUrl(p, backendUrl)
            const isMuted = mutedSet.has(p.id)
            const intent = intents[p.id]
            const intentPill = intent && INTENT_PILL[intent.intent_type]
            return (
              <div
                key={p.id}
                className="group flex items-center gap-2.5 px-2 py-2 rounded-lg hover:bg-white/[0.03] transition-colors cursor-pointer"
                draggable
                onDragStart={(e) => onDragStartPersona?.(e, p.id)}
                onClick={() => onOpenProfile?.(p.id)}
                title={intent?.reason || `${p.name} — click for profile`}
              >
                <div className="relative flex-shrink-0">
                  <div className="w-11 h-11 rounded-full overflow-hidden border border-white/10 bg-white/5">
                    {avatarUrl ? (
                      <img src={avatarUrl} alt={p.name} className="w-full h-full object-cover" />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center text-[10px] text-white/30 font-bold">
                        {p.name[0]?.toUpperCase()}
                      </div>
                    )}
                  </div>
                  <span className={`absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border border-black ${STATUS_DOT[status]}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-white/70 font-medium truncate">{p.name}</div>
                  <div className="flex items-center gap-1">
                    <span className={`text-xs ${STATUS_TEXT_COLOR[status]}`}>{STATUS_LABEL[status]}</span>
                    {intentPill && (
                      <span className={`text-[9px] px-1.5 py-px rounded ${intentPill.bg} ${intentPill.text}`}>{intentPill.label}</span>
                    )}
                  </div>
                </div>
                {/* Quick actions on hover */}
                <div className="flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                  {onCallOn && !isMuted && (
                    <button
                      onClick={() => onCallOn(p.id)}
                      className="p-1 rounded hover:bg-cyan-500/15 text-white/20 hover:text-cyan-300 transition-colors"
                      title={`Call on ${p.name}`}
                    >
                      <Mic size={10} />
                    </button>
                  )}
                  {onToggleMute && (
                    <button
                      onClick={() => onToggleMute(p.id)}
                      className={`p-1 rounded transition-colors ${
                        isMuted ? 'text-red-400 hover:bg-red-500/15' : 'text-white/20 hover:bg-white/5 hover:text-white/40'
                      }`}
                      title={isMuted ? 'Unmute' : 'Mute'}
                    >
                      {isMuted ? <MicOff size={10} /> : <MicOff size={10} />}
                    </button>
                  )}
                  <button
                    onClick={() => onRemoveParticipant(p.id)}
                    className="p-1 rounded hover:bg-red-500/15 text-white/20 hover:text-red-400 transition-colors"
                    title="Remove"
                  >
                    <X size={10} />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Divider */}
      <div className="mx-3 my-2 border-t border-white/[0.04]" />

      {/* Available section */}
      <div className="px-3 flex-1 min-h-0 flex flex-col">
        <div className="text-xs font-semibold text-white/30 uppercase tracking-wider mb-2">
          Available ({available.length})
        </div>
        {/* Search */}
        <div className="relative mb-2">
          <Search size={10} className="absolute left-2 top-1/2 -translate-y-1/2 text-white/20" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search..."
            className="w-full pl-6 pr-2 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-[11px] text-white/70 placeholder:text-white/15 focus:outline-none focus:border-white/10 transition-colors"
          />
        </div>
        {/* List */}
        <div className="flex-1 overflow-y-auto scrollbar-hide space-y-0.5">
          {available.length === 0 && (
            <div className="text-[10px] text-white/20 italic py-2 text-center">
              {search ? 'No matches' : 'All personas in meeting'}
            </div>
          )}
          {available.map((p) => {
            const avatarUrl = resolveAvatarUrl(p, backendUrl)
            return (
              <div
                key={p.id}
                className="group flex items-center gap-2.5 px-2 py-2 rounded-lg hover:bg-white/[0.03] transition-colors cursor-grab active:cursor-grabbing"
                draggable
                onDragStart={(e) => onDragStartPersona?.(e, p.id)}
                onClick={() => onOpenProfile?.(p.id)}
              >
                <div className="w-10 h-10 rounded-full overflow-hidden border border-white/10 bg-white/5 flex-shrink-0">
                  {avatarUrl ? (
                    <img src={avatarUrl} alt={p.name} className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-[9px] text-white/30 font-bold">
                      {p.name[0]?.toUpperCase()}
                    </div>
                  )}
                </div>
                <span className="text-xs text-white/50 truncate flex-1">{p.name}</span>
                <button
                  onClick={() => onAddParticipant(p.id)}
                  className="p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-cyan-500/15 text-cyan-400/60 hover:text-cyan-300 transition-all"
                  title={`Add ${p.name}`}
                >
                  <Plus size={10} />
                </button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
