/**
 * TeamsLandingPage — Studio-style gallery for the Teams tab.
 *
 * Clean grid layout with large session cards:
 *   - Responsive: 1→2→3→4 columns
 *   - Big participant avatars (w-10 h-10)
 *   - Clear visual hierarchy with gradient accents
 *   - Empty state with onboarding CTA
 */

import React, { useState, useCallback } from 'react'
import {
  Users,
  Plus,
  Trash2,
  Clock,
  MessageSquare,
  Zap,
  Crown,
  User,
  ArrowRight,
} from 'lucide-react'
import type { MeetingRoom, PersonaSummary } from './types'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface TeamsLandingPageProps {
  rooms: MeetingRoom[]
  personas: PersonaSummary[]
  backendUrl: string
  onNewSession: () => void
  onOpenRoom: (room: MeetingRoom) => void
  onDeleteRoom: (id: string) => void
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTimeAgo(timestamp: number): string {
  const seconds = Math.floor((Date.now() / 1000 - timestamp))
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
  return `${Math.floor(seconds / 86400)}d ago`
}

const TURN_MODE_LABELS: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  'round-robin': { label: 'Round Robin', icon: <Zap size={12} />, color: 'text-violet-300/70 bg-violet-500/10 border-violet-500/15' },
  'free-form': { label: 'Free Form', icon: <MessageSquare size={12} />, color: 'text-blue-300/70 bg-blue-500/10 border-blue-500/15' },
  'moderated': { label: 'Moderated', icon: <Crown size={12} />, color: 'text-amber-300/70 bg-amber-500/10 border-amber-500/15' },
  'reactive': { label: 'Reactive', icon: <Zap size={12} />, color: 'text-cyan-300/70 bg-cyan-500/10 border-cyan-500/15' },
}

