/**
 * MeetingRoomV2 — Simplified MMORPG-style meeting layout.
 *
 * Architecture:
 *   ┌──────────────────────────────────────────────────────────────────────────┐
 *   │ ← Room Name                                        [⚙] [People toggle] │
 *   ├──────────────┬───────────────────────────┬──────────────────────────────┤
 *   │ LEFT RAIL    │ CENTER STAGE              │ RIGHT RAIL (Tabbed)          │
 *   │ People       │ Meeting Table (oval)      │ Transcript | Docs | Agenda   │
 *   │ In Meeting   │                           │ Actions | Stats              │
 *   │ Available    │                           │                              │
 *   ├──────────────┴───────────────────────────┴──────────────────────────────┤
 *   │ [Type message…___________________________________________]       [Send] │
 *   └──────────────────────────────────────────────────────────────────────────┘
 *
 * Key difference from MeetingRoom (V1):
 *   - Transcript lives in the right rail (not center)
 *   - Simpler seat rendering without paging/pinning/drag-drop
 *   - Cleaner, MMORPG-inspired UI with less visual noise
 *
 * Additive — lives alongside MeetingRoom.tsx; switch via parent.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft,
  Send,
  User,
  Users,
  Plus,
  X,
  MessageSquare,
  FileText,
  ListChecks,
  Zap,
  BarChart3,
  Settings as SettingsIcon,
} from 'lucide-react'
import type { MeetingRoom as MeetingRoomT, PersonaSummary } from './types'
import { DocumentsPanel } from './DocumentsPanel'
import { TeamsSettingsDrawer } from './TeamsSettingsDrawer'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface MeetingRoomV2Props {
  room: MeetingRoomT
  personas: PersonaSummary[]
  backendUrl: string
  apiKey?: string
  onBack: () => void
  onSendMessage: (content: string) => Promise<void>
  onAddParticipant: (personaId: string) => Promise<void>
  onRemoveParticipant: (personaId: string) => Promise<void>
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveAvatarUrl(persona: PersonaSummary, backendUrl: string): string | null {
  const file = persona.persona_appearance?.selected_thumb_filename || persona.persona_appearance?.selected_filename
  if (!file) return null
  if (file.startsWith('http')) return file
  return `${backendUrl}/files/${file}`
}

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function seatPositions(count: number): Array<{ x: number; y: number }> {
  const positions: Array<{ x: number; y: number }> = []
  for (let i = 0; i < count; i++) {
    const angle = (2 * Math.PI * i) / count - Math.PI / 2
    positions.push({
      x: 50 + 42 * Math.cos(angle),
      y: 50 + 35 * Math.sin(angle),
    })
  }
  return positions
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type RightTab = 'transcript' | 'documents' | 'agenda' | 'actions' | 'stats'

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MeetingRoomV2({
  room,
  personas,
  backendUrl,
  apiKey,
  onBack,
  onSendMessage,
  onAddParticipant,
  onRemoveParticipant,
}: MeetingRoomV2Props) {
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [leftCollapsed, setLeftCollapsed] = useState(false)
  const [rightTab, setRightTab] = useState<RightTab>('transcript')
  const [settingsOpen, setSettingsOpen] = useState(false)

  const transcriptRef = useRef<HTMLDivElement>(null)

  const personaMap = useMemo(() => new Map(personas.map((p) => [p.id, p])), [personas])

  const inMeeting = useMemo(
    () => room.participant_ids.map((id) => personaMap.get(id)).filter(Boolean) as PersonaSummary[],
    [room.participant_ids, personaMap],
  )

  const available = useMemo(
    () => personas.filter((p) => p.project_type === 'persona' && !room.participant_ids.includes(p.id)),
    [personas, room.participant_ids],
  )

  const seats = useMemo(() => seatPositions(1 + inMeeting.length), [inMeeting.length])

  const lastMsg = (room.messages || []).slice(-1)[0]

  // Keep transcript pinned to bottom
  useEffect(() => {
    if (rightTab !== 'transcript') return
    const el = transcriptRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [rightTab, room.messages?.length])

  const handleSend = useCallback(async () => {
    const text = message.trim()
    if (!text || sending) return
    setSending(true)
    setMessage('')
    try {
      await onSendMessage(text)
      setRightTab('transcript')
    } catch (e) {
      console.error('send failed', e)
    } finally {
      setSending(false)
    }
  }, [message, sending, onSendMessage])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSend()
      }
    },
    [handleSend],
  )

  // Tab button helper
  const TabBtn = ({ id, label, icon }: { id: RightTab; label: string; icon: React.ReactNode }) => {
    const active = rightTab === id
    return (
      <button
        onClick={() => setRightTab(id)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium border transition-colors ${
          active
            ? 'bg-cyan-500/15 text-cyan-200 border-cyan-500/25'
            : 'bg-white/[0.03] text-white/35 border-white/[0.06] hover:bg-white/[0.05] hover:text-white/50'
        }`}
      >
        {icon}
        {label}
      </button>
    )
  }

  return (
    <div className="h-full w-full bg-black text-white overflow-hidden flex flex-col">

      {/* ═══ HEADER ═══ */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
        <div className="flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-1.5 rounded-lg hover:bg-white/5 text-white/40 hover:text-white/60 transition-colors"
          >
            <ArrowLeft size={16} />
          </button>
          <div>
            <h2 className="text-sm font-semibold text-white">{room.name}</h2>
            <div className="text-[10px] text-white/30 flex items-center gap-2">
              <span className="flex items-center gap-1">
                <Users size={9} />
                {room.participant_ids.length + 1} participants
              </span>
              <span className="text-white/20">&middot;</span>
              <span className="text-white/35">{(room.turn_mode || 'round-robin').replace('-', ' ')}</span>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setSettingsOpen(true)}
            className="p-2 rounded-lg bg-white/[0.04] border border-white/[0.06] text-white/45 hover:text-white/70 hover:bg-white/[0.06] transition-colors"
            title="Room Settings"
          >
            <SettingsIcon size={16} />
          </button>
          <button
            onClick={() => setLeftCollapsed((v) => !v)}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-white/[0.04] border border-white/[0.06] text-white/45 hover:bg-white/[0.06] hover:text-white/70 transition-colors"
          >
            {leftCollapsed ? 'People' : 'Hide'}
          </button>
        </div>
      </div>

      {/* ═══ 3-ZONE BODY ═══ */}
      <div className="flex-1 min-h-0 flex">

        {/* ── LEFT RAIL (People) ── */}
        <div
          className={`min-h-0 border-r border-white/[0.06] bg-white/[0.02] transition-all overflow-hidden ${
            leftCollapsed ? 'w-0 opacity-0 pointer-events-none' : 'w-72 opacity-100'
          }`}
        >
          <div className="h-full flex flex-col min-h-0">
            <div className="px-3 py-3 border-b border-white/[0.06]">
              <div className="text-xs text-white/70 font-medium">People</div>
              <div className="text-[10px] text-white/30 mt-0.5">
                In Meeting ({inMeeting.length + 1}) &middot; Available ({available.length})
              </div>
            </div>

            <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-4 scrollbar-hide">
              {/* In Meeting */}
              <div>
                <div className="text-[10px] text-white/35 font-medium mb-2">In Meeting</div>
                <div className="space-y-2">
                  {/* Human host */}
                  <div className="flex items-center justify-between gap-2 rounded-xl border border-white/[0.06] bg-white/[0.02] px-3 py-2">
                    <div className="flex items-center gap-2 min-w-0">
                      <div className="w-8 h-8 rounded-full bg-cyan-500/15 border border-cyan-500/25 flex items-center justify-center">
                        <User size={14} className="text-cyan-300" />
                      </div>
                      <div className="min-w-0">
                        <div className="text-xs text-white/75 font-medium truncate">You</div>
                        <div className="text-[10px] text-white/25">Host</div>
                      </div>
                    </div>
                  </div>

                  {inMeeting.map((p) => {
                    const avatarUrl = resolveAvatarUrl(p, backendUrl)
                    const isSpeaking = lastMsg?.sender_id === p.id && lastMsg?.role === 'assistant'
                    return (
                      <div
                        key={p.id}
                        className={`flex items-center justify-between gap-2 rounded-xl border px-3 py-2 transition-colors ${
                          isSpeaking
                            ? 'border-emerald-500/25 bg-emerald-500/10'
                            : 'border-white/[0.06] bg-white/[0.02]'
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <div className="w-8 h-8 rounded-full overflow-hidden border border-white/10 bg-white/5">
                            {avatarUrl ? (
                              <img src={avatarUrl} className="w-full h-full object-cover" alt={p.name} />
                            ) : (
                              <div className="w-full h-full flex items-center justify-center text-[10px] text-white/30 font-bold">
                                {p.name[0]?.toUpperCase()}
                              </div>
                            )}
                          </div>
                          <div className="min-w-0">
                            <div className="text-xs text-white/75 font-medium truncate">{p.name}</div>
                            <div className="text-[10px] text-white/25">{isSpeaking ? 'Speaking' : 'Listening'}</div>
                          </div>
                        </div>
                        <button
                          onClick={() => onRemoveParticipant(p.id)}
                          className="p-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] hover:bg-red-500/10 hover:border-red-500/20 text-white/30 hover:text-red-300 transition-colors"
                          title={`Remove ${p.name}`}
                        >
                          <X size={12} />
                        </button>
                      </div>
                    )
                  })}
                </div>
              </div>

              {/* Available */}
              <div>
                <div className="text-[10px] text-white/35 font-medium mb-2">Available</div>
                {available.length === 0 ? (
                  <div className="text-xs text-white/25 italic border border-white/[0.06] rounded-xl p-3 bg-white/[0.02]">
                    No available personas.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {available.map((p) => {
                      const avatarUrl = resolveAvatarUrl(p, backendUrl)
                      return (
                        <button
                          key={p.id}
                          onClick={() => onAddParticipant(p.id)}
                          className="w-full flex items-center justify-between gap-2 rounded-xl border border-white/[0.06] bg-white/[0.02] hover:bg-cyan-500/[0.05] hover:border-cyan-500/20 px-3 py-2 transition-colors"
                        >
                          <div className="flex items-center gap-2 min-w-0">
                            <div className="w-8 h-8 rounded-full overflow-hidden border border-white/10 bg-white/5">
                              {avatarUrl ? (
                                <img src={avatarUrl} className="w-full h-full object-cover" alt={p.name} />
                              ) : (
                                <div className="w-full h-full flex items-center justify-center text-[10px] text-white/30 font-bold">
                                  {p.name[0]?.toUpperCase()}
                                </div>
                              )}
                            </div>
                            <div className="min-w-0 text-left">
                              <div className="text-xs text-white/75 font-medium truncate">{p.name}</div>
                              <div className="text-[10px] text-white/25">Add to meeting</div>
                            </div>
                          </div>
                          <div className="p-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-white/35">
                            <Plus size={12} />
                          </div>
                        </button>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* ── CENTER STAGE (Table + Input) ── */}
        <div className="flex-1 min-h-0 flex flex-col">
          {/* Meeting table */}
          <div className="flex-1 min-h-0 p-4">
            <div className="h-full rounded-2xl border border-white/[0.06] bg-white/[0.02] relative overflow-hidden">
              {/* Table oval */}
              <div className="absolute inset-[12%] rounded-[50%] border border-white/[0.05] bg-white/[0.015]" />

              {/* Center label */}
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="text-[10px] text-white/15 font-medium max-w-[160px] text-center truncate">
                  {room.name}
                </div>
              </div>

              {/* Human seat */}
              {seats.length > 0 && (
                <div
                  className="absolute -translate-x-1/2 -translate-y-1/2"
                  style={{ left: `${seats[0].x}%`, top: `${seats[0].y}%` }}
                >
                  <div className="flex flex-col items-center gap-1">
                    <div className="w-16 h-16 lg:w-20 lg:h-20 rounded-full bg-cyan-500/15 border-2 border-cyan-500/35 flex items-center justify-center shadow-lg shadow-cyan-500/10">
                      <User size={24} className="text-cyan-300" />
                    </div>
                    <span className="text-[10px] text-cyan-300/60 font-medium">You</span>
                  </div>
                </div>
              )}

              {/* Persona seats */}
              {inMeeting.map((p, i) => {
                const pos = seats[i + 1]
                if (!pos) return null
                const avatarUrl = resolveAvatarUrl(p, backendUrl)
                const isSpeaking = lastMsg?.sender_id === p.id && lastMsg?.role === 'assistant'

                return (
                  <div
                    key={p.id}
                    className="absolute -translate-x-1/2 -translate-y-1/2"
                    style={{ left: `${pos.x}%`, top: `${pos.y}%` }}
                  >
                    <div className="flex flex-col items-center gap-1">
                      <div
                        className={`w-16 h-16 lg:w-20 lg:h-20 rounded-full border-2 overflow-hidden flex items-center justify-center transition-all ${
                          isSpeaking
                            ? 'border-emerald-400 shadow-lg shadow-emerald-500/20'
                            : 'border-white/15 hover:border-white/25'
                        }`}
                      >
                        {avatarUrl ? (
                          <img src={avatarUrl} alt={p.name} className="w-full h-full object-cover" />
                        ) : (
                          <div className="w-full h-full bg-white/5 flex items-center justify-center text-sm text-white/30 font-bold">
                            {p.name[0]?.toUpperCase()}
                          </div>
                        )}
                      </div>
                      <span
                        className={`text-[10px] font-medium truncate max-w-[80px] ${
                          isSpeaking ? 'text-emerald-300/80' : 'text-white/35'
                        }`}
                      >
                        {p.name}
                      </span>
                      <span className="text-[9px] text-white/20">
                        {isSpeaking ? 'Speaking' : 'Listening'}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Bottom input */}
          <div className="px-4 pb-4">
            <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3">
              <div className="flex items-end gap-2">
                <textarea
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Type a message..."
                  rows={1}
                  className="flex-1 px-4 py-2.5 rounded-xl bg-white/[0.04] border border-white/[0.08] text-sm text-white placeholder:text-white/20 focus:outline-none focus:border-cyan-500/40 transition-colors resize-none"
                />
                <button
                  onClick={handleSend}
                  disabled={!message.trim() || sending}
                  className={`p-2.5 rounded-xl transition-all ${
                    message.trim() && !sending
                      ? 'bg-cyan-600 hover:bg-cyan-500 text-white'
                      : 'bg-white/[0.04] text-white/15'
                  }`}
                >
                  <Send size={16} />
                </button>
              </div>
              <div className="text-[9px] text-white/15 mt-1 text-center">Press Enter to send</div>
            </div>
          </div>
        </div>

        {/* ── RIGHT RAIL (Tabbed: Transcript + Docs + Agenda + Actions + Stats) ── */}
        <div className="w-[380px] max-w-[42vw] min-h-0 border-l border-white/[0.06] bg-white/[0.02] flex flex-col">
          {/* Tabs */}
          <div className="px-3 py-3 border-b border-white/[0.06]">
            <div className="flex items-center gap-1.5 flex-wrap">
              <TabBtn id="transcript" label="Transcript" icon={<MessageSquare size={12} />} />
              <TabBtn id="documents" label="Docs" icon={<FileText size={12} />} />
              <TabBtn id="agenda" label="Agenda" icon={<ListChecks size={12} />} />
              <TabBtn id="actions" label="Actions" icon={<Zap size={12} />} />
              <TabBtn id="stats" label="Stats" icon={<BarChart3 size={12} />} />
            </div>
          </div>

          {/* Tab content */}
          <div className="flex-1 min-h-0 overflow-hidden">
            {/* ═══ TRANSCRIPT ═══ */}
            {rightTab === 'transcript' && (
              <div ref={transcriptRef} className="h-full min-h-0 overflow-y-auto px-3 py-3 space-y-3 scrollbar-hide">
                {(!room.messages || room.messages.length === 0) ? (
                  <div className="text-center py-8">
                    <MessageSquare size={24} className="mx-auto text-white/10 mb-2" />
                    <p className="text-xs text-white/25">No messages yet. Start by sending a message.</p>
                  </div>
                ) : (
                  (room.messages || []).map((msg) => {
                    const isHuman = msg.role === 'user'
                    const persona = personaMap.get(msg.sender_id)
                    const avatarUrl = persona ? resolveAvatarUrl(persona, backendUrl) : null

                    return (
                      <div key={msg.id} className={`flex gap-3 ${isHuman ? 'flex-row-reverse' : ''}`}>
                        <div className="w-8 h-8 rounded-full flex-shrink-0 overflow-hidden border border-white/10">
                          {isHuman ? (
                            <div className="w-full h-full bg-cyan-500/15 flex items-center justify-center">
                              <User size={14} className="text-cyan-300" />
                            </div>
                          ) : avatarUrl ? (
                            <img src={avatarUrl} alt={msg.sender_name} className="w-full h-full object-cover" />
                          ) : (
                            <div className="w-full h-full bg-white/5 flex items-center justify-center text-[10px] text-white/30 font-bold">
                              {msg.sender_name[0]?.toUpperCase()}
                            </div>
                          )}
                        </div>

                        <div className={`max-w-[78%] ${isHuman ? 'items-end' : ''}`}>
                          <div className="flex items-center gap-2 mb-0.5">
                            <span className={`text-[10px] font-medium ${isHuman ? 'text-cyan-300/60' : 'text-white/40'}`}>
                              {msg.sender_name}
                            </span>
                            <span className="text-[9px] text-white/15">{formatTime(msg.timestamp)}</span>
                          </div>
                          <div
                            className={`px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed ${
                              isHuman
                                ? 'bg-cyan-500/15 border border-cyan-500/20 text-white/90 rounded-tr-md'
                                : 'bg-white/[0.04] border border-white/[0.06] text-white/75 rounded-tl-md'
                            }`}
                          >
                            {msg.content}
                          </div>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            )}

            {/* ═══ DOCUMENTS ═══ */}
            {rightTab === 'documents' && (
              <div className="h-full p-3 overflow-hidden">
                <DocumentsPanel
                  backendUrl={backendUrl}
                  apiKey={apiKey}
                  roomId={room.id}
                  initialDocuments={room.documents || []}
                />
              </div>
            )}

            {/* ═══ AGENDA ═══ */}
            {rightTab === 'agenda' && (
              <div className="h-full overflow-y-auto p-4 scrollbar-hide">
                <div className="text-xs text-white/70 font-medium mb-2">Agenda</div>
                {room.agenda && room.agenda.length > 0 ? (
                  <div className="space-y-2">
                    {room.agenda.map((item, i) => (
                      <div key={i} className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3 text-sm text-white/70">
                        <span className="text-white/40 text-xs mr-2">{i + 1}.</span>
                        {item}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-white/25 italic border border-white/[0.06] rounded-xl p-3 bg-white/[0.02]">
                    No agenda items set. Add agenda items when creating a session.
                  </div>
                )}
              </div>
            )}

            {/* ═══ ACTIONS ═══ */}
            {rightTab === 'actions' && (
              <div className="h-full overflow-y-auto p-4 scrollbar-hide">
                <div className="text-xs text-white/70 font-medium mb-2">Actions</div>
                <div className="text-xs text-white/25 italic border border-white/[0.06] rounded-xl p-3 bg-white/[0.02]">
                  Action items will be auto-extracted from the transcript in a future update.
                </div>
              </div>
            )}

            {/* ═══ STATS ═══ */}
            {rightTab === 'stats' && (
              <div className="h-full overflow-y-auto p-4 scrollbar-hide">
                <div className="text-xs text-white/70 font-medium mb-2">Stats</div>
                <div className="space-y-2">
                  <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3">
                    <div className="text-[10px] text-white/30 mb-0.5">Messages</div>
                    <div className="text-sm text-white/60 font-medium">{(room.messages || []).length}</div>
                  </div>
                  <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3">
                    <div className="text-[10px] text-white/30 mb-0.5">Participants</div>
                    <div className="text-sm text-white/60 font-medium">{room.participant_ids.length + 1}</div>
                  </div>
                  <div className="rounded-lg bg-white/[0.03] border border-white/[0.06] p-3">
                    <div className="text-[10px] text-white/30 mb-0.5">Documents</div>
                    <div className="text-sm text-white/60 font-medium">{(room.documents || []).length}</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ═══ SETTINGS DRAWER ═══ */}
      <TeamsSettingsDrawer
        room={room}
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />

      <style>{`
        .scrollbar-hide::-webkit-scrollbar { display: none; }
        .scrollbar-hide { -ms-overflow-style: none; scrollbar-width: none; }
      `}</style>
    </div>
  )
}