function resolveAvatarUrl(persona: PersonaSummary, backendUrl: string): string | null {
  const thumb = persona.persona_appearance?.selected_thumb_filename
  const main = persona.persona_appearance?.selected_filename
  const file = thumb || main
  if (!file) return null
  if (file.startsWith('http')) return file
  return `${backendUrl}/files/${file}`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TeamsLandingPage({
  rooms,
  personas,
  backendUrl,
  onNewSession,
  onOpenRoom,
  onDeleteRoom,
}: TeamsLandingPageProps) {
  const [deleteCandidate, setDeleteCandidate] = useState<MeetingRoom | null>(null)

  const personaMap = new Map(personas.map((p) => [p.id, p]))

  const confirmDelete = useCallback(() => {
    if (deleteCandidate) {
      onDeleteRoom(deleteCandidate.id)
      setDeleteCandidate(null)
    }
  }, [deleteCandidate, onDeleteRoom])

  return (
    <div className="h-full w-full bg-black text-white font-sans overflow-hidden flex flex-col relative">

      {/* ═══════════════ HEADER ═══════════════ */}
      <div className="flex-shrink-0 flex justify-between items-center px-6 py-5 border-b border-white/[0.04]">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center">
            <Users size={20} className="text-cyan-400" />
          </div>
          <div>
            <div className="text-base font-bold text-white leading-tight">Teams</div>
            <div className="text-xs text-white/35 leading-tight mt-0.5">
              {rooms.length > 0 ? `${rooms.length} session${rooms.length !== 1 ? 's' : ''}` : 'Meeting Rooms'}
            </div>
          </div>
        </div>

        <button
          className="flex items-center gap-2 bg-gradient-to-r from-cyan-600 to-blue-600 hover:brightness-110 border border-cyan-500/20 px-5 py-2.5 rounded-xl text-sm font-semibold shadow-lg shadow-cyan-500/10 hover:shadow-cyan-500/20 transition-all"
          type="button"
          onClick={onNewSession}
        >
          <Plus size={16} />
          <span>New Session</span>
        </button>
      </div>

      {/* ═══════════════ ROOM GRID ═══════════════ */}
      <div className="flex-1 overflow-y-auto px-6 py-6 scrollbar-hide">
        <div className="max-w-[1400px] mx-auto grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5 content-start">

          {/* Empty state */}
          {rooms.length === 0 && (
            <div className="col-span-full">
              <div className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-16 text-center">
                <div className="mx-auto w-16 h-16 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center">
                  <Users size={28} className="text-cyan-400/70" />
                </div>

                <h2 className="mt-6 text-xl font-bold text-white/90">
                  Create your first team session
                </h2>

                <p className="mt-3 text-sm text-white/40 max-w-lg mx-auto leading-relaxed">
                  Bring your AI personas together in a virtual meeting room.
                  Each persona keeps its own personality, memory, and tools
                  while collaborating in a shared conversation.
                </p>

                <div className="mt-8">
                  <button
                    type="button"
                    onClick={onNewSession}
                    className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 hover:brightness-110 border border-cyan-500/20 text-sm font-semibold text-white shadow-lg shadow-cyan-500/10 hover:shadow-cyan-500/20 transition-all"
                  >
                    <Plus size={18} />
                    <span>New Session</span>
                  </button>
                </div>

                <p className="mt-6 text-xs text-white/20">
                  Sessions are saved automatically
                </p>
              </div>
            </div>
          )}

          {/* Room cards */}
          {rooms.map((room) => {
            const participantPersonas = room.participant_ids
              .map((id) => personaMap.get(id))
              .filter(Boolean) as PersonaSummary[]
            const msgCount = room.message_count ?? room.messages?.length ?? 0
            const modeInfo = TURN_MODE_LABELS[room.turn_mode] || TURN_MODE_LABELS['round-robin']

            return (
              <div
                key={room.id}
                onClick={() => onOpenRoom(room)}
                className="group relative rounded-2xl overflow-hidden bg-white/[0.02] border border-white/[0.06] hover:border-cyan-500/30 hover:bg-white/[0.04] transition-all duration-200 cursor-pointer"
              >
                {/* Top gradient accent */}
                <div className="h-1.5 bg-gradient-to-r from-cyan-500/50 via-blue-500/50 to-violet-500/50 opacity-60 group-hover:opacity-100 transition-opacity" />

                <div className="p-5 space-y-4">
                  {/* Title + mode badge */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <h3 className="text-[15px] font-bold text-white group-hover:text-cyan-50 truncate transition-colors">
                        {room.name}
                      </h3>
                      {room.description && (
                        <p className="text-xs text-white/35 mt-1 line-clamp-2 leading-relaxed">
                          {room.description}
                        </p>
                      )}
                    </div>
                    <button
                      className="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg bg-red-500/10 hover:bg-red-500/25 text-red-400/70 hover:text-red-400 transition-all flex-shrink-0"
                      type="button"
                      title="Delete session"
                      onClick={(e) => { e.stopPropagation(); setDeleteCandidate(room) }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>

                  {/* Participant avatars — bigger */}
                  <div className="flex items-center gap-1.5">
                    {/* Human seat */}
                    <div className="w-14 h-14 rounded-full bg-cyan-500/15 border-2 border-cyan-500/30 flex items-center justify-center flex-shrink-0" title="You (Host)">
                      <User size={22} className="text-cyan-300" />
                    </div>

                    {participantPersonas.slice(0, 4).map((p) => {
                      const avatarUrl = resolveAvatarUrl(p, backendUrl)
                      return (
                        <div
                          key={p.id}
                          className="w-14 h-14 rounded-full border-2 border-white/10 bg-white/5 flex-shrink-0 overflow-hidden hover:border-white/20 transition-colors"
                          title={p.name}
                        >
                          {avatarUrl ? (
                            <img src={avatarUrl} alt={p.name} className="w-full h-full object-cover" />
                          ) : (
                            <div className="w-full h-full flex items-center justify-center text-xs text-white/40 font-bold">
                              {p.name.charAt(0).toUpperCase()}
                            </div>
                          )}
                        </div>
                      )
                    })}

                    {participantPersonas.length > 4 && (
                      <div className="w-14 h-14 rounded-full bg-white/5 border-2 border-white/10 flex items-center justify-center text-xs text-white/40 font-semibold flex-shrink-0">
                        +{participantPersonas.length - 4}
                      </div>
                    )}

                    {participantPersonas.length === 0 && (
                      <span className="text-xs text-white/25 italic ml-2">No personas yet</span>
                    )}
                  </div>

                  {/* Footer: stats + mode badge */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 text-[11px] text-white/30">
                      <span className="flex items-center gap-1">
                        <Users size={11} />
                        {room.participant_count ?? room.participant_ids.length}
                      </span>
                      <span className="flex items-center gap-1">
                        <MessageSquare size={11} />
                        {msgCount}
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock size={11} />
                        {formatTimeAgo(room.last_activity ?? room.updated_at)}
                      </span>
                    </div>
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium border ${modeInfo.color}`}>
                      {modeInfo.icon}
                      {modeInfo.label}
                    </span>
                  </div>
                </div>

                {/* Hover arrow */}
                <div className="absolute top-1/2 right-3 -translate-y-1/2 opacity-0 group-hover:opacity-100 translate-x-2 group-hover:translate-x-0 transition-all duration-200">
                  <ArrowRight size={16} className="text-cyan-400/50" />
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Floating New Session FAB */}
      {rooms.length > 0 && (
        <div className="absolute bottom-6 right-6 z-30">
          <button
            onClick={onNewSession}
            className="w-14 h-14 rounded-2xl bg-gradient-to-br from-cyan-600 to-blue-600 text-white hover:brightness-110 transition-all shadow-2xl shadow-cyan-500/20 flex items-center justify-center"
            type="button"
            title="New session"
          >
            <Plus size={24} />
          </button>
        </div>
      )}

      {/* ═══════════════ DELETE CONFIRMATION ═══════════════ */}
      {deleteCandidate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
          onClick={() => setDeleteCandidate(null)}
        >
          <div
            className="w-full max-w-sm mx-4 rounded-2xl border border-white/10 bg-[#0a0a0a] shadow-2xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-5 py-4 space-y-3">
              <div className="flex items-center gap-3">
                <div className="w-11 h-11 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center justify-center">
                  <Trash2 size={20} className="text-red-400" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">Delete this session?</h3>
                  <p className="text-xs text-white/40 mt-0.5">
                    &quot;{deleteCandidate.name}&quot; and all messages will be removed.
                  </p>
                </div>
              </div>
            </div>
            <div className="px-5 py-3 border-t border-white/5 flex items-center justify-end gap-2">
              <button
                onClick={() => setDeleteCandidate(null)}
                className="px-4 py-2 rounded-xl text-sm text-white/60 hover:text-white/80 bg-white/5 hover:bg-white/10 border border-white/[0.08] transition-all"
              >
                Cancel
              </button>
              <button
                onClick={confirmDelete}
                className="px-4 py-2 rounded-xl text-sm font-semibold text-red-200 bg-red-500/20 hover:bg-red-500/40 border border-red-500/20 transition-all"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
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
